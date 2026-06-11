#!/usr/bin/env python3

import argparse
import json
import math

from osgeo import ogr, osr


class Config:
    def __init__(self, args):
        from configparser import ConfigParser

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
        import psycopg2

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


def get_tiles_for_geometry(conn, geom):
    with conn.cursor() as cursor:
        query = """
select shape_tiles_s2.tile_id,
        shape_tiles_s2.epsg_code,
        ST_AsBinary(ST_SnapToGrid(ST_Transform(shape_tiles_s2.geog :: geometry, shape_tiles_s2.epsg_code), 1)) as tile_extent
from shape_tiles_s2
where ST_Intersects(shape_tiles_s2.geog, ST_GeogFromWKB(%s));
        """
        cursor.execute(query, (geom.ExportToWkb(),))

        result = []
        srs_cache = {}
        for tile_id, epsg_code, tile_extent_wkb in cursor:
            tile_extent = ogr.CreateGeometryFromWkb(tile_extent_wkb)
            srs = srs_cache.get(epsg_code)
            if not srs:
                srs = osr.SpatialReference()
                srs.ImportFromEPSG(epsg_code)
                srs.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)
                srs_cache[epsg_code] = srs
            tile_extent.AssignSpatialReference(srs)
            result.append((tile_id, epsg_code, tile_extent))
        return result


def main():
    ogr.UseExceptions()

    parser = argparse.ArgumentParser(
        description="Compute tile bounds against an area of interest"
    )
    parser.add_argument(
        "--site-geom", required=True, help="Site geometry as EWKT or GDAL dataset"
    )
    parser.add_argument(
        "--tiles",
        help="Input tile CSV path (tile_id, epsg_code, wkt)",
    )
    parser.add_argument(
        "-c",
        "--config-file",
        default="/etc/sen2agri/sen2agri.conf",
        help="Configuration file location",
    )
    parser.add_argument("--output", required=True, help="Output JSON path")
    args = parser.parse_args()

    site_geom = get_geometry(args.site_geom)
    site_srs = site_geom.GetSpatialReference()

    tiles = []
    if args.tiles is not None:
        with open(args.tiles) as f:
            import csv

            reader = csv.reader(f)

            srs_cache = {}
            for tile_id, epsg_str, wkt_str in reader:
                epsg_code = int(epsg_str)
                srs = srs_cache.get(epsg_code)
                if not srs:
                    srs = osr.SpatialReference()
                    srs.ImportFromEPSG(epsg_code)
                    srs.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)
                    srs_cache[epsg_code] = srs
                geom = ogr.CreateGeometryFromWkt(wkt_str)
                geom.AssignSpatialReference(srs)
                tiles.append((tile_id, epsg_code, geom))
    else:
        config = Config(args)

        wgs84_srs = osr.SpatialReference()
        wgs84_srs.ImportFromEPSG(4326)
        wgs84_srs.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)

        db_geom = site_geom.Clone()
        if not site_srs.IsSame(wgs84_srs):
            transform = osr.CoordinateTransformation(site_srs, wgs84_srs)
            db_geom.Transform(transform)

        with config.get_connection() as conn:
            tiles = get_tiles_for_geometry(conn, db_geom)

    transforms = {}
    tile_intersections = []
    for tile_id, epsg_code, original_geom in tiles:
        tile_geom = original_geom.Clone()
        tile_srs = tile_geom.GetSpatialReference()
        tile_env = tile_geom.GetEnvelope()

        same_srs = site_srs.IsSame(tile_srs)

        if not same_srs:
            if epsg_code not in transforms:
                transforms[epsg_code] = (
                    osr.CoordinateTransformation(tile_srs, site_srs),
                    osr.CoordinateTransformation(site_srs, tile_srs),
                )
            tile_to_site, site_to_tile = transforms[epsg_code]
            tile_geom.Transform(tile_to_site)

        if site_geom.Contains(tile_geom):
            intersection_env = None
        else:
            intersection = site_geom.Intersection(tile_geom)
            if intersection.IsEmpty():
                continue

            if not same_srs:
                intersection.Transform(site_to_tile)
            intersection_env = intersection.GetEnvelope()

        tile_intersections.append((tile_id, tile_env, intersection_env))

    all_results = {}
    for resolution, size in [(10, 10980), (20, 5490)]:
        results = []
        for tile_id, tile_env, intersection_env in tile_intersections:
            if intersection_env is None:
                bbox = None
            else:
                tile_min_x, tile_max_x, tile_min_y, tile_max_y = tile_env
                min_x, max_x, min_y, max_y = intersection_env

                start_x = int(math.floor((min_x - tile_min_x) / resolution))
                end_x = int(math.ceil((max_x - tile_min_x) / resolution))
                start_y = int(math.floor((tile_max_y - max_y) / resolution))
                end_y = int(math.ceil((tile_max_y - min_y) / resolution))

                start_x, start_y = max(0, start_x), max(0, start_y)
                end_x, end_y = min(size, end_x), min(size, end_y)
                width, height = end_x - start_x, end_y - start_y

                if width == 0 or height == 0:
                    continue

                if start_x == 0 and start_y == 0 and width == size and height == size:
                    bbox = None
                else:
                    bbox = [start_x, start_y, width, height]

            results.append({"id": tile_id, "bbox": bbox})
        all_results[str(resolution)] = results

    with open(args.output, "w") as f:
        json.dump(all_results, f, indent=2)


if __name__ == "__main__":
    main()
