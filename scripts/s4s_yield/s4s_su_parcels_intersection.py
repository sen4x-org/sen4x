#!/usr/bin/env python3
from __future__ import print_function

import argparse
import sys
from osgeo import ogr
import csv
from configparser import ConfigParser
import psycopg2
from psycopg2.sql import SQL, Literal, Identifier

from osgeo import gdal

# gdal.SetConfigOption("CPL_DEBUG", "ON")

# ----------------------------
# Input files
# ----------------------------
parcel_id_field = "parcel_id"

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
        self.season_id = args.season_id

def get_connection(config):
    return psycopg2.connect(
        host=config.host,
        port=config.port,
        dbname=config.dbname,
        user=config.user,
        password=config.password,
    )
    
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


def main():
    parser = argparse.ArgumentParser(
        description="Parcels to SU mapping intersection"
    )
    parser.add_argument(
        "-c",
        "--config-file",
        default="/etc/sen2agri/sen2agri.conf",
        help="configuration file location",
    )
    parser.add_argument(
        "--site-id", required=True, help="The site id"
    )
    parser.add_argument(
        "--season-id", required=True, help="The season id"
    )
    parser.add_argument(
        "-s", "--su-path", required=True, help="The shapefile containing the statistical units"
    )
    parser.add_argument(
        "-u", "--su-unique-id", required=False, help="The shapefile containing the statistical units", default="ID_2"
    )
    parser.add_argument(
        "-o", "--output", required=True, help="The output parcels to SU mapping file"
    )

    args = parser.parse_args()
    
    config = Config(args)
    
    with get_connection(config) as conn:
        print("Retrieving site tiles")
        site_name = get_site_name(conn, config.site_id)
        season_name, season_start_date = get_season_infos(conn, config.season_id)

    pg_conn_str = (
        f"PG:host={config.host} "
        f"port={config.port} "
        f"dbname={config.dbname} "
        f"user={config.user} "
        f"password={config.password}"
    )
    parcels_table = "in_situ_polygons_{}_{}".format(site_name, season_name)
    print(parcels_table)
    
    parcels_ds = ogr.Open(pg_conn_str)
    if parcels_ds is None:
        raise RuntimeError("Could not connect to PostGIS database")

    parcels_layer = parcels_ds.GetLayerByName(parcels_table)
    
    layer_def = parcels_layer.GetLayerDefn()
    print("Parcel layer fields:")
    for i in range(layer_def.GetFieldCount()):
        field_def = layer_def.GetFieldDefn(i)
        print("-", field_def.GetName())
    
    # ----------------------------
    # Open data sources
    # ----------------------------
    stats_ds = ogr.Open(args.su_path)
    stat_id_field = args.su_unique_id

    if stats_ds is None:
        raise RuntimeError("Could not open statistical units shapefile")

    stats_layer = stats_ds.GetLayer()

    # ----------------------------
    # Prepare output CSV
    # ----------------------------
    
    rows = []   # collect results instead of writing immediately
    
    with open(args.output, "w", newline="", encoding="utf-8") as f:
#        writer = csv.writer(f)
#        writer.writerow(["NewID", "SU_ID"])

        # ----------------------------
        # Loop through statistical units
        # ----------------------------
        for stat_feat in stats_layer:
            stat_geom = stat_feat.GetGeometryRef()
            stat_id = stat_feat.GetField(stat_id_field)

            # Spatial filter: only parcels intersecting this stat unit
            parcels_layer.SetSpatialFilter(stat_geom)

            for parcel_feat in parcels_layer:
                parcel_geom = parcel_feat.GetGeometryRef()
                # parcel_id = parcel_feat.GetField(parcel_id_field)
                parcel_id = parcel_feat.GetFID()

                # Optional extra check (safe for edge cases)
                if parcel_geom and parcel_geom.Intersects(stat_geom):
                    rows.append((parcel_id, stat_id))

            parcels_layer.ResetReading()

        parcels_layer.SetSpatialFilter(None)

    rows.sort(key=lambda x: x[0])  # sort by parcel_id
    with open(args.output, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["NewID", "SU_ID"])
        writer.writerows(rows)
        
    print("CSV written:", args.output)


if __name__ == "__main__":
    main()
    