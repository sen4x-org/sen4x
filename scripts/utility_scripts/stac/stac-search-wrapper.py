#!/usr/bin/env python3

import argparse
import json
import subprocess
import sys
import os

def parse_args():
    parser = argparse.ArgumentParser(
        description="Wrapper for stac-search.py supporting params-file"
    )

    parser.add_argument("--params-file", help="JSON file containing parameters")

    parser.add_argument(
        "--collection",
        choices=["sentinel-1-slc", "sentinel-2-l1c", "sentinel-2-l2a"],
    )
    parser.add_argument("--tiles", nargs="+")
    parser.add_argument("--start-date")
    parser.add_argument("--end-date")
    parser.add_argument("--geom")
    parser.add_argument("--output", "-o")

    args = parser.parse_args()

    if args.params_file and os.path.exists(args.params_file):
        with open(args.params_file) as f:
            data = json.load(f)
        parser.set_defaults(**data)
        args = parser.parse_args()

    return args


def build_command(args):
    cmd = ["stac-search.py"]

    if args.collection:
        cmd += ["--collection", args.collection]

    if args.tiles:
        cmd += ["--tiles"] + args.tiles

    if args.start_date:
        cmd += ["--start-date", args.start_date]

    if args.end_date:
        cmd += ["--end-date", args.end_date]

    if args.geom:
        cmd += ["--geom", args.geom]

    if args.output:
        cmd += ["--output", args.output]

    return cmd


def main():
    args = parse_args()

    if not args.collection:
        raise ValueError("collection must be provided (CLI or params-file)")

    cmd = build_command(args)

    subprocess.run(cmd, check=True)


if __name__ == "__main__":
    main()