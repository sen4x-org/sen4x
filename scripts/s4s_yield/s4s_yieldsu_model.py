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

def run_command(args, env=None):
    args = list(map(str, args))
    cmd_line = " ".join(map(pipes.quote, args))

    print(cmd_line)
    result = subprocess.call(args, env=env)
    if result != 0:
        print("WARNING: Command `{}` failed with exit code {}".format(cmd_line, result))

def read_input_files(input_file):
    year_ct_input_files = dict()
    ct_year_input_files = dict()
    if input_file is None or input_file == "":
        return year_ct_input_files,ct_year_input_files    
    input_file_dir = os.path.dirname(input_file)
    with open(input_file, "r") as file:
        # skip headers
        reader = csv.reader(file)
        next(reader)
        for row in reader:
            if len(row) == 3:
                year = row[0]
                crop_type = row[1]
                file_path = row[2]
                abs_path = file_path
                if not os.path.isabs(file_path):
                    abs_path = os.path.join(input_file_dir, file_path)
                if not year in year_ct_input_files:
                    year_ct_input_files[year] = dict()
                year_ct_input_files[year][crop_type] = abs_path

                if not crop_type in ct_year_input_files:
                    ct_year_input_files[crop_type] = dict()
                ct_year_input_files[crop_type][year] = abs_path

    return year_ct_input_files,ct_year_input_files

def read_prev_years_files(input_file):
    input_files = dict()
    if input_file is None or input_file == "":
        return input_files    
    input_file_dir = os.path.dirname(input_file)
    with open(input_file, "r") as file:
        # skip headers
        reader = csv.reader(file)
        next(reader)
        for row in reader:
            if len(row) == 2:
                crop_type = row[0]
                file_path = row[1]
                abs_path = file_path
                if not os.path.isabs(file_path):
                    abs_path = os.path.join(input_file_dir, file_path)
                input_files[crop_type] = abs_path

    return input_files

def merge_yearly_ct_files(years_input_files, output_file) : 
    sorted_years = list(years_input_files.keys())
    sorted_years.sort()
    list_files = []
    for year in sorted_years : 
        list_files.append(years_input_files[year])
    out_header = []
    all_lines = []
    for year, input_file in zip(sorted_years, list_files):
        print("Processing file {} for year {}".format(input_file, year))
        with open(input_file, "r") as file:  
            r = csv.reader(file)
            header = next(r)
            if len(out_header) == 0 and len(header) > 1 : 
                out_header = header
                out_header.insert(len(out_header)-1, "year")
                all_lines.append(out_header)

            # ensure that we have the header
            if len(out_header) > 0 :
                for item in r:
                    item.insert(len(item)-1, year)
                    all_lines.append(item)
    
    with open(output_file, 'w') as csvoutput:
        writer = csv.writer(csvoutput)
        writer.writerows(all_lines)



def main():
    parser = argparse.ArgumentParser(
        description="Yield model computation"
    )
    parser.add_argument(
        "-a", "--algo", required=False, default="rf", help="The algorithm to be used. lm - LinerarRegression, svm - SupportVectortMachine. Default rf = RandomForest", choices=['rf', 'lm', 'svm']
    )
    parser.add_argument(
        "-s", "--selection", required=False, default="none", help="The selection mode. Possible values: automatic or manual or none", choices=['none', 'manual', 'automatic'] 
    )

    parser.add_argument(
        "-m", "--manual-selection-features", required=False, help="The selection features list for the manual mode", nargs='+', type=str
    )

    parser.add_argument(
        "-n", "--max-automatic-features-no", required=False, help="The maximum number of selection features for the automatic mode", type=int, default = 44
    )
    
    parser.add_argument(
        "-i", "--input-features", required=True, help="The input features file"
    )

    parser.add_argument(
        "-t", "--input-training-features", nargs="+", required=False, help="The input training features file", default = None
    )

    parser.add_argument(
        "-r", "--yield-reference", required=True, help="The input yield reference file"
    )

    parser.add_argument(
        "-c", "--crop-codes", required=True, help="List of crop codes"
    )  ### change  ex : -c /mnt/archive/orchestrator_temp/s4s_yield_feat/8067/81836-s4s-merge-lai-with-grid/lai_with_grid.csv -> I saw that the crop type was added in the lai with grid file

    parser.add_argument(
        "-o", "--output", required=True, help="The output estimation file"
    )

    args = parser.parse_args()
    
    input_files, _ = read_input_files(args.input_features)
    training_input_files = dict()
    if args.input_training_features:
        training_input_files, _ = read_input_files(args.input_training_features[0])
        
    prev_years_files = read_prev_years_files(args.yield_reference)
    print("Using the previous years files: {}".format(prev_years_files))
    
    if len(input_files) != 1:
        print("Input files for year does not contains exactly one year but it has = {}. Exiting ...".format(input_files))
        sys.exit(1)

    # If there are provided files that contain the previous years products, we need to merge them
    if args.input_training_features : 
        if not os.path.samefile(args.input_training_features[0], args.input_features) :
            out_file_parent_dir = os.path.dirname(os.path.abspath(args.output))
            output_file, file_extension = os.path.splitext(args.output)
            master_merge_out_path = os.path.join(out_file_parent_dir, output_file + "_prev_years_merge_tmp.csv")
            
            merge_output_files_dict = dict()
            tr_in_files = dict()
            for trainig_file in args.input_training_features:
                _, training_file_info = read_input_files(trainig_file)
                for crop_type, years_dict in training_file_info.items():
                    if crop_type not in tr_in_files:
                        tr_in_files[crop_type] = dict()
                    for year, path in years_dict.items():
                        tr_in_files[crop_type][year] = path    
            
            for crop_type in tr_in_files.keys():
                print(f"Merging training data on ct = {crop_type}")
                years_input_files = tr_in_files[crop_type]

                ct_merge_out_file = output_file + "_prev_years_merge_tmp_" + str(crop_type) + ".csv"
                merge_output_files_dict[str(crop_type)] = ct_merge_out_file
                
                merge_yearly_ct_files(years_input_files, ct_merge_out_file)

            with open(master_merge_out_path, 'w') as out_sg:  
                writer = csv.writer(out_sg)
                writer.writerow(["crop_type", "features_file"])
                for key, value in merge_output_files_dict.items():
                    # In this case, write the relative path instead of the full path
                    # as usually the full path is from a temporary folder
                    # NOTE: Attention in the loading modules to handle the relative path
                    writer.writerow([key, os.path.basename(value)])
            
            # The files extracted this way have priority against the ones in the current product
            prev_years_files = read_prev_years_files(master_merge_out_path)
            
    proc_year = list(input_files.keys())[0]
    ct_input_files = input_files[proc_year]
    
    print("Using the previous years files: {}".format(prev_years_files))

    output_files_dict = dict()
    for crop_type in ct_input_files.keys() : 
        input_file = ct_input_files[crop_type]
        if not crop_type in prev_years_files:
            print("Crop type {} will be ignored as it was not found in the previous years files".format(crop_type))
            continue
        prev_years_file = prev_years_files[crop_type]
        
        output_file, file_extension = os.path.splitext(args.output)
        output_file = output_file + "_" + str(crop_type) + ".csv"
        output_files_dict[str(crop_type)] = output_file
        
        print("Extracting yield features for crop type {} and file {}".format(crop_type, input_file))
        
        command = []
        command += ["S4S_Yield_Model.py", 
                    "--algo", args.algo, 
                    "--selection", args.selection,
                    "--manual-selection-features", args.manual_selection_features,
                    "--max-automatic-features-no", args.max_automatic_features_no,
                    "--input-features", input_file,
                    "--yield-reference", prev_years_file,
                    "--crop-codes", args.crop_codes,
                    "--output", output_file,
                    "--has-trend"
                    ]

        ct_train_input_file = (training_input_files.get(proc_year, {}).get(crop_type))
        if ct_train_input_file:
            print("Using training file {} for crop type {}".format(ct_train_input_file, crop_type))
            command += ["--input-training-features", ct_train_input_file]

        run_command(command)
    
    with open(args.output, 'w') as out_sg:  
        writer = csv.writer(out_sg)
        writer.writerow(["crop_type", "features_file"])
        for key, value in output_files_dict.items():
            # In this case, write the relative path instead of the full path
            # as usually the full path is from a temporary folder
            # NOTE: Attention in the loading modules to handle the relative path
            writer.writerow([key, os.path.basename(value)])

    
if __name__ == "__main__":
    main()
