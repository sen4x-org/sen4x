#!/usr/bin/env python3
from __future__ import print_function
import argparse
import re
import glob
from osgeo import gdal
from osgeo import osr
from osgeo import ogr
import subprocess
import math
import os
from os.path import isfile, isdir, join
import glob
import sys
import time
import datetime
from time import gmtime, strftime
import shutil
import psycopg2
import psycopg2.errorcodes
import optparse
import subprocess, sys
import json

try:
    from configparser import ConfigParser
except ImportError:
    from ConfigParser import ConfigParser

###########################################################################
L2A_PRD_TYPE_ID = 1
FMASK_PRD_TYPE_ID = 25
L2A_MSK_PRD_TYPE_ID = 26
PRODUCT_MAP = {
    "MSIL2A":       (1, 1),
    "L3B":          (3, 14),
    "L3BNDVI":      (36, 14),
    "L3BNDWI":      (40, 14),
    "L3BBRIGHT":    (41, 14),
    "L3BLAI":       (37, 14),
    "L3BFAPAR":     (38, 14),
    "L3BFCOVER":    (39, 14),
    # add more mappings here
}


SENTINEL2_SATELLITE_ID = int(1)
LANDSAT8_SATELLITE_ID = int(2)
UNKNOWN_SATELLITE_ID = None

UUID_REGEX = re.compile(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}")

class Config(object):

    def __init__(self):
        self.host = ""
        self.port = ""
        self.database = ""
        self.user = ""
        self.password = ""
        self.orig_host = ""
        
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

class DBHelper(object):

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

    def create_site(self, name) :
        if not self.database_connect():
            return -1
        try:
            geog = "POLYGON((23.705476819901342 44.38221848137339,23.892244398026342 44.38221848137339,23.892244398026342 44.275139739801844,23.705476819901342 44.275139739801844,23.705476819901342 44.38221848137339))"
            self.cursor.execute("""select * from sp_dashboard_add_site(%(name)s :: character varying,
                           %(geog)s :: character varying,
                           %(enabled)s :: boolean)""",
                                {
                                    "name": name,
                                    "geog": geog,
                                    "enabled": False
                                })
            row = self.cursor.fetchone()
            self.conn.commit()
            if row is None:
                return -1
            site_id = row[0]
            self.database_disconnect()
            return site_id
                
        except Exception as e:
            print("Database update query failed: {}".format(e))
            self.database_disconnect()
            return -1        

    def get_site_short_name_from_product_id(self, product_id):
        if not self.database_connect():
            return ""
        try:
            # self.cursor.execute("select site_id from product where id='{}'".format(product_id))
            self.cursor.execute("SELECT s.short_name FROM product p JOIN site s ON p.site_id = s.id WHERE p.id = {}".format(product_id))
            row = self.cursor.fetchone()
            self.database_disconnect()
            return row[0] if row else None
        except Exception as e:
            print("Unable to execute select site_id from product {}".format(e))
            self.database_disconnect()
            return ""
 
    def get_site_id(self, short_name):
        if not self.database_connect():
            return ""
        try:
            self.cursor.execute("select id from site where short_name='{}'".format(short_name))
            rows = self.cursor.fetchall()
            self.database_disconnect()
            return rows[0][0]
        except Exception as e:
            print("Unable to execute select id from site {}".format(e))
            self.database_disconnect()
            return ""

    def get_site_short_name(self, site_id):
        if not self.database_connect():
            return ""
        try:
            self.cursor.execute("select short_name from site where id='{}'".format(site_id))
            rows = self.cursor.fetchall()
            self.database_disconnect()
            return rows[0][0]
        except Exception as e:
            print("Unable to execute select id from site {}".format(e))
            self.database_disconnect()
            return ""

    def get_product_type_name(self, product_type_id):
        if not self.database_connect():
            return ""
        try:
            print("Product Type ID = {}".format(product_type_id)) 
            self.cursor.execute("select name from product_type where id='{}'".format(product_type_id))
            rows = self.cursor.fetchall()
            self.database_disconnect()
            return rows[0][0]
        except Exception as e:
            print("Unable to execute select name from product_type {}".format(e))
            self.database_disconnect()
            return ""

    def update_product_full_path(self, product_id, full_path):
        if not self.database_connect():
            print("Could not connect")
            return ""
        try:
            print("update product set full_path = '{}' where id='{}'".format(full_path, product_id))
            self.cursor.execute("update product set full_path = '{}' where id='{}'".format(full_path, product_id))
            self.conn.commit()
            self.database_disconnect()
        except Exception as e:
            print("Unable to execute select id from product_type {}".format(e))
            self.database_disconnect()

    def get_l2a_geog(self, name, site_id):
        if not self.database_connect():
            return ""
        try:
            self.cursor.execute("select geog from product where name='{}' and site_id = {}".format(name, site_id))
            rows = self.cursor.fetchall()
            self.database_disconnect()
            count = (len(rows))
            if count == 0 :
                print("L2A product for site_id = {} and product name = {} does not exist in product table".format(site_id, name))
                return ""
            print("Extracted geography {} from product for site_id = {} and product name = {}".format(rows[0][0], site_id, name))
            return rows[0][0]
        except Exception as e:
            print("Unable to execute geog from product for site_id = {} and product name = {}, exception = {}".format(site_id, name, e))
            self.database_disconnect()
            return ""

    def set_processed_product(self, processor_id, product_type_id, site_id, l2a_processed_tiles, full_path, product_name, footprint, sat_id, acquisition_date, orbit_id, mosaic_img):
        # input params:
        # product type by default is 1
        # processor id
        # site id
        # job id has to be NULL
        # full path is the whole path to the product including the name
        # created timestamp NULL
        # name product (basename from the full path)
        # quicklook image has to be NULL
        # footprint
        if not self.database_connect():
            return -1
        try:
            if len(l2a_processed_tiles) > 0:
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
                                        "tiles": '[' + ', '.join(['"' + t + '"' for t in l2a_processed_tiles]) + ']'
                                    })
                row = self.cursor.fetchone()
                self.conn.commit()
                if row is None:
                    return -1
                product_id = row[0]
                self.database_disconnect()
                return product_id
                
        except Exception as e:
            print("Database update query failed: {}".format(e))
            self.database_disconnect()
            return -1

def extract_uuid(path):
    parts = path.split(os.sep)
    for p in parts:
        if UUID_REGEX.fullmatch(p):
            uuid_dir = os.path.join(*(parts[:parts.index(p)+1]))
            if os.path.isdir(uuid_dir):
                return p
    return None

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
    if product_type_id == L2A_PRD_TYPE_ID or product_type_id == L2A_MSK_PRD_TYPE_ID or product_type_id == FMASK_PRD_TYPE_ID:
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
        m = re.match(r"\w+(_A|_V)(\w+)", product_name)
        if m != None:
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


def get_product_orbit_id(product_name):
    print("Product name is: {}".format(product_name))
    orbit_id = re.search(r"_R(\d{3})_", product_name)
    if orbit_id == None:
        print("OrbitId cannot be extracted from product name {}".format(product_name))
        return 0
    print("OrbitId is: {}".format(int(orbit_id.group(1))))
    return int(orbit_id.group(1))
    
    
    
def get_product_type_info(product_name):
    m = re.search(r'^[^_]+_([^_]+)_', product_name)
    if not m:
        raise ValueError("Invalid product name format: {}".format(product_name))

    prd_str = m.group(1)

    if prd_str not in PRODUCT_MAP:
        raise ValueError("Unknown product type: {}".format(prd_str))

    product_type_id, processor_id = PRODUCT_MAP[prd_str]

    return prd_str, product_type_id, processor_id

def read_stac_products(jsonl_file):
    results = []
    with open(jsonl_file) as f:
        for line in f:
            item = json.loads(line)
            product_id = item.get("id")
            product_db_id = item.get("properties").get("product_db_id", {})
            product_path = item.get("properties").get("sen4x:disk_path", {})
            relative_orbit = item.get("properties").get("sat:relative_orbit", {})
            orbit_type = item.get("properties").get("sat:orbit_state", {})
            product_type_id = item.get("properties").get("product_type_id", {})
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
                "product_db_id": product_db_id,
                "product_type_id": product_type_id,
                "product_metadata": product_metadata_path,
                "relative_orbit": relative_orbit,
                "orbit_type": orbit_type,
                "geometry" : geometry,
                "parent_products": parent_products
            })

    return results
    
def export_product(config, product_type_id, product_id):
    result = subprocess.run(
        ["stac-ingest-products.py", "--dsn", "dbname={} user={} password={} host={} port={}".format(config.database, config.user, config.password, config.host, config.port), 
            "--stac-url", "http://" + config.host + ":8082", "--product-type-id", str(product_type_id), "--product-id", str(product_id)],
        capture_output=True,
        text=True
    )
    stac_items = result.stdout
    stac_items = stac_items.replace(config.host, config.orig_host)

    print("stac-ingest-products.py Return code:", result.returncode)
    print("stac-ingest-products.py STDOUT:")
    print(result.stdout)
    print("stac-ingest-products.py STDERR:")
    print(result.stderr)
    print("stac items : ");
    print(stac_items)
    
    return stac_items


def copy_product_to_output_dir(product_path, site_short_name, product_type, dest_root_dir):
    dest_path = product_path

    if not dest_root_dir:
        return dest_path

    # Common destination preparation
    dest_root_dir = os.path.join(dest_root_dir, site_short_name, product_type )

    print("Destination root is : {}".format(dest_root_dir))

    os.makedirs(dest_root_dir, exist_ok=True)

    if os.path.isdir(product_path):
        folder_name = os.path.basename(os.path.normpath(product_path))
        dest_path = os.path.join(dest_root_dir, folder_name)

        try:
            print("Copying {} to {}...".format(folder_name, dest_root_dir))
            shutil.copytree(product_path, dest_path)
            print("Successfully copied {}".format(folder_name))
        except shutil.Error as e:
            print("Error copying directory {} - {}".format(folder_name, e))
        except OSError as e:
            print("OS error during copy of {}: {}".format(folder_name, e))

    elif os.path.isfile(product_path):
        file_name = os.path.basename(product_path)
        file_base_name = os.path.splitext(file_name)[0]

        # Create a folder named after the file (without extension)
        dest_folder = os.path.join(dest_root_dir, file_base_name)
        os.makedirs(dest_folder, exist_ok=True)

        dest_path = os.path.join(dest_folder, file_name)

        try:
            print("Copying {} to {}...".format(file_name, dest_folder))
            shutil.copy2(product_path, dest_path)
            print("Successfully copied {}".format(file_name))
        except OSError as e:
            print("OS error during copy of {}: {}".format(file_name, e))

    return dest_path
    
def create_user_global_site_if_missing(db_helper, site_name) :
    site_short_name = site_name.lower()
    site_short_name = site_short_name.replace('-', '_')

    site_id = db_helper.get_site_id(site_short_name)
    if(site_id == ''):
        print("Site with name {} does not exist. Creating a new one.".format(site_short_name))    
        site_id = db_helper.create_site(site_short_name)
        site_short_name = db_helper.get_site_short_name(site_id)

    return site_id, site_short_name
    
def insert_product(db_helper, site_id, processor_id, product_type_id, product_dir):
    l2a_processed_tiles = []
    wkt = []
    sat_id = 0
    acquisition_date = ""
    mosaic_img = "mosaic.jpg"

    if not product_dir.endswith(os.path.sep):
        product_dir += os.path.sep
    print("Output path: {}".format(product_dir))

    product_name = os.path.basename(product_dir[:len(product_dir) - 1]) if product_dir.endswith("/") else os.path.basename(product_dir)
    print("Product dir is: {}".format(product_name))
    wgs84_extent_list = []
    if product_type_id == L2A_PRD_TYPE_ID or product_type_id == L2A_MSK_PRD_TYPE_ID or product_type_id == FMASK_PRD_TYPE_ID:
        if product_name.startswith("S2"):
            satellite_id = SENTINEL2_SATELLITE_ID
        else:
            satellite_id = LANDSAT8_SATELLITE_ID
        tiles_dir_list = (glob.glob("{}*.DBL.DIR".format(product_dir)))
        tile_img = []
        if len(tiles_dir_list) > 0 :
            print("Creating common footprint for tiles: DBL.DIR List: {}".format(tiles_dir_list))
            for tile_dir in tiles_dir_list:
                if satellite_id == SENTINEL2_SATELLITE_ID:
                    tile_img = (glob.glob("{}/*_FRE_R1.DBL.TIF".format(tile_dir)))
                else:  # satellite_id is LANDSAT8_SATELLITE_ID:
                    tile_img = (glob.glob("{}/*_FRE.DBL.TIF".format(tile_dir)))
        else :
            # Check for MAJA format
            tiles_dir_list = (glob.glob("{}SENTINEL2*".format(product_dir)))
            if len(tiles_dir_list) > 0 :
                print("Creating common footprint for tiles: DBL.DIR List: {}".format(tiles_dir_list))
                for tile_dir in tiles_dir_list:
                    if satellite_id == SENTINEL2_SATELLITE_ID:
                        tile_img = (glob.glob("{}/*_FRE_B2.tif".format(tile_dir)))
            else :
                # Check for Sen2Cor format
                tiles_dir_list = (glob.glob("{}GRANULE/L2A_T*".format(product_dir)))
                if len(tiles_dir_list) > 0 :
                    print("Creating common footprint for tiles: {}".format(tiles_dir_list))
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
            print("Creating common footprint for tiles: {}".format(tiles_dir_list))
            for tile_dir in tiles_dir_list:
                tile_img = (glob.glob("{}/IMG_DATA/S2AGRI_*.TIF".format(tile_dir)))
                if len(tile_img) > 0:
                    wgs84_extent_list.append(get_footprint(tile_img[0]))

    wkt = get_envelope(wgs84_extent_list)

    orbit_id = 0
    if len(wkt) == 0:
        print("Could not create the footprint")
    else:
        sat_id, acquisition_date = get_product_info(product_name, product_type_id)
        if product_type_id == L2A_PRD_TYPE_ID or product_type_id == L2A_MSK_PRD_TYPE_ID or product_type_id == FMASK_PRD_TYPE_ID:
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
                print("Processed tiles: {}  to path: {}".format(l2a_processed_tiles, product_dir))
            else:
                print("Could not get the acquisition date from the product name {}".format(product_dir))
        else:
            for tile_dbl_dir in tiles_dir_list:
                tile = re.search("\w+_T(\w+)", tile_dbl_dir)
                if tile is not None and not tile.group(1) in l2a_processed_tiles:
                    l2a_processed_tiles.append(tile.group(1))

    if len(l2a_processed_tiles) > 0:
        print("Insert info in product table and set state as processed in product table for product {}".format(product_dir))
    else:
        print("Only set the state as processed in product (no l2a tiles found after maccs) for product {}".format(product_dir))

    return db_helper.set_processed_product(processor_id, product_type_id, site_id, l2a_processed_tiles, product_dir, os.path.basename(product_dir[:len(product_dir) - 1]), wkt, sat_id, acquisition_date, orbit_id, mosaic_img)
    
def main():
    parser = argparse.ArgumentParser(
        description="Script for inserting products into the database")
    parser.add_argument('-c', '--config', default="/etc/sen2agri/sen2agri.conf", help="configuration file")

    group = parser.add_mutually_exclusive_group(required=True)
    
    group.add_argument("-i", "--input-products-json", help="Input JSON file containing products extracted from STAC")
    group.add_argument('-d', '--root-dir', help="The root directory containing the product folder")

    parser.add_argument('-o', '--output-dir', help="The target directory where the product is copied", default="", required=False)
    parser.add_argument('-e', '--output-stack-entries-file', help="Output file containing the STAC entries created")

    args = parser.parse_args()

    config = Config()
    if not config.loadConfig(args.config):
        print("Could not load the config from configuration file")
        sys.exit(-1)


    db_helper = DBHelper(config.host, config.database, config.user, config.password)
    
    stac_products = []
    
    if args.input_products_json:
        print("Processing file:", args.input_products_json)
        products = read_stac_products(args.input_products_json)
        for p in products:
            product_db_id = p["product_db_id"]
            product_path = p["product"]
            product_type_id = p["product_type_id"]
            site_short_name = db_helper.get_site_short_name_from_product_id(product_db_id)
            product_type_name = db_helper.get_product_type_name(product_type_id)
            
            print("Copying product {} (from json) with db_id = {} to {} for site {} and product type {} ...".format(product_path, product_db_id, args.output_dir, site_short_name, product_type_name))
            
            product_path = copy_product_to_output_dir(product_path, site_short_name, product_type_name, args.output_dir)
            print("Updating product in DB...")
            db_helper.update_product_full_path(product_db_id, product_path)
            stac_product = export_product(config, product_type_id, product_db_id)
            stac_products.append(stac_product)
            
    elif args.root_dir:
        print("Root directory provided for products: {}".format(args.root_dir))
        site_name = extract_uuid(args.root_dir)
        if site_name :
            site_id, site_short_name = create_user_global_site_if_missing(db_helper, site_name)
            search_pattern = os.path.join(args.root_dir, 'S2AGRI_*')
            
            for product_path in glob.glob(search_pattern):
                if os.path.isdir(product_path):
                    product_name = os.path.basename(product_path[:len(product_path) - 1]) if product_path.endswith("/") else os.path.basename(product_path)
                    prd_str, product_type_id, processor_id = get_product_type_info(product_name)
                    product_type_name = db_helper.get_product_type_name(product_type_id)
                     
                    print("Copying product {} (from directory) to {} for site {} and product type {} ...".format(product_path, args.output_dir, site_short_name, product_type_name))
                    
                    product_path = copy_product_to_output_dir(product_path, site_short_name, product_type_name, args.output_dir)
                    product_id = insert_product(db_helper, site_id, processor_id, product_type_id, product_path)
                    stac_product = export_product(config,  product_type_id, product_id)
                    stac_products.append(stac_product)

    with open(args.output_stack_entries_file, "w") as output_stack_entries_file:
        for product in stac_products:
            output_stack_entries_file.write(product)

if __name__ == "__main__":
    main()
    
