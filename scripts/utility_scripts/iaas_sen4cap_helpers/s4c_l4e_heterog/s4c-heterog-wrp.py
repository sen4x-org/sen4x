#!/usr/bin/env python
"""
Standalone runner for the S4C Heterogeneity processor.

Reads execution context and product lists from JSON files, queries processor
configuration from the database, then constructs and immediately executes
every command in the heterogeneity pipeline while preserving the original
loops over tiles, S2 bands and clustering periods.
"""

from __future__ import annotations

import argparse
import configparser
import fnmatch
import json
import os
import re
import subprocess
import sys
from datetime import datetime, date
from typing import Dict, List, Optional
from urllib.parse import urlparse

import psycopg2

S2_BANDS = ["B02", "B03", "B04", "B08", "NDVI"]

S4C_HETEROGENEITY_CFG_PREFIX = "processor.s4c_heterog."


# ---------------------------------------------------------------------------
# Database / config helpers
# ---------------------------------------------------------------------------

class Config(object):
    """Reads database connection parameters from the sen2agri config file."""
    def __init__(self, args):
        cfg = configparser.ConfigParser()
        cfg.read(args.config_file)
        self.host     = cfg.get("Database", "HostName",  fallback="localhost")
        self.port     = cfg.getint("Database", "Port",   fallback=5432)
        self.dbname   = cfg.get("Database", "DatabaseName", fallback="sen2agri")
        self.user     = cfg.get("Database", "UserName",  fallback="postgres")
        self.password = cfg.get("Database", "Password",  fallback="")

# ---------------------------------------------------------------------------
# LPIS helpers
# ---------------------------------------------------------------------------

class LpisInfos(object):
    def __init__(self,
                 product_path="",
                 optical_ids_geom_shape_path="",
                 sar_geom_shape_paths=None,
                 opt_tiles_geoms_rasters=None,
                 sar_tiles_geoms_rasters=None):
        self.product_path                = product_path
        self.optical_ids_geom_shape_path = optical_ids_geom_shape_path
        self.sar_geom_shape_paths        = sar_geom_shape_paths  or {}
        self.opt_tiles_geoms_rasters     = opt_tiles_geoms_rasters or {}
        self.sar_tiles_geoms_rasters     = sar_tiles_geoms_rasters or {}


class ParcelPrdFilePatterns(object):
    def __init__(self,
                 parcels_csv_file_name_pattern=r"decl_.*_\d{4}.csv",
                 opt_parcels_pattern=r".*_buf_5m\.shp",
                 sar_parcels_pattern=r".*_(\d{4,5})_buf_10m\.shp",
                 opt_parcels_tiffs_pattern="",
                 sar_parcels_tiffs_pattern=""):
        self.parcels_csv_file_name_pattern = parcels_csv_file_name_pattern
        self.opt_parcels_pattern           = opt_parcels_pattern
        self.sar_parcels_pattern           = sar_parcels_pattern
        self.opt_parcels_tiffs_pattern     = opt_parcels_tiffs_pattern
        self.sar_parcels_tiffs_pattern     = sar_parcels_tiffs_pattern

def _int(key, default):
    v = cfg_values.get(S4C_HETEROGENEITY_CFG_PREFIX + key)
    return int(v) if v is not None else default

def _float(key, default):
    v = cfg_values.get(S4C_HETEROGENEITY_CFG_PREFIX + key)
    return float(v) if v is not None else default

def _bool(key, default):
    v = cfg_values.get(S4C_HETEROGENEITY_CFG_PREFIX + key)
    return bool(int(v)) if v is not None else default

def _str(key, default=""):
    v = cfg_values.get(S4C_HETEROGENEITY_CFG_PREFIX + key)
    return v if v is not None else default

def get_config_values(conn, site_id=None):
    """
    Fetch all S4C Heterogeneity processor parameters from the config table.
    Site-level rows take precedence over global (site_id IS NULL) rows.
    """
    prefix = S4C_HETEROGENEITY_CFG_PREFIX
    suffixes = [
        "mask_value",
        "nan_value",
        "temporal_resampling_max_dist",
        "temporal_resampling_windows_radius",
        "s1_temporal_resampling_interval",
        "s2_temporal_resampling_interval",
        "clustering_period",
        "s1_clusters_number",
        "s2_clusters_number",
        "isolated_pixels_thr",
        "isolated_pixels_smoothing_radius",
        "search_radius_s1",
        "search_radius_s2",
        "full_connectivity",
        "s1_min_cluster_pixels",
        "s2_min_cluster_pixels",
        "ndvi_clust_dist_thr",
        "percentage_hererogeneity",
        "existing_ct_dir",
    ]
    keys = [prefix + s for s in suffixes]
    query = """
        SELECT key, value
        FROM config
        WHERE key = ANY(%s)
          AND (
                (%s IS NOT NULL AND site_id = %s)
             OR (%s IS NULL    AND site_id IS NULL)
          )
    """
    with conn.cursor() as cur:
        cur.execute(query, (keys, site_id, site_id, site_id))
        rows = cur.fetchall()
    return {k: v for k, v in rows}


# ---------------------------------------------------------------------------
# Context / product-input helpers
# ---------------------------------------------------------------------------

def read_request_context_file(request_context_file):
    """Return site_info and request_parameters dicts from a JSON context file."""
    with open(request_context_file) as f:
        data = json.load(f)
    return {
        "site_info":          data.get("site_info", {}),
        "request_parameters": data.get("request_parameters", {}),
    }

def convert_s3_to_local_path(href):
    parsed = urlparse(href)
    return "/" + parsed.netloc + parsed.path


def extract_feature_info(feature):
    result = {}
    result["id"] = feature.get("id")

    feature_properties = feature.get("properties", {})
    result["product_path"] = feature_properties.get("sen4x:disk_path", "")

    metadata_asset = feature.get("assets", {}).get("product_metadata", {})
    metadata_href  = metadata_asset.get("href")
    if metadata_href:
        if metadata_href.startswith("s3://"):
            result["metadata_path"] = convert_s3_to_local_path(metadata_href)
        else:
            result["metadata_path"] = metadata_href

    print(result)
    return result


def get_raster_files_from_dir(dir_path, file_name_substr_filter="",
                               prefix="*", suffix="*",
                               extensions=None):
    print("Extracting rasters from dir {} with pattern = {}, prefix = {}, "
          "suffix = {} and extensions = {}".format(
              dir_path, file_name_substr_filter, prefix, suffix, extensions))

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
    file_name  = os.path.basename(meta_file)
    parent_dir = os.path.dirname(os.path.abspath(meta_file))

    print("Processing {} and band {}".format(meta_file, file_name_substr_filter))

    if file_name == "MTD_MSIL2A.xml":
        granules_path = os.path.normpath(os.path.join(parent_dir, "GRANULE"))
        try:
            sub_dirs = os.listdir(granules_path)
        except OSError:
            return ret_list

        for sub_dir_name in sub_dirs:
            sub_dir_path = os.path.normpath(os.path.join(granules_path, sub_dir_name))
            if not os.path.isdir(sub_dir_path):
                continue
            img_path         = os.path.normpath(os.path.join(sub_dir_path, "IMG_DATA"))
            rasters_10m_path = os.path.normpath(os.path.join(img_path, "R10m"))
            new_filter = file_name_substr_filter if file_name_substr_filter else "_B*_*0m"
            rasters_10m = get_raster_files_from_dir(rasters_10m_path, new_filter)
            ret_list.extend(rasters_10m)

            if file_name_substr_filter:
                if rasters_10m:
                    return ret_list
                rasters_20m_path = os.path.normpath(os.path.join(img_path, "R20m"))
                ret_list.extend(get_raster_files_from_dir(rasters_20m_path, new_filter))
                return ret_list
            else:
                if not rasters_10m:
                    raise RuntimeError(
                        "Unsupported L2A Sen2Cor product without 10m res rasters in path {}".format(
                            sub_dir_path)
                    )
                rasters_20m_path = os.path.normpath(os.path.join(img_path, "R20m"))
                rasters_20m = get_raster_files_from_dir(rasters_20m_path)
                band_filters = ["_B05", "_B06", "_B07", "_B8A", "_B11", "_B12"]
                for raster_file in rasters_20m:
                    if any(f in os.path.basename(raster_file) for f in band_filters):
                        ret_list.append(raster_file)
            return ret_list

    elif file_name.startswith("SENTINEL2"):
        new_filter = "_FRE_" + file_name_substr_filter
        new_filter = new_filter.replace("0", "")
        ret_list.extend(get_raster_files_from_dir(parent_dir, new_filter, extensions=[".tif"]))

    elif file_name.startswith("S2"):
        resolution_filter = "_R1"
        if file_name_substr_filter:
            if file_name_substr_filter not in ["B02", "B03", "B04", "B08"]:
                resolution_filter = "_R2"
        base_name  = os.path.splitext(file_name)[0]
        rasters_dir = os.path.normpath(os.path.join(parent_dir, "{0}.DBL.DIR".format(base_name)))
        ret_list.extend(get_raster_files_from_dir(rasters_dir, "_FRE{0}".format(resolution_filter)))
        if not file_name_substr_filter:
            ret_list.extend(get_raster_files_from_dir(rasters_dir, "_FRE_R2"))

    return ret_list


def get_product_raster(product_path, product_type, product_subtype):
    results = []
    if product_type in ["L2A"]:
        results = get_s2_product_files(product_path, product_subtype)
    if product_type in ["AMP", "COHE", "BCK"]:
        results.append(product_path)
    if product_type in ["NDVI", "LAI", "FAPAR", "FCOVER", "NDWI", "BRGHT"]:
        folder_name  = os.path.basename(os.path.normpath(product_path))
        parts        = folder_name.split("_")
        date_part    = parts[5]
        tile_part    = parts[6]
        inner_folder = "S2AGRI_L3B{}_{}_{}".format(product_type, date_part, tile_part)
        if product_type in ["LAI", "FAPAR", "FCOVER"]:
            file_name = "S2AGRI_L3B{}_S{}MONO_{}_{}.TIF".format(
                product_type, product_type, date_part, tile_part)
        else:
            file_name = "S2AGRI_L3B{}_S{}_{}_{}.TIF".format(
                product_type, product_type, date_part, tile_part)
        results.append(os.path.join(product_path, "TILES", inner_folder, "IMG_DATA", file_name))
    return results


def extract_input_products(input_products_json_file, product_type, product_subtype):
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
            features = data["features"] if "features" in data else [data]
            for feature in features:
                info     = extract_feature_info(feature)
                prd_path = info["product_path"]
                if product_type in ["L2A"]:
                    prd_path = info["metadata_path"]
                products += get_product_raster(prd_path, product_type, product_subtype)
    return products

def extract_lpis_infos(site_id, lpis_prd_full_path, parcels_prd_descr):
    if not lpis_prd_full_path:
        raise RuntimeError(
            "No LPIS product found in database for the Heterogeneity execution "
            "for site {}.".format(site_id)
        )
    re_opt         = re.compile(parcels_prd_descr.opt_parcels_pattern)
    re_sar         = re.compile(parcels_prd_descr.sar_parcels_pattern)
    allowed_extensions = {".shp", ".csv", ".gpkg", ".tif"}
    directory = lpis_prd_full_path
    print("Heterogeneity: Extracting files for LPIS product {}".format(lpis_prd_full_path))

    try:
        dir_files = [
            f for f in os.listdir(directory)
            if os.path.isfile(os.path.join(directory, f))
            and os.path.splitext(f)[1].lower() in allowed_extensions
        ]
    except OSError:
        dir_files = []

    lpis_info = LpisInfos()
    for file_name in dir_files:
        file_path = os.path.join(directory, file_name)
        print("Heterogeneity: Checking the LPIS file {}".format(file_path))
        if re_opt.search(file_name) and not lpis_info.optical_ids_geom_shape_path:
            lpis_info.optical_ids_geom_shape_path = file_path
            print("Heterogeneity: Using for Optical products the LPIS file {}".format(file_path))
        sar_match = re_sar.search(file_name)
        if sar_match:
            proj_id = sar_match.group(1)
            lpis_info.sar_geom_shape_paths[proj_id] = file_path
            print("Heterogeneity: Using for SAR products the LPIS file {} "
                  "for projection {}".format(file_path, proj_id))

    if lpis_info.optical_ids_geom_shape_path and lpis_info.sar_geom_shape_paths:
        lpis_info.product_path = lpis_prd_full_path
        print("Heterogeneity: Using LPIS {}".format(lpis_prd_full_path))
    else:
        print("Heterogeneity: LPIS infos couldn't be extracted from path {}".format(
            lpis_prd_full_path))
    return lpis_info


# ---------------------------------------------------------------------------
# Subprocess helper
# ---------------------------------------------------------------------------

def run_command(cmd):
    print("Running: " + " ".join(cmd))
    try:
        subprocess.run(cmd, check=True)
    except AttributeError:
        # Python 2 fallback
        ret = subprocess.call(cmd)
        if ret != 0:
            raise RuntimeError("Command failed with exit code {}".format(ret))


# ---------------------------------------------------------------------------
# Individual command runners (one per logical processor step)
# ---------------------------------------------------------------------------

def run_extract_parcels(site_id, start_date, end_date,
                        parcels_path, lut_path, tiles_path,
                        optical_path, radar_path, lpis_path):
    cmd = [
        "s4c-l4a-extract-parcels",
        "-s", str(site_id),
        "--season-start", start_date.strftime("%Y-%m-%d"),
        "--season-end",   end_date.strftime("%Y-%m-%d"),
        "--",
        parcels_path, lut_path, tiles_path, optical_path, radar_path, lpis_path,
    ]
    run_command(cmd)


def run_crop_type(site_id, working_path, tiles_path, radar_path, lpis_path):
    cmd = [
        "s4c-heterog-crop-type",
        "-s", str(site_id),
        "--working-path",    working_path,
        "--tile-footprints", tiles_path,
        "--radar-products",  radar_path,
        "--lpis-path",       lpis_path,
    ]
    run_command(cmd)


def run_gdalbuildvrt(input_files, vrt_file):
    cmd = ["gdalbuildvrt", "-separate", vrt_file] + list(input_files)
    run_command(cmd)


def run_temporal_resampling(in_rasters, in_masks, in_dates, out_dates, out_path,
                            mask_value, nan_value, s2_max_dist, win_radius):
    cmd = [
        "otbcli_TemporalResampling",
        "-in",        in_rasters,
        "-mask",      in_masks,
        "-out",       out_path + "?gdal:co:COMPRESS=DEFLATE",
        "-bv",        str(mask_value),
        "-nan",       str(nan_value),
        "-maxdist",   str(s2_max_dist),
        "-winradius", str(win_radius),
        "-indates",
    ] + [str(d) for d in in_dates] + [
        "-outdates",
    ] + list(out_dates)
    run_command(cmd)


def run_s2_cluster_preparation(in_files, lpis_raster, n_clusters, n_images,
                                period_idx, out_path):
    cmd = (
        ["s4c-cluster-preparation-s2", "--input-images"] + list(in_files) +
        ["--lpis-buffered-raster", lpis_raster,
         "--number-of-clusters",  str(n_clusters),
         "--number-of-images",    str(n_images),
         "--period",              str(period_idx),
         "--output",              out_path]
    )
    run_command(cmd)


def run_s1_cluster_preparation(in_ct_dir, lpis_raster, n_clusters, n_images,
                                period_idx, year, tile, out_path):
    cmd = [
        "s4c-cluster-preparation-s1",
        "--input-dir",            in_ct_dir,
        "--lpis-buffered-raster", lpis_raster,
        "--number-of-clusters",   str(n_clusters),
        "--number-of-images",     str(n_images),
        "--period",               str(period_idx),
        "--year",                 str(year),
        "--tile",                 tile,
        "--output",               out_path,
    ]
    run_command(cmd)


def run_remove_isolated_pixels(in_path, out_path, isolated_pixels_thr,
                               smoothing_radius, n_clusters):
    cmd = (
        ["otbcli_HeterogeneityRemoveIsolated",
         "-in",        in_path,
         "-threshold", str(isolated_pixels_thr),
         "-radius",    str(smoothing_radius),
         "-nodata",    "0",
         "-classes"]  + [str(c) for c in range(1, n_clusters + 1)] +
        ["-out",       out_path + "?gdal:co:COMPRESS=DEFLATE"]
    )
    run_command(cmd)


def run_spatial_connectivity(in_path, out_path, full_connectivity, search_radius):
    cmd = [
        "otbcli_HeterogeneityLocalClassConnectivityIndex",
        "-in",               in_path,
        "-fullconnectivity", str(int(full_connectivity)),
        "-radius",           str(search_radius),
        "-out",              out_path + "?gdal:co:COMPRESS=DEFLATE",
    ]
    run_command(cmd)


def run_s2_cluster_analysis(in_ndvi, lpis_csv, lpis_raster,
                             smoothed_raster, local_con_raster,
                             n_images, period_idx, clust_pix_num_s2,
                             ndvi_thr_dist, compactness_thr_s2, percent_hetero,
                             out_path):
    cmd = [
        "s4c-cluster-analysis-s2",
        "--ndvi-image",               in_ndvi,
        "--lpis-csv",                 lpis_csv,
        "--lpis-buffered-raster",     lpis_raster,
        "--smooted-raster",           smoothed_raster,
        "--local-conn-raster",        local_con_raster,
        "--number-of-images",         str(n_images),
        "--period",                   str(period_idx),
        "--min-s2-pixels",            str(clust_pix_num_s2),
        "--ndvi-thr-dist",            str(ndvi_thr_dist),
        "--s2-compactness-threshold", str(compactness_thr_s2),
        "--percentage-heterogeneity", str(percent_hetero),
        "--output",                   out_path,
    ]
    run_command(cmd)


def run_s1_cluster_analysis(lpis_csv, lpis_raster, smoothed_raster, local_con_raster,
                             n_images, period_idx, clust_pix_num_s1,
                             compactness_thr_s1, percent_hetero, out_path):
    # Note: S2 LPIS raster used intentionally — S1 rasters are at 20 m but
    # all processing runs at 10 m to avoid resampling (matches original C++)
    cmd = [
        "s4c-cluster-analysis-s1",
        "--lpis-csv",                 lpis_csv,
        "--lpis-buffered-raster",     lpis_raster,
        "--smooted-raster",           smoothed_raster,
        "--local-conn-raster",        local_con_raster,
        "--number-of-images",         str(n_images),
        "--period",                   str(period_idx),
        "--min-s1-pixels",            str(clust_pix_num_s1),
        "--s1-compactness-threshold", str(compactness_thr_s1),
        "--percentage-heterogeneity", str(percent_hetero),
        "--output",                   out_path,
    ]
    run_command(cmd)


def run_tiles_analysis_merge(input_files, out_file):
    cmd = (
        ["s4c-cluster-tiles-analysis-merge",
         "--output", out_file,
         "--input-files"] + list(input_files)
    )
    run_command(cmd)


def run_period_analysis(lpis_csv, periods, period_files, out_file):
    cmd = (
        ["s4c-heterog-period-analysis",
         "--lpis-csv", lpis_csv,
         "--periods"]  + [str(p) for p in periods] +
        ["--periods-files"] + list(period_files) +
        ["--output", out_file]
    )
    run_command(cmd)


def run_product_formatter(site_id, start_date, end_date, input_files, out_dir):
    str_time_period = (
        start_date.strftime("%Y%m%dT%H%M%S") + "_" + end_date.strftime("%Y%m%dT%H%M%S")
    )
    cmd = (
        ["s4c-product-formatter",
         "--processor",   "S4C_HETEROGENEITY",
         "--time-period", str_time_period,
         "--site-id",     str(site_id),
         "--out-dir",     out_dir,
         "-processor.generic.files"] + list(input_files)
    )
    run_command(cmd)


# ---------------------------------------------------------------------------
# RunConfig
# ---------------------------------------------------------------------------

class RunConfig(object):
    """All parameters needed by run_heterogeneity()."""

    def __init__(self,
                 working_dir,
                 out_dir,
                 site_id,
                 year,
                 start_date,
                 end_date,
                 out_dates,
                 tile_rasters,
                 tile_masks,
                 tile_dates,
                 lpis_csv,
                 lpis_product_path,
                 s2_tiled_rasters,
                 s1_tiled_rasters,
                 existing_ct_sar_dir="",
                 mask_value=0,
                 nan_value=-10000,
                 s2_max_dist=30,
                 win_radius=15,
                 s1_temporal_resampling_interval=7,
                 s2_temporal_resampling_interval=10,
                 clustering_period=30,
                 clustering_intervals=1,
                 s1_clusters_no=5,
                 s2_clusters_no=4,
                 isolated_pixels_thr=1,
                 smoothing_radius=1,
                 search_radius_s1=1,
                 search_radius_s2=1,
                 full_connectivity=False,
                 clust_pix_num_s1=20,
                 clust_pix_num_s2=20,
                 ndvi_thr_dist=0.17,
                 percent_hetero=0.9):
        self.working_dir      = working_dir
        self.out_dir          = out_dir
        self.site_id          = site_id
        self.year             = year
        self.start_date       = start_date
        self.end_date         = end_date
        self.out_dates        = out_dates
        self.tile_rasters     = tile_rasters
        self.tile_masks       = tile_masks
        self.tile_dates       = tile_dates
        self.lpis_csv         = lpis_csv
        self.lpis_product_path = lpis_product_path
        self.s2_tiled_rasters = s2_tiled_rasters
        self.s1_tiled_rasters = s1_tiled_rasters
        self.existing_ct_sar_dir = existing_ct_sar_dir
        self.mask_value       = mask_value
        self.nan_value        = nan_value
        self.s2_max_dist      = s2_max_dist
        self.win_radius       = win_radius
        self.clustering_period     = clustering_period
        self.clustering_intervals  = clustering_intervals
        self.s1_clusters_no   = s1_clusters_no
        self.s2_clusters_no   = s2_clusters_no
        self.s1_num_images    = clustering_period // max(s1_temporal_resampling_interval, 1)
        self.s2_num_images    = clustering_period // max(s2_temporal_resampling_interval, 1)
        self.isolated_pixels_thr = isolated_pixels_thr
        self.smoothing_radius    = smoothing_radius
        self.search_radius_s1    = search_radius_s1
        self.search_radius_s2    = search_radius_s2
        self.full_connectivity   = full_connectivity
        self.clust_pix_num_s1    = clust_pix_num_s1
        self.clust_pix_num_s2    = clust_pix_num_s2
        self.ndvi_thr_dist       = ndvi_thr_dist
        self.compactness_thr_s1  = 2 * search_radius_s1 + 1
        self.compactness_thr_s2  = 2 * search_radius_s2 + 1
        self.percent_hetero      = percent_hetero

    def path(self, subdir, filename):
        """Return an absolute path under working_dir/subdir, creating dirs as needed."""
        d = os.path.join(self.working_dir, subdir)
        os.makedirs(d, exist_ok=True)
        return os.path.join(d, filename)


# ---------------------------------------------------------------------------
# Main pipeline entry point
# ---------------------------------------------------------------------------

def run_heterogeneity(cfg):
    """
    Build and execute every command in the heterogeneity pipeline, preserving
    the original loops over tiles, S2 bands and clustering periods.
    """
    prd_formatter_files = []

    # -----------------------------------------------------------------------
    # 1. Extract parcels + crop-type (skipped if existing_ct_sar_dir is set)
    # -----------------------------------------------------------------------
    if cfg.existing_ct_sar_dir:
        ct_files_path = cfg.existing_ct_sar_dir
    else:
        ct_working_path = os.path.join(cfg.working_dir, "crop_type_working_dir")
        os.makedirs(ct_working_path, exist_ok=True)

        parcels_path = os.path.join(ct_working_path, "parcels.csv")
        lut_path     = os.path.join(ct_working_path, "lut.csv")
        tiles_path   = os.path.join(ct_working_path, "tiles.csv")
        optical_path = os.path.join(ct_working_path, "optical.csv")
        radar_path   = os.path.join(ct_working_path, "radar.csv")
        lpis_path    = os.path.join(ct_working_path, "lpis.txt")

        run_extract_parcels(
            cfg.site_id, cfg.start_date, cfg.end_date,
            parcels_path, lut_path, tiles_path, optical_path, radar_path, lpis_path,
        )

        ct_files_path = ct_working_path
        run_crop_type(cfg.site_id, ct_files_path, tiles_path, radar_path, lpis_path)

    # -----------------------------------------------------------------------
    # 2. Per-tile: VRT build + temporal resampling, then per-period clustering
    # -----------------------------------------------------------------------
    s2_period_analysis_tiles = {}
    s1_period_analysis_tiles = {}

    for tile in cfg.tile_rasters.keys():
        map_rasters = cfg.tile_rasters[tile]
        map_masks   = cfg.tile_masks[tile]
        map_dates   = cfg.tile_dates[tile]

        temporal_resampling_files = []
        ndvi_resampled_raster = ""

        # 2a. S2 bands: VRT build + temporal resampling
        #     Iterating S2_BANDS (not map keys) preserves order and puts NDVI last
        for band in S2_BANDS:
            if band not in map_rasters:
                continue

            list_rasters = map_rasters[band]
            list_masks   = map_masks.get(band, [])
            list_dates   = map_dates.get(band, [])

            rasters_vrt  = cfg.path("vrt", "{}_{}_{}.vrt".format(tile, band, "S2"))
            masks_vrt    = cfg.path("vrt", "{}_{}_msks.vrt".format(tile, band))
            temp_res_out = cfg.path("temporal_resampling", "{}_{}_{}.tif".format(tile, band, "S2_all"))

            run_gdalbuildvrt(list_rasters, rasters_vrt)
            run_gdalbuildvrt(list_masks,   masks_vrt)
            run_temporal_resampling(
                rasters_vrt, masks_vrt, list_dates, cfg.out_dates, temp_res_out,
                cfg.mask_value, cfg.nan_value, cfg.s2_max_dist, cfg.win_radius,
            )

            temporal_resampling_files.append(temp_res_out)
            if band == "NDVI":
                ndvi_resampled_raster = temp_res_out

        # 2b. Per clustering period: S2 then S1 chain
        for period in range(1, cfg.clustering_intervals + 1):

            # ---- S2 --------------------------------------------------------

            if tile not in cfg.s2_tiled_rasters:
                raise RuntimeError(
                    "Heterogeneity: Cannot find 5m buffered raster for tile {} "
                    "in LPIS {}".format(tile, cfg.lpis_product_path)
                )

            s2_cluster_file = cfg.path(
                "cluster_prep", "{}_cluster_prep_S2_{}.tif".format(tile, period))
            run_s2_cluster_preparation(
                temporal_resampling_files, cfg.s2_tiled_rasters[tile],
                cfg.s2_clusters_no, cfg.s2_num_images, period, s2_cluster_file,
            )

            s2_iso_path = cfg.path(
                "isolated_pixels", "L4D_ClS2_{}_{}_{}.tif".format(cfg.site_id, tile, period))
            run_remove_isolated_pixels(
                s2_cluster_file, s2_iso_path,
                cfg.isolated_pixels_thr, cfg.smoothing_radius, cfg.s2_clusters_no,
            )
            prd_formatter_files.append(s2_iso_path)

            s2_connect_path = cfg.path(
                "spatial_connectivity",
                "L4D_ClS2_{}_{}_{}_{}.tif".format(cfg.site_id, tile, period, "Connect"))
            run_spatial_connectivity(
                s2_iso_path, s2_connect_path, cfg.full_connectivity, cfg.search_radius_s2,
            )
            prd_formatter_files.append(s2_connect_path)

            s2_clust_csv = cfg.path(
                "cluster_analysis", "L4D_ClS2_{}_{}_{}.csv".format(cfg.site_id, tile, period))
            run_s2_cluster_analysis(
                ndvi_resampled_raster, cfg.lpis_csv, cfg.s2_tiled_rasters[tile],
                s2_iso_path, s2_connect_path,
                cfg.s2_num_images, period,
                cfg.clust_pix_num_s2, cfg.ndvi_thr_dist, cfg.compactness_thr_s2,
                cfg.percent_hetero, s2_clust_csv,
            )
            s2_period_analysis_tiles.setdefault(period, []).append(s2_clust_csv)

            # ---- S1 --------------------------------------------------------

            if tile not in cfg.s1_tiled_rasters:
                raise RuntimeError(
                    "Heterogeneity: Cannot find 5m buffered raster for tile {} "
                    "in LPIS {}".format(tile, cfg.lpis_product_path)
                )

            s1_cluster_file = cfg.path(
                "cluster_prep", "{}_cluster_prep_S1_{}.tif".format(tile, period))
            run_s1_cluster_preparation(
                ct_files_path, cfg.s1_tiled_rasters[tile],
                cfg.s1_clusters_no, cfg.s1_num_images, period, cfg.year, tile, s1_cluster_file,
            )

            s1_iso_path = cfg.path(
                "isolated_pixels", "L4D_ClS1_{}_{}_{}.tif".format(cfg.site_id, tile, period))
            run_remove_isolated_pixels(
                s1_cluster_file, s1_iso_path,
                cfg.isolated_pixels_thr, cfg.smoothing_radius, cfg.s1_clusters_no,
            )
            prd_formatter_files.append(s1_iso_path)

            s1_connect_path = cfg.path(
                "spatial_connectivity",
                "L4D_ClS1_{}_{}_{}_{}.tif".format(cfg.site_id, tile, period, "Connect"))
            run_spatial_connectivity(
                s1_iso_path, s1_connect_path, cfg.full_connectivity, cfg.search_radius_s1,
            )
            prd_formatter_files.append(s1_connect_path)

            s1_clust_csv = cfg.path(
                "cluster_analysis", "L4D_ClS1_{}_{}_{}.csv".format(cfg.site_id, tile, period))
            run_s1_cluster_analysis(
                cfg.lpis_csv, cfg.s2_tiled_rasters[tile],  # S2 raster intentional — see comment
                s1_iso_path, s1_connect_path,
                cfg.s1_num_images, period,
                cfg.clust_pix_num_s1, cfg.compactness_thr_s1,
                cfg.percent_hetero, s1_clust_csv,
            )
            s1_period_analysis_tiles.setdefault(period, []).append(s1_clust_csv)
            prd_formatter_files.append(s1_clust_csv)

    # -----------------------------------------------------------------------
    # 3. Merge tile-level results across all tiles, per period
    # -----------------------------------------------------------------------
    period_analysis_files = []
    periods = []

    for period in range(1, cfg.clustering_intervals + 1):
        s2_merged_csv = cfg.path(
            "tiles_merge", "L4D_HeteS2_{}_{}_{}".format(cfg.site_id, cfg.year, period) + ".csv")
        run_tiles_analysis_merge(s2_period_analysis_tiles.get(period, []), s2_merged_csv)
        prd_formatter_files.append(s2_merged_csv)

        s1_merged_csv = cfg.path(
            "tiles_merge", "L4D_HeteS1_{}_{}_{}".format(cfg.site_id, cfg.year, period) + ".csv")
        run_tiles_analysis_merge(s1_period_analysis_tiles.get(period, []), s1_merged_csv)
        prd_formatter_files.append(s1_merged_csv)

        periods.append(period)
        period_analysis_files.append(s2_merged_csv)  # S2 feeds the final decision step

    # -----------------------------------------------------------------------
    # 4. Final period analysis (S2-based decision)
    # -----------------------------------------------------------------------
    period_decision_csv = cfg.path(
        "period_analysis",
        "L4D_HeteDecisionS2_{}_{}.csv".format(cfg.site_id, cfg.year))
    run_period_analysis(cfg.lpis_csv, periods, period_analysis_files, period_decision_csv)
    prd_formatter_files.append(period_decision_csv)

    # -----------------------------------------------------------------------
    # 5. Product formatter
    # -----------------------------------------------------------------------
    run_product_formatter(cfg.site_id, cfg.start_date, cfg.end_date,
                          prd_formatter_files, cfg.out_dir)


# ---------------------------------------------------------------------------
# Date / interval helpers
# ---------------------------------------------------------------------------

def _days_in_month(d):
    if d.month == 12:
        return (date(d.year + 1, 1, 1) - date(d.year, 12, 1)).days
    return (date(d.year, d.month + 1, 1) - date(d.year, d.month, 1)).days


def _compute_out_dates(start_date, end_date, s2_temporal_resampling_interval):
    season_start_doy = start_date.timetuple().tm_yday
    season_end_doy   = end_date.timetuple().tm_yday
    out_dates = []
    doy = season_start_doy
    while doy <= season_end_doy:
        out_dates.append(str(doy))
        doy += s2_temporal_resampling_interval
    if not out_dates or out_dates[-1] != str(season_end_doy):
        out_dates.append(str(season_end_doy))
    return out_dates


def _compute_clustering_intervals(start_date, end_date, clustering_period):
    first_of_month = start_date.date().replace(day=1)
    end_of_month   = end_date.date().replace(day=_days_in_month(end_date.date()))
    days = (end_of_month - first_of_month).days
    add_cluster = 1 if (days % clustering_period) > 20 else 0
    return (days // clustering_period) + add_cluster


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Runs the Heterogeneity processor"
    )
    parser.add_argument("-c", "--config-file",
                        default="/mnt/tao/cfg/sen4cap/sen2agri.conf",
                        help="configuration file")
    parser.add_argument("--request-context-file", required=True,
                        help="JSON containing the information about the execution context "
                             "(site, request parameters etc.)")
    parser.add_argument("--input-s2-products-json", required=True,
                        help="Input JSON file containing S2 products extracted from STAC")
    parser.add_argument("--input-ndvi-products-json", required=True,
                        help="Input JSON file containing NDVI products extracted from STAC")
    parser.add_argument("--keep-temp-files", action="store_true",
                        help="Keep temporary working files after processing")
    parser.add_argument("-w", "--working-dir", help="Working dir", required=True)
    parser.add_argument("-o", "--out-dir", help="Output Heterogeneity folder", required=True)
    parser.add_argument("--output-json", required=True,
                        help="Output JSON file containing the produced products")
    args = parser.parse_args()

    config = Config(args)
    conn = psycopg2.connect(
        host=config.host,
        port=config.port,
        dbname=config.dbname,
        user=config.user,
        password=config.password,
    )
    conn.autocommit = False

    if not os.path.exists(args.out_dir):
        os.makedirs(args.out_dir)

    result     = read_request_context_file(args.request_context_file)
    req_params = result["request_parameters"]
    site_info  = result["site_info"]

    site_id      = site_info["site_id"]
    season_start = site_info["season_start"]
    season_end   = site_info["season_end"]
    lpis_prd_path = site_info["insitu_path"]

    print("Site ID = {}, lpis path = {}".format(site_id, lpis_prd_path))

    # -- Extract LPIS geometry information -----------------------------------
    parcel_prd_file_patterns = ParcelPrdFilePatterns()
    lpis_infos = extract_lpis_infos(site_id, lpis_prd_path, parcel_prd_file_patterns)

    # The optical CSV (parcels declaration) is the lpis_csv consumed downstream
    lpis_csv = lpis_infos.optical_ids_geom_shape_path

    # s2_tiled_rasters and s1_tiled_rasters come from the tiff raster maps in LpisInfos
    s2_tiled_rasters = lpis_infos.opt_tiles_geoms_rasters   # tile -> 5m-buffered optical raster
    s1_tiled_rasters = lpis_infos.sar_tiles_geoms_rasters   # tile -> 5m-buffered SAR raster

    # -- Fetch configuration from the database --------------------------------
    cfg_values = get_config_values(conn, site_id)

    mask_value                   = _int("mask_value", 0)
    nan_value                    = _int("nan_value", -10000)
    s2_max_dist                  = _int("temporal_resampling_max_dist", 30)
    win_radius                   = _int("temporal_resampling_windows_radius", 15)
    s1_temporal_resampling_interval = max(_int("s1_temporal_resampling_interval", 7), 1)
    s2_temporal_resampling_interval = max(_int("s2_temporal_resampling_interval", 10), 1)
    clustering_period            = max(_int("clustering_period", 30), 20)
    s1_clusters_no               = _int("s1_clusters_number", 5)
    s2_clusters_no               = _int("s2_clusters_number", 4)
    isolated_pixels_thr          = _int("isolated_pixels_thr", 1)
    smoothing_radius             = _int("isolated_pixels_smoothing_radius", 1)
    search_radius_s1             = _int("search_radius_s1", 1)
    search_radius_s2             = _int("search_radius_s2", 1)
    full_connectivity            = _bool("full_connectivity", False)
    clust_pix_num_s1             = _int("s1_min_cluster_pixels", 20)
    clust_pix_num_s2             = _int("s2_min_cluster_pixels", 20)
    ndvi_thr_dist                = _float("ndvi_clust_dist_thr", 0.17)
    percent_hetero               = _float("percentage_hererogeneity", 0.9)
    existing_ct_sar_dir          = _str("existing_ct_dir", "")

    # -- Dates ----------------------------------------------------------------
    start_date = datetime.strptime(season_start, "%Y-%m-%d")
    end_date   = datetime.strptime(season_end,   "%Y-%m-%d")
    year       = end_date.year

    clustering_intervals = _compute_clustering_intervals(start_date, end_date, clustering_period)
    out_dates            = _compute_out_dates(start_date, end_date, s2_temporal_resampling_interval)

    # -- Populate tile raster/mask/date maps from the S2 and S1 product JSONs
    # Each product JSON contains GeoJSON features; we extract per-tile per-band
    # raster paths and day-of-year acquisition dates.
    tile_rasters = {}   # tile -> band -> [raster_path, ...]
    tile_masks   = {}   # tile -> band -> [mask_path,   ...]
    tile_dates   = {}   # tile -> band -> [doy,         ...]

    s2_products = extract_input_products(args.input_s2_products_json, "L2A", "")
    ndvi_products = extract_input_products(args.input_ndvi_products_json, "NDVI", "")

    # For S2 bands the product raster files are already per-band per-tile;
    # group them by tile (derived from the path) and band.
    for raster_path in s2_products:
        # Derive tile from path — expected segment like "T31UFR" in the path
        tile_match = re.search(r"_(T\d{2}[A-Z]{3})_", raster_path)
        if not tile_match:
            continue
        tile = tile_match.group(1)
        # Derive band from filename
        band_match = re.search(r"_(B0[2348]|B8A|B11|B12)_", os.path.basename(raster_path),
                               re.IGNORECASE)
        if not band_match:
            continue
        band = band_match.group(1).upper()
        if band not in S2_BANDS:
            continue
        # Derive doy from path segment like _20250305T_ or similar
        date_match = re.search(r"_(\d{8})T", raster_path)
        doy = (datetime.strptime(date_match.group(1), "%Y%m%d").timetuple().tm_yday
               if date_match else 0)

        tile_rasters.setdefault(tile, {}).setdefault(band, []).append(raster_path)
        tile_masks.setdefault(tile, {}).setdefault(band, [])   # masks populated separately
        tile_dates.setdefault(tile, {}).setdefault(band, []).append(doy)

    for raster_path in ndvi_products:
        tile_match = re.search(r"_(T\d{2}[A-Z]{3})_", raster_path)
        if not tile_match:
            continue
        tile = tile_match.group(1)
        date_match = re.search(r"_A(\d{8})T", raster_path)
        doy = (datetime.strptime(date_match.group(1), "%Y%m%d").timetuple().tm_yday
               if date_match else 0)

        tile_rasters.setdefault(tile, {}).setdefault("NDVI", []).append(raster_path)
        tile_masks.setdefault(tile, {}).setdefault("NDVI", [])
        tile_dates.setdefault(tile, {}).setdefault("NDVI", []).append(doy)

    print("Tiles found: {}".format(list(tile_rasters.keys())))

    # -- Build and run --------------------------------------------------------
    run_cfg = RunConfig(
        working_dir=args.working_dir,
        out_dir=args.out_dir,
        site_id=site_id,
        year=year,
        start_date=start_date,
        end_date=end_date,
        out_dates=out_dates,
        tile_rasters=tile_rasters,
        tile_masks=tile_masks,
        tile_dates=tile_dates,
        lpis_csv=lpis_csv,
        lpis_product_path=lpis_prd_path,
        s2_tiled_rasters=s2_tiled_rasters,
        s1_tiled_rasters=s1_tiled_rasters,
        existing_ct_sar_dir=existing_ct_sar_dir,
        mask_value=mask_value,
        nan_value=nan_value,
        s2_max_dist=s2_max_dist,
        win_radius=win_radius,
        s1_temporal_resampling_interval=s1_temporal_resampling_interval,
        s2_temporal_resampling_interval=s2_temporal_resampling_interval,
        clustering_period=clustering_period,
        clustering_intervals=clustering_intervals,
        s1_clusters_no=s1_clusters_no,
        s2_clusters_no=s2_clusters_no,
        isolated_pixels_thr=isolated_pixels_thr,
        smoothing_radius=smoothing_radius,
        search_radius_s1=search_radius_s1,
        search_radius_s2=search_radius_s2,
        full_connectivity=full_connectivity,
        clust_pix_num_s1=clust_pix_num_s1,
        clust_pix_num_s2=clust_pix_num_s2,
        ndvi_thr_dist=ndvi_thr_dist,
        percent_hetero=percent_hetero,
    )

    run_heterogeneity(run_cfg)


if __name__ == "__main__":
    main()
