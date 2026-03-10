#!/usr/bin/env python3
import sys
import argparse
import json
from datetime import datetime, timedelta
from osgeo import ogr
from pystac_client import Client
from pystac_client.stac_api_io import StacApiIO
from urllib3 import Retry
from urllib.parse import urlparse, urlunparse
from pathlib import PurePosixPath

CDSE_API_URL = "https://stac.dataspace.copernicus.eu/v1"
SEN4X_SCHEMA_URL = "https://example.com/stac/sen4x/v1.0.0/schema.json"


def main():
    ogr.UseExceptions()

    parser = argparse.ArgumentParser(
        description="Query a STAC API and output JSONL STAC features."
    )
    parser.add_argument(
        "--collection",
        required=True,
        choices=["sentinel-1-slc", "sentinel-2-l1c", "sentinel-2-l2a"],
        help="STAC collection to query",
    )
    parser.add_argument("--tiles", nargs="+", help="Sentinel-2 tile IDs")
    parser.add_argument("--start-date", help="Start date (YYYY-MM-DD), inclusive")
    parser.add_argument("--end-date", help="End date (YYYY-MM-DD), inclusive")
    parser.add_argument("--geom", help="WKT geometry for filtering")
    parser.add_argument("--output", "-o", help="Output file (default: stdout)")
    args = parser.parse_args()

    search_kwargs = {"collections": [args.collection]}

    if args.tiles:
        if len(args.tiles) == 1:
            search_kwargs["filter"] = f"grid:code = 'MGRS-{args.tiles[0]}'"
        else:
            tiles_str = ", ".join(f"'MGRS-{t}'" for t in args.tiles)
            search_kwargs["filter"] = f"grid:code IN ({tiles_str})"

    start_date_str = ".."
    if args.start_date:
        start_date_str = datetime.strptime(args.start_date, "%Y-%m-%d").strftime(
            "%Y-%m-%dT00:00:00Z"
        )

    end_date_str = ".."
    if args.end_date:
        end_date_str = (
            datetime.strptime(args.end_date, "%Y-%m-%d") + timedelta(days=1)
        ).strftime("%Y-%m-%dT00:00:00Z")

    if args.start_date or args.end_date:
        search_kwargs["datetime"] = f"{start_date_str}/{end_date_str}"

    if args.geom:
        input_geom = ogr.CreateGeometryFromWkt(args.geom)
        search_kwargs["intersects"] = json.loads(input_geom.ExportToJson())

    retry = Retry(
        total=20,
        backoff_factor=1,
        status_forcelist=[429, 502, 503, 504],
        allowed_methods=None,
    )
    stac_api_io = StacApiIO(max_retries=retry)
    client = Client.open(CDSE_API_URL, stac_io=stac_api_io)
    search = client.search(**search_kwargs)

    if args.output:
        output_stream = open(args.output, "w")
    else:
        output_stream = sys.stdout

    try:
        for feature in search.items_as_dicts():
            assets = feature.get("assets", {})

            s3_path = None
            safe_manifest = assets.get("safe_manifest", {}).get("href", "")
            if safe_manifest.startswith("s3://"):
                url = urlparse(safe_manifest)
                path = str(PurePosixPath(url.path).parent) + "/"
                s3_path = urlunparse(url._replace(path=path))

            disk_path = None
            if s3_path:
                disk_path = s3_path[4:]

            granule_name = None
            granule_metadata = assets.get("granule_metadata", {}).get("href", "")
            if granule_metadata:
                url = urlparse(granule_metadata)
                granule_name = PurePosixPath(url.path).parent.name

            offsets = {}
            for asset_name, asset in assets.items():
                roles = asset.get("roles", [])
                if "reflectance" in roles and "sampling:original" in roles:
                    offset = asset.get("raster:offset")
                    scale = asset.get("raster:scale")
                    if offset is not None and scale is not None:
                        band_name = asset_name.split("_")[0]
                        offsets[band_name] = int(offset / scale)

            if "properties" not in feature:
                feature["properties"] = {}
            properties = feature["properties"]
            if s3_path:
                properties["sen4x:s3_path"] = s3_path
            if disk_path:
                properties["sen4x:disk_path"] = disk_path
            if granule_name:
                properties["sen4x:granule"] = granule_name
            if offsets:
                properties["sen4x:offsets"] = offsets

            if "stac_extensions" not in feature:
                feature["stac_extensions"] = []
            feature["stac_extensions"].append(SEN4X_SCHEMA_URL)

            output_stream.write(json.dumps(feature) + "\n")
    finally:
        if args.output:
            output_stream.close()


if __name__ == "__main__":
    main()
