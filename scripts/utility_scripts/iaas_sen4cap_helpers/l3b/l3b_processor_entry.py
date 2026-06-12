#!/usr/bin/env python3

import argparse
import json
import subprocess
import sys
import os

def build_initialize_user_site(args, out_site_info_file):
    cmd = ["initialize_user_site.py"]

    if args.config_file:
        cmd += ["--config-file", args.config_file]

    if args.start_date:
        cmd += ["--season-start", args.start_date]

    if args.end_date:
        cmd += ["--season-end", args.end_date]

    if args.geom:
        cmd += ["--wkt", args.geom]

    cmd += ["--out", out_site_info_file]

    return cmd


def build_stac_search(args):
    cmd = ["stac-search-wrapper.py", "--collection", "sentinel-2-l2a"]

    if args.start_date:
        cmd += ["--start-date", args.start_date]

    if args.end_date:
        cmd += ["--end-date", args.end_date]

    if args.geom:
        cmd += ["--geom", args.geom]

    cmd += ["--output", args.output_stac_entries]

    return cmd

def wrap_site_json(args, input_file, output_file):
    with open(input_file) as f:
        site_data = json.load(f)

    context_data = {
        "request_parameters": {
            "indicator_name": args.indicator_name
        },
        "site_info": site_data
    }
    
    with open(output_file, "w") as f:
        json.dump(context_data, f, indent=4)

def main():
    parser = argparse.ArgumentParser(
        description="L3B Processor Entry script"
    )
    parser.add_argument(
        "-c",
        "--config-file",
        default="/etc/sen2agri/sen2agri.conf",
        help="configuration file location",
    )

    parser.add_argument("--params-file", help="JSON file containing parameters")

    parser.add_argument("--start-date", help="Season start date (YYYY-MM-DD)")
    parser.add_argument("--end-date", help="Season end date (YYYY-MM-DD)")
    parser.add_argument("--indicator-name", help="Name of the Spectral or Biophysical Indicator to be computed", default = "NDVI")
    parser.add_argument("--geom", help="Area of interest")
    parser.add_argument("--output-context-info", required=True, help="Output info about the execution context (site, request parameters etc.)")
    parser.add_argument("--output-stac-entries", required=True, help="Output STAC entries")

    args = parser.parse_args()

    if args.params_file and os.path.exists(args.params_file):
        with open(args.params_file) as f:
            data = json.load(f)
        parser.set_defaults(**data)
        args = parser.parse_args()

    base, ext = os.path.splitext(args.output_context_info)
    out_site_info_file = base + "_site_info" + ext

    cmd = build_initialize_user_site(args, out_site_info_file)
    subprocess.run(cmd, check=True)
    
    wrap_site_json(args, out_site_info_file, args.output_context_info)
    
    cmd = build_stac_search(args)
    subprocess.run(cmd, check=True)


if __name__ == "__main__":
    main()