#!/usr/bin/env python3

import argparse
import json
import subprocess
import sys
import os

MISSING = object()

def build_initialize_user_site(args, out_site_info_file):
    cmd = ["initialize_user_site.py",
            "--season-start", args.start_date,
            "--season-end", args.end_date,
            "--wkt", args.geom,
            "--out", out_site_info_file
    ]

    if args.config_file:
        cmd += ["--config-file", args.config_file]

    if not args.skip_insitu_import :
        if args.parcels is not None and args.parcels is not MISSING:
            cmd += ["--parcels", args.parcels]

        if args.lut is not None and args.lut is not MISSING:
            cmd += ["--lut", args.lut]
        
    return cmd


def build_stac_search(args, collection, output_stac_entries):
    cmd = ["stac-search-wrapper.py", 
        "--collection", collection,
        "--start-date", args.start_date,
        "--end-date", args.end_date,
        "--geom", args.geom,
        "--output", output_stac_entries
    ]

    return cmd

def wrap_site_json(args, input_file, output_file):
    with open(input_file) as f:
        site_data = json.load(f)

    context_data = {
        "request_parameters": {
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
    parser.add_argument("--use-s1", help="Use Sentinel-1")
    parser.add_argument("--geom", help="Area of interest")
    parser.add_argument("--output-context-info", required=True, help="Output info about the execution context (site, request parameters etc.)")
    parser.add_argument("--output-stac-s2-entries", required=True, help="Output STAC S2 entries")
    parser.add_argument("--output-stac-s1-entries", required=False, help="Output STAC S1 entries")

    parser.add_argument("--parcels", help="Optional parcels.shp", nargs="?", const=MISSING, default=None)
    parser.add_argument("--lut", help="Optional lut.csv", nargs="?", const=MISSING, default=None)
    parser.add_argument("--skip-insitu-import", action="store_true", help="Skip insitu import")
        
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

    cmd = build_stac_search(args, "sentinel-2-l2a", args.output_stac_s2_entries)
    subprocess.run(cmd, check=True)
    if args.use_s1:
        cmd = build_stac_search(args, "sentinel-1-slc", args.output_stac_s1_entries)
        subprocess.run(cmd, check=True)


if __name__ == "__main__":
    main()