#!/usr/bin/env python3
"""
add_user_to_tao.py

Runs INSIDE the docker container. Responsible only for:
  1. Creating the TAO user (or finding the existing one)
  2. Authenticating to Keycloak (password + TOTP) and exchanging for an
     OpenStack session
  3. Creating the user's Swift bucket/container if it doesn't already exist

Mounting is intentionally NOT done here -- it's handled by a separate
host-level script (mount depends on FUSE device access / --privileged,
which shouldn't be required just to provision a user).

IMPORTANT for the calling wrapper script:
  All informational/progress messages go to stderr.
  The ONLY thing written to stdout is the final line: the user id, alone.
  This makes it safe to capture with e.g. `user_id=$(docker run ... )`
  without needing to grep/parse log lines.
"""

import argparse
import sys
import time

import psycopg2
import base64
import hashlib
from typing import List, Optional

from Crypto.Cipher import AES
from Crypto.Util.Padding import pad, unpad

import pyotp
import requests
from keystoneauth1 import loading, session
import openstack
from openstack import exceptions as os_exceptions

DB_HOST = "localhost"
DB_NAME = "taodata"
DB_USER = "tao"
DB_PASSWORD = "tao"


def log(msg: str) -> None:
    """Progress/info messages go to stderr, keeping stdout clean for the
    final user id only."""
    print(msg, file=sys.stderr)


# ---------------------------------------------------------------------------
# Internal helper
# ---------------------------------------------------------------------------

def _create_key(secret: str) -> bytes:
    """
    Mirrors Java createKey():
        byte[] key = secret.getBytes(UTF_8)
        key = SHA1.digest(key)
        key = Arrays.copyOf(key, 16)      # truncate to 128-bit AES key
    """
    raw = secret.encode("utf-8")
    sha1 = hashlib.sha1(raw).digest()   # 20-byte SHA-1 digest
    return sha1[:16]                     # keep first 16 bytes


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def encrypt(str_to_encrypt: str, secret: str) -> Optional[str]:
    """
    Encrypts a string using AES-128/ECB/PKCS5 and returns a Base64 string.
    """
    if str_to_encrypt is None or secret is None:
        return None
    try:
        key    = _create_key(secret)
        cipher = AES.new(key, AES.MODE_ECB)
        ct     = cipher.encrypt(pad(str_to_encrypt.encode("utf-8"), AES.block_size))
        return base64.b64encode(ct).decode("utf-8")
    except Exception as e:
        log(str(e))
        return None


def decrypt(str_to_decrypt: str, secret: str) -> Optional[str]:
    """
    Decrypts a Base64-encoded AES-128/ECB/PKCS5 ciphertext.
    """
    if str_to_decrypt is None or secret is None:
        return None
    try:
        key    = _create_key(secret)
        cipher = AES.new(key, AES.MODE_ECB)
        return unpad(cipher.decrypt(base64.b64decode(str_to_decrypt)), AES.block_size).decode("utf-8")
    except Exception:
        # Java silently returns strToDecrypt on failure
        return str_to_decrypt


def hash_md5(inputs: List[str]) -> Optional[str]:
    """
    Returns a Base64-encoded MD5 hash of the concatenated inputs.
    """
    if not inputs:
        return None
    md5 = hashlib.md5()
    for item in inputs:
        md5.update(item.encode())
    return base64.b64encode(md5.digest()).decode("utf-8")


def build_username(first_name, last_name):
    """
    John Smith -> jsmith
    """
    return (first_name[0] + last_name).lower()


def username_exists(cur, username):
    cur.execute(
        """ SELECT 1 FROM usr."user" WHERE username = %s """, (username,)
    )
    return cur.fetchone() is not None


def user_exists(cur, first_name, last_name, email):
    cur.execute(
        """ SELECT username, id FROM usr."user" WHERE lower(first_name) = lower(%s)
            AND  lower(last_name) = lower(%s)
            AND lower(email) = lower(%s) """,
        (first_name, last_name, email)
    )
    return cur.fetchone()


def find_available_username(cur, base):
    if not username_exists(cur, base):
        return base

    i = 1
    while True:
        candidate = f"{base}_{i}"
        if not username_exists(cur, candidate):
            return candidate
        i += 1


def generate_password(username, initial_password):
    return encrypt(initial_password, username)


def create_user(conn, first_name, last_name, email, initial_password, role):
    group_id = 1 if role == "admin" else 2

    with conn.cursor() as cur:
        existing = user_exists(cur, first_name, last_name, email)
        if existing:
            existing_username, existing_user_id = existing
            log(f"User already exists (name = {existing_username}, id = {existing_user_id}). Nothing to do.")
            return existing_user_id

        base_username = build_username(first_name, last_name)
        username = find_available_username(cur, base_username)
        password = generate_password(username, initial_password)

        cur.execute(
            """ INSERT INTO usr."user" (username, password, email, alternative_email, last_name,
                first_name, input_quota, actual_input_quota, processing_quota, actual_processing_quota,
                cpu_quota, memory_quota, organization, status_id, user_type_id, created)
            VALUES (%s, %s, %s, NULL, %s, %s, -1, -1, -1, -1, -1, -1, 'TAO', 2, 1, CURRENT_TIMESTAMP)
            RETURNING id """,
            (username, password, email, last_name, first_name, ),
        )

        user_id = cur.fetchone()[0]

        cur.execute(""" INSERT INTO usr.user_group (user_id, group_id) VALUES (%s, %s) """, (user_id, group_id),)

        conn.commit()
        log(f"Created user: {username}")
        log(f"User ID: {user_id}")
        log(f"Group: {role} ({group_id})")

        return user_id


# --------------------------------------------------------------------------
# Keycloak authentication (password + TOTP)
# --------------------------------------------------------------------------

def generate_totp(secret: str) -> str:
    """
    Generate a fresh 6-digit TOTP code from a base32 secret.
    """
    normalized = secret.replace(" ", "").upper()
    return pyotp.TOTP(normalized).now()


def get_keycloak_access_token(token_url: str, client_id: str, client_secret: str,
                               username: str, password: str, totp_secret: str = None,
                               max_retries: int = 2) -> str:
    """
    Authenticate against Keycloak's token endpoint using the Resource Owner
    Password Credentials grant, optionally with a TOTP one-time code.
    Retries once with a freshly generated code if the first attempt fails.
    """
    last_error = None
    for attempt in range(max_retries):
        data = {
            "grant_type": "password",
            "username": username,
            "password": password,
            "client_id": client_id,
            "client_secret": client_secret,
        }
        if totp_secret:
            data["otp"] = generate_totp(totp_secret)

        response = requests.post(
            token_url,
            data=data,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            timeout=30,
        )
        payload = response.json()

        if response.status_code == 200 and "access_token" in payload:
            return payload["access_token"]

        last_error = payload
        if attempt < max_retries - 1:
            seconds_into_window = int(time.time()) % 30
            time.sleep(max(1, 30 - seconds_into_window) + 1)

    raise RuntimeError(f"Keycloak authentication failed: {last_error}")


# --------------------------------------------------------------------------
# Exchange the Keycloak access token for an OpenStack session
# --------------------------------------------------------------------------

def get_openstack_connection(auth_url: str, identity_provider: str,
                              access_token: str, project_id: str,
                              domain_id: str = None, region: str = None):
    """
    Build an authenticated openstacksdk Connection using the v3oidcaccesstoken
    auth plugin. Note: client_id/client_secret are NOT passed here --
    keystoneauth1's OidcAccessToken plugin doesn't accept them; they're only
    needed for plugins that perform the Keycloak login themselves.
    """
    loader = loading.get_plugin_loader("v3oidcaccesstoken")
    auth_kwargs = {
        "auth_url": auth_url,
        "identity_provider": identity_provider,
        "protocol": "openid",
        "access_token": access_token,
        "project_id": project_id,
    }
    if domain_id:
        auth_kwargs["project_domain_id"] = domain_id
    auth = loader.load_from_options(**auth_kwargs)

    sess = session.Session(auth=auth)
    conn = openstack.connection.Connection(session=sess, region_name=region)
    return conn


# --------------------------------------------------------------------------
# Create the bucket (Swift container) if it doesn't exist
# --------------------------------------------------------------------------

def create_bucket_if_not_exists(conn, bucket_name: str) -> None:
    """
    Create a Swift container with the given name if it doesn't already exist.
    Idempotent -- safe to call every time.
    """
    try:
        conn.object_store.get_container_metadata(bucket_name)
        log(f"Bucket '{bucket_name}' already exists, skipping creation.")
        return
    except os_exceptions.ResourceNotFound:
        pass

    conn.object_store.create_container(name=bucket_name)
    log(f"Bucket '{bucket_name}' created.")


# --------------------------------------------------------------------------
# Config loading
# --------------------------------------------------------------------------

_CONFIG_KEY_SUFFIXES = {
    "username":         "user",
    "password":         "password",
    "auth_url":         "auth.url",
    "region":           "region",
    "domain_id":        "domain",
    "tenant_id":        "tenantId",
    "token_url":        "token.url",
    "identity_provider": "identity.provider",
    "client_id":        "client",
    "client_secret":    "client.secret",
    "totp_secret":      "user.secret",
}

_REQUIRED_CONFIG_KEYS = [
    "token_url", "client_id", "client_secret", "username", "password",
    "identity_provider", "auth_url", "tenant_id",
]


def load_config_from_db(cur, key_prefix: str) -> dict:
    cur.execute(
        'SELECT id, value FROM config.config WHERE id LIKE %s',
        (key_prefix + "%",),
    )
    rows = dict(cur.fetchall())

    cfg = {}
    for cfg_key, suffix in _CONFIG_KEY_SUFFIXES.items():
        cfg[cfg_key] = rows.get(key_prefix + suffix)

    missing = [k for k in _REQUIRED_CONFIG_KEYS if not cfg.get(k)]
    if missing:
        missing_ids = [key_prefix + _CONFIG_KEY_SUFFIXES[k] for k in missing]
        raise RuntimeError(f"Missing required config.config rows: {', '.join(missing_ids)}")

    return cfg


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--first-name", required=True)
    parser.add_argument("--last-name", required=True)
    parser.add_argument("--email", required=True)
    parser.add_argument("--password", required=True)
    parser.add_argument("--role", choices=["admin", "user"], default="user", help="User role (default: user)")
    args = parser.parse_args()

    host = DB_HOST
    if host in ("127.0.0.1", "::1", "localhost"):
        host = "172.17.0.1"

    conn = psycopg2.connect(host=host, dbname=DB_NAME, user=DB_USER, password=DB_PASSWORD)

    try:
        user_id = create_user(conn, args.first_name, args.last_name, args.email, args.password, args.role)

        with conn.cursor() as cur:
            cfg = load_config_from_db(cur, "openstack.swift.")
    finally:
        conn.close()

    log("Authenticating with Keycloak...")
    access_token = get_keycloak_access_token(
        token_url=cfg["token_url"],
        client_id=cfg["client_id"],
        client_secret=cfg["client_secret"],
        username=cfg["username"],
        password=cfg["password"],
        totp_secret=cfg["totp_secret"],
    )

    log("Exchanging for OpenStack session...")
    os_conn = get_openstack_connection(
        auth_url=cfg["auth_url"],
        identity_provider=cfg["identity_provider"],
        access_token=access_token,
        project_id=cfg["tenant_id"],
        domain_id=cfg["domain_id"],
        region=cfg["region"],
    )

    bucket_name = str(user_id)
    create_bucket_if_not_exists(os_conn, bucket_name)

    # Only line on stdout: the user id, so the calling wrapper can capture it
    # cleanly (e.g. `user_id=$(docker run ... )`) without parsing log output.
    print(user_id)


if __name__ == "__main__":
    main()
