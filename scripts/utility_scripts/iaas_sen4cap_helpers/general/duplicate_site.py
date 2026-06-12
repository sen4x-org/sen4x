#!/usr/bin/env python3

import argparse
import psycopg2
from psycopg2.extras import DictCursor
import sys
import re

from configparser import ConfigParser

class Config(object):
    def __init__(self, args):
        parser = ConfigParser()
        parser.read([args.config_file])

        self.host = parser.get("Database", "HostName")

        # work around Docker networking scheme
        if self.host == "127.0.0.1" or self.host == "::1" or self.host == "localhost":
            self.host = "172.17.0.1"

        self.port = int(parser.get("Database", "Port", vars={"Port": "5432"}))
        self.dbname = parser.get("Database", "DatabaseName")
        self.user = parser.get("Database", "UserName")
        self.password = parser.get("Database", "Password")

        self.site_id = args.site_id
        self.site_short_name = args.site_short_name
        self.dry_run = args.dry_run

def get_next_suffix(cur, base_short_name):
    """
    Safely compute the next available suffix by locking
    all candidate rows to avoid race conditions.
    """
    cur.execute(
        """
        SELECT short_name
        FROM site
        WHERE short_name = %s
           OR short_name ~ %s
        FOR UPDATE
        """,
        (
            base_short_name,
            f"^{re.escape(base_short_name)}_[0-9]+$",
        ),
    )

    max_suffix = 0
    for row in cur.fetchall():
        match = re.match(rf"{re.escape(base_short_name)}_(\d+)$", row["short_name"])
        if match:
            max_suffix = max(max_suffix, int(match.group(1)))

    return max_suffix + 1


def clone_site(config):
    site_id=config.site_id
    site_short_name=config.site_short_name
    dry_run = config.dry_run
    if not site_id and not site_short_name:
        raise ValueError("Provide either --site-id or --site-short-name")

    conn = psycopg2.connect(            
            host=config.host,
            port=config.port,
            dbname=config.dbname,
            user=config.user,
            password=config.password,
)
    try:
        with conn:
            with conn.cursor(cursor_factory=DictCursor) as cur:
                if site_id:
                    cur.execute("SELECT * FROM site WHERE id = %s", (site_id,))
                else:
                    cur.execute("SELECT * FROM site WHERE short_name = %s", (site_short_name,))

                site = cur.fetchone()
                if not site:
                    raise ValueError("Source site not found")

                original_site_id = site["id"]
                base_name = site["name"]
                base_short_name = site["short_name"]

                suffix = get_next_suffix(cur, base_short_name)

                new_name = f"{base_name}_{suffix}"
                new_short_name = f"{base_short_name}_{suffix}"

                print("📋 Clone plan:")
                print(f"  Source site_id     : {original_site_id}")
                print(f"  New site name      : {new_name}")
                print(f"  New site short_name: {new_short_name}")

                if dry_run:
                    print("\n🟡 DRY-RUN: no data will be written\n")
                    return

                cur.execute(
                    """
                    INSERT INTO site (name, short_name, geog, enabled)
                    VALUES (%s, %s, %s, %s)
                    RETURNING id
                    """,
                    # (new_name, new_short_name, site["geog"], site["enabled"]),
                    (new_name, new_short_name, site["geog"], "false"),
                )
                new_site_id = cur.fetchone()[0]

                cur.execute(
                    """
                    INSERT INTO season (site_id, name, start_date, end_date, mid_date, enabled)
                    SELECT %s, name, start_date, end_date, mid_date, enabled
                    FROM season
                    WHERE site_id = %s
                    """,
                    (new_site_id, original_site_id),
                )

                cur.execute(
                    """
                    INSERT INTO site_tiles (site_id, satellite_id, tiles)
                    SELECT %s, satellite_id, tiles
                    FROM site_tiles
                    WHERE site_id = %s
                    """,
                    (new_site_id, original_site_id),
                )

                cur.execute(
                    """
                    INSERT INTO config (key, site_id, value, last_updated)
                    SELECT key, %s, value, now()
                    FROM config
                    WHERE site_id = %s
                    """,
                    (new_site_id, original_site_id),
                )

                print(f"\n✅ Site cloned successfully (new_site_id={new_site_id})")

    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def main():
    parser = argparse.ArgumentParser(
        description="Clone a site and all related entities (seasons, tiles, config)"
    )
    parser.add_argument(
        "-c",
        "--config-file",
        default="/etc/sen2agri/sen2agri.conf",
        help="configuration file location",
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--site-id", type=int, help="ID of the site to clone")
    group.add_argument("--site-short-name", help="Short name of the site to clone")

    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be done without modifying the database",
    )

    args = parser.parse_args()

    config = Config(args)

    clone_site(config)


if __name__ == "__main__":
    main()
