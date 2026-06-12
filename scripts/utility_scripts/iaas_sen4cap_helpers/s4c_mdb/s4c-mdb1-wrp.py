#!/usr/bin/env python

from __future__ import print_function

import argparse
import json
import re
import os
import uuid
import subprocess
import fnmatch

from multiprocessing import Pool

from datetime import datetime


try:
    from urllib.parse import urlparse
except ImportError:
    from urlparse import urlparse
    

class LpisInfos(object):
    def __init__(self,
                 product_path="",
                 optical_ids_geom_shape_path="",
                 sar_geom_shape_paths=None,
                 opt_tiles_geoms_rasters=None,
                 sar_tiles_geoms_rasters=None):

        self.product_path = product_path
        self.optical_ids_geom_shape_path = optical_ids_geom_shape_path
        self.sar_geom_shape_paths = sar_geom_shape_paths or {}
        self.opt_tiles_geoms_rasters = opt_tiles_geoms_rasters or {}
        self.sar_tiles_geoms_rasters = sar_tiles_geoms_rasters or {}
        
class ParcelPrdFilePatterns(object):
    def __init__(self,
                 parcels_csv_file_name_pattern="decl_.*_\d{4}.csv",         # SEN4STAT decl_.*_\d{4}.csv
                 opt_parcels_pattern=".*_buf_5m.shp",                       # SEN4STAT in_?situ_.*_buf_10m.shp
                 sar_parcels_pattern=".*_(\d{4,5})_buf_10m.shp",            # SEN4STAT in_?situ_.*_(\d{4,5})_buf_10m.shp
                 opt_parcels_tiffs_pattern="",
                 sar_parcels_tiffs_pattern="",
):

        self.opt_parcels_pattern = opt_parcels_pattern
        self.sar_parcels_pattern = sar_parcels_pattern
        self.opt_parcels_tiffs_pattern = opt_parcels_tiffs_pattern
        self.sar_parcels_tiffs_pattern = sar_parcels_tiffs_pattern
        
def extract_lpis_infos(site_id, lpis_prd_full_path, parcels_prd_descr) : 
    if not lpis_prd_full_path:
        raise RuntimeError(
            "No LPIS product found in database for the MDB1 execution for site {}.".format(site_id)
        )

    re_opt         = re.compile(parcels_prd_descr.opt_parcels_pattern)
    re_sar         = re.compile(parcels_prd_descr.sar_parcels_pattern)
    re_opt_rasters = re.compile(parcels_prd_descr.opt_parcels_tiffs_pattern)
    re_sar_rasters = re.compile(parcels_prd_descr.sar_parcels_tiffs_pattern)

    allowed_extensions = {".shp", ".csv", ".gpkg", ".tif"}

    directory = lpis_prd_full_path
    print("MDB1: Extracting files for LPIS product {}".format(lpis_prd_full_path))

    # Collect matching files (mirrors QDir::entryList with extension filter)
    dir_files = [
        f for f in os.listdir(directory)
        if os.path.isfile(os.path.join(directory, f)) and
           os.path.splitext(f)[1].lower() in allowed_extensions
    ]

    lpis_info = LpisInfos()

    for file_name in dir_files:
        file_path = os.path.join(directory, file_name)
        print("MDB1: Checking the LPIS file {}".format(file_path))

        # Optical geometry shapefile (first match wins, no LAEA)
        if re_opt.search(file_name) and not lpis_info.optical_ids_geom_shape_path:
            lpis_info.optical_ids_geom_shape_path = file_path
            print("MDB1: Using for Optical products the LPIS file {}".format(file_path))

        # SAR geometry shapefile (LAEA projection has priority; keyed by proj id)
        sar_match = re_sar.search(file_name)
        if sar_match:
            proj_id = sar_match.group(1)
            lpis_info.sar_geom_shape_paths[proj_id] = file_path
            print("MDB1: Using for SAR products the LPIS file {} for projection {}".format(file_path, proj_id))

        # Optical raster tile
        # opt_raster_match = re_opt_rasters.search(file_name)
        # if opt_raster_match:
        #     tile_str = opt_raster_match.group(1)
        #     lpis_info.opt_tiles_geoms_rasters[tile_str] = file_path
        # 
        # # SAR raster tile
        # sar_raster_match = re_sar_rasters.search(file_name)
        # if sar_raster_match:
        #     tile_str = sar_raster_match.group(1)
        #     lpis_info.sar_tiles_geoms_rasters[tile_str] = file_path

    # Only store the result if both mandatory geometry files were found
    if lpis_info.optical_ids_geom_shape_path and lpis_info.sar_geom_shape_paths:
        lpis_info.product_path  = lpis_prd_full_path
        print("MDB1: Using LPIS {}".format(lpis_prd_full_path))
    else:
        print("MDB1: LPIS infos couldn't be extracted from path {}".format(lpis_prd_full_path))

    return lpis_info    

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

def convert_s3_to_local_path(href):
    parsed = urlparse(href)
    return "/" + parsed.netloc + parsed.path

def extract_feature_info(feature):

    result = {}

    product_id = feature.get("id")
    result["id"] = product_id

    # Extract only product_metadata href
    feature_properties = feature.get("properties")
    product_path = feature_properties.get("sen4x:disk_path", {})
    result["product_path"] = product_path

    metadata_asset = feature.get("assets", {}).get("product_metadata", {})
    metadata_href = metadata_asset.get("href")
    if metadata_href :
        if metadata_href.startswith("s3://"):
            result["metadata_path"] = convert_s3_to_local_path(metadata_href)
        else :
            result["metadata_path"] = metadata_href

    print(result)
    
    return result

def get_product_raster(product_path, product_type, product_subtype):
    results = []
    if product_type in ["L2A"]:
        results = get_s2_product_files(product_path, product_subtype)
    if product_type in ["AMP", "COHE", "BCK"]:
        results.append(product_path)
    if product_type in ["NDVI", "LAI", "FAPAR", "FCOVER", "NDWI", "BRGHT"]:
        folder_name = os.path.basename(os.path.normpath(product_path))
        parts = folder_name.split("_")
        date_part = parts[5]          # A20250305T104951
        tile_part = parts[6]          # T31UFR
        # Build inner folder name
        inner_folder = "S2AGRI_L3B{}_{}_{}".format(product_type, date_part, tile_part)
        # Build filename
        if product_type in ["LAI", "FAPAR", "FCOVER"]:
            file_name = "S2AGRI_L3B{}_S{}MONO_{}_{}.TIF".format(product_type, product_type, date_part, tile_part)
        else:
            file_name = "S2AGRI_L3B{}_S{}_{}_{}.TIF".format(product_type, product_type, date_part, tile_part)
        # Construct full path
        full_path = os.path.join(product_path, "TILES", inner_folder, "IMG_DATA", file_name)
        results.append(full_path)
    
    return results
    
def get_raster_files_from_dir(dir_path, file_name_substr_filter="", prefix="*", suffix="*", extensions=[".jp2", ".tif"] ):
    
    print("Extracting rasters from dir {} with pattern = {}, prefix = {}, suffix = {} and extensions = {}".format(dir_path, file_name_substr_filter, prefix, suffix, extensions)) 
    
    if extensions is None:
        extensions = [".jp2", ".JP2", ".tif", ".TIF", ".vrt", ".VRT"]

    if not os.path.isdir(dir_path):
        return []

    patterns = []
    for ext in extensions:
        if file_name_substr_filter:
            patterns.append("{0}{1}{2}{3}".format(prefix, file_name_substr_filter, suffix, ext))
            patterns.append("{0}{1}{2}{3}".format(prefix, file_name_substr_filter, suffix, ext.upper()))
        else:
            patterns.append("*{0}".format(ext))
            patterns.append("*{0}".format(ext.upper()))

    result = []
    try:
        all_files = os.listdir(dir_path)
    except OSError:
        return []

    print(patterns)
    for pattern in patterns:
        for file_name in sorted(all_files):
            if fnmatch.fnmatch(file_name, pattern):
                full_path = os.path.normpath(os.path.join(dir_path, file_name))
                if os.path.isfile(full_path) and full_path not in result:
                    result.append(full_path)

    return result


def get_s2_product_files(meta_file, file_name_substr_filter, prd_details=None):
    ret_list = []
    file_name = os.path.basename(meta_file)
    parent_dir = os.path.dirname(os.path.abspath(meta_file))

    print("Processing {} and band {}".format(meta_file, file_name_substr_filter))

    if file_name == "MTD_MSIL2A.xml":
        # Sen2Cor L2A product
        granules_path = os.path.normpath(os.path.join(parent_dir, "GRANULE"))

        try:
            sub_dirs = os.listdir(granules_path)
        except OSError:
            return ret_list

        for sub_dir_name in sub_dirs:
            sub_dir_path = os.path.normpath(os.path.join(granules_path, sub_dir_name))
            if not os.path.isdir(sub_dir_path):
                continue

            img_path = os.path.normpath(os.path.join(sub_dir_path, "IMG_DATA"))
            rasters_10m_path = os.path.normpath(os.path.join(img_path, "R10m"))

            new_filter = file_name_substr_filter if file_name_substr_filter else "_B*_*0m"

            # First get the rasters in the R10m directory
            rasters_10m = get_raster_files_from_dir(rasters_10m_path, new_filter)
            ret_list.extend(rasters_10m)

            if file_name_substr_filter:
                if rasters_10m:
                    return ret_list
                else:
                    # Try to get from 20m resolution
                    rasters_20m_path = os.path.normpath(os.path.join(img_path, "R20m"))
                    rasters_20m = get_raster_files_from_dir(rasters_20m_path, new_filter)
                    ret_list.extend(rasters_20m)
                    return ret_list
            else:
                if not rasters_10m:
                    raise RuntimeError(
                        "Unsupported L2A Sen2Cor product without 10m res rasters in path {0}".format(full_path)
                    )

                # Get also the raster for 8A from 20m
                rasters_20m_path = os.path.normpath(os.path.join(img_path, "R20m"))
                rasters_20m = get_raster_files_from_dir(rasters_20m_path)
                band_filters = ["_B05", "_B06", "_B07", "_B8A", "_B11", "_B12"]

                for raster_file in rasters_20m:
                    if any(f in os.path.basename(raster_file) for f in band_filters):
                        ret_list.append(raster_file)

            # No need to iterate other dirs
            return ret_list

    elif file_name.startswith("SENTINEL2"):
        # MAJA format - files are in the same directory as the metadata file
        new_filter = "_FRE_" + file_name_substr_filter
        new_filter = new_filter.replace("0", "")
        rasters = get_raster_files_from_dir(parent_dir, new_filter, extensions=[".tif"])
        ret_list.extend(rasters)

    elif file_name.startswith("S2"):
        # MACCS format
        resolution_filter = "_R1"
        if file_name_substr_filter:
            if file_name_substr_filter not in ["B02", "B03", "B04", "B08"]:
                resolution_filter = "_R2"

        base_name = os.path.splitext(file_name)[0]
        rasters_dir = os.path.normpath(os.path.join(parent_dir, "{0}.DBL.DIR".format(base_name)))
        rasters = get_raster_files_from_dir(rasters_dir, "_FRE{0}".format(resolution_filter))
        ret_list.extend(rasters)

        if not file_name_substr_filter:
            rasters_20m = get_raster_files_from_dir(rasters_dir, "_FRE_R2")
            ret_list.extend(rasters_20m)

    return ret_list
    
def extract_input_products(input_products_json_file, product_type, product_subtype) :
    products = []
    
    with open(input_products_json_file) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                data = json.loads(line)
            except ValueError:
                continue

            if "features" in data:
                features = data["features"]
            else:
                features = [data]
            
            for feature in features:
                info = extract_feature_info(feature)
                prd_path = info["product_path"]
                if product_type in ["L2A"]:
                    prd_path = info["metadata_path"]
                raster_paths = get_product_raster(prd_path, product_type, product_subtype)
                products += raster_paths
    
    return products

def process_file(file, prd_type, lpis_file, out_dir):
    
    if prd_type in ["NDVI", "LAI", "FAPAR", "FCOVER", "NDWI", "BRGHT"]:
        prd_type = "L3B_" + prd_type
        
    cmd_flags = [
        "otbcli", "Markers1Extractor",
        "-field", "NewID",
        "-prdtype", prd_type,
        "-outdir", out_dir,
        "-il", file,
        "-vec", lpis_file,
        "-validpixelscnt", "0",
        "-invalidpixelscnt", "0",
        "-minmax", "0",
        "-median", "0",
        "-p25", "0",
        "-p75", "0"
    ]
        
    run_command(cmd_flags)

def _wrapper(args):
    f, prd_type, lpis_file, out_dir = args
    return process_file(f, prd_type, lpis_file, out_dir)

def main():

    parser = argparse.ArgumentParser(
        description="Runs the MDB processor"
    )
    parser.add_argument("--request-context-file", required=True,
                        help="JSON containing the information about the execution context (site, request parameters etc.)")
    parser.add_argument("-i", "--input-products-json", required=True,
                        help="Input JSON file containing products")
    parser.add_argument("-t", "--product-type",
                        help="The product type in the input products json",
                        default="NDVI")
                        
    parser.add_argument("-o", "--out-dir", help="Output MDB1 folder", required=True)
    parser.add_argument("-p", "--parallelism", type=int, help="Parallel concurent extractions", default=4)
    
    args = parser.parse_args()
    
    product_type = args.product_type
    product_subtype = None
    if ":" in product_type:
        product_type, product_subtype = product_type.split(":", 1)
    
    if not os.path.exists(args.out_dir):
        os.makedirs(args.out_dir)
    
    result = read_request_context_file(args.request_context_file)
    req_params = result["request_parameters"]
    site_info = result["site_info"]
    
    site_id = site_info["site_id"]
    lpis_prd_path = site_info["insitu_path"]
    
    print("Site ID = {}, lpis path = {}".format(site_id, lpis_prd_path))
    
    products = extract_input_products(args.input_products_json, product_type, product_subtype)
    
    print(products)
    
    parcel_prd_file_patterns = ParcelPrdFilePatterns()
    lpis_infos = extract_lpis_infos(site_id, lpis_prd_path, parcel_prd_file_patterns)
    
    if product_type in ["L2A", "L3B", "NDVI", "LAI", "FAPAR", "FCOVER", "NDWI", "BRGHT"]:
        lpis_file = lpis_infos.optical_ids_geom_shape_path
    elif product_type in ["AMP", "BCK", "COHE"]:
        lpis_file = lpis_infos.sar_geom_shape_paths
    
    output_files = []
    pool = Pool(processes=args.parallelism)
    try:
        results = pool.map(
            _wrapper,
            [(f, product_type, lpis_file, args.out_dir) for f in products]
        )

        # If process_file returns something, collect it
        output_files.extend(results)

    finally:
        pool.close()
        pool.join()

if __name__ == "__main__":
    main()

