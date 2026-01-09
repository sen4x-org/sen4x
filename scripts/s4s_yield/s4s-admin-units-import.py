#!/usr/bin/env python
from __future__ import print_function

import argparse
from configparser import ConfigParser
import os
import os.path
import pipes
import psycopg2
from psycopg2.sql import SQL, Literal
import psycopg2.extras
import subprocess
from shutil import copyfile
from zipfile import ZipFile
from pathlib import Path
import shutil

DEFAULT_SU_PATH = "/mnt/archive/s4s_yield/{site}/yield_su/"
SU_CFG_KEY = "processor.s4s_yield.su_path"

class Config(object):
    def __init__(self, args):
        parser = ConfigParser()
        parser.read([args.config_file])

        self.host = parser.get("Database", "HostName")
        self.port = int(parser.get("Database", "Port", vars={"Port": "5432"}))
        self.dbname = parser.get("Database", "DatabaseName")
        self.user = parser.get("Database", "UserName")
        self.password = parser.get("Database", "Password")

        # work around Docker networking scheme
        if self.host == "127.0.0.1" or self.host == "::1" or self.host == "localhost":
            self.host = "172.17.0.1"

        self.site_id = args.site_id
        self.input_file = args.input_file

def getSiteShortName(conn, site_id):
    site_short_name = ""
    with conn.cursor() as cursor:
        query = SQL(
            """
            select short_name from site
            where id = {}
            """
        )
        query = query.format(Literal(site_id))
        print(query.as_string(conn))

        cursor.execute(query)
        for row in cursor:
            site_short_name = row[0]
        conn.commit()
    return site_short_name

def setConfigValue(conn, site_id, key, value):
    with conn.cursor() as cursor:
        id = -1
        if not site_id:
            query = SQL(
                """ select id from config where key = {} and site_id is null"""
            ).format(Literal(key), Literal(site_id))
        else:
            query = SQL(
                """ select id from config where key = {} and site_id = {}"""
            ).format(Literal(key), Literal(site_id))
        print(query.as_string(conn))
        cursor.execute(query)
        for row in cursor:
            id = row[0]
        conn.commit()

        if id == -1:
            if not site_id:
                query = SQL(
                    """ insert into config (key, value) values ({}, {}) """
                ).format(Literal(key), Literal(value))
            else:
                query = SQL(
                    """ insert into config (key, site_id, value) values ({}, {}, {}) """
                ).format(Literal(key), Literal(site_id), Literal(value))
            print(query.as_string(conn))
            cursor.execute(query)
            conn.commit()
        else:
            if not site_id:
                query = SQL(
                    """ update config set value = {} where key = {} and site_id is null """
                ).format(Literal(value), Literal(key), Literal(site_id))
            else:
                query = SQL(
                    """ update config set value = {} where key = {} and site_id = {} """
                ).format(Literal(value), Literal(key), Literal(site_id))
            print(query.as_string(conn))
            cursor.execute(query)
            conn.commit()

        if not site_id:
            query = SQL(
                """ select value from config where key = {} and site_id is null"""
            ).format(Literal(key), Literal(site_id))
        else:
            query = SQL(
                """ select value from config where key = {} and site_id = {}"""
            ).format(Literal(key), Literal(site_id))
        print(query.as_string(conn))
        cursor.execute(query)
        read_value = ""
        for row in cursor:
            read_value = row[0]
        conn.commit()

        print("========")
        if str(value) == str(read_value):
            print(
                "Key {} succesfuly updated for site id {} with value {}".format(
                    key, site_id, value
                )
            )
        else:
            print(
                "Error updating key {} for site id {} with value {}. The read value was: {}".format(
                    key, site_id, value, read_value
                )
            )
        print("========")


def getSiteConfigKey(conn, key, site_id):
    value = ""
    with conn.cursor() as cursor:
        query = SQL(""" select value from config where key = {} and site_id = {} """)
        query = query.format(Literal(key), Literal(site_id))
        print(query.as_string(conn))

        cursor.execute(query)
        for row in cursor:
            value = row[0]
        conn.commit()

        # get the default value if not found
        if value == "":
            query = SQL(
                """ select value from config where key = {} and site_id is null """
            )
            query = query.format(Literal(key))
            print(query.as_string(conn))

            cursor.execute(query)
            for row in cursor:
                value = row[0]
            conn.commit()

    return value


def unzipFiles(filePath, outDir):
    with ZipFile(filePath, 'r') as zipObj:
       # Extract all the contents of zip file in different directory
       zipObj.extractall(outDir)            

def main():
    parser = argparse.ArgumentParser(
        description="Handles the upload of the Yiel SU Historical Data file"
    )
    parser.add_argument("-c", "--config-file", default="/etc/sen2agri/sen2agri.conf", help="Configuration file location")
    parser.add_argument("-s", "--site-id", required=True, help="Site id for which the file was uploaded")
    parser.add_argument("-i", "--input-file", required=True, help="The uploaded SU Yield historical data file")
    args = parser.parse_args()

    config = Config(args)

    with psycopg2.connect(
        host=config.host,
        dbname=config.dbname,
        user=config.user,
        password=config.password,
    ) as conn:
        site_short_name = getSiteShortName(conn, config.site_id)

        out_dir = getSiteConfigKey(conn, SU_CFG_KEY, config.site_id)
        if out_dir == "":
            print("The {} key is not configured in the database. Creating it ...".format(SU_CFG_KEY))
            out_dir = DEFAULT_SU_PATH
            setConfigValue(conn, None, SU_CFG_KEY, out_dir,)

        out_dir = out_dir.replace("{site}", site_short_name)
        target_dir = Path(out_dir)
        target_dir.mkdir(parents=True, exist_ok=True)
   
        for item in target_dir.iterdir():
            if item.is_file():
                item.unlink()
        
        input_file = os.path.realpath(config.input_file)
        if os.path.splitext(input_file)[1].lower() == ".zip":
            print("Extracting the SU data archive from {} to {}".format(config.input_file, out_dir))
            unzipFiles(config.input_file, out_dir)
        elif os.path.splitext(input_file)[1].lower() == ".gpkg" :
            src_file = Path(config.input_file)
            print("Copying the SU data file from {} to {}".format(config.input_file, out_dir))
            shutil.copy2(src_file, out_dir / src_file.name)

if __name__ == "__main__":
    main()
