#!/usr/bin/env python

from __future__ import print_function

import argparse
import json
import re
import os
import uuid
import subprocess

try:
    from urllib.parse import urlparse
except ImportError:
    from urlparse import urlparse

spectral_indices_mapping = {
    "NDVI": "Vegetation:NDVI",
    "TNDVI": "Vegetation:TNDVI",
    "RVI": "Vegetation:RVI",
    "SAVI": "Vegetation:SAVI",
    "TSAVI": "Vegetation:TSAVI",
    "MSAVI": "Vegetation:MSAVI",
    "MSAVI2": "Vegetation:MSAVI2",
    "GEMI": "Vegetation:GEMI",
    "IPVI": "Vegetation:IPVI",
    "LAIFromNDVILog": "Vegetation:LAIFromNDVILog",
    "LAIFromReflLinear": "Vegetation:LAIFromReflLinear",
    "NDWI": "Water:NDWI",
    "NDWI2": "Water:NDWI2",
    "MNDWI": "Water:MNDWI",
    "NDTI": "Water:NDTI",
    "RI": "Soil:RI",
    "CI": "Soil:CI",
    "BI": "Soil:BI",
    "BI2": "Soil:BI2"
}

def get_full_spectral_index_name(spectral_index):
    return spectral_indices_mapping.get(spectral_index)

def create_product_processing_workdir(base_out):
    workdir = os.path.join(base_out, str(uuid.uuid4()))
    if not os.path.exists(workdir):
        os.makedirs(workdir)
    return workdir

def run_command(cmd):
    print("Running:", " ".join(cmd))

    try:
        subprocess.run(cmd, check=True)  # Python 3
    except AttributeError:
        # Python 2 fallback
        ret = subprocess.call(cmd)
        if ret != 0:
            raise RuntimeError("Command failed with exit code {}".format(ret))

def generate_ipp_xml_file(full_xml_path, spectral_indicator, out_dir):
    match = re.search(r"MSIL2A_(\d{8}T\d{6})", full_xml_path)

    if not match:
        return "executionInfos.xml"

    timestamp = match.group(1)

    ipp_filename = "S2AGRI_L3B" + spectral_indicator + "_IPP_A{}.xml".format(timestamp)
    ipp_filepath = os.path.join(out_dir, ipp_filename)

    xml_content = """<?xml version="1.0" ?>
<metadata>
  <General>
  </General>
  <XML_files>
    <XML_0>{}</XML_0>
  </XML_files>
</metadata>
""".format(full_xml_path)

    with open(ipp_filepath, "w") as f:
        f.write(xml_content)

    print("Generated IPP file:", ipp_filepath)

    return ipp_filepath
    
def run_spectral_indicator_processing(xml_path, site_id, tile_id, spectral_indicator, workdir, out_dir):

    mask_dir = os.path.join(workdir, spectral_indicator + "-processor-mask-flags")
    spectral_indicator_dir = os.path.join(workdir, spectral_indicator + "-processor-extractor")
    prd_formatter_dir = os.path.join(workdir, "product-formatter")

    for d in [mask_dir, spectral_indicator_dir, prd_formatter_dir]:
        if not os.path.exists(d):
            os.makedirs(d)

    mask_path = os.path.join(mask_dir, spectral_indicator + "_date_msk_flgs_img.tif")
    mask_resampled_path = os.path.join(mask_dir, spectral_indicator + "_date_msk_flgs_img_resampled.tif")
    spectral_indicator_path = os.path.join(spectral_indicator_dir, spectral_indicator + "_img.tif")
    prd_properties = os.path.join(prd_formatter_dir, "product_properties.txt")
    ipp_filepath = generate_ipp_xml_file(xml_path, spectral_indicator, prd_formatter_dir)

    cmd_flags = [
        "otbcli",
        "GenerateLaiMonoDateMaskFlags",
        "-inxml", xml_path,
        "-out", mask_path, #  + "?&box=4363:3583:4731:3955",
        "-outres", "10",
        "-outresampled", mask_resampled_path  + "?&box=4363:3583:4731:3955"
    ]

    cmd_radiometric_indice = [
        "otbcli",
        "Sen4XRadiometricIndices",
        "-xml", xml_path,
        # "-msks", mask_path,
        "-list", get_full_spectral_index_name(spectral_indicator),
        "-out", spectral_indicator_path, #  + "?&box=4363:3583:4731:3955",
    ]

    cmd_product_formatter = [
        "otbcli",
        "ProductFormatter",
        "-destroot", out_dir,
        "-fileclass", "OPER",
        "-level", "L3B" + spectral_indicator,
        "-baseline", "01.00",
        "-processor", "vegetation",
        "-siteid", str(site_id),
        "-compress", "1",
        "-vectprd", "0",
        "-prdnamesuffix", "T" + tile_id,
        "-gipp", ipp_filepath,
        "-outprops", prd_properties,
        "-il", xml_path,
        "-processor.vegetation.laistatusflgs", "TILE_" + tile_id, mask_resampled_path,
        "-processor.vegetation." + spectral_indicator.lower(), "TILE_" + tile_id, spectral_indicator_path,
        "-aggregatetiles", "0"
    ]

    run_command(cmd_flags)
    run_command(cmd_radiometric_indice)
    run_command(cmd_product_formatter)
    
    with open(prd_properties, "r") as f:
        line = str(f.readline()).strip()
        
    return line


def run_biophysical_indicator_processing(xml_path, site_id, tile_id, indicator_name, workdir, out_dir):
    
    bi_bands_cfg = "/usr/share/sen2agri/Lai_Bands_Cfgs_Belcam.cfg"
   
    mask_dir = os.path.join(workdir, indicator_name + "-processor-mask-flags")
    create_angles_dir = os.path.join(workdir, "create-angles")
    indicator_dir = os.path.join(workdir, indicator_name + "-processor")
    prd_formatter_dir = os.path.join(workdir, "product-formatter")

    for d in [mask_dir, create_angles_dir, indicator_dir, prd_formatter_dir]:
        if not os.path.exists(d):
            os.makedirs(d)

    mask_path = os.path.join(mask_dir, indicator_name + "_date_msk_flgs_img.tif")
    mask_resampled_path = os.path.join(mask_dir, indicator_name + "_date_msk_flgs_img_resampled.tif")
    
    angles_small_res_file_path = os.path.join(create_angles_dir, "angles_small_res.tif");
    angles_small_res_no_data_path = os.path.join(create_angles_dir, "angles_small_res_no_data.tif");
    
    angles_vrt_path = os.path.join(create_angles_dir, "angles.vrt");
    angles_path = os.path.join(create_angles_dir, "angles_resampled.tif");
    
    indicator_path = os.path.join(indicator_dir, indicator_name + "_img.tif")
    domain_flags_path = os.path.join(indicator_dir, indicator_name + "_out_domain_flags.tif");
    corrected_spectral_indicator_path = os.path.join(indicator_dir, indicator_name + "_corrected_img.tif");
    quantified_bi_path = os.path.join(indicator_dir, indicator_name + "_img_16.tif");
    
    prd_properties = os.path.join(prd_formatter_dir, "product_properties.txt")
    ipp_filepath = generate_ipp_xml_file(xml_path, indicator_name, prd_formatter_dir)

    cmd_flags = [
        "otbcli",
        "GenerateLaiMonoDateMaskFlags",
        "-inxml", xml_path,
        "-out", mask_path + "?&box=4363:3583:4731:3955",
        "-outres", "10",
        "-outresampled", mask_resampled_path
    ]

    cmd_angles = [ "otbcli", "CreateAnglesRaster",
        "-xml", xml_path,
        "-out", angles_small_res_file_path
    ]
    
    cmd_angles_translate = [
        "gdal_translate", "-of", "GTiff", "-a_nodata", "-10000",
        angles_small_res_file_path,
        angles_small_res_no_data_path
    ]
    
    cmd_angles_vrt = [
        "gdalbuildvrt",  "-tr", "10", "10", "-r", "bilinear", "-srcnodata", "-10000", "-vrtnodata", "-10000", 
        angles_vrt_path,
        angles_small_res_no_data_path
    ]
    
    cmd_angles_translate_2 = [
        "gdal_translate", 
        angles_vrt_path,
        angles_path
    ]
    
    cmd_indicator_execution = [
        "otbcli",
        "BVLaiNewProcessor",
        "-xml", xml_path,
        "-angles", angles_path,
        "-out" + indicator_name.lower(), indicator_path + "?&box=4363:3583:4731:3955",
        "-outres", "10",
        "-laicfgs", bi_bands_cfg
    ]
    
    # cmd_gen_quality_flgs = [
    #     "otbcli",
    #     "GenerateDomainQualityFlags",
    #     "-xml", xml_path,
    #     "-in", indicator_path,
    #     "-laicfgs", bi_bands_cfg,
    #     "-indextype", indicator_name.lower(),
    #     "-outf", domain_flags_path,
    #     "-out", corrected_spectral_indicator_path,
    #     "-outres", "10",
    # ]
    
    cmd_quantify_img = [
        "otbcli",
        "QuantifyImage",
        "-in", indicator_path, #corrected_spectral_indicator_path,
        "-out", quantified_bi_path,
    ]
    
    cmd_product_formatter = [
        "otbcli",
        "ProductFormatter",
        "-destroot", out_dir,
        "-fileclass", "OPER",
        "-level", "L3B" + indicator_name,
        "-baseline", "01.00",
        "-processor", "vegetation",
        "-siteid", str(site_id),
        "-compress", "1",
        "-vectprd", "0",
        "-prdnamesuffix", "T" + tile_id,
        "-gipp", ipp_filepath,
        "-outprops", prd_properties,
        "-il", xml_path,
        "-processor.vegetation.laistatusflgs", "TILE_" + tile_id, mask_resampled_path,
        "-processor.vegetation." + indicator_name.lower() + "monodate", "TILE_" + tile_id, quantified_bi_path,
        "-aggregatetiles", "0"
    ]

    run_command(cmd_flags)
    run_command(cmd_angles)
    run_command(cmd_angles_translate)
    run_command(cmd_angles_vrt)
    run_command(cmd_angles_translate_2)
    run_command(cmd_indicator_execution)
    # run_command(cmd_gen_quality_flgs)
    run_command(cmd_quantify_img)
    run_command(cmd_product_formatter)
    
    with open(prd_properties, "r") as f:
        line = str(f.readline()).strip()
        
    return line

def extract_tile_id(product_id):
    match = re.search(r"_T([0-9]{2}[A-Z]{3})_", product_id)
    if match:
        return match.group(1)
    return None


def convert_s3_to_local_path(href):
    parsed = urlparse(href)
    return "/" + parsed.netloc + parsed.path


def extract_feature_info(feature):

    result = {}

    product_id = feature.get("id")
    result["id"] = product_id
    result["tile"] = extract_tile_id(product_id)

    product_props = feature.get("properties")
    product_path = product_props.get("sen4x:disk_path", {})
    processing_status = product_props.get("processing_status")
    result["processing_status"] = processing_status
    result["product_path"] = product_path
    
    metadata_asset = feature.get("assets", {}).get("product_metadata", {})
    metadata_href = metadata_asset.get("href")
    result["metadata_path"] = metadata_href 
    
    if metadata_href : 
        if metadata_href.startswith("s3://"):
            result["metadata_path"] = convert_s3_to_local_path(metadata_href) 
    
    # result_product = metadata_asset.get("result_product")
    result_product = next(
            (
                link["href"]
                for link in feature.get("links", [])
                if link.get("rel") == "derived_l3b"
            ),
        None
    )
    result["result_product"] = result_product

    print(result)
    
    return result

def read_request_context_file(request_context_file):

    with open(request_context_file) as f:
        data = json.load(f)

    # "site_info" contains : "site_id", "season_id", "season_start", "season_end", "wkt"
    return {
        "site_info": data.get("site_info", {}),
        "request_parameters": data.get("request_parameters", {})
    }

def write_stac_products(products, output_file):
    with open(output_file, "w") as f:
        for entry in products:
            product_path = entry["product"]
            parent_products = entry.get("parent_products", [])
            product_id = os.path.basename(product_path)
            item = {
                "id": product_id,
                "type": "Feature",
                "properties": {
                    "sen4x:disk_path": product_path
                },
                "links": []
            }
            if parent_products:
                for parent in parent_products:
                    item["links"].append({
                        "rel": "derived_from",
                        "href": parent
                    })
            json.dump(item, f)
            f.write("\n")
            
def process_input_products_file(input_products_json, site_info, indicator_name, working_dir, out_dir) :
    products = []
    site_id = site_info["site_id"]
    
    with open(input_products_json) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                data = json.loads(line)
            except ValueError:
                continue

            print(data)
            if "features" in data:
                features = data["features"]
            else:
                features = [data]
            
            for feature in features:
                info = extract_feature_info(feature)
                tile_id = info['tile']
                print("tile:", tile_id)

                # If product is already processed, it will not be reprocessed but instead we will use the processed product
                if info["processing_status"] == "PROCESSED":
                    prd_path = info["result_product"]
                else:
                    workdir = create_product_processing_workdir(working_dir)
                    indicator_name_uc = indicator_name.upper()
                    if indicator_name_uc == "NDVI" or indicator_name_uc == "NDWI" or indicator_name_uc == "BRIGHTNESS": 
                        prd_path = run_spectral_indicator_processing( info["metadata_path"], site_id, tile_id, indicator_name, workdir, out_dir)
                    elif indicator_name_uc == "LAI" or indicator_name_uc == "FAPAR" or indicator_name_uc == "FCOVER": 
                        prd_path = run_biophysical_indicator_processing( info["metadata_path"], site_id, tile_id, indicator_name, workdir, out_dir)
                
                products .append({
                    "product": prd_path,
                    "parent_products": [info["product_path"]]
                })            
    return products
    
def create_working_dir(out_file_path, subfolder_name):
    file_path = os.path.abspath(out_file_path)
    parent_dir = os.path.dirname(file_path)
    new_dir = os.path.join(parent_dir, subfolder_name)
    if not os.path.exists(new_dir):
        os.makedirs(new_dir)

    return parent_dir, new_dir
    
def main():

    MISSING = object()
    
    parser = argparse.ArgumentParser(
        description="Runs the L3B Spectral indices processor"
    )
    parser.add_argument("--request-context-file", required=True,
                        help="JSON containing the information about the execution context (site, request parameters etc.)")
    parser.add_argument("-i", "--input-products-json", required=True,
                        help="Input JSON file containing products extracted from STAC")
    parser.add_argument("-w", "--working-dir", default = None, help="The output folder where intermediate files will be created")
    parser.add_argument("-o", "--out-root-dir", default = "/mnt/archive/l3b/", help="The output root folder where products will be created")
    parser.add_argument("--output-json", required=True, help="Output JSON file containing the produced products")
    
    parser.add_argument("--indicator-name", nargs="?", const=MISSING, default=None)
    
    args = parser.parse_args()
    
    result = read_request_context_file(args.request_context_file)
    req_params = result["request_parameters"]
    site_info = result["site_info"]
    
    site_id = site_info["site_id"]
    if args.indicator_name is None or args.indicator_name is MISSING:
        indicator_name = req_params["indicator_name"]
        print("Using indicator name = {} extracted from the request context".format(indicator_name))
    else :
        indicator_name = args.indicator_name
        print("Using indicator name = {} provided as parameter to the script".format(indicator_name))
    
    if not args.working_dir : 
        parent_dir, working_dir = create_working_dir(args.output_json, "l3b_working_dir")
    else :
        working_dir = args.working_dir
    
    out_dir = os.path.join(args.out_root_dir, "site_" + str(site_id))
    
    products = process_input_products_file(args.input_products_json, site_info, indicator_name, working_dir, out_dir)
            
    write_stac_products(products, args.output_json)

if __name__ == "__main__":
    main()
    
    
