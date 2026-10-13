#!/usr/bin/env python

from __future__ import print_function

import argparse
import json
import re
import os
import uuid
import subprocess

import configparser
from pathlib import Path

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

def get_time_series_params(config_file, practice):
    practice = practice.upper()

    parser = configparser.ConfigParser(interpolation=None)
    parser.optionxform = str      # preserve case of keys
    parser.read(config_file)

    default_section = "DEFAULT_TIME_SERIES_ANALYSIS_PARAMS"
    practice_section = f"{practice}_TIME_SERIES_ANALYSIS_PARAMS"

    if default_section not in parser:
        raise ValueError(f"Missing section [{default_section}]")

    if practice_section not in parser:
        raise ValueError(f"Missing section [{practice_section}]")

    # Start with defaults
    params = {
        key.lower(): value.strip().strip('"')
        for key, value in parser[default_section].items()
    }

    prefix = practice + "_"

    # Override with practice-specific values
    for key, value in parser[practice_section].items():
        if key.startswith(prefix):
            base_key = key[len(prefix):].lower()
            params[base_key] = value.strip().strip('"')

    return params
    
def run_time_series_analysis(ts_config_params_file, year, practices, ndvi_mdb, amp_mdb, cohe_mdb, out_dir):
    
    if not os.path.exists(out_dir):
        os.makedirs(out_dir)

    
    for practice in practices:
        cmd_ts_analysis = [
                "otbcli",
                "TimeSeriesAnalysis",
                "-intype", "mcsv",
                "-allowgaps", "1", 
                "-plotgraph", "1",
                "-rescontprd", "0", 
                "-country", "GEN", 
                "-practice", practice,
                "-year", year, 
                "-harvestshp", practicesFile,
                "-diramp", amp_mdb, 
                "-dircohe", cohe_mdb, 
                "-dirndvi", ndvi_mdb,
                "-tillage", "0", 
                "-outdir", out_dir
            ]
        
        practice_params = get_time_series_params(ts_config_params_file, practice)
        for key, value in practice_params.items():
            cmd_ts_analysis.extend([f"-{key}", value])
        
        run_command(cmd_ts_analysis)
    

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
    parser.add_argument("--ndvi-mdb", required=True, help="NDVI MDB1")
    parser.add_argument("--amp-mdb", required=True, help="AMP MDB1")
    parser.add_argument("--cohe-mdb", required=True, help="COHE MDB1")
    parser.add_argument("--out-dir", help="output folder", required=True)
    
    args = parser.parse_args()
    
    result = read_request_context_file(args.request_context_file)
    req_params = result["request_parameters"]
    site_info = result["site_info"]
    
    site_id = site_info["site_id"]
    season_start = site_info["season_start"]
    season_end   = site_info["season_end"]

    start_date = datetime.strptime(season_start, "%Y-%m-%d")
    end_date   = datetime.strptime(season_end,   "%Y-%m-%d")
    year       = end_date.year
    
    run_time_series_analysis(year, args.ndvi_mdb, args.amp_mdb, args.cohe_mdb, args.out_dir)

if __name__ == "__main__":
    main()
    
    