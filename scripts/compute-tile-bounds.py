#!/usr/bin/env python3

import argparse
import csv
import json
import math
from osgeo import ogr, osr


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
    ogr.UseExceptions()

    parser = argparse.ArgumentParser(
        description="Compute tile bounds against an area of interest"
    )
    parser.add_argument(
        "--site-geom", required=True, help="Site geometry as EWKT or GDAL dataset"
    )
    parser.add_argument(
        "--tiles",
        required=True,
        help="Input tile CSV path (tile_id, epsg_code, wkt)",
    )
    parser.add_argument("--output", required=True, help="Output JSON path")
    args = parser.parse_args()

    site_geom = get_geometry(args.site_geom)
    site_srs = site_geom.GetSpatialReference()

    tiles = []
    with open(args.tiles) as f:
        reader = csv.reader(f)

        for row in reader:
            tile_id, epsg_str, wkt_str = row
            epsg_code = int(epsg_str)
            srs = osr.SpatialReference()
            srs.ImportFromEPSG(epsg_code)
            srs.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)
            geom = ogr.CreateGeometryFromWkt(wkt_str)
            geom.AssignSpatialReference(srs)
            tiles.append((tile_id, epsg_code, geom))

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
