#!/usr/bin/env python
from __future__ import print_function

import argparse
import csv
from collections import defaultdict
from datetime import date
import logging
import multiprocessing.dummy
import os
import os.path
from posixpath import dirname
from osgeo import osr
from osgeo import ogr
import pipes
import psycopg2
from psycopg2.sql import SQL, Literal, Identifier
import psycopg2.extras
import psycopg2.extensions
import shutil
import subprocess
import sys
from pathlib import Path

try:
    from configparser import ConfigParser
except ImportError:
    from ConfigParser import ConfigParser

def try_rm_file(f):
    try:
        os.remove(f)
        return True
    except OSError:
        return False

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

def run_command(args, env=None):
    args = list(map(str, args))
    cmd_line = " ".join(map(pipes.quote, args))
    logging.debug(cmd_line)
    subprocess.call(args, env=env)


def table_exists(conn, schema, name):
    with conn.cursor() as cursor:
        query = SQL(
            """
select exists (
    select *
    from pg_class
    inner join pg_namespace on pg_namespace.oid = pg_class.relnamespace
    where pg_class.relname = %s
      and pg_namespace.nspname = %s
);"""
        )
        cursor.execute(query, (name, schema))
        return cursor.fetchone()[0]

def get_site_srid(conn, parcels_table):
    with conn.cursor() as cursor:
        query = SQL("select Find_SRID('public', %s, 'wkb_geometry')")
        cursor.execute(query, (parcels_table,))
        rows = cursor.fetchall()
        conn.commit()
        return rows[0][0]

def get_site_name(conn, site_id):
    with conn.cursor() as cursor:
        query = SQL("select short_name from site where id = %s")
        cursor.execute(query, (site_id,))
        rows = cursor.fetchall()
        conn.commit()
        return rows[0][0]

def get_season_infos(conn, season_id):
    with conn.cursor() as cursor:
        query = SQL("select name, start_date from season where id = %s")
        cursor.execute(query, (season_id,))
        rows = cursor.fetchall()
        conn.commit()
        return rows[0]

def get_site_srid(conn, parcels_table):
    with conn.cursor() as cursor:
        query = SQL("select Find_SRID('public', %s, 'wkb_geometry')")
        cursor.execute(query, (parcels_table,))
        rows = cursor.fetchall()
        conn.commit()
        return rows[0][0]


class DataExtraction(object):

    def __init__(self, config, season_id, output, parcel_features_csv):
        self.config = config
        self.season_id = season_id

        with self.get_connection() as conn:
            print("Retrieving site name and season name:")
            site_name = get_site_name(conn, config.site_id)
            season_name, season_start_date = get_season_infos(conn, self.season_id)
            print(site_name)
            print(season_name)

        self.parcels_table = "in_situ_polygons_{}_{}".format(site_name, season_name)
        self.parcel_attributes_table = "polygon_attributes_{}_{}".format(
            site_name, season_name
        )
        self.statistical_data_table = "in_situ_data_{}_{}".format(site_name, season_name)
        
        print("Using tables {}, {}, {}".format(self.parcels_table, self.parcel_attributes_table, self.statistical_data_table))

        insitu_path = get_insitu_path(conn, config.site_id)
        insitu_path = insitu_path.replace("{season}", season_name)
        insitu_path = insitu_path.replace("{site}", site_name)

        self.site_name = site_name
        self.season_name = season_name
        self.insitu_path = insitu_path
        self.output = output
        self.parcel_features_csv = parcel_features_csv

    def get_connection(self):
        return psycopg2.connect(
            host=self.config.host,
            port=self.config.port,
            dbname=self.config.dbname,
            user=self.config.user,
            password=self.config.password,
        )

    def get_ogr_connection_string(self):
        return "PG:dbname={} host={} port={} user={} password={}".format(
            self.config.dbname,
            self.config.host,
            self.config.port,
            self.config.user,
            self.config.password,
        )

    def export_parcels(self):
        with self.get_connection() as conn:
            if not table_exists(conn, "public", self.parcels_table):
                logging.info("Parcels table {} does not exist, skipping export".format(self.parcels_table))
                sys.exit(1)

            try_rm_file(self.output)

            sql = SQL(
                """
select parcels.parcel_id,
    parcels.wkb_geometry,
    parcel_attributes.geom_valid,
    parcel_attributes.area_meters,
    statistical_data.crop_code,
    statistical_data.crop_id,
    crop_list_n3.code_n3,
    crop_list_n2.code_n2,
    crop_list_n2.code_n1
from {} parcels
inner join {} parcel_attributes using (parcel_id)
inner join {} statistical_data using (parcel_id)
inner join crop_list_n4 on statistical_data.crop_code = crop_list_n4.code_n4
inner join crop_list_n3 using (code_n3)
inner join crop_list_n2 using (code_n2)
where parcel_attributes.geom_valid = true

"""
            ).format(
                Identifier(self.parcels_table),
                Identifier(self.parcel_attributes_table),
                Identifier(self.statistical_data_table),
            )
            sql = sql.as_string(conn)
            
            srid = get_site_srid(conn, self.parcels_table)
            command = []
            command += ["ogr2ogr"]
            command += ["-overwrite"]
            command += ["-a_srs", "EPSG:{}".format(srid)]
            command += ["-sql", sql]
            command += [self.output]
            command += [ self.get_ogr_connection_string() ]
            
            run_command(command)

    def export_parcels_features_csv(self):
        
        if self.parcel_features_csv == "":
            return
        
        output_dir = os.path.dirname(self.parcel_features_csv)
        output_dir_tmp = os.path.join(output_dir, "temp")
        output_file_layer = Path(self.parcel_features_csv).stem
        output_file_name =  os.path.basename(self.parcel_features_csv)
        
        with self.get_connection() as conn:
            if not table_exists(conn, "public", self.parcels_table):
                logging.info("Parcels table {} does not exist, skipping export".format(self.parcels_table))
                sys.exit(1)

            try_rm_file(self.parcel_features_csv)
            shutil.rmtree(output_dir_tmp, ignore_errors=True)

            sql = SQL(
                """
select parcels.parcel_id,
    statistical_data.crop_code,
    parcel_attributes.area_meters
from {} parcels
inner join {} parcel_attributes using (parcel_id)
inner join {} statistical_data using (parcel_id)
inner join crop_list_n4 on statistical_data.crop_code = crop_list_n4.code_n4
inner join crop_list_n3 using (code_n3)
inner join crop_list_n2 using (code_n2)
where parcel_attributes.geom_valid = true
order by parcels.parcel_id asc

"""
            ).format(
                Identifier(self.parcels_table),
                Identifier(self.parcel_attributes_table),
                Identifier(self.statistical_data_table),
            )
            sql = sql.as_string(conn)
            
            srid = get_site_srid(conn, self.parcels_table)
            command = []
            command += ["ogr2ogr"]
            command += ["-overwrite"]
            command += ["-a_srs", "EPSG:{}".format(srid)]
            command += ["-f", "CSV"]
            command += ["-sql", sql]
            command += ["-nln", output_file_layer]
            command += [output_dir_tmp]
            command += [ self.get_ogr_connection_string() ]
            
            run_command(command)
            
            tmp_file_path = os.path.join(output_dir_tmp, output_file_name)
            normalize_csv(tmp_file_path)
            
            shutil.move(tmp_file_path, output_dir)
            shutil.rmtree(output_dir_tmp, ignore_errors=True)
            

def get_insitu_path(conn, site_id):
    with conn.cursor() as cursor:
        query = SQL(
            """
select value
from sp_get_parameters('processor.insitu.path')
where site_id is null or site_id = %s
order by site_id;"""
        )
        cursor.execute(query, (site_id,))

        path = cursor.fetchone()[0]
        conn.commit()

        return path

def normalize_csv(csv_path):
    csv_path = Path(csv_path)
    tmp_path = csv_path.with_suffix(".tmp")

    with csv_path.open("r", newline="", encoding="utf-8") as fin, \
         tmp_path.open("w", newline="", encoding="utf-8") as fout:

        reader = csv.reader(fin)
        writer = csv.writer(
            fout,
            quoting=csv.QUOTE_MINIMAL,  # removes unnecessary quotes
        )

        header = next(reader)
        header = ["NewID" if h == "parcel_id" else h for h in header]
        writer.writerow(header)

        for row in reader:
            writer.writerow(row)

    tmp_path.replace(csv_path)

def main():
    parser = argparse.ArgumentParser(description="Export parcels for yield data extraction")
    parser.add_argument(
        "-c",
        "--config-file",
        default="/etc/sen2agri/sen2agri.conf",
        help="configuration file location",
    )
    parser.add_argument(
        "-s", "--site-id", type=int, required=True, help="site ID to filter by"
    )
    parser.add_argument("--season-id", help="season", type=int)
    parser.add_argument("-d", "--debug", help="debug mode", action="store_true")
    parser.add_argument("-w", "--working-path", help="working path")
    parser.add_argument("-o", "--output", help="the output gpkg file")
    parser.add_argument("-p", "--parcel-features-csv", help="output file containing the mapping from id to crop type and area", required=False, default="")

    args = parser.parse_args()

    if args.debug:
        level = logging.DEBUG
    else:
        level = logging.INFO

    logging.basicConfig(level=level)

    config = Config(args)
    data_extraction = DataExtraction(config, args.season_id, args.output, args.parcel_features_csv)

    data_extraction.export_parcels()
    data_extraction.export_parcels_features_csv()


if __name__ == "__main__":
    main()
