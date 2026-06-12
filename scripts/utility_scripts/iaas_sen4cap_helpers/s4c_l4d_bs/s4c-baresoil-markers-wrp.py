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

def run_markers(input_s2, input_s1, season_start, season_end, out_markers_s2, out_markers_s1, out_markers_all):
    
    model_cmd = [   "s4c_bs_markers.py", 
                    "--input-s2", input_s2,
                    "--input-s1", input_s1,
                    "--out-markers-s2", out_markers_s2,
                    "--out-markers-s1", out_markers_s1,
                    "--out-markers-all", out_markers_all,
                    "--start-date", season_start,
                    "--end-date", season_end
                ]
    run_command(model_cmd)

def main():

    parser = argparse.ArgumentParser(
        description="Runs the Bare Soil Model application"
    )
    parser.add_argument("--request-context-file", required=True,
                        help="JSON containing the information about the execution context (site, request parameters etc.)")
    parser.add_argument("--input-s2", required=True, help="Input S2 results file")
    parser.add_argument("--input-s1", required=True, help="Input S1 results file")
    parser.add_argument("-m", "--out-markers-s2", help="Output S2 markers", required=True)
    parser.add_argument("-n", "--out-markers-s1", help="Output S1 markers", required=True)
    parser.add_argument("-o", "--out-markers-all", help="All markers output", required=True)
    
    args = parser.parse_args()
    
    result = read_request_context_file(args.request_context_file)
    req_params = result["request_parameters"]
    site_info = result["site_info"]
    
    site_id = site_info["site_id"]
    season_start = site_info["season_start"]
    season_end = site_info["season_end"]
    
    print("Site ID = {}, season start = {}, season end = {}".format(site_id, season_start, season_end))

    run_markers(args.input_s2, args.input_s1, season_start, season_end, args.out_markers_s2, args.out_markers_s1, args.out_markers_all)
    
if __name__ == "__main__":
    main()

