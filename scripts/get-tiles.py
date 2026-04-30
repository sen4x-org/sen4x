#!/usr/bin/env python3

import argparse
import csv
from configparser import ConfigParser

import psycopg2
from osgeo import ogr, osr


class Config:
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

    def get_connection(self):
        return psycopg2.connect(
            host=self.host,
            port=self.port,
            dbname=self.dbname,
            user=self.user,
            password=self.password,
        )


def geom_from_ewkt(ewkt):
    srid, wkt = ewkt.split(";", 1)

    srs = osr.SpatialReference()
    srs.ImportFromEPSG(int(srid.split("=", 1)[1]))
    srs.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)

    geom = ogr.CreateGeometryFromWkt(wkt)
    geom.AssignSpatialReference(srs)
    return geom


def get_geometry(site):
    if ";" in site and "=" in site:
        return geom_from_ewkt(site)

    ogr_ds = ogr.Open(site)
    layer = ogr_ds.GetLayer(0)
    feat = next(iter(layer))
    return feat.GetGeometryRef().Clone()


def main():
    parser = argparse.ArgumentParser(
        description="Find Sentinel-2 tiles intersecting an area of interest"
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument(
        "--site-geom",
        help="Site geometry as EWKT or GDAL dataset",
    )
    group.add_argument(
        "--site-id",
        type=int,
        help="Site ID",
    )
    parser.add_argument(
        "-c",
        "--config-file",
        default="/etc/sen2agri/sen2agri.conf",
        help="Configuration file location",
    )
    parser.add_argument(
        "--output", required=True, help="Output tile CSV path (tile_id, epsg_code, wkt)"
    )
    args = parser.parse_args()

    ogr.UseExceptions()

    config = Config(args)
    with config.get_connection() as conn:
        if args.site_id is not None:
            with conn.cursor() as cursor:
                cursor.execute(
                    "select ST_AsBinary(geog) from site where id = %s", (args.site_id,)
                )
                row = cursor.fetchone()
                geom = ogr.CreateGeometryFromWkb(row[0])
                srs = osr.SpatialReference()
                srs.ImportFromEPSG(4326)
                srs.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)
                geom.AssignSpatialReference(srs)
        else:
            geom = get_geometry(args.site_geom)

        source_srs = geom.GetSpatialReference()

        wgs84_srs = osr.SpatialReference()
        wgs84_srs.ImportFromEPSG(4326)
        wgs84_srs.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)

        if not source_srs.IsSame(wgs84_srs):
            transform = osr.CoordinateTransformation(source_srs, wgs84_srs)
            geom.Transform(transform)

        with conn.cursor() as cursor, open(args.output, "w", newline="") as f:
            query = """
                    select tile_id,
                        epsg_code,
                        ST_AsText(ST_SnapToGrid(ST_Transform(ST_GeomFromWKB(geog), epsg_code), 1))
                    from shape_tiles_s2
                    where ST_Intersects(geog, %s);
                """
            cursor.execute(query, (geom.ExportToWkb(),))

            writer = csv.writer(f, quoting=csv.QUOTE_MINIMAL)
            for tile_id, epsg_code, geom in cursor:
                writer.writerow([tile_id, epsg_code, geom])


if __name__ == "__main__":
    main()
