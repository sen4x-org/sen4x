#!/usr/bin/env python

from __future__ import print_function

import argparse
import json
import re
import os
import uuid
import subprocess

def run_command(cmd):
    print("Running:", " ".join(str(x) for x in cmd))

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

def main():

    parser = argparse.ArgumentParser(
        description="Runs the L3B Spectral indices processor"
    )
    parser.add_argument(
        "-c",
        "--config-file",
        default="/mnt/tao/cfg/sen4cap/sen2agri.conf",
        help="configuration file location",
    )
    parser.add_argument("--request-context-file", required=True,
                        help="JSON containing the information about the execution context (site, request parameters etc.)")
    parser.add_argument("-i", "--input-products-json", required=True,
                        help="Input JSON file containing products extracted from STAC")
    parser.add_argument("--out-l3b-products-file", help="output optical products", default="")
    parser.add_argument("--out-s1-products-file", help="output radar products", default="")
    
    args = parser.parse_args()
    
    result = read_request_context_file(args.request_context_file)
    req_params = result["request_parameters"]
    site_info = result["site_info"]
    
    site_id = site_info["site_id"]
    season_start = site_info["season_start"]
    season_end = site_info["season_end"]
    
    cmd_flags = [
        "/usr/share/sen2agri/S4C_L4B_GrasslandMowing/Bin/s4c-l4b-extract-products.py",
        "--config-file", args.config_file,
        "--site-id", str(site_id),
        "--season-start", season_start,
        "--season-end", season_end
    ]
    if args.out_l3b_products_file: 
        cmd_flags += ["--out-l3b-products-file", args.out_l3b_products_file]

    if args.out_s1_products_file: 
        cmd_flags += ["--out-s1-products-file", args.out_s1_products_file]
        
    run_command(cmd_flags)

if __name__ == "__main__":
    main()
    
    