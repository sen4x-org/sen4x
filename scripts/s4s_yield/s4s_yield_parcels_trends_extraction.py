#!/usr/bin/env python

import argparse
from collections import defaultdict
from datetime import date
import datetime as dt
# from datetime import datetime
from datetime import timedelta
from glob import glob
import multiprocessing.dummy
import os
import os.path
import re
import pipes
import shutil
import subprocess
import sys
import csv
import errno
import pandas as pd

def read_input_files(input_file):
    input_files = dict()
    if input_file is None or input_file == "":
        return input_files    
    input_file_dir = os.path.dirname(input_file)
    with open(input_file, "r") as file:
        # skip headers
        reader = csv.reader(file)
        next(reader)
        for row in reader:
            if len(row) == 3:
                year = int(row[0])
                crop_type = row[1]
                file_path = row[2]
                abs_path = file_path
                if not os.path.isabs(file_path):
                    abs_path = os.path.join(input_file_dir, file_path)
                if not year in input_files:
                    input_files[year] = dict()
                input_files[year][crop_type] = abs_path
                    
    return input_files

def get_year_entry(input_files, year):
    if not input_files:
        raise ValueError("input_files is empty")

    if year in input_files:
        return year, input_files[year]

    latest_year = max(input_files)
    return latest_year, input_files[latest_year]

def main():
    parser = argparse.ArgumentParser(
        description="Performs the extraction of the trends for each parcel"
    )
    parser.add_argument("-t", "--trend-features-list-file", help="File containing the trend features files for each crop", required=True)
    parser.add_argument("-p", "--parcels-info", help="File containing parcel infos (crop type and others)", required=True)
    parser.add_argument("-m", "--parcels-to-su", help="File containing the mapping from parcels to SU", required=True)
    parser.add_argument("-o", "--output", help="Output merged file", required=True)
    parser.add_argument('-y', '--year', type=int, help="Year where to compute", required=False, default=0)
    
    args = parser.parse_args()
    
    trend_input_files = read_input_files(args.trend_features_list_file)

    year_used, crop_type_files = get_year_entry(trend_input_files, args.year)
            
    df_parcel_crop = pd.read_csv(args.parcels_info)            
    df_parcel_su = pd.read_csv(args.parcels_to_su)
    
    df_parcels = df_parcel_su.merge(
        df_parcel_crop, on="NewID", how="inner"
    )
            
    trend_dfs = []

    for crop_code, file_path in crop_type_files.items():
        df = pd.read_csv(file_path).rename(
            columns={"NewID": "SU_ID"}
        )
        # Ensure expected columns exist
        if not {"SU_ID", "Trend"}.issubset(df.columns):
            raise ValueError(f"Invalid trend file structure: {file_path}")

        df["crop_code"] = int(crop_code)

        trend_dfs.append(df)

    df_trends = pd.concat(trend_dfs, ignore_index=True)
            
    df_result = df_parcels.merge(
        df_trends,
        on=["SU_ID", "crop_code"],
        how="left"
    )
    cols = ["NewID", "SU_ID", "Trend"]
    df_result[cols].sort_values(by="NewID").to_csv(args.output, index=False)
    
if __name__ == "__main__":
    main()
