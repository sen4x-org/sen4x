#!/usr/bin/env python

from __future__ import print_function

import argparse
import json
import re
import os
import subprocess
import shutil

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
    
def run_tillage(season_start, season_end, mdb1_path, out_csv):
    
    tillage_cmd = [   "s4c_tillage_processor.py",
                        "--start-date", season_start,
                        "--end-date", season_end,
                        "--mdb1-filename", mdb1_path,
                        "--output", out_csv
                  ];
    
    run_command(tillage_cmd)

def main():

    parser = argparse.ArgumentParser(
        description="Runs the Tillage processor"
    )
    parser.add_argument("--request-context-file", required=True,
                        help="JSON containing the information about the execution context (site, request parameters etc.)")
    parser.add_argument("-i", "--mdb1-path", help="MDB1 markers path", required=True)
    parser.add_argument("-o", "--out-csv", help="Output Tillage CSV file", required=True)
    
    args = parser.parse_args()
    
    result = read_request_context_file(args.request_context_file)
    req_params = result["request_parameters"]
    site_info = result["site_info"]
    
    site_id = site_info["site_id"]
    season_start = site_info["season_start"]
    season_end = site_info["season_end"]
    
    print("Site ID = {}, mdb1 path = {}".format(site_id, args.mdb1_path))

    run_tillage(season_start, season_end, args.mdb1_path, args.out_csv)
    
if __name__ == "__main__":
    main()

