#!/usr/bin/env python

from __future__ import print_function

import argparse
import json
import subprocess

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

def run_model(sensor, bs_calib_path, mdb_file, out_model, out_csv, site_tiles):
    
    exec_script = "s4c_bs_model_s2.py"
    calib_flag = "--s2-bs-calib"
    if sensor == "s1":
        exec_script = "s4c_bs_model_s1.py"
        calib_flag = "--s1-bs-calib"
    model_cmd = [exec_script, 
                           "--input", mdb_file,
                           calib_flag, bs_calib_path,
                           "--output", out_csv,
                           "--output-model", out_model,
                           "--tiles", " ".join(site_tiles)
                    ]
    run_command(model_cmd)

def main():

    parser = argparse.ArgumentParser(
        description="Runs the Bare Soil Model application"
    )
    parser.add_argument("--request-context-file", required=True,
                        help="JSON containing the information about the execution context (site, request parameters etc.)")
    parser.add_argument("--mdb-file", required=True, help="Input MDB (MDB1 or MDB4) ipc file")
    parser.add_argument("--bs-calib-file", required=True, help="File resulted after calibration")
    parser.add_argument("-o", "--out-csv", help="Output file containing S2 results", required=True)
    parser.add_argument("-m", "--out-model", help="Output Bare Soil model file", required=True)
    parser.add_argument("--sensor", choices=["s1", "s2"], required=True, help="Choose sensor: s1 or s2")
    
    args = parser.parse_args()
    
    result = read_request_context_file(args.request_context_file)
    req_params = result["request_parameters"]
    site_info = result["site_info"]
    
    site_id = site_info["site_id"]
    lpis_prd_path = site_info["insitu_path"]
    site_tiles = site_info["site_tiles"] 
    
    print("Site ID = {}, lpis path = {}, site tiles = {}".format(site_id, lpis_prd_path, site_tiles))

    run_model(args.sensor, args.bs_calib_file, args.mdb_file, args.out_model, args.out_csv, site_tiles)
    
if __name__ == "__main__":
    main()

