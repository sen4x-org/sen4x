#!/usr/bin/env python3

import argparse
import json
import sys
import subprocess
from datetime import datetime
import os
import psycopg2
from pathlib import Path
from psycopg2.sql import SQL, Identifier, Literal
from osgeo import gdal, ogr, osr
import tempfile
import csv

from configparser import ConfigParser

INSITU_DATA_PRODUCT_TYPE_ID = 14
S2_SATELLITE_ID = 1

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
        
        self.wkt = args.wkt
        self.season_start = args.season_start
        self.season_end = args.season_end
        self.validate_dates(self.season_start, self.season_end)
        self.mid_date = self.compute_mid_date(self.season_start, self.season_end)

        self.parcels = args.parcels
        self.lut = args.lut
        
        self.parcel_id_cols = args.parcel_id_cols
        self.crop_code_col = args.crop_code_col
        self.holding_id_cols = args.holding_id_cols
        
    def validate_dates(self, start, end):
        try:
            start_date = datetime.strptime(start, "%Y-%m-%d")
            end_date = datetime.strptime(end, "%Y-%m-%d")
        except ValueError:
            raise ValueError("Dates must be in YYYY-MM-DD format")

        if start_date >= end_date:
            raise ValueError("Season start must be before season end")

    def compute_mid_date(self, start_str, end_str):
        start_date = datetime.strptime(start_str, "%Y-%m-%d")
        end_date = datetime.strptime(end_str, "%Y-%m-%d")

        mid_date = start_date + (end_date - start_date) / 2

        return mid_date.date().isoformat()

class Tile:
    def __init__(self, tile_id, epsg_code, tile_extent):
        self.tile_id = tile_id
        self.epsg_code = epsg_code
        self.tile_extent = tile_extent


def get_user_by_tao_id(cur, tao_user_id):
    cur.execute("""
        SELECT id
        FROM public.user
        WHERE login = %s
        LIMIT 1;
    """, (tao_user_id,))

    row = cur.fetchone()
    return row[0] if row else None


def create_sen4cap_user(cur, tao_user_id):
    dummy_email = f"{tao_user_id}@sen4cap.local"

    cur.execute("""
        SELECT public.sp_insert_update_user(%s, %s);
    """, (tao_user_id, dummy_email))

    # Get the generated Sen4CAP user ID
    user_id = get_user_by_tao_id(cur, tao_user_id)

    if user_id is None:
        raise RuntimeError(
            f"Failed to create Sen4CAP user for TAO user '{tao_user_id}'"
        )

    return user_id
    
def add_site_to_user(cur, user_id, site_id):
    cur.execute("""
        UPDATE public.user
        SET site_id = COALESCE(site_id, ARRAY[]::integer[]) || %s
        WHERE id = %s;
    """, ([site_id], user_id))   
    
# -------------------------------------------------
# Generate Next Site Name (site_1, site_2, ...)
# -------------------------------------------------
def generate_site_name(cur, user_id):
    cur.execute("""SELECT COALESCE(MAX(id), 0) + 1 FROM site;""")
    next_id = cur.fetchone()[0]
    return f"user_{user_id}_site_{next_id}"

def generate_season_name(cur):
    cur.execute("SELECT COUNT(*) FROM season;")
    count = cur.fetchone()[0]
    return f"season_{count + 1}"
    
def get_latest_product_by_type(conn, site_id, product_type_id):
    with conn.cursor() as cursor:
        cursor.execute("""
        SELECT full_path
        FROM product
        WHERE site_id = %s and product_type_id = %s
        ORDER BY inserted_timestamp DESC
        LIMIT 1;
    """, (site_id, product_type_id,))
        row = cursor.fetchone()

        if row is None:
            return None

        return row[0]
        
# -------------------------------------------------
# Check if site exists by geometry
# -------------------------------------------------
def get_existing_site(cur, user_id, wkt, start_date, end_date):
    cur.execute("""
        SELECT s.id, se.id
        FROM site s
        JOIN season se ON se.site_id = s.id
        JOIN public.user u ON u.id = %s
        WHERE s.id = ANY(u.site_id)
        AND ST_Equals(
            s.geog::geometry,
            ST_Multi(ST_Force2D(ST_GeometryFromText(%s, 4326)))
        )
        AND se.start_date = %s
        AND se.end_date = %s
        LIMIT 1;
    """, (user_id, wkt, start_date, end_date))

    row = cur.fetchone()

    if row:
        return row[0], row[1]

    return None, None
    
def get_site_by_geometry(cur, wkt):
    cur.execute("""
        SELECT id
        FROM site
        WHERE ST_Equals(
            geog::geometry,
            ST_Multi(ST_Force2D(ST_GeometryFromText(%s, 4326)))
        )
        LIMIT 1;
    """, (wkt,))

    row = cur.fetchone()
    return row[0] if row else None
    
def get_site_tiles(cursor, site_id):
    query = SQL(
        """
select shape_tiles_s2.tile_id,
   shape_tiles_s2.epsg_code,
   ST_AsBinary(ST_SnapToGrid(ST_Transform(shape_tiles_s2.geog :: geometry, shape_tiles_s2.epsg_code), 1)) as tile_extent
from sp_get_site_tiles(%s :: smallint, 1 :: smallint) site_tiles
inner join shape_tiles_s2 on shape_tiles_s2.tile_id = site_tiles.tile_id;"""
    )
    cursor.execute(query, (site_id,))
    rows = cursor.fetchall()
    result = []
    for tile_id, epsg_code, tile_extent in rows:
        tile_extent = ogr.CreateGeometryFromWkb(tile_extent)
        srs = osr.SpatialReference()
        srs.ImportFromEPSG(epsg_code)
        srs.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)
        tile_extent.AssignSpatialReference(srs)
        result.append(Tile(tile_id, epsg_code, tile_extent))

    return result
        
# def get_site_tiles(cur, site_id, satellite_id):
#     cur.execute(
#         "SELECT tile_id FROM sp_get_site_tiles(%s::smallint, %s::smallint)",
#         (site_id, satellite_id)
#     )
#     rows = cur.fetchall()
#     tiles = [row[0] for row in rows]
#     return tiles
    
# -------------------------------------------------
# Create Site
# -------------------------------------------------
def create_site(cur, name, wkt):
    cur.execute(""" SELECT sp_dashboard_add_site(%s, %s, %s); """, (name, wkt, True))
    return cur.fetchone()[0]

def get_site_additional_info(cursor, site_id):
    query = SQL(
        "select short_name, ST_AsBinary(geog::geometry) from site where id = %s"
    )
    cursor.execute(query, (site_id,))
    row = cursor.fetchone()
    if row:
        name, wkb = row
        geom = ogr.CreateGeometryFromWkb(wkb)
        srs = osr.SpatialReference()
        srs.ImportFromEPSG(4326)
        srs.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)
        geom.AssignSpatialReference(srs)
        return name, geom
    return None, None

# -------------------------------------------------
# Check if Season Exists
# -------------------------------------------------
def get_existing_season(cur, site_id, start_date, end_date):
    cur.execute("""
        SELECT id FROM season WHERE site_id = %s
            AND start_date = %s
            AND end_date = %s
        LIMIT 1;
    """, (site_id, start_date, end_date))
    row = cur.fetchone()
    return row[0] if row else None


# -------------------------------------------------
# Create Season
# -------------------------------------------------
def create_season(cur, name, site_id, start_date, end_date, mid_date):
    cur.execute("""
        INSERT INTO season (name, site_id, start_date, end_date, mid_date, enabled)
        VALUES (%s, %s, %s, %s, %s, TRUE)
        RETURNING id;
    """, (name, site_id, start_date, end_date, mid_date))
    return cur.fetchone()[0]


# -------------------------------------------------
# Optional Data Preparation
# -------------------------------------------------
def run_data_preparation(config_file, site_id, season_id, year, parcels, lut, parcel_id_col_name, crop_code_col_name, hold_id_col_name):
    if parcels and lut:
        cmd = [
            "data-preparation.py",
            "-c", config_file,
            "--site-id", str(site_id),
            # "--season-id", str(season_id),
            "--year", str(year),
            "--mode","replace",
            "--lpis", parcels,
            "--lut", lut,
            "--parcel-id-cols", parcel_id_col_name,             
            "--crop-code-col", crop_code_col_name,             
            "--holding-id-cols", hold_id_col_name           
            
        ]
        print(cmd)
        subprocess.run(cmd, check=True)

def compute_tile_bounds(config_file, site_geom, tiles, working_path):
    print("Computing tile bounds")
    output_path = os.path.join(working_path, "tile_bounds.json")

    site_epsg = site_geom.GetSpatialReference().GetAuthorityCode(None)
    site_wkt = f"SRID={site_epsg};{site_geom.ExportToWkt()}"

    with tempfile.NamedTemporaryFile(mode="wt", suffix=".csv") as f:
        writer = csv.writer(f, quoting=csv.QUOTE_MINIMAL)
        for tile in tiles:
            writer.writerow(
                [tile.tile_id, tile.epsg_code, tile.tile_extent.ExportToWkt()]
            )
        f.flush()

        subprocess.check_call(
            [
                str(Path(__file__).parent / "compute-tile-bounds.py"),
                "--config-file", 
                config_file, 
                "--site-geom",
                site_wkt,
                "--tiles",
                f.name,
                "--output",
                output_path,
            ]
        )
    if not os.path.exists(output_path):
        return None
        
    with open(output_path, "r") as f:
        ret_json = json.load(f)
        
    os.remove(output_path)
    
    return ret_json
    
# -------------------------------------------------
# Write Output JSON
# -------------------------------------------------
def write_output_json(path, site_id, site_short_name, season_id, season_start, season_end, insitu_path, tile_ids, tile_bounds):
    output = {
        "site_id": site_id,
        "site_short_name" : site_short_name,
        "season_id": season_id,
        "season_start": season_start,
        "season_end": season_end,
        "insitu_path": insitu_path,
        "site_tiles" : tile_ids,
        "tile_bounds" : tile_bounds
    }
    with open(path, "w") as f:
        json.dump(output, f, indent=4)

# -------------------------------------------------
# Argument Parsing
# -------------------------------------------------
def parse_args():
    parser = argparse.ArgumentParser(description="Create site and season")

    parser.add_argument(
        "-c",
        "--config-file",
        default="/etc/sen2agri/sen2agri.conf",
        help="configuration file location",
    )

    parser.add_argument("--params-file", help="Parameters of the script provided in a file")
    
    parser.add_argument("--wkt", help="Site extent as WKT")
    parser.add_argument("--season-start", help="Season start date (YYYY-MM-DD)")
    parser.add_argument("--season-end", help="Season end date (YYYY-MM-DD)")

    parser.add_argument("--parcels", help="Optional parcels.shp")
    parser.add_argument("--lut", help="Optional lut.csv")
    
    parser.add_argument("--parcel-id-cols", help="Original parcel ID column name", default = "OBJECTID")
    parser.add_argument("--crop-code-col", help="Original crop code column name", default = "CULT_CODE")
    parser.add_argument("--holding-id-cols", help="Original holding id column name", default = "holding_id")
    
    parser.add_argument("--out", required=True, help="Output JSON file path")

    return parser.parse_args()

# -------------------------------------------------
# Main Logic
# -------------------------------------------------
def main():
    args = parse_args()

    if args.params_file and os.path.exists(args.params_file):
        with open(args.params_file) as f:
            data = json.load(f)
        parser.set_defaults(**data)
        args = parser.parse_args()    

    # -------------------------------------------------
    # Get TAO user ID from environment
    # -------------------------------------------------
    tao_username = os.environ.get("TAO_USERNAME")

    if not tao_username:
        raise RuntimeError("TAO_USERNAME environment variable is not set")

    config = Config(args)

    conn = psycopg2.connect(
        host=config.host,
        port=config.port,
        dbname=config.dbname,
        user=config.user,
        password=config.password
    )

    conn.autocommit = False
    cur = conn.cursor()

    working_path = Path(args.out).parent

    try:
        sen4cap_user_id = get_user_by_tao_id(cur, tao_username)
        if sen4cap_user_id is not None:
            print(f"Found Sen4CAP user {sen4cap_user_id} for TAO user {tao_username}")
        else:
            sen4cap_user_id = create_sen4cap_user(cur, tao_username)
            print(f"Created Sen4CAP user {sen4cap_user_id} for TAO user {tao_username}")

        # -------------------------------------------------
        # Check if site already exists FOR THIS USER
        # -------------------------------------------------
        site_id, season_id = get_existing_site(cur, sen4cap_user_id, config.wkt, config.season_start, config.season_end)

        if site_id and season_id:
            print(f"Using existing site {site_id}and season {season_id} for Sen4CAP user {sen4cap_user_id}")
        else:
            # -------------------------------------------------
            # Create new site
            # -------------------------------------------------
            site_name = generate_site_name(cur, sen4cap_user_id)
            site_id = create_site(cur, site_name, config.wkt)
            print(f"Created new site {site_id} ('{site_name}')")

            # -------------------------------------------------
            # Associate site with user
            # -------------------------------------------------
            add_site_to_user(cur, sen4cap_user_id, site_id)
            print(f"Added site {site_id} to Sen4CAP user {sen4cap_user_id}")

            # -------------------------------------------------
            # Create season
            # -------------------------------------------------
            season_name = generate_season_name(cur)
            season_id = create_season(cur, season_name, site_id, config.season_start, config.season_end, config.mid_date)
            print(f"Created new season {season_id}")

        site_tiles = get_site_tiles(cur, site_id)
        tile_ids = [t.tile_id for t in site_tiles]
        site_short_name, site_geom = get_site_additional_info(cur, site_id)
        print(f"Extracted S2 tiles for site id = {site_id} : {tile_ids}")

        conn.commit()
    except Exception as e:
        conn.rollback()
        print("Error:", e)
        sys.exit(1)
    finally:
        cur.close()
        conn.close()

    # -------------------------------------------------
    # Continue with processing
    # -------------------------------------------------
    year = datetime.strptime(config.season_start, "%Y-%m-%d").year
    run_data_preparation(args.config_file, site_id, season_id, year, config.parcels, config.lut, 
                        config.parcel_id_cols, config.crop_code_col, config.holding_id_cols)
    
    tile_bounds = compute_tile_bounds(args.config_file, site_geom, site_tiles, str(working_path))

    conn = psycopg2.connect(
        host=config.host,
        port=config.port,
        dbname=config.dbname,
        user=config.user,
        password=config.password
    )
    cur = conn.cursor()
    try :
        insitu_prd_path = get_latest_product_by_type(conn, site_id, INSITU_DATA_PRODUCT_TYPE_ID)
    except Exception as e:
        conn.rollback()
        print("Error:", e)
        sys.exit(1)
    finally:
        cur.close()
        conn.close()
    
    # Write JSON output
    write_output_json(args.out, site_id, site_short_name, season_id, config.season_start, config.season_end, insitu_prd_path, tile_ids, tile_bounds)

    print("Done.")

if __name__ == "__main__":
    main()
    