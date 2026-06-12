#!/usr/bin/env python3
from __future__ import print_function
import argparse
import re
import glob
from osgeo import gdal
from osgeo import osr
import subprocess
import lxml.etree
from lxml.builder import E
import math
import os
from os.path import isfile, isdir, join
import glob
import sys
import time
import datetime
from time import gmtime, strftime
import pipes
import shutil
import psycopg2
import psycopg2.errorcodes
import optparse
from osgeo import ogr
import json

from pathlib import Path
from datetime import datetime

try:
    from configparser import ConfigParser
except ImportError:
    from ConfigParser import ConfigParser

try:
    from urllib.parse import urlparse
except ImportError:
    from urlparse import urlparse

SENTINEL2_SATELLITE_ID = int(1)
LANDSAT8_SATELLITE_ID = int(2)
UNKNOWN_SATELLITE_ID = None
general_log_filename = "log.log"

DEBUG = 1

PRODUCT_MAP = {
    "MSIL2A":       (1, 1),
    "L3B":          (3, 3),
    "L3BNDVI":      (36, 3),
    "L3BNDWI":      (40, 3),
    "L3BBRIGHT":    (41, 3),
    "L3BLAI":       (37, 3),
    "L3BFAPAR":     (38, 3),
    "L3BFCOVER":    (39, 3),
    "AMP":          (10, 7),
    "COHE":         (11, 7),
    "MDB1":         (17, 14)
    
    # add more mappings here
}

def log(location, info, log_filename=None):
    if log_filename == None:
        log_filename = "log.txt"
    try:
        logfile = os.path.join(location, log_filename)
        if DEBUG:
            #print("logfile: {}".format(logfile))
            print("{}:{}".format(str(datetime.datetime.now()), str(info)))
            sys.stdout.flush()
        log = open(logfile, 'a')
        log.write("{}:{}\n".format(str(datetime.datetime.now()), str(info)))
        log.close()
    except:
        print("Could NOT write inside the log file {}".format(logfile))
        sys.stdout.flush()


def GetExtent(gt, cols, rows):
    ext = []
    xarr = [0, cols]
    yarr = [0, rows]

    for px in xarr:
        for py in yarr:
            x = gt[0] + px * gt[1] + py * gt[2]
            y = gt[3] + px * gt[4] + py * gt[5]
            ext.append([x, y])
        yarr.reverse()
    return ext


def ReprojectCoords(coords, src_srs, tgt_srs):
    trans_coords = []
    transform = osr.CoordinateTransformation(src_srs, tgt_srs)
    for x, y in coords:
        x, y, z = transform.TransformPoint(x, y)
        trans_coords.append([x, y])
    return trans_coords


def get_footprint(image_filename):
    dataset = gdal.Open(image_filename, gdal.gdalconst.GA_ReadOnly)

    size_x = dataset.RasterXSize
    size_y = dataset.RasterYSize

    geo_transform = dataset.GetGeoTransform()

    spacing_x = geo_transform[1]
    spacing_y = geo_transform[5]

    extent = GetExtent(geo_transform, size_x, size_y)

    source_srs = osr.SpatialReference()
    source_srs.ImportFromWkt(dataset.GetProjection())
    epsg_code = source_srs.GetAttrValue("AUTHORITY", 1)
    target_srs = osr.SpatialReference()
    target_srs.ImportFromEPSG(4326)

    wgs84_extent = ReprojectCoords(extent, source_srs, target_srs)
    return wgs84_extent


def get_envelope(footprints):
    geomCol = ogr.Geometry(ogr.wkbGeometryCollection)

    for footprint in footprints:
        #ring = ogr.Geometry(ogr.wkbLinearRing)
        for pt in footprint:
            #ring.AddPoint(pt[0], pt[1])
            point = ogr.Geometry(ogr.wkbPoint)
            point.AddPoint_2D(pt[0], pt[1])
            geomCol.AddGeometry(point)

        #poly = ogr.Geometry(ogr.wkbPolygon)
        # poly

    hull = geomCol.ConvexHull()
    return hull.ExportToWkt()


def get_product_info(product_name, product_type_id):
    acquisition_date = None
    sat_id = UNKNOWN_SATELLITE_ID
    if product_type_id == 1 or product_type_id == 25 or product_type_id == 26: # L2A, FMASK or L2A_MSK
        if product_name.startswith("S2"):
            m = re.match(r"\w+_V(\d{8}T\d{6})_\w+.SAFE", product_name)
            if m is not None:
                sat_id = SENTINEL2_SATELLITE_ID
                acquisition_date = m.group(1)
            else:
                # Check if it is the new S2 L2A format
                for prd_id in ["MSI.+", "L2AMSK", "FMASK"] :
                    regex_str = r"S2[A-D]_" + prd_id + "_(\d{8}T\d{6})_\w+.SAFE"
                    m = re.match(regex_str, product_name)
                    if m is not None:
                        sat_id = SENTINEL2_SATELLITE_ID
                        acquisition_date = m.group(1)
                        break
        else:
            m = re.match(r"LC8\d{6}(\d{7})[A-Z]{3}\d{2}", product_name)
            if m is not None:
                sat_id = LANDSAT8_SATELLITE_ID
                acquisition_date = datetime.datetime.strptime("{} {}".format(m.group(1)[0:4], m.group(1)[4:]), '%Y %j').strftime("%Y%m%dT%H%M%S")
                print("Acquisition date: {}".format(acquisition_date))
            else:
                print(product_name)
                for prd_id in ["L2A", "L2AMSK", "FMASK"] :
                    regex_str = r"LC08_" + prd_id + "_\d{6}_(\d{8})_\d{8}_\d{2}_(?:T1|T2|RT)"
                    m = re.match(regex_str, product_name)
                    if m is not None:
                        sat_id = LANDSAT8_SATELLITE_ID
                        acquisition_date = datetime.datetime.strptime(m.group(1), '%Y%m%d').strftime("%Y%m%dT%H%M%S")
                        print("Acquisition date: {}".format(acquisition_date))
    else:
        m = re.search(r"_(A|V)(\d{8}T\d{6})", product_name)
        if m:
            acquisition_date = m.group(2)
            original_words = acquisition_date.split('_')
            words = [word for word in original_words if "NOTV" not in word]
            if len(words) == 1:
                acquisition_date = words[0]
            else:
                if len(words) == 2:
                    acquisition_date = words[1]
                else:
                    acquisition_date = ""
            if (acquisition_date != ""):
                if (not "T" in acquisition_date):
                    acquisition_date = acquisition_date + "T000000"
    
    return (sat_id, acquisition_date)

def geojson_to_wkt(geometry):
    coords = geometry["coordinates"][0]  # outer ring
    coord_str = ", ".join(f"{x} {y}" for x, y in coords)
    return f"POLYGON(({coord_str}))"
    
    site_id,

def build_simple_product_output_name(input_file, site_id, start_date, end_date):
    input_path = Path(input_file)

    # Keep original extension (.ipc or .csv)
    ext = input_path.suffix
    
    start_date_str = datetime.strptime(start_date, "%Y-%m-%d").strftime("%Y%m%d")
    end_date_str = datetime.strptime(end_date, "%Y-%m-%d").strftime("%Y%m%d")

    # Current timestamp: YYYYMMDDTHHMMSS
    creation_time = datetime.utcnow().strftime("%Y%m%dT%H%M%S")
    new_name = (f"SEN4CAP_MDB1_"f"S{site_id}_"f"V{start_date_str}_{end_date_str}_"f"{creation_time}"f"{ext}")

    return input_path.with_name(new_name)
    
def handle_simple_product(l2a_db, site_id, start_date, end_date, prd_str, product_info) :    
    l2a_processed_tiles = []
    
    product_path =  product_info["product"]
    if prd_str == "MDB1":
        old_path = Path(product_path)
        product_path = build_simple_product_output_name(product_path, site_id, start_date, end_date)
        old_path.rename(product_path)
        product_path = str(product_path)
        product_info["product"] = product_path
        product_info["product_metadata"] = product_path
        product_info["id"] = os.path.basename(product_path[:len(product_path) - 1]) if product_path.endswith("/") else os.path.basename(product_path)

    # product_type_id = product_info["product_type_id"]
    product_name = product_info["id"]
    wkt = product_info["geometry"]
    sat_id = UNKNOWN_SATELLITE_ID
    acquisition_date = end_date
    orbit_id = product_info["relative_orbit"]
    mosaic_img = "mosaic.jpg"
    product_type_id, processor_id = PRODUCT_MAP[prd_str]
        
    product_id = l2a_db.set_processed_product(processor_id, product_type_id, site_id, l2a_processed_tiles, product_path, product_name, wkt, sat_id, acquisition_date, orbit_id, mosaic_img)
    
    return product_id, product_type_id
    
def handle_s1_slc_product(l2a_db, site_id, product_info) :
    footprint = geojson_to_wkt(product_info["geometry"])
    geom = ogr.CreateGeometryFromWkt(footprint)
    print(geom)
    
    product_dir =  product_info["product"]
    product_dir = get_safe_path(product_dir)
    print("SAFE Output path : {}".format(product_dir))

    if not product_dir.endswith(os.path.sep):
        product_dir += os.path.sep
        
    product_name = os.path.basename(product_dir[:len(product_dir) - 1]) if product_dir.endswith("/") else os.path.basename(product_dir)
    relative_orbit = product_info["relative_orbit"]
    orbit_type_id = 1 if product_info["orbit_type"] == "ascending" else 2
    
    pattern = r'^S1[A-Z]_([A-Z0-9]+)_SLC__[^_]+_\d{8}T\d{6}_(\d{8}T\d{6})_'
    m = re.match(pattern, product_name)
    if m:
        acquisition_date = m.group(2)
        print(acquisition_date)
    current_time = datetime.utcnow().strftime("%Y%m%dT%H%M%S")
    
    l2a_db.insert_into_downloader_history(site_id, 3, product_name, product_dir, current_time, 2, 1,
                                  acquisition_date, relative_orbit, None, None, footprint, orbit_type_id)
   
    return None, None
    

def get_product_orbit_id(product_name):
    print("Product name is: {}".format(product_name))
    orbit_id = re.search(r"_R(\d{3})_", product_name)
    if orbit_id == None:
        print("OrbitId cannot be extracted from product name {}".format(product_name))
        return 0
    print("OrbitId is: {}".format(int(orbit_id.group(1))))
    return int(orbit_id.group(1))

def get_safe_path(path):
    if not path.lower().endswith(".xml"):
        return path
    m = re.search(r'(.+?\.SAFE)/', path)
    if m:
        return m.group(1) + "/"

    return None
    
def insert_product(l2a_db, site_id, product_info):
    l2a_processed_tiles = []
    wkt = []
    sat_id = 0
    acquisition_date = ""
    mosaic_img = "mosaic.jpg"

    product_dir =  product_info["product"]
    product_dir = get_safe_path(product_dir)
    print("SAFE Output path : {}".format(product_dir))

    if not product_dir.endswith(os.path.sep):
        product_dir += os.path.sep
    print("Output path: {}".format(product_dir))

    product_name = os.path.basename(product_dir[:len(product_dir) - 1]) if product_dir.endswith("/") else os.path.basename(product_dir)
    prd_str, product_type_id, processor_id = get_product_type_info(product_name)
    print("Product dir is: {}".format(product_name))
    if prd_str == "SLC" :
        # Handle differently the SLC - these should be inserted into downloader_history
        return handle_s1_slc_product(l2a_db, site_id, product_info)
    
    prd_db_info = l2a_db.get_db_product_info(site_id, product_dir)
    if prd_db_info:
        product_id = prd_db_info["id"]
        product_type_id = prd_db_info["product_type_id"]
        print("Product found (will not be inserted into DB) for site_id = {}: id = {}, product_type_id = {}, full_path = {}".format(site_id, product_id, product_type_id, product_dir))
        return product_id, product_type_id

    wgs84_extent_list = []
    if product_type_id == 1 or product_type_id == 25 or product_type_id == 26: # L2A, FMASK or L2A_MSK
        if product_name.startswith("S2"):
            satellite_id = SENTINEL2_SATELLITE_ID
        else:
            satellite_id = LANDSAT8_SATELLITE_ID
        tiles_dir_list = (glob.glob("{}*.DBL.DIR".format(product_dir)))
        tile_img = []
        if len(tiles_dir_list) > 0 :
            log(product_dir, "Creating common footprint for tiles: DBL.DIR List: {}".format(tiles_dir_list), general_log_filename)
            for tile_dir in tiles_dir_list:
                if satellite_id == SENTINEL2_SATELLITE_ID:
                    tile_img = (glob.glob("{}/*_FRE_R1.DBL.TIF".format(tile_dir)))
                else:  # satellite_id is LANDSAT8_SATELLITE_ID:
                    tile_img = (glob.glob("{}/*_FRE.DBL.TIF".format(tile_dir)))
        else :
            # Check for MAJA format
            tiles_dir_list = (glob.glob("{}SENTINEL2*".format(product_dir)))
            if len(tiles_dir_list) > 0 :
                log(product_dir, "Creating common footprint for tiles: DBL.DIR List: {}".format(tiles_dir_list), general_log_filename)
                for tile_dir in tiles_dir_list:
                    if satellite_id == SENTINEL2_SATELLITE_ID:
                        tile_img = (glob.glob("{}/*_FRE_B2.tif".format(tile_dir)))
            else :
                # Check for Sen2Cor format
                tiles_dir_list = (glob.glob("{}GRANULE/L2A_T*".format(product_dir)))
                if len(tiles_dir_list) > 0 :
                    log(product_dir, "Creating common footprint for tiles: {}".format(tiles_dir_list), general_log_filename)
                    for tile_dir in tiles_dir_list:
                        if satellite_id == SENTINEL2_SATELLITE_ID:
                            tile_img = (glob.glob("{}/IMG_DATA/R10m/T*_B08_10m.jp2".format(tile_dir)))
                else :
                    # check for fmask or L2A_MSK format
                    tiles_dir_list = [product_dir]
                    if satellite_id == SENTINEL2_SATELLITE_ID:
                        tile_img = (glob.glob("{}/*Fmask4_10m.tif".format(product_dir)))
                    else :
                        if satellite_id == LANDSAT8_SATELLITE_ID:
                            tile_img = (glob.glob("{}/*Fmask4_30m.tif".format(product_dir)))
                        
                    
        if len(tile_img) > 0:
            wgs84_extent_list.append(get_footprint(tile_img[0]))
    else:
        if product_name.startswith("S2AGRI_"):
            mosaic_files_list = (glob.glob("{}*_PVI_*.jpg".format(product_dir)))
            if len(mosaic_files_list) > 0:
                mosaic_img = os.path.basename(mosaic_files_list[0])
                print ("mosaic image is {}".format(mosaic_img))

            tiles_dir_list = (glob.glob("{}TILES/S2AGRI_*".format(product_dir)))
            log(product_dir, "Creating common footprint for tiles: {}".format(tiles_dir_list), general_log_filename)
            for tile_dir in tiles_dir_list:
                tile_img = (glob.glob("{}/IMG_DATA/S2AGRI_*.TIF".format(tile_dir)))
                if len(tile_img) > 0:
                    wgs84_extent_list.append(get_footprint(tile_img[0]))

    wkt = get_envelope(wgs84_extent_list)

    orbit_id = 0
    if len(wkt) == 0:
        log(product_dir, "Could not create the footprint", general_log_filename)
    else:
        sat_id, acquisition_date = get_product_info(product_name, product_type_id)
        if product_type_id == 1 or product_type_id == 25 or product_type_id == 26: # L2A, FMASK or L2A_MSK
            if satellite_id == SENTINEL2_SATELLITE_ID:
                orbit_id = get_product_orbit_id(product_name)
            if sat_id > 0 and acquisition_date != None:
                # check for MACCS tiles output. If none was processed, only the record from
                # product table will be updated. No l2a product will be added into product table
                for tile_dbl_dir in tiles_dir_list:
                    tile = None
                    print("tile_dbl_dir {}".format(tile_dbl_dir))
                    if satellite_id == SENTINEL2_SATELLITE_ID:
                        tile = re.search(r"_L2VALD_(\d\d[a-zA-Z]{3})____[\w\.]+$", tile_dbl_dir)
                        if tile is None:
                            # Check for MAJA format
                            tile = re.search(r"_L2A_T(\d\d[a-zA-Z]{3})_.+$", tile_dbl_dir)
                        if tile is None:
                            # Check for Sen2Cor format
                            tile = re.search(r"L2A_T(\d\d[a-zA-Z]{3})_.+$", tile_dbl_dir)
                        if tile is None:
                            # Check for FMask format
                            tile = re.search(r"S2[A-D]_MSIFMASK_\d{8}T\d{6}_N\d+_R\d+_T(\d{2}\w{3})_\d{8}T\d{6}(?:.SAFE)?", tile_dbl_dir)
                    else:
                        tile = re.search(r"_L2VALD_([\d]{6})_[\w\.]+$", tile_dbl_dir)
                    if tile is not None and not tile.group(1) in l2a_processed_tiles:
                        l2a_processed_tiles.append(tile.group(1))
                log(product_dir, "Processed tiles: {}  to path: {}".format(l2a_processed_tiles, product_dir), general_log_filename)
            else:
                log(product_dir, "Could not get the acquisition date from the product name {}".format(product_dir), general_log_filename)
        else:
            for tile_dbl_dir in tiles_dir_list:
                tile = re.search("\w+_T(\w+)", tile_dbl_dir)
                if tile is not None and not tile.group(1) in l2a_processed_tiles:
                    l2a_processed_tiles.append(tile.group(1))

    if len(l2a_processed_tiles) > 0:
        log(product_dir, "Insert info in product table and set state as processed in product table for product {}".format(product_dir), general_log_filename)
    else:
        log(product_dir, "Only set the state as processed in product (no l2a tiles found after maccs) for product {}".format(product_dir), general_log_filename)

    product_id = l2a_db.set_processed_product(processor_id, product_type_id, site_id, l2a_processed_tiles, product_dir, os.path.basename(product_dir[:len(product_dir) - 1]), wkt, sat_id, acquisition_date, orbit_id, mosaic_img)
    
    return product_id, product_type_id

###########################################################################


class Config(object):

    def __init__(self):
        self.host = ""
        self.database = ""
        self.user = ""
        self.password = ""

    def loadConfig(self, configFile):
            parser = ConfigParser()
            parser.read([configFile])

            self.host = parser.get("Database", "HostName")
            self.orig_host = self.host

            # work around Docker networking scheme
            if self.host == "127.0.0.1" or self.host == "::1" or self.host == "localhost":
                self.host = "172.17.0.1"

            self.port = int(parser.get("Database", "Port", vars={"Port": "5432"}))
            self.database = parser.get("Database", "DatabaseName")
            self.user = parser.get("Database", "UserName")
            self.password = parser.get("Database", "Password")
            
            return True

###########################################################################


class InputProductInfo(object):

    def __init__(self, server_ip, database_name, user, password, log_file=None):
        self.server_ip = server_ip
        self.database_name = database_name
        self.user = user
        self.password = password
        self.is_connected = False
        self.log_file = log_file

    def database_connect(self):
        if self.is_connected:
            return True
        connectString = "dbname='{}' user='{}' host='{}' password='{}'".format(self.database_name, self.user, self.server_ip, self.password)
        try:
            self.conn = psycopg2.connect(connectString)
            self.cursor = self.conn.cursor()
            self.is_connected = True
        except:
            print("Unable to connect to the database")
            exceptionType, exceptionValue, exceptionTraceback = sys.exc_info()
            # Exit the script and print an error telling what happened.
            print("Database connection failed!\n ->{}".format(exceptionValue))
            self.is_connected = False
            return False
        return True

    def database_disconnect(self):
        if self.conn:
            self.conn.close()
            self.is_connected = False

    def get_db_product_info(self, site_id, full_path):
        if not self.database_connect():
            return None
            
        self.cursor.execute(
            "SELECT id, product_type_id, satellite_id, processor_id, created_timestamp, name "
            "FROM product WHERE full_path = %s and site_id = %s",
            (full_path,site_id,)
        )
        row = self.cursor.fetchone()
        if row:
            # Product already exists, return the info
            return {
                "id": row[0],
                "product_type_id": row[1],
                "satellite_id": row[2],
                "processor_id": row[3],
                "created_timestamp": row[4],
                "name": row[5]
            }
        return None
        
    def set_processed_product(self, processor_id, product_type_id, site_id, l2a_processed_tiles, full_path, product_name, footprint, sat_id, acquisition_date, orbit_id, mosaic_img):
        product_id = None
        if not self.database_connect():
            return product_id
        try:
            # normally , sp_insert_product should upsert the record
            self.cursor.execute("""select * from sp_insert_product(%(product_type_id)s :: smallint,
                           %(processor_id)s :: smallint,
                           %(satellite_id)s :: smallint,
                           %(site_id)s :: smallint,
                           %(job_id)s :: smallint,
                           %(full_path)s :: character varying,
                           %(created_timestamp)s :: timestamp,
                           %(name)s :: character varying,
                           %(quicklook_image)s :: character varying,
                           %(footprint)s,
                           %(orbit_id)s :: integer,
                           %(tiles)s :: json)""",
                                {
                                    "product_type_id": product_type_id,
                                    "processor_id": processor_id,
                                    "satellite_id": sat_id,
                                    "site_id": site_id,
                                    "job_id": None,
                                    "full_path": full_path,
                                    "created_timestamp": acquisition_date,
                                    "name": product_name,
                                    "quicklook_image": mosaic_img,
                                    "footprint": footprint,
                                    "orbit_id": orbit_id,
                                    "tiles": json.dumps(l2a_processed_tiles)
                                    # "tiles": '[' + ', '.join(['"' + t + '"' for t in l2a_processed_tiles]) + ']'
                                })
            row = self.cursor.fetchone()
            self.conn.commit()
            if row is None:
                return -1
            product_id = row[0]
            return product_id

        except Exception as e:
            print("Database update query failed: {}".format(e))
            self.database_disconnect()
            return product_id
        self.database_disconnect()
        return product_id

    def insert_product_provenance(self, site_id, product_id, parent_paths):
        if not self.database_connect():
            return        
        
        if not parent_paths:
            print("No parent products provided for product with ID: {}".format(product_id))
            return

        with self.conn.cursor() as cursor:
            for parent_path in parent_paths:
                parent_path = get_safe_path(parent_path)
                print("Checking for parent path {} of the product_id = {}".format(parent_path, product_id))
                cursor.execute(
                    """
                    SELECT id, created_timestamp FROM product WHERE full_path = %s and site_id = %s
                    """,
                    (parent_path,site_id,)
                )
                row = cursor.fetchone()
                if row:
                    parent_id, parent_date = row
                    print("Updating product provenance for product_id = {} and parent_id = {}".format(product_id, parent_id))
                    cursor.execute(
                        """
                        INSERT INTO product_provenance (product_id, parent_product_id, parent_product_date)
                        VALUES (%s, %s, %s) ON CONFLICT DO NOTHING
                        """,
                        (product_id, parent_id, parent_date)
                    )
                else:
                    print("Cannot find parent id for product_id = {} and parent_path = {}".format(product_id, parent_path))
                    
        self.conn.commit()
        
        self.database_disconnect()

    def insert_into_downloader_history(self, site_id, satellite_id, product_name, full_path, created_timestamp, status_id, no_of_retries,
                                  product_date, orbit_id, status_reason, tiles, footprint, orbit_type_id):
        sql = """
            INSERT INTO public.downloader_history(
                site_id, satellite_id, product_name,
                full_path, created_timestamp, status_id,
                no_of_retries, product_date,
                orbit_id, status_reason, tiles,
                footprint, orbit_type_id
            )
            SELECT %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
            WHERE NOT EXISTS (
                SELECT 1 FROM public.downloader_history
                WHERE site_id = %s
                  AND satellite_id = %s
                  AND product_name = %s
            )
        """
        if not self.database_connect():
            return        
        values = ( site_id, satellite_id, product_name, full_path, created_timestamp, status_id,
            no_of_retries, product_date, orbit_id, status_reason, tiles, footprint, orbit_type_id,
            site_id, satellite_id, product_name
        )

        with self.conn.cursor() as cursor:
            cursor.execute(sql, values)

        self.conn.commit()

def get_product_type_info(product_name):
    m = re.search(r'^[^_]+_([^_]+)_', product_name)
    if not m:
        raise ValueError("Invalid product name format: {}".format(product_name))

    prd_str = m.group(1)

    if prd_str not in PRODUCT_MAP:
        # check if it is a SLC product
        m_s1 = re.match(r'^(S1[A-Z])_([A-Z0-9]+)_([A-Z]+)__', product_name)
        if m_s1:
            prd_str = m_s1.group(3)
            if prd_str != "SLC":
                raise ValueError("Unsupported Sentine-1 product: {}".format(prd_str))
            product_type_id = None
            processor_id = None
        else:
            raise ValueError("Unknown product type: {}".format(prd_str))

    if prd_str != "SLC":
        product_type_id, processor_id = PRODUCT_MAP[prd_str]

    return prd_str, product_type_id, processor_id
    
def convert_s3_to_local_path(href):
    parsed = urlparse(href)
    return "/" + parsed.netloc + parsed.path
    
def read_stac_products(jsonl_file):
    results = []
    with open(jsonl_file) as f:
        for line in f:
            item = json.loads(line)
            product_id = item.get("id")
            product_path = item.get("properties").get("sen4x:disk_path", {})
            relative_orbit = item.get("properties").get("sat:relative_orbit", {})
            orbit_type = item.get("properties").get("sat:orbit_state", {})
            geometry = item.get("geometry", {})
            product_metadata_path = item.get("assets", {}).get("product_metadata", {}).get("href")
            
            if product_path and product_path.startswith("s3://"):
                product_path = convert_s3_to_local_path(product_path)
            parent_products = [
                link["href"]
                for link in item.get("links", [])
                if link.get("rel") == "derived_from"
            ]
            results.append({
                "id": product_id,
                "product": product_path,
                "product_metadata": product_metadata_path,
                "relative_orbit": relative_orbit,
                "orbit_type": orbit_type,
                "geometry" : geometry,
                "parent_products": parent_products
            })

    return results
   
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
            product_id = entry["id"]
            product_path = entry["product"]
            product_metadata_path = entry["product_metadata"]
            relative_orbit = entry["relative_orbit"]
            orbit_type = entry["orbit_type"]
            geometry = entry["geometry"]
            parent_products = entry.get("parent_products", [])
            product_db_id = entry.get("product_db_id")
            product_type_id = entry.get("product_type_id")
            item = {
                "id": product_id,
                "geometry": geometry,
                "type": "Feature",
                "properties": {
                    "product_db_id": product_db_id,
                    "sen4x:disk_path": product_path,
                    "sat:relative_orbit": relative_orbit,
                    "sat:orbit_state": orbit_type,
                    "product_type_id": product_type_id
                },      
                "assets": {
                    "product_metadata": {
                        "href": product_metadata_path
                    }
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
    
def main():
    parser = argparse.ArgumentParser(
        description="Script for inserting products into the database")
    parser.add_argument('-c', '--config', default="/etc/sen2agri/sen2agri.conf", help="configuration file")

    parser.add_argument( "--request-context-file", required=True,
                        help="JSON containing the information about the execution context (site, request parameters etc.)")

    parser.add_argument("-i", "--input-products-json", help="Input JSON file containing products descriptions")

    parser.add_argument("--product-full-path", help="Full path of a single product")
    parser.add_argument("--product-type-id", help="Product type id of the single product")

    parser.add_argument("--output-json", required=True, help="Output JSON file containing the produced products")
    
    args = parser.parse_args()

    config = Config()
    if not config.loadConfig(args.config):
        log(general_log_path, "Could not load the config from configuration file", general_log_filename)
        sys.exit(-1)

    l2a_db = InputProductInfo(config.host, config.database, config.user, config.password)
    
    result = read_request_context_file(args.request_context_file)
    req_params = result["request_parameters"]
    site_info = result["site_info"]
    site_id = site_info["site_id"]
    start_date = site_info["season_start"]
    end_date = site_info["season_end"]

    if args.input_products_json:
        products = read_stac_products(args.input_products_json)
        for p in products:
            print("Product:", p["product"])
            product_id, product_type_id = insert_product(l2a_db, site_id, p)
            
            if product_id and product_type_id:
                p["product_db_id"] = str(product_id)
                p["product_type_id"] = str(product_type_id)
                
                parent_products = p["parent_products"]
                l2a_db.insert_product_provenance(site_id, product_id, parent_products)        
    elif args.product_full_path and args.product_type_id:
        # Single product mode
        product_path = args.product_full_path
        product_info = {}
        product_info["id"] = os.path.basename(product_path[:len(product_path) - 1]) if product_path.endswith("/") else os.path.basename(product_path)
        product_info["product"] = product_path
        product_info["product_metadata"] = product_path
        product_info["relative_orbit"] = str(0)
        product_info["orbit_type"] = None
        product_info["geometry"] = "POLYGON((0 0,0 0,0 0,0 0,0 0))"
        product_info["parent_products"] = []
        
        product_id, product_type_id = handle_simple_product(l2a_db, site_id, start_date, end_date, args.product_type_id, product_info)
        
        product_info["product_db_id"] = str(product_id)
        product_info["product_type_id"] = str(product_type_id)
        
        products = [product_info]
        
    else:
        parser.error(
            "You must provide either --input-products-json "
            "or both --product-full-path and --product-id"
        )
    write_stac_products(products, args.output_json)
    
if __name__ == "__main__":
    main()
    
    