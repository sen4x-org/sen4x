#!/usr/bin/env python

from __future__ import print_function

import argparse
import json
import re
import os
import uuid
import subprocess

import psycopg2


PRODUCT_MAP = {
    "NDVI":      (36),
    "NDWI":      (40),
    "BRIGHT":    (41),
    "LAI":       (37),
    "FAPAR":     (38),
    "FCOVER":    (39),
}
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


def extract_tile_id(product_id):
    match = re.search(r"_T([0-9]{2}[A-Z]{3})_", product_id)
    if match:
        return match.group(1)
    return None


def read_request_context_file(request_context_file):

    with open(request_context_file) as f:
        data = json.load(f)

    # "site_info" contains : "site_id", "season_id", "season_start", "season_end", "wkt"
    return {
        "site_info": data.get("site_info", {}),
        "request_parameters": data.get("request_parameters", {})
    }

def get_safe_path(path):
    if not path.lower().endswith(".xml"):
        return path
    m = re.search(r'(.+?\.SAFE)/', path)
    if m:
        return m.group(1) + "/"

    return None

def get_products_in_provenance(conn, site_id, parent_product_type, derived_product_type):
    query = """
        SELECT
            child.full_path  AS child_full_path,
            parent.full_path AS parent_full_path
        FROM product_provenance pp
        JOIN product child
            ON child.id = pp.product_id
        JOIN product parent
            ON parent.id = pp.parent_product_id
        WHERE
            child.site_id = %(site_id)s
            AND child.product_type_id = %(derived_product_type)s
            AND parent.product_type_id = %(parent_product_type)s
    """

    result = {}

    with conn.cursor() as cur:
        cur.execute(query, {
            "site_id": site_id,
            "derived_product_type": derived_product_type,
            "parent_product_type": parent_product_type
        })

        for child_fp, parent_fp in cur.fetchall():
            result[parent_fp] = child_fp

    return result
    
def convert_s3_to_local_path(href):
    parsed = urlparse(href)
    return "/" + parsed.netloc + parsed.path

def get_product_type_info(prd_type_str):
    if prd_type_str not in PRODUCT_MAP:
        raise ValueError("Unknown product type: {}".format(prd_type_str))

    product_type_id = PRODUCT_MAP[prd_type_str]

    return prd_type_str, product_type_id
    
def process_input_products_file(conn, input_products_json, site_info, product_type_id) :
    products = []
    
    site_id = site_info["site_id"]
    
    paths_in_provenance = get_products_in_provenance(conn, site_id=site_id, parent_product_type=1, derived_product_type=product_type_id)

    with open(input_products_json) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                data = json.loads(line)
            except ValueError:
                continue

            if "features" in data:
                features = data["features"]
            else:
                features = [data]
            
            for feature in features:
                info = extract_feature_info(feature)
                product_id = info["id"]

                tile_id = info['tile']
                print("tile: {}".format(tile_id))

                xml_path = info["metadata_path"]
                safe_path = get_safe_path(xml_path)
                
                processing_status = "UNPROCESSED"
                value = paths_in_provenance.get(safe_path)
                
                if value is not None:
                    processing_status = "PROCESSED"
                    print("Product {} found already processed for product type {} in {}".format(safe_path, product_type_id, value))
                else:
                    print("Found unprocessed product: {} of product_type = {} and derived product_type_id = {}.".format(xml_path, "1", product_type_id))
                    
                products.append({
                    "id": product_id,
                    "type": "Feature",
                    "properties": {
                        "sen4x:disk_path": safe_path,
                        "sat:relative_orbit": None,
                        "sat:orbit_state": None,
                        "product_type_id": product_type_id,
                        "processing_status": processing_status
                    },
                    "assets": {
                        "product_metadata": {
                            "href": xml_path
                        }
                    },
                    "links": [ 
                        {
                            "rel": "derived_l3b",
                            "href": value
                        }
                    ]
                })            
    return products       
            
def extract_feature_info(feature):

    result = {}

    product_id = feature.get("id")
    result["id"] = product_id
    result["tile"] = extract_tile_id(product_id)

    # Extract only product_metadata href
    feature_properties = feature.get("properties")
    product_path = feature_properties.get("sen4x:disk_path", {})
    result["product_path"] = product_path

    metadata_asset = feature.get("assets", {}).get("product_metadata", {})
    metadata_href = metadata_asset.get("href")
    if metadata_href :
        if metadata_href.startswith("s3://"):
            result["metadata_path"] = convert_s3_to_local_path(metadata_href)
        else :
            result["metadata_path"] = metadata_href

    print(result)
    
    return result
    
def main():

    MISSING = object()
    
    parser = argparse.ArgumentParser(
        description="Runs the L3B Spectral indices processor"
    )
    
    parser.add_argument('-c', '--config-file', default="/mnt/tao/cfg/sen4cap/sen2agri.conf", help="configuration file")
    parser.add_argument("-i", "--input-products-json", required=True,
                        help="Input JSON file containing products extracted from STAC")    
    parser.add_argument("--request-context-file", required=True,
                        help="JSON containing the information about the execution context (site, request parameters etc.)")
    parser.add_argument("-o", "--out-filtered-l2a", required=True, help="Output JSON file containing the filtered L2A products not processed for the specific L3B product type")
    
    parser.add_argument("--indicator-name", nargs="?", const=MISSING, default=None)
    
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

    result = read_request_context_file(args.request_context_file)
    req_params = result["request_parameters"]
    site_info = result["site_info"]
    
    if args.indicator_name is None or args.indicator_name is MISSING:
        indicator_name = req_params["indicator_name"]
        print("Using indicator name = {} extracted from the request context".format(indicator_name))
    else :
        indicator_name = args.indicator_name
        print("Using indicator name = {} provided as parameter to the script".format(indicator_name))
    
    prd_str, product_type_id = get_product_type_info(indicator_name)
    
    products = process_input_products_file(conn, args.input_products_json, site_info, product_type_id)
       
    with open(args.out_filtered_l2a, "w") as f:
        for product in products:
            json.dump(product, f)
            f.write("\n")
        
if __name__ == "__main__":
    main()
    
    