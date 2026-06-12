#!/usr/bin/env python

from __future__ import print_function

import argparse
import json
import re
import os
import uuid
import subprocess

from datetime import datetime

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
    parser.add_argument("--path", help="output optical products", default="")
    
    args = parser.parse_args()
    
    result = read_request_context_file(args.request_context_file)
    req_params = result["request_parameters"]
    site_info = result["site_info"]
    
    site_id = site_info["site_id"]
    season_start = site_info["season_start"]
    # season_end = site_info["season_end"]
    year = datetime.strptime(season_start, "%Y-%m-%d").year
    
    cmd_flags = [
        "/usr/share/sen2agri/S4C_L4B_GrasslandMowing/Bin/generate_grassland_mowing_input_shp.py",
        "--config-file", args.config_file,
        "--site-id", str(site_id),
        "--year", str(year),
        "--path", args.path
    ]
    run_command(cmd_flags)

if __name__ == "__main__":
    main()
    
    