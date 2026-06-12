#!/usr/bin/env python

from __future__ import print_function

import argparse
import json
import re
import os
import uuid
import subprocess
import shutil

from datetime import datetime

import psycopg2

try:
    from configparser import ConfigParser
except ImportError:
    from ConfigParser import ConfigParser

try:
    from urllib.parse import urlparse
except ImportError:
    from urlparse import urlparse

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

def get_site_name(conn, site_id):
    with conn.cursor() as cursor:
        query = """
            select short_name
            from site
            where id = %s
            """
        cursor.execute(query, (site_id,))
        rows = cursor.fetchall()
        return rows[0][0]

def get_site_footprint(conn, site_id):
    with conn.cursor() as cursor:
        query = """
            select st_astext(geof)
            from site
            where id = %s
            """
        cursor.execute(query, (site_id,))
        rows = cursor.fetchall()
        return rows[0][0]

def get_config_values(conn, site_id=None):
    prefix = ""
    suffixes = ["lc",
                "min-s2-pix",
                "min-s1-pix",
                "best-s2-pix",
                "pa-min",
                "pa-train-h",
                "pa-train-l",
                "sample-ratio-h",
                "sample-ratio-l",
                "smote-target",
                "smote-k",
                "num-trees",
                "min-node-size",
                "mode"
               ]
    keys = [prefix + s for s in suffixes]
    query = """
        SELECT key, value
        FROM config
        WHERE key = ANY(%s)
          AND (
                (%s IS NOT NULL AND site_id = %s)
             OR (%s IS NULL AND site_id IS NULL)
          )
    """

    with conn.cursor() as cur:
        cur.execute(query, (keys, site_id, site_id, site_id))
        rows = cur.fetchall()

    return {k: v for k, v in rows}
    
def set_processed_product(conn, product_type_id, site_id, full_path, product_name, acquisition_date):
    processor_id = 9
    footprint = "POLYGON((0.0 0.0, 0.0 0.0, 0.0 0.0, 0.0 0.0, 0.0 0.0))"
    try:
        with conn.cursor() as cursor:
            cursor.execute("""select * from sp_insert_product(%(product_type_id)s :: smallint,
                           %(processor_id)s :: smallint,
                           %(satellite_id)s :: smallint,
                           %(site_id)s :: smallint,
                           %(job_id)s :: smallint,
                           %(full_path)s :: character varying,
                           %(created_timestamp)s :: timestamp,
                           %(name)s :: character varying,
                           %(quicklook_image)s :: character varying,
                           %(footprint)s,
                           %(orbit_id)s :: integer,
                           %(tiles)s :: json)""",
                                {
                                    "product_type_id": product_type_id,
                                    "processor_id": processor_id,
                                    "satellite_id": None,
                                    "site_id": site_id,
                                    "job_id": None,
                                    "full_path": full_path,
                                    "created_timestamp": acquisition_date,
                                    "name": product_name,
                                    "quicklook_image": None,
                                    "footprint": footprint,
                                    "orbit_id": None,
                                    "tiles": None
                                })
            row = cursor.fetchone()
            conn.commit()
            if row is None:
                return -1
            product_id = row[0]
            return product_id
    except Exception as e:
        print("Database update query failed: {}".format(e))
        return None
        
def run_command(cmd):
    print("Running:", " ".join(cmd))

    try:
        subprocess.run(cmd, check=True)  # Python 3
    except AttributeError:
        # Python 2 fallback
        ret = subprocess.call(cmd)
        if ret != 0:
            raise RuntimeError("Command failed with exit code {}".format(ret))

def read_request_context_file(request_context_file):

    with open(request_context_file) as f:
        data = json.load(f)

    # "site_info" contains : "site_id", "season_id", "season_start", "season_end", "wkt"
    return {
        "site_info": data.get("site_info", {}),
        "request_parameters": data.get("request_parameters", {})
    }
    
def extract_mdb4_products(mdb4_files_infos):
    results = []
    if os.path.exists(mdb4_files_infos):
        print("S4C L4A: Extracting the marker files from {}".format(mdb4_files_infos))
        i = 0
        map_header = {
            "product_type_id": -1,
            "name": -1,
            "path": -1,
            "created_timestamp": -1,
            "tiles": -1
        }

        with open(mdb4_files_infos, "r") as f:
            for cur_line in f:
                cur_line = cur_line.strip()
                items = cur_line.split(",")
                if i == 0:
                    for j in range(len(items)):
                        map_header[items[j]] = j
                    i += 1
                else:
                    product_type_idx = map_header["product_type_id"]
                    name_idx = map_header["name"]
                    path_idx = map_header["path"]
                    creation_time_idx = map_header["created_timestamp"]
                    tiles_idx = map_header["tiles"]

                    if (0 <= product_type_idx < len(items) and
                        0 <= name_idx < len(items) and
                        0 <= path_idx < len(items) and
                        0 <= creation_time_idx < len(items) and
                        0 <= tiles_idx < len(items)
                    ):
                        print("S4C L4A: Inserting markers product with name = {}, full path = {}".format(items[name_idx],items[path_idx]))
                        entry = {
                            "product_type": int(items[product_type_idx]),
                            "full_path": items[path_idx],
                            "created_timestamp": datetime.strptime(
                                items[creation_time_idx],
                                "%Y-%m-%d %H:%M:%S"
                            ),
                            "name": items[name_idx]
                        }
                        results.append(entry)

                    else:
                        print("S4C L4A: One of required headers was not found in the markers products file with name = {}!".format(mdb4_files_infos))
    else:
        print("S4C L4A: Markers products file with name = {} does not exist!".format(mdb4_files_infos))    
    
    return results

def extract_s4c_l4a_product_infos(file_path):
    results = []

    with open(file_path, "r") as f:
        for line in f:
            full_path = line.strip()
            if not full_path:
                continue  # skip empty lines

            name = os.path.basename(full_path)

            results.append({
                "full_path": full_path,
                "name": name
            })
            print("S4C L4A: Inserting L4A product with name = {}, full path = {}".format(name,full_path))

    return results

def run_crop_type(conn, config_file, site_id, site_name, season_start, season_end, working_dir, out_dir, ct_config_dict, keep_temp_files):
    
    min_date = datetime.strptime(season_start, "%Y-%m-%d")
    max_date = datetime.strptime(season_end, "%Y-%m-%d").replace(hour=23, minute=59, second=59)
    str_time_period = (min_date.strftime("%Y%m%dT%H%M%S") + "_" + max_date.strftime("%Y%m%dT%H%M%S"))    

    ct_working_path = os.path.join(working_dir, "crop_type_working_dir")
    parcels_path = os.path.join(ct_working_path, "parcels.csv")
    lut_path = os.path.join(ct_working_path, "lut.csv");
    tiles_path = os.path.join(ct_working_path, "tiles.csv");
    optical_path = os.path.join(ct_working_path, "optical.csv");
    radar_path = os.path.join(ct_working_path, "radar.csv");
    lpis_path = os.path.join(ct_working_path, "lpis.txt");
    out_marker_files_infos = os.path.join(ct_working_path, "markers_product_infos.csv");
    
    product_formatter_path = os.path.join(working_dir, "product_formatter_output");
    ipp_filepath = os.path.join(product_formatter_path, "execution_infos.txt");
    prd_properties = os.path.join(product_formatter_path, "product_properties.txt");
    
    final_product_path = os.path.join(out_dir, site_name, "s4c_l4a");
    
    if not os.path.exists(ct_working_path):
        os.makedirs(ct_working_path)

    if not os.path.exists(product_formatter_path):
        os.makedirs(product_formatter_path)
    
    extract_parcels_cmd = ["extract-parcels.py", 
                           "--config-file", config_file,
                           "-s", str(site_id),
                           "--season-start", season_start,
                           "--season-end", season_end,
                           "--",
                           parcels_path,
                           lut_path,
                           tiles_path,
                           optical_path,
                           radar_path,
                           lpis_path
                          ]
    
    crop_type_cmd = [   "crop-type-wrapper.py",
                        "-s", str(site_id),
                        "--season-start", season_start,
                        "--season-end", season_end,
                        "--working-path", ct_working_path,
                        "--out-path", product_formatter_path,
                        "--parcels", parcels_path,
                        "--lut", lut_path,
                        "--tile-footprints", tiles_path,
                        "--optical-products", optical_path,
                        "--radar-products", radar_path,
                        "--lpis", lpis_path,
                        "--target-path", final_product_path,
                        "--outputs", out_marker_files_infos];
    
    for key, value in ct_config_dict.items():
        if value: 
            crop_type_cmd.append("--{}".format(key))
            crop_type_cmd.append(str(value))
            
            
    cmd_product_formatter = [
            "otbcli",
            "ProductFormatter",
            "-destroot", final_product_path,
            "-fileclass", "OPER",
            "-level", "S4C_L4A",
            "-baseline", "01.00",
            "-processor", "generic",
            "-siteid", str(site_id),
            "-compress", "0",
            "-vectprd", "1",
            "-gipp", ipp_filepath,
            "-outprops", prd_properties,
            "-processor.generic.files", product_formatter_path,
            "-timeperiod", str_time_period
        ]
                                             
    run_command(extract_parcels_cmd)
    run_command(crop_type_cmd)
    run_command(cmd_product_formatter)
    
    mdb_prds_infos = extract_mdb4_products(out_marker_files_infos)
    for mdb_prd_info in mdb_prds_infos:
        set_processed_product(conn, mdb_prd_info["product_type"], site_id, mdb_prd_info["full_path"], mdb_prd_info["name"],  mdb_prd_info["created_timestamp"])
    
    l4a_prds_infos = extract_s4c_l4a_product_infos(prd_properties)
    results = []
    for l4a_prd_info in l4a_prds_infos:
        product_id = set_processed_product(conn, str(12), site_id, l4a_prd_info["full_path"], l4a_prd_info["name"],  max_date)
        results.append({
                "id":  l4a_prd_info["name"],
                "product": l4a_prd_info["full_path"],
                "product_db_id" : product_id,
                "product_type_id" : str(12),
                "product_metadata": "",
                "relative_orbit": "",
                "orbit_type": "",
                "geometry" : "",
                "parent_products": []
            })
        # TODO: For this should be actually a new component that does the export
        # prd_info_file = os.path.join(product_formatter_path, "db_prd_info.txt")
        # with open(file_path, "w") as f:
        #     line = "{};{}\n".format(product_id, l4a_prd_info["full_path"])
        #     f.write(line)
        #     
        # cmd_export_product_gpkg = [
        #             "export-product-launcher.py",
        #             "-f", prd_info_file
        #             "-o", "CropType.gpkg",
        # ]
        # run_command(cmd_export_product_gpkg)
        
    if not keep_temp_files : 
        shutil.rmtree(ct_working_path)
        shutil.rmtree(product_formatter_path)
        
    return results

def write_stac_products(products, output_file):
    with open(output_file, "w") as f:
        for entry in products:
            product_id = entry["id"]
            product_path = entry["product"]
            product_metadata_path = entry["product_metadata"]
            relative_orbit = entry["relative_orbit"]
            orbit_type = entry["orbit_type"]
            geometry = entry["geometry"]
            parent_products = entry.get("parent_products", [])
            product_db_id = entry.get("product_db_id")
            product_type_id = entry.get("product_type_id")
            item = {
                "id": product_id,
                "geometry": "",
                "type": "Feature",
                "properties": {
                    "product_db_id": product_db_id,
                    "sen4x:disk_path": product_path,
                    "sat:relative_orbit": relative_orbit,
                    "sat:orbit_state": orbit_type,
                    "product_type_id": product_type_id
                },      
                "assets": {
                    "product_metadata": {
                        "href": product_metadata_path
                    }
                },
                "links": []
            }
            if parent_products:
                for parent in parent_products:
                    item["links"].append({
                        "rel": "derived_from",
                        "href": parent
                    })
            json.dump(item, f)
            f.write("\n")

def main():

    parser = argparse.ArgumentParser(
        description="Runs the Crop Type processor"
    )
    parser.add_argument('-c', '--config-file', default="/mnt/tao/cfg/sen4cap/sen2agri.conf", help="configuration file")
    parser.add_argument("--request-context-file", required=True,
                        help="JSON containing the information about the execution context (site, request parameters etc.)")
    parser.add_argument("-i", "--input-products-json", required=True,
                        help="Input JSON file containing products extracted from STAC")
    parser.add_argument("--keep-temp-files", action="store_true", help="Skip insitu import")
    parser.add_argument("-w", "--working-dir", help="Working dir", required=True)
    parser.add_argument("-o", "--out-dir", help="Output Crop Type folder", required=True)
    parser.add_argument("--output-json", required=True, help="Output JSON file containing the produced products")
    
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
    
    if not os.path.exists(args.out_dir):
        os.makedirs(args.out_dir)
    
    result = read_request_context_file(args.request_context_file)
    req_params = result["request_parameters"]
    site_info = result["site_info"]
    
    site_id = site_info["site_id"]
    season_start = site_info["season_start"]
    season_end = site_info["season_end"]
    lpis_prd_path = site_info["insitu_path"]
    
    print("Site ID = {}, lpis path = {}".format(site_id, lpis_prd_path))

    ct_config_dict = get_config_values(conn, site_id)
    site_name = get_site_name(conn, site_id)
    
    products = run_crop_type(conn, args.config_file, site_id, site_name, season_start, season_end, args.working_dir, args.out_dir, ct_config_dict, args.keep_temp_files)
    
    write_stac_products(products, args.output_json)
    
if __name__ == "__main__":
    main()

