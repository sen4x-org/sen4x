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



PRODUCT_MAP = {
    "MSIL2A":                   (1, 1),
    "L3B":                      (3, 3),
    "L3BNDVI":                  (36, 3),
    "L3BNDWI":                  (40, 3),
    "L3BBRIGHT":                (41, 3),
    "L3BLAI":                   (37, 3),
    "L3BFAPAR":                 (38, 3),
    "L3BFCOVER":                (39, 3),
    "AMP":                      (10, 7),
    "COHE":                     (11, 7),
    "L4B":                      (13, 10),
    "S4C_L4B":                  (13, 10),
    "MDB1":                     (17, 14),
    "BARESOIL":                 (33, 26),
    "S4C_BARE_SOIL":            (33, 26),
    "S4C_BARESOIL":             (33, 26),
    "TILLAGE":                  (44, 29),
    "S4C_TILLAGE" :             (44, 29),
    "S4C_TILLAGE_DETECTION":    (44, 29)
    
    # add more mappings here
}


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

def set_processed_product(conn, product_type_id, processor_id, site_id, full_path, product_name, acquisition_date):
    footprint = "POLYGON((0.0 0.0, 0.0 0.0, 0.0 0.0, 0.0 0.0, 0.0 0.0))"
    tao_job_id = os.environ.get("TAO_JOBID")
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
                                    "job_id": tao_job_id,
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
    
def extract_product_infos(file_path):
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
            print("Product Formatter Wrapper: Inserting product with name = {}, full path = {}".format(name,full_path))

    return results

def run_product_formatter(conn, site_id, site_name, input_paths, season_start, season_end, product_type_str, working_dir, out_dir):
    
    
    product_type_id, processor_id = PRODUCT_MAP[product_type_str]
    
    min_date = datetime.strptime(season_start, "%Y-%m-%d")
    max_date = datetime.strptime(season_end, "%Y-%m-%d").replace(hour=23, minute=59, second=59)
    str_time_period = (min_date.strftime("%Y%m%dT%H%M%S") + "_" + max_date.strftime("%Y%m%dT%H%M%S"))    

    product_formatter_path = os.path.join(working_dir, "product_formatter_output");
    ipp_filepath = os.path.join(product_formatter_path, "execution_infos.txt");
    prd_properties = os.path.join(product_formatter_path, "product_properties.txt");
    
    final_product_path = os.path.join(out_dir, site_name, product_type_str);
    
    if not os.path.exists(product_formatter_path):
        os.makedirs(product_formatter_path)
    
    cmd_product_formatter = [
            "otbcli",
            "ProductFormatter",
            "-destroot", final_product_path,
            "-fileclass", "OPER",
            "-level", product_type_str,
            "-baseline", "01.00",
            "-processor", "generic",
            "-siteid", str(site_id),
            "-compress", "0",
            "-vectprd", "1",
            "-gipp", ipp_filepath,
            "-outprops", prd_properties,
            "-timeperiod", str_time_period,
            "-processor.generic.files"
        ] 
    cmd_product_formatter += input_paths         
                                             
    run_command(cmd_product_formatter)
    
    prds_infos = extract_product_infos(prd_properties)
    results = []
    for prd_info in prds_infos:
        product_id = set_processed_product(conn, product_type_id, processor_id, site_id, prd_info["full_path"], prd_info["name"],  max_date)
        results.append({
                "id":  prd_info["name"],
                "product": prd_info["full_path"],
                "product_db_id" : product_id,
                "product_type_id" : product_type_id,
                "product_metadata": "",
                "relative_orbit": "",
                "orbit_type": "",
                "geometry" : "",
                "parent_products": []
            })
    
    # shutil.rmtree(product_formatter_path)
        
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
    parser.add_argument("-i", "--inputs", nargs="+", required=True, help="Input files/folders")
    parser.add_argument("-p", "--product-type", required=True, help="Product type")
    parser.add_argument("-o", "--out-dir", help="Output Product Formatter folder", required=True)
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
    site_short_name = site_info["site_short_name"]
    season_start = site_info["season_start"]
    season_end = site_info["season_end"]
    
    working_dir = os.path.dirname(args.output_json)
    
    print("Site ID = {}, site_short_name = {}, product_type = {}, season_start = {}, season_end = {}".format(site_id, site_short_name, args.product_type, season_start, season_end))
    
    products = run_product_formatter(conn, site_id, site_short_name, args.inputs, season_start, season_end, args.product_type, working_dir, args.out_dir)
    
    write_stac_products(products, args.output_json)
    
if __name__ == "__main__":
    main()
