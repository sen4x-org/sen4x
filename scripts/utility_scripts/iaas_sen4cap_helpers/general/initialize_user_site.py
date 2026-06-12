#!/usr/bin/env python3

import argparse
import json
import sys
import subprocess
from datetime import datetime
import os
import psycopg2

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

# -------------------------------------------------
# Generate Next Site Name (site_1, site_2, ...)
# -------------------------------------------------
def generate_site_name(cur):
    cur.execute(""" SELECT COUNT(*) FROM site; """)
    count = cur.fetchone()[0]
    return f"site_{count + 1}"

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
def get_existing_site(cur, wkt, start_date, end_date):
    cur.execute("""
        SELECT s.id, se.id
        FROM site s
        JOIN season se ON se.site_id = s.id
        WHERE ST_Equals(
            s.geog::geometry,
            ST_Multi(ST_Force2D(ST_GeometryFromText(%s, 4326)))
        )
        AND se.start_date = %s
        AND se.end_date = %s
        LIMIT 1;
    """, (wkt, start_date, end_date))

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
    
def get_site_tiles(cur, site_id, satellite_id):
    cur.execute(
        "SELECT tile_id FROM sp_get_site_tiles(%s::smallint, %s::smallint)",
        (site_id, satellite_id)
    )
    rows = cur.fetchall()
    tiles = [row[0] for row in rows]
    return tiles
    
# -------------------------------------------------
# Create Site
# -------------------------------------------------
def create_site(cur, name, wkt):
    cur.execute(""" SELECT sp_dashboard_add_site(%s, %s, %s); """, (name, wkt, False))
    return cur.fetchone()[0]


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
def run_data_preparation(config_file, site_id, season_id, year, parcels, lut):
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
            "--parcel-id-cols", "OBJECTID",             # TODO
            "--crop-code-col", "CULT_CODE",             # TODO
            "--holding-id-cols", "holding_id"           # TODO
            
        ]
        print(cmd)
        subprocess.run(cmd, check=True)

# -------------------------------------------------
# Write Output JSON
# -------------------------------------------------
def write_output_json(path, site_id, season_id, season_start, season_end, insitu_path, tiles):
    output = {
        "site_id": site_id,
        "season_id": season_id,
        "season_start": season_start,
        "season_end": season_end,
        "insitu_path": insitu_path,
        "site_tiles" : tiles
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

    try:
        site_id, season_id = get_existing_site(cur, config.wkt, config.season_start, config.season_end)
        if site_id and season_id:
            print(f"Using existing site {site_id} and season {season_id}")
        else:
            site_name = generate_site_name(cur)
            site_id = create_site(cur, site_name, config.wkt)
            print(f"Created new site {site_id}")

            season_name = generate_season_name(cur)
            season_id = create_season(cur, season_name, site_id, config.season_start, config.season_end, config.mid_date)
            print(f"Created new season {season_id}")
            
        site_tiles = get_site_tiles(cur, site_id, S2_SATELLITE_ID)
        print(f"Extracted S2 tiles for site id = {site_id} : {site_tiles}")
            
        conn.commit()
    except Exception as e:
        conn.rollback()
        print("Error:", e)
        sys.exit(1)
    finally:
        cur.close()
        conn.close()

    # Optional processing outside transaction
    year = datetime.strptime(config.season_start, "%Y-%m-%d").year
    run_data_preparation(args.config_file, site_id, season_id, year, config.parcels, config.lut)
    
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
    write_output_json(args.out, site_id, season_id, config.season_start, config.season_end, insitu_prd_path, site_tiles)

    print("Done.")

if __name__ == "__main__":
    main()
    
