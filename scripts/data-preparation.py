#!/usr/bin/env python3
import argparse
import csv
import io
import json
import logging
import os
import os.path
import queue
import shutil
import subprocess
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor
from configparser import ConfigParser
from datetime import date
from pathlib import Path
from urllib.parse import urlsplit

import psycopg2
import psycopg2.extensions
from osgeo import gdal, ogr, osr
from psycopg2.sql import SQL, Identifier, Literal

PRODUCT_TYPE_LPIS = 14
PROCESSOR_LPIS = 8

MODE_UPDATE = 0
MODE_REPLACE = 1
MODE_INCREMENTAL = 2

INTEGER_TYPES = {
    "smallint",
    "integer",
    "bigint",
}
NUMERIC_TYPES = INTEGER_TYPES | {"real", "double precision", "numeric"}


def try_rm_file(f):
    try:
        os.remove(f)
        return True
    except OSError:
        return False


def get_ogr_path(path):
    if path.startswith(("http://", "https://")):
        is_zip = urlsplit(path).path.lower().endswith(".zip")
        path = f"/vsicurl/{path}"
    else:
        is_zip = path.lower().endswith(".zip")
    if is_zip:
        path = f"/vsizip/{path}"
    return path


class Config:
    def __init__(self, args):
        parser = ConfigParser()
        parser.read([args.config_file])

        self.host = parser.get("Database", "HostName")

        # work around Docker networking scheme
        if self.host == "127.0.0.1" or self.host == "::1" or self.host == "localhost":
            self.host = "172.17.0.1"

        self.port = int(parser.get("Database", "Port", vars={"Port": "5432"}))
        self.dbname = parser.get("Database", "DatabaseName")
        self.user = parser.get("Database", "UserName")
        self.password = parser.get("Database", "Password")

        self.site_id = args.site_id


class RasterizeDatasetCommand:
    def __init__(
        self,
        input,
        output,
        tile,
        resolution,
        sql,
        field,
        srs,
        dst_xmin,
        dst_ymin,
        dst_xmax,
        dst_ymax,
    ):
        self.input = input
        self.output = output
        self.tile = tile
        self.resolution = str(resolution)
        self.sql = sql
        self.field = field
        self.srs = srs
        self.dst_xmin = str(dst_xmin)
        self.dst_ymin = str(dst_ymin)
        self.dst_xmax = str(dst_xmax)
        self.dst_ymax = str(dst_ymax)

    def run(self):
        options = gdal.RasterizeOptions(
            attribute=self.field,
            outputSRS=self.srs,
            outputBounds=[
                self.dst_xmin,
                self.dst_ymin,
                self.dst_xmax,
                self.dst_ymax,
            ],
            xRes=self.resolution,
            yRes=self.resolution,
            SQLStatement=self.sql,
            outputType=gdal.GDT_Int32,
            creationOptions=["COMPRESS=DEFLATE", "PREDICTOR=2"],
        )
        gdal.Rasterize(self.output, self.input, options=options)


class ExportParcelsCsvCommand:
    def __init__(self, sql, destination, source):
        self.sql = sql
        self.destination = destination
        self.source = source

    def run(self):
        options = gdal.VectorTranslateOptions(
            layerCreationOptions=["STRING_QUOTING=IF_NEEDED"],
            SQLStatement=self.sql,
        )
        gdal.VectorTranslate(self.destination, self.source, options=options)


class ExportParcelsGpkgCommand:
    def __init__(self, srs, sql, destination, source):
        self.srs = srs
        self.sql = sql
        self.destination = destination
        self.source = source

    def run(self):
        options = gdal.VectorTranslateOptions(
            dstSRS=self.srs,
            mapFieldType="DateTime=String",
            SQLStatement=self.sql,
        )
        gdal.VectorTranslate(self.destination, self.source, options=options)


class ExportParcelsShpCommand:
    def __init__(self, sql, destination, source):
        self.sql = sql
        self.destination = destination
        self.source = source

    def run(self):
        options = gdal.VectorTranslateOptions(
            accessMode="overwrite", SQLStatement=self.sql
        )
        gdal.VectorTranslate(self.destination, self.source, options=options)


def get_esri_wkt(epsg_code):
    srs = osr.SpatialReference()
    srs.ImportFromEPSG(epsg_code)
    srs.MorphToESRI()
    return srs.ExportToWkt()


class Tile:
    def __init__(self, tile_id, epsg_code, tile_extent):
        self.tile_id = tile_id
        self.epsg_code = epsg_code
        self.tile_extent = tile_extent


def get_table_column_types(conn, schema, table, columns=None):
    with conn.cursor() as cursor:
        query = SQL(
            """
select column_name, data_type
from information_schema.columns
where table_schema = %s
  and table_name = %s"""
        )
        params = [schema, table]
        if columns is not None:
            query += SQL(" and column_name = any(%s)")
            params.append(columns)
        cursor.execute(query, params)
        return dict(cursor.fetchall())


def get_integer_type(conn, table, column):
    with conn.cursor() as cursor:
        query = SQL(
            """select bool_and({column} = trunc({column})
                       and {column} >= -9223372036854775808
                       and {column} < 9223372036854775808),
       bool_and({column} >= -2147483648 and {column} <= 2147483647)
from {table}"""
        ).format(column=Identifier(column), table=Identifier(table))
        cursor.execute(query)
        valid, fits_integer = cursor.fetchone()
    if valid is False:
        raise ValueError(
            f"Invalid column `{column}`: expected finite integers within bigint range"
        )
    return "bigint" if fits_integer is False else "integer"


def validate_lut(conn, table):
    integer_columns = ["ctnum", "lc", "ctnuml4a", "ctnumdiv"]
    flag_columns = ["eaa", "al", "pgrass", "tgrass", "fallow", "cwater"]
    types = get_table_column_types(conn, "public", table)
    errors = []

    column_type = types.get("ori_crop")
    if column_type is None:
        errors.append("missing column `ori_crop`")
    elif column_type != "text" and column_type not in NUMERIC_TYPES:
        errors.append(
            f"column `ori_crop` has type {column_type}, expected text or numeric"
        )

    for column in integer_columns:
        column_type = types.get(column)
        if column_type is None:
            errors.append(f"missing column `{column}`")
        elif column_type not in INTEGER_TYPES:
            errors.append(f"column `{column}` has type {column_type}, expected integer")

    for column in flag_columns:
        column_type = types.get(column)
        if column_type is None:
            errors.append(f"missing column `{column}`")
        elif column_type not in INTEGER_TYPES and column_type != "boolean":
            errors.append(
                f"column `{column}` has type {column_type}, expected integer or boolean"
            )
    if errors:
        raise ValueError(f"Invalid LUT: {'; '.join(errors)}")

    with conn.cursor() as cursor:
        for column in flag_columns:
            if types[column] == "boolean":
                continue
            query = SQL(
                "select {col} from {table} where {col} not in (0, 1) limit 1"
            ).format(col=Identifier(column), table=Identifier(table))
            cursor.execute(query)
            row = cursor.fetchone()
            if row is not None:
                raise ValueError(
                    f"Invalid LUT column `{column}` expected 0 or 1, got {row[0]!r}"
                )
    return types


def validate_lpis(conn, table, parcel_id_cols, holding_id_cols, crop_code_col):
    types = get_table_column_types(conn, "public", table)
    errors = []
    for column in parcel_id_cols + holding_id_cols + [crop_code_col]:
        column_type = types.get(column)
        if column_type is None:
            errors.append(f"missing column `{column}`")
        elif column_type != "text" and column_type not in NUMERIC_TYPES:
            errors.append(
                f"column `{column}` has type {column_type}, expected text or numeric"
            )
    for column in ["ori_id", "ori_hold", "ori_crop"]:
        if column in types:
            errors.append(f"`{column}` is not an allowed LPIS column name")
    if errors:
        raise ValueError(f"Invalid LPIS: {'; '.join(errors)}")
    return types


def adjust_crop_code_types(conn, tables):
    types = {
        table: get_table_column_types(conn, "public", table, ["ori_crop"])["ori_crop"]
        for table in tables
    }
    column_types = set(types.values())
    if len(column_types) <= 1:
        return next(iter(column_types), None)

    if "smallint" in column_types or "integer" in column_types:
        target_type = "integer"
    else:
        target_type = "bigint"

    try:
        with conn.cursor() as cursor:
            if target_type == "integer":
                for table, column_type in types.items():
                    if column_type != "bigint":
                        continue
                    cursor.execute(
                        SQL(
                            "select exists (select * from {} "
                            "where ori_crop not between -2147483648 and 2147483647)"
                        ).format(Identifier(table))
                    )
                    if cursor.fetchone()[0]:
                        target_type = "bigint"
                        break
            for table, column_type in types.items():
                if column_type == target_type:
                    continue
                logging.info(
                    "Converting %s.ori_crop from %s to %s",
                    table,
                    column_type,
                    target_type,
                )
                cursor.execute(
                    SQL(
                        "alter table {table} alter column ori_crop type {type} "
                        "using ori_crop::{type}"
                    ).format(table=Identifier(table), type=SQL(target_type))
                )
    except psycopg2.DataError as exc:
        raise ValueError(
            "Cannot match crop codes: `ori_crop` contains values that cannot be "
            f"converted to {target_type}: {exc.diag.message_primary}"
        ) from exc
    return target_type


def table_exists(conn, schema, name):
    with conn.cursor() as cursor:
        query = SQL(
            """
select exists (
    select *
    from pg_class
    inner join pg_namespace on pg_namespace.oid = pg_class.relnamespace
    where pg_class.relname = %s
      and pg_namespace.nspname = %s
);"""
        )
        cursor.execute(query, (name, schema))
        return cursor.fetchone()[0]


def index_exists(conn, name):
    with conn.cursor() as cursor:
        query = SQL(
            """
select exists (
    select *
    from pg_index
    inner join pg_class on pg_class.oid = pg_index.indexrelid
    where pg_class.relname = %s
);"""
        )
        cursor.execute(query, (name,))
        return cursor.fetchone()[0]


def add_table_columns(conn, schema, table, columns):
    existing_columns = get_table_column_types(conn, schema, table)
    with conn.cursor() as cursor:
        query = SQL("alter table {}\n").format(Identifier(table))
        to_add = []
        for column, ty in columns:
            if column not in existing_columns:
                q = SQL("add column {} {}").format(Identifier(column), SQL(ty))
                to_add.append(q)
        if to_add:
            query += SQL(",\n").join(to_add)
            query += SQL(";")
            logging.debug(query.as_string(conn))
            cursor.execute(query)


def drop_table_columns(conn, schema, table, columns):
    existing_columns = get_table_column_types(conn, schema, table)
    with conn.cursor() as cursor:
        query = SQL("alter table {}\n").format(Identifier(table))
        to_drop = []
        for column in columns:
            if column in existing_columns:
                q = SQL("drop column if exists {}").format(Identifier(column))
                to_drop.append(q)
        if to_drop:
            query += SQL(",\n").join(to_drop)
            query += SQL(";")
            logging.debug(query.as_string(conn))
            cursor.execute(query)


def create_index(conn, table, columns):
    with conn.cursor() as cursor:
        name = "ix_{}_{}".format(table, "_".join(columns))
        if not index_exists(conn, name):
            cols = SQL(", ").join([Identifier(c) for c in columns])
            query = SQL("create index {} on {}({});").format(
                Identifier(name), Identifier(table), cols
            )
            logging.debug(query.as_string(conn))
            cursor.execute(query)


def drop_index(conn, table, columns):
    with conn.cursor() as cursor:
        name = "ix_{}_{}".format(table, "_".join(columns))
        query = SQL("drop index if exists {};").format(Identifier(name))
        logging.debug(query.as_string(conn))
        cursor.execute(query)


def create_spatial_index(conn, table, column):
    with conn.cursor() as cursor:
        name = f"ix_{table}_{column}"
        if not index_exists(conn, name):
            query = SQL("create index {} on {} using gist({});").format(
                Identifier(name), Identifier(table), Identifier(column)
            )
            logging.debug(query.as_string(conn))
            cursor.execute(query)


def drop_spatial_index(conn, table, column):
    with conn.cursor() as cursor:
        name = f"ix_{table}_{column}"
        query = SQL("drop index if exists {};").format(Identifier(name))
        logging.debug(query.as_string(conn))
        cursor.execute(query)


def create_primary_key(conn, table, columns):
    with conn.cursor() as cursor:
        name = f"{table}_pkey"
        if not index_exists(conn, name):
            cols = SQL(", ").join([Identifier(c) for c in columns])
            query = SQL("alter table {} add constraint {} primary key({});").format(
                Identifier(table), Identifier(name), cols
            )
            logging.debug(query.as_string(conn))
            cursor.execute(query)


def get_site_info(conn, site_id):
    with conn.cursor() as cursor:
        query = SQL(
            "select short_name, ST_AsBinary(geog::geometry) from site where id = %s"
        )
        cursor.execute(query, (site_id,))
        row = cursor.fetchone()
        conn.commit()
        if row:
            name, wkb = row
            geom = ogr.CreateGeometryFromWkb(wkb)
            srs = osr.SpatialReference()
            srs.ImportFromEPSG(4326)
            srs.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)
            geom.AssignSpatialReference(srs)
            return name, geom
    return None, None


def get_site_srid(conn, lpis_table):
    with conn.cursor() as cursor:
        query = SQL("select Find_SRID('public', %s, 'wkb_geometry')")
        cursor.execute(query, (lpis_table,))
        rows = cursor.fetchall()
        conn.commit()
        return rows[0][0]


def get_site_utm_epsg_codes(conn, site_id):
    with conn.cursor() as cursor:
        query = SQL(
            """
            select distinct
                   shape_tiles_s2.epsg_code
            from sp_get_site_tiles(%s::smallint, 1::smallint) site_tiles
            inner join shape_tiles_s2 on shape_tiles_s2.tile_id = site_tiles.tile_id;"""
        )

        cursor.execute(query, (site_id,))
        rows = cursor.fetchall()

        result = []
        for (epsg_code,) in rows:
            result.append(epsg_code)

        return result


def get_site_tiles(conn, site_id):
    with conn.cursor() as cursor:
        query = SQL(
            """
select shape_tiles_s2.tile_id,
       shape_tiles_s2.epsg_code,
       ST_AsBinary(ST_SnapToGrid(ST_Transform(shape_tiles_s2.geog::geometry, shape_tiles_s2.epsg_code), 1)) as tile_extent
from sp_get_site_tiles(%s::smallint, 1::smallint) site_tiles
inner join shape_tiles_s2 on shape_tiles_s2.tile_id = site_tiles.tile_id;"""
        )
        logging.debug(query.as_string(conn))
        cursor.execute(query, (site_id,))

        rows = cursor.fetchall()
        conn.commit()

        result = []
        for tile_id, epsg_code, tile_extent in rows:
            tile_extent = ogr.CreateGeometryFromWkb(tile_extent)
            srs = osr.SpatialReference()
            srs.ImportFromEPSG(epsg_code)
            srs.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)
            tile_extent.AssignSpatialReference(srs)
            result.append(Tile(tile_id, epsg_code, tile_extent))

        return result


class DataPreparation:
    def __init__(self, config, year, working_path):
        self.config = config
        self.year = year
        self.pool = ThreadPoolExecutor()

        with self.get_connection() as conn:
            print("Retrieving site tiles")
            site_name, self.site_geom = get_site_info(conn, config.site_id)
            self.tiles = get_site_tiles(conn, config.site_id)

        self.lpis_table = f"decl_{site_name}_{year}"
        self.lpis_table_staging = f"decl_{site_name}_{year}_staging"
        self.lut_table = f"lut_{site_name}_{year}"

        lpis_path = get_lpis_path(conn, config.site_id)
        lpis_path = lpis_path.replace("{year}", str(year))
        lpis_path = lpis_path.replace("{site}", site_name)

        os.makedirs(lpis_path, exist_ok=True)
        if not working_path:
            working_path = lpis_path
        else:
            os.makedirs(working_path, exist_ok=True)

        self.lpis_path = lpis_path
        self.working_path = working_path

    def get_connection(self):
        return psycopg2.connect(
            host=self.config.host,
            port=self.config.port,
            dbname=self.config.dbname,
            user=self.config.user,
            password=self.config.password,
        )

    def get_ogr_connection_string(self):
        return f"PG:dbname={self.config.dbname} host={self.config.host} port={self.config.port} user={self.config.user} password={self.config.password}"

    def find_overlaps(self, srid, tile_counts, total):
        if total == 0:
            return set()

        try:
            q = queue.Queue()
            futures = [
                self.pool.submit(self.get_overlapping_parcels, srid, q, t)
                for t in self.tiles
            ]

            progress = 0
            sys.stdout.write("Finding overlapping parcels: 0.00%")
            sys.stdout.flush()
            for i in range(len(self.tiles)):
                tile = q.get()
                progress += tile_counts[tile.tile_id]
                sys.stdout.write(
                    f"\rFinding overlapping parcels: {100.0 * progress / total:.2f}%"
                )
                sys.stdout.flush()
            sys.stdout.write("\n")
            sys.stdout.flush()

            overlaps = {parcel for future in futures for parcel in future.result()}
            if overlaps:
                logging.warning(f"{len(overlaps)} overlapping parcels")
            return overlaps
        except Exception as e:
            logging.error(e)
            sys.exit(1)

    def find_duplicates(self, srid, tile_counts, total):
        if total == 0:
            return set()

        try:
            q = queue.Queue()
            futures = [
                self.pool.submit(self.get_duplicate_parcels, srid, q, t)
                for t in self.tiles
            ]

            progress = 0
            sys.stdout.write("Finding duplicate parcels: 0.00%")
            sys.stdout.flush()
            for i in range(len(self.tiles)):
                tile = q.get()
                progress += tile_counts[tile.tile_id]
                sys.stdout.write(
                    f"\rFinding duplicate parcels: {100.0 * progress / total:.2f}%"
                )
                sys.stdout.flush()
            sys.stdout.write("\n")
            sys.stdout.flush()

            duplicates = {parcel for future in futures for parcel in future.result()}
            if duplicates:
                logging.warning(f"{len(duplicates)} duplicate parcels")
            return duplicates
        except Exception as e:
            logging.error(e)
            sys.exit(1)

    def prepare_lut(self, lut_path):
        with self.get_connection() as conn:
            print("Importing LUT")
            is_csv = urlsplit(lut_path).path.lower().endswith(".csv")
            lut_path = get_ogr_path(lut_path)
            if lut_path.startswith("/vsizip/"):
                is_csv = any(
                    name.lower().endswith(".csv")
                    for name in gdal.ReadDir(lut_path) or []
                )
            lut_ds = gdal.OpenEx(
                lut_path,
                gdal.OF_VECTOR,
                # force CSV when a query string is present
                allowed_drivers=["CSV"] if is_csv else [],
                open_options=["AUTODETECT_TYPE=YES"] if is_csv else [],
            )
            options = gdal.VectorTranslateOptions(
                layerCreationOptions=["FID=ogc_fid", "PRECISION=NO"],
                layerName=self.lut_table,
                accessMode="overwrite",
            )
            gdal.VectorTranslate(
                self.get_ogr_connection_string(), lut_ds, options=options
            )

            print("Preparing LUT")
            column_types = validate_lut(conn, self.lut_table)
            crop_type = column_types["ori_crop"]
            if crop_type in NUMERIC_TYPES - INTEGER_TYPES:
                crop_type = get_integer_type(conn, self.lut_table, "ori_crop")
            with conn.cursor() as cursor:
                lut_pkey_name = f"{self.lut_table}_pkey"
                lut_key_name = f"{self.lut_table}_ori_crop_key"

                query = SQL(
                    """alter table {table}
drop column ogc_fid,
alter column ori_crop type {crop_type} using ori_crop::{crop_type},
alter column ctnum type int using ctnum::int,
alter column lc type int using lc::int,
alter column ctnuml4a type int using ctnuml4a::int,
alter column ctnumdiv type int using ctnumdiv::int,
alter column eaa type bit using eaa::int::bit,
alter column al type bit using al::int::bit,
alter column pgrass type bit using pgrass::int::bit,
alter column tgrass type bit using tgrass::int::bit,
alter column fallow type bit using fallow::int::bit,
alter column cwater type bit using cwater::int::bit,
alter column ctnum set not null,
alter column lc set not null,
alter column ctnuml4a set not null,
alter column ctnumdiv set not null,
alter column eaa set not null,
alter column al set not null,
alter column pgrass set not null,
alter column tgrass set not null,
alter column fallow set not null,
alter column cwater set not null,
add constraint {pkey} primary key(ctnum),
add constraint {key} unique(ori_crop);"""
                ).format(
                    table=Identifier(self.lut_table),
                    crop_type=SQL(crop_type),
                    pkey=Identifier(lut_pkey_name),
                    key=Identifier(lut_key_name),
                )
                logging.debug(query.as_string(conn))
                cursor.execute(query)
                if table_exists(conn, "public", self.lpis_table):
                    adjust_crop_code_types(conn, [self.lpis_table, self.lut_table])
                conn.commit()

    def prepare_lpis_staging(
        self,
        mode,
        parcel_id_cols,
        holding_id_cols,
        crop_code_col,
        lpis,
        parcel_id_offset,
        holding_id_offset,
    ):
        if not parcel_id_cols or not holding_id_cols or not crop_code_col:
            raise ValueError(
                "LPIS import requires --parcel-id-cols, --holding-id-cols and --crop-code-col"
            )
        lpis = get_ogr_path(lpis)
        ds = ogr.Open(lpis, 0)
        layer = ds.GetLayer()
        srs = layer.GetSpatialRef()
        is_projected = srs.IsProjected()
        del ds

        parcel_id_cols = [col.lower() for col in parcel_id_cols]
        holding_id_cols = [col.lower() for col in holding_id_cols]
        crop_code_col = crop_code_col.lower()

        print("Importing LPIS")
        options = gdal.VectorTranslateOptions(
            layerCreationOptions=[
                "UNLOGGED=YES",
                "SPATIAL_INDEX=NONE",
                "FID=ogc_fid",
                "GEOMETRY_NAME=wkb_geometry",
                "PRECISION=NO",
            ],
            geometryType="MULTIPOLYGON",
            layerName=self.lpis_table_staging,
            accessMode="overwrite",
        )
        gdal.VectorTranslate(self.get_ogr_connection_string(), lpis, options=options)

        print("Preparing LPIS")
        with self.get_connection() as conn:
            with conn.cursor() as cursor:
                print("Initializing")
                lpis_table_id = Identifier(self.lpis_table)
                lpis_table_staging_id = Identifier(self.lpis_table_staging)
                lpis_ids_table = f"{self.lpis_table}_ids"
                lpis_ids_id = Identifier(lpis_ids_table)

                column_types = validate_lpis(
                    conn,
                    self.lpis_table_staging,
                    parcel_id_cols,
                    holding_id_cols,
                    crop_code_col,
                )
                id_columns = {
                    column: Identifier(column)
                    for column in parcel_id_cols + holding_id_cols + [crop_code_col]
                }
                for column in id_columns:
                    if column_types[column] in NUMERIC_TYPES - INTEGER_TYPES:
                        column_type = get_integer_type(
                            conn, self.lpis_table_staging, column
                        )
                        id_columns[column] = SQL("{}::{}").format(
                            Identifier(column), SQL(column_type)
                        )
                cursor.execute(SQL("analyze {}").format(lpis_table_staging_id))

                print("Computing parcel identifiers")
                cursor.execute(SQL("drop table if exists {}").format(lpis_ids_id))
                query = SQL(
                    """create unlogged table {ids} as
with parcels as (
    select ogc_fid,
           {parcel_id} as ori_id,
           ({holding_id})::text as ori_hold,
           {crop_code} as ori_crop,
           row_number() over(partition by {partition} order by ogc_fid) as rn,
           count(*) over(partition by {partition}) as count
    from {staging}
)
select ogc_fid,
       ori_id || case
           when count = 1 then ''
           when rn <= 26 then '-' || chr(64 + rn::int)
           else '-' || chr(64 + (rn / 26)::int) || chr(64 + (rn % 26)::int)
       end as ori_id,
       ori_hold, ori_crop,
       null::int as "NewID",
       null::int as "HoldID",
       true as is_new
from parcels;"""
                ).format(
                    ids=lpis_ids_id,
                    staging=lpis_table_staging_id,
                    parcel_id=SQL(" || '-' || ").join(
                        id_columns[column] for column in parcel_id_cols
                    ),
                    holding_id=SQL(" || '-' || ").join(
                        id_columns[column] for column in holding_id_cols
                    ),
                    crop_code=id_columns[crop_code_col],
                    partition=SQL(", ").join(map(Identifier, parcel_id_cols)),
                )
                logging.debug(query.as_string(conn))
                cursor.execute(query)

                print("Fixing up types")
                query = SQL(
                    """alter table {}
alter column ori_id set not null,
alter column ori_hold set not null,
alter column ori_crop set not null;"""
                ).format(lpis_ids_id)
                logging.debug(query.as_string(conn))
                cursor.execute(query)

                crop_tables = [lpis_ids_table]
                reuse_lpis = mode != MODE_REPLACE and table_exists(
                    conn, "public", self.lpis_table
                )
                if reuse_lpis:
                    crop_tables.append(self.lpis_table)
                if table_exists(conn, "public", self.lut_table):
                    crop_tables.append(self.lut_table)
                crop_code_type = adjust_crop_code_types(conn, crop_tables)
                cursor.execute(SQL("analyze {}").format(lpis_ids_id))

                if mode == MODE_REPLACE:
                    print("Removing old LPIS")
                    query = SQL("drop table if exists {};").format(lpis_table_id)
                    logging.debug(query.as_string(conn))
                    cursor.execute(query)

                print("Making sure destination table exists")
                query = SQL(
                    """create table if not exists {} (
    like {},
    ori_id text not null,
    ori_hold text not null,
    ori_crop {} not null,
    "NewID" int,
    "HoldID" int,
    "GeomValid" boolean not null,
    "Duplic" boolean not null,
    "Overlap" boolean not null,
    "Area_meters" real not null,
    "ShapeInd" real,
    "S1Pix" int not null default 0,
    "S2Pix" int not null default 0,
    is_deleted boolean default false,
    inserted_timestamp timestamp with time zone not null default now(),
    updated_timestamp timestamp with time zone,
    geom_change_ratio real
);"""
                ).format(lpis_table_id, lpis_table_staging_id, SQL(crop_code_type))
                logging.debug(query.as_string(conn))
                cursor.execute(query)

                print("Fixing up columns")
                drop_table_columns(conn, "public", self.lpis_table, ["ogc_fid"])

                if reuse_lpis:
                    add_table_columns(
                        conn,
                        "public",
                        self.lpis_table,
                        [
                            ("is_deleted", "boolean default false"),
                            (
                                "inserted_timestamp",
                                "timestamp with time zone not null default now()",
                            ),
                            ("updated_timestamp", "timestamp with time zone"),
                            ("geom_change_ratio", "real"),
                        ],
                    )
                    create_index(conn, self.lpis_table, ["ori_id"])
                    create_index(conn, self.lpis_table, ["ori_hold"])

                    print("Copying existing parcel and holding identifiers")
                    query = SQL(
                        """with holdings as (
    select ori_hold, min("HoldID") as "HoldID"
    from {lpis}
    group by ori_hold
), matches as (
    select new.ogc_fid, old."NewID", holdings."HoldID",
           old.ori_id is null as is_new
    from {ids} new
    left join {lpis} old on old.ori_id = new.ori_id
    left join holdings on holdings.ori_hold = new.ori_hold
)
update {ids} new
set "NewID" = matches."NewID",
    "HoldID" = matches."HoldID",
    is_new = matches.is_new
from matches
where new.ogc_fid = matches.ogc_fid;"""
                    ).format(lpis=lpis_table_id, ids=lpis_ids_id)
                    logging.debug(query.as_string(conn))
                    cursor.execute(query)

                    query = SQL(
                        'select coalesce(max("NewID"), 0), coalesce(max("HoldID"), 0) from {}'
                    ).format(lpis_table_id)
                    logging.debug(query.as_string(conn))
                    cursor.execute(query)
                    parcel_base, holding_base = cursor.fetchone()
                else:
                    parcel_base = holding_base = 0

                print("Renumbering new parcels and holdings")
                query = SQL(
                    """with parcels as (
    select ogc_fid, row_number() over (order by ori_id) + %s as "NewID"
    from {ids}
    where "NewID" is null
), holdings as (
    select ogc_fid, dense_rank() over (order by ori_hold) + %s as "HoldID"
    from {ids}
    where "HoldID" is null
)
update {ids} new
set "NewID" = coalesce(new."NewID", parcels."NewID"),
    "HoldID" = coalesce(new."HoldID", holdings."HoldID")
from parcels
full join holdings using (ogc_fid)
where new.ogc_fid = coalesce(parcels.ogc_fid, holdings.ogc_fid);"""
                ).format(ids=lpis_ids_id)
                logging.debug(query.as_string(conn))
                cursor.execute(
                    query,
                    (parcel_id_offset + parcel_base, holding_id_offset + holding_base),
                )

                print("Creating identifier indexes")
                create_primary_key(conn, lpis_ids_table, ["ogc_fid"])
                create_index(conn, lpis_ids_table, ["ori_id"])
                cursor.execute(SQL("analyze {}").format(lpis_ids_id))

                conn.commit()
                if reuse_lpis and mode != MODE_INCREMENTAL:
                    print("Marking deleted parcels")
                    query = SQL(
                        """
update {} old
set is_deleted = true,
    updated_timestamp = now()
where old.is_deleted is not true
and not exists (
    select *
    from {} new
    where new.ori_id = old.ori_id
);"""
                    ).format(lpis_table_id, lpis_ids_id)
                    logging.debug(query.as_string(conn))
                    cursor.execute(query)
                    conn.commit()

                raw_cols = [col for col in column_types if col != "is_new"]
                id_cols = [
                    "ori_id",
                    "ori_hold",
                    "ori_crop",
                    "NewID",
                    "HoldID",
                    "is_new",
                ]
                cols = raw_cols + id_cols
                parcel_source = SQL(
                    """select {columns}, {id_columns}
from {staging} staging
join {ids} ids using (ogc_fid)"""
                ).format(
                    columns=SQL(", ").join(
                        SQL("staging.{}").format(Identifier(col)) for col in raw_cols
                    ),
                    id_columns=SQL(", ").join(
                        SQL("ids.{}").format(Identifier(col)) for col in id_cols
                    ),
                    staging=lpis_table_staging_id,
                    ids=lpis_ids_id,
                )
                if is_projected:
                    area_expr = SQL("coalesce(ST_Area(new_geom), 0)")
                    perimeter_expr = SQL("ST_Perimeter(new_geom)")
                else:
                    area_expr = SQL("coalesce(ST_Area(new_geom::geography), 0)")
                    perimeter_expr = SQL("ST_Perimeter(new_geom::geography)")
                if reuse_lpis:
                    drop_index(conn, self.lpis_table, ["ori_hold"])
                    drop_spatial_index(conn, self.lpis_table, "wkb_geometry")

                    print("Updating existing parcels")
                    attribute_cols = [
                        Identifier(col)
                        for col in cols
                        if col
                        not in ("ogc_fid", "is_new", "NewID", "ori_id", "wkb_geometry")
                    ]
                    old_cols = SQL(", ").join(attribute_cols)
                    p_old_cols = SQL(", ").join(
                        SQL("old.{}").format(col) for col in attribute_cols
                    )
                    new_cols = SQL(", ").join(
                        SQL("new.{}").format(col) for col in attribute_cols
                    )
                    query = SQL(
                        """
with parcels as not materialized (
    {source}
), geometries as materialized (
    select new.ogc_fid,
           coalesce(ST_IsValid(new.wkb_geometry), false) as geom_valid,
           ST_MakeValid(new.wkb_geometry) as new_geom,
           ST_MakeValid(old.wkb_geometry) as old_geom
    from parcels new
    join {lpis} old on old.ori_id = new.ori_id
    where new.wkb_geometry is distinct from old.wkb_geometry
), measurements as materialized (
    select ogc_fid, geom_valid,
           {area} as area,
           {perimeter} as perimeter,
           ST_Area(ST_SymDifference(old_geom, new_geom)) / ST_Area(ST_Union(old_geom, new_geom)) as change_ratio
    from geometries
)
update {lpis} old
set ({columns}) = ({new_columns}),
    wkb_geometry = case when m.ogc_fid is null then old.wkb_geometry else new.wkb_geometry end,
    "GeomValid" = case when m.ogc_fid is null then old."GeomValid" else m.geom_valid end,
    "Area_meters" = case when m.ogc_fid is null then old."Area_meters" else m.area end,
    "ShapeInd" = case when m.ogc_fid is null then old."ShapeInd" else m.perimeter / (2 * sqrt(pi() * nullif(m.area, 0))) end,
    "S1Pix" = case when m.ogc_fid is null then old."S1Pix" else 0 end,
    "S2Pix" = case when m.ogc_fid is null then old."S2Pix" else 0 end,
    is_deleted = false,
    updated_timestamp = now(),
    geom_change_ratio = case when m.ogc_fid is null then old.geom_change_ratio else m.change_ratio end
from parcels new
left join measurements m on m.ogc_fid = new.ogc_fid
where new.ori_id = old.ori_id
and (old.is_deleted or m.ogc_fid is not null or ({new_columns}) is distinct from ({old_columns}));"""
                    ).format(
                        lpis=lpis_table_id,
                        source=parcel_source,
                        columns=old_cols,
                        new_columns=new_cols,
                        old_columns=p_old_cols,
                        area=area_expr,
                        perimeter=perimeter_expr,
                    )
                    logging.debug(query.as_string(conn))
                    cursor.execute(query)
                    conn.commit()

                print("Inserting new parcels")
                insert_cols = [
                    Identifier(col) for col in cols if col not in ("ogc_fid", "is_new")
                ]
                query = SQL(
                    """
with parcels as not materialized (
    {source}
), geometries as materialized (
    select ogc_fid,
           coalesce(ST_IsValid(wkb_geometry), false) as geom_valid,
           ST_MakeValid(wkb_geometry) as new_geom
    from parcels
    where is_new
), measurements as materialized (
    select ogc_fid, geom_valid, {area} as area, {perimeter} as perimeter
    from geometries
)
insert into {lpis}({columns}, "GeomValid", "Duplic", "Overlap", "Area_meters", "ShapeInd")
select {new_columns},
    m.geom_valid,
    false as "Duplic",
    false as "Overlap",
    m.area as "Area_meters",
    m.perimeter / (2 * sqrt(pi() * nullif(m.area, 0))) as "ShapeInd"
from parcels new
join measurements m on m.ogc_fid = new.ogc_fid;"""
                ).format(
                    lpis=lpis_table_id,
                    source=parcel_source,
                    columns=SQL(", ").join(insert_cols),
                    new_columns=SQL(", ").join(
                        SQL("new.{}").format(col) for col in insert_cols
                    ),
                    area=area_expr,
                    perimeter=perimeter_expr,
                )
                logging.debug(query.as_string(conn))
                cursor.execute(query)

                conn.commit()

                print("Cleaning up")
                query = SQL("drop table {}, {};").format(
                    lpis_table_staging_id, lpis_ids_id
                )
                logging.debug(query.as_string(conn))
                cursor.execute(query)

                print("Creating indexes")
                create_spatial_index(conn, self.lpis_table, "wkb_geometry")
                create_primary_key(conn, self.lpis_table, ["NewID"])
                create_index(conn, self.lpis_table, ["ori_id"])
                cursor.execute(SQL("analyze {}").format(lpis_table_id))

    def prepare_lpis(self):
        with self.get_connection() as conn:
            print("Retrieving site SRID")
            srid = get_site_srid(conn, self.lpis_table)

        tile_counts = self.get_tile_parcel_counts(srid)
        total = 0
        for c in tile_counts.values():
            total += c
        overlaps = self.find_overlaps(srid, tile_counts, total)
        duplicates = self.find_duplicates(srid, tile_counts, total)
        self.update_parcel_flags(overlaps, duplicates)

    def export_lpis(self, full_vacuum=False):
        with self.get_connection() as conn:
            if not table_exists(conn, "public", self.lpis_table):
                logging.info("LPIS table does not exist, skipping export")
                return
            if not table_exists(conn, "public", self.lut_table):
                logging.info("LUT table does not exist, skipping export")
                return

        commands = []
        base = self.lpis_table

        with self.get_connection() as conn:
            for tile in self.tiles:
                zone_srs = osr.SpatialReference()
                zone_srs.ImportFromEPSG(tile.epsg_code)

                (
                    dst_xmin,
                    dst_xmax,
                    dst_ymin,
                    dst_ymax,
                ) = tile.tile_extent.GetEnvelope()

                for resolution in [10, 20]:
                    if resolution == 10:
                        satellite = "S2"
                    else:
                        satellite = "S1"

                    output = f"{base}_{tile.tile_id}_{satellite}.tif"
                    output = os.path.join(self.lpis_path, output)

                    sql = SQL(
                        """
with transformed as (
    select epsg_code, ST_Transform(shape_tiles_s2.geog::geometry, Find_SRID('public', {}, 'wkb_geometry')) as geom
    from shape_tiles_s2
    where tile_id = {}
)
select "NewID", ST_Buffer(ST_Transform(wkb_geometry, epsg_code), {})
from {}, transformed
where "GeomValid"
  and not is_deleted
  and ST_Intersects(wkb_geometry, transformed.geom);"""
                    )
                    sql = sql.format(
                        Literal(self.lpis_table),
                        Literal(tile.tile_id),
                        Literal(int(-resolution // 2)),
                        Identifier(self.lpis_table),
                    )
                    sql = sql.as_string(conn)

                    rasterize_dataset = RasterizeDatasetCommand(
                        self.get_ogr_connection_string(),
                        output,
                        tile.tile_id,
                        resolution,
                        sql,
                        "NewID",
                        f"EPSG:{tile.epsg_code}",
                        int(dst_xmin),
                        int(dst_ymin),
                        int(dst_xmax),
                        int(dst_ymax),
                    )

                    if resolution == 10:
                        cost = 5
                    else:
                        cost = 2
                    commands.append((rasterize_dataset, cost))

        q = queue.Queue()

        def work(w):
            (c, cost) = w
            try:
                c.run()
            except Exception as e:
                logging.error(e)
            q.put(cost)

        futures = [self.pool.submit(work, w) for w in commands]

        total = len(self.tiles) * 7
        progress = 0
        sys.stdout.write("Rasterizing LPIS: 0.00%")
        sys.stdout.flush()
        for i in range(len(commands)):
            progress += q.get()
            sys.stdout.write(f"\rRasterizing LPIS: {100.0 * progress / total:.2f}%")
            sys.stdout.flush()
        sys.stdout.write("\n")
        sys.stdout.flush()

        [f.result() for f in futures]

        inputs_s2 = []
        inputs_s1 = []
        for tile in self.tiles:
            output = f"{base}_{tile.tile_id}_S2.tif"
            inputs_s2.append(os.path.join(self.lpis_path, output))

            output_s1 = f"{base}_{tile.tile_id}_S1.tif"
            inputs_s1.append(os.path.join(self.lpis_path, output_s1))

        counts_10m = os.path.join(self.working_path, "counts_10m.csv")
        counts_20m = os.path.join(self.working_path, "counts_20m.csv")

        def compute_counts(inputs, output):
            subprocess.check_call(
                ["erdy", "compute-class-counts", "--output", output, "--inputs"]
                + inputs
            )

        sys.stdout.write("Counting pixels...\n")
        sys.stdout.flush()
        list(
            self.pool.map(
                compute_counts, [inputs_s2, inputs_s1], [counts_10m, counts_20m]
            )
        )

        counts = os.path.join(self.working_path, "counts.csv")
        subprocess.check_call(
            ["erdy", "merge-class-counts", "--output", counts, counts_10m, counts_20m]
        )

        try_rm_file(counts_10m)
        try_rm_file(counts_20m)

        sys.stdout.write("Reading pixel counts...\n")
        sys.stdout.flush()
        c = {}
        with open(counts, "r") as file:
            for row in csv.reader(file):
                seq_id = int(row[0])
                if seq_id == 0:
                    continue
                s2pix = int(row[1])
                s1pix = int(row[2])
                c[seq_id] = (s2pix, s1pix)

        if c:
            updates = [(id, s2pix, s1pix) for (id, (s2pix, s1pix)) in c.items()]
            del c

            sys.stdout.write("Updating pixel counts...\n")
            sys.stdout.flush()

            f = io.StringIO()
            for e in updates:
                f.write(f"{e[0]}\t{e[1]}\t{e[2]}\n")
            f.seek(0)

            sql = SQL(
                """
merge into {} as lpis
using updates
on lpis."NewID" = updates.id
when matched and (
    lpis."S2Pix" is distinct from updates.s2_pix or
    lpis."S1Pix" is distinct from updates.s1_pix
) then
    update set "S2Pix" = updates.s2_pix,
               "S1Pix" = updates.s1_pix
when not matched by source and (
    lpis."S2Pix" != 0 or
    lpis."S1Pix" != 0
) then
    update set
        "S2Pix" = 0,
        "S1Pix" = 0;"""
            ).format(Identifier(self.lpis_table))

            with self.get_connection() as conn:
                with conn.cursor() as cursor:
                    cursor.execute(
                        "create temp table updates(id int, s2_pix int, s1_pix int) on commit drop;"
                    )
                    cursor.copy_expert("copy updates from stdin with (freeze)", f)

                    logging.debug(sql.as_string(conn))
                    cursor.execute(sql)

                    conn.commit()

            try_rm_file(counts)

            with conn.cursor() as cursor:
                print("Cleaning up")
                conn.set_isolation_level(psycopg2.extensions.ISOLATION_LEVEL_AUTOCOMMIT)
                sql = SQL("vacuum ({}) {};").format(
                    SQL("full, analyze" if full_vacuum else "analyze"),
                    Identifier(self.lpis_table),
                )
                logging.debug(sql.as_string(conn))
                cursor.execute(sql)
                conn.set_isolation_level(psycopg2.extensions.ISOLATION_LEVEL_DEFAULT)

                tiles = [t.tile_id for t in self.tiles]
                name = f"SEN4CAP_LPIS_S{self.config.site_id}_{self.year}"
                dt = date(self.year, 1, 1)
                sql = SQL(
                    """
delete
from product
where site_id = %s
 and product_type_id = %s
 and created_timestamp = %s;"""
                )
                logging.debug(sql.as_string(conn))
                cursor.execute(sql, (self.config.site_id, PRODUCT_TYPE_LPIS, dt))

                sql = SQL(
                    "select sp_insert_product(%s::smallint, %s::smallint, null, %s::smallint, null, %s, %s, %s, null, null, null, %s);"
                )
                logging.debug(sql.as_string(conn))
                cursor.execute(
                    sql,
                    (
                        PRODUCT_TYPE_LPIS,
                        PROCESSOR_LPIS,
                        self.config.site_id,
                        self.lpis_path,
                        dt,
                        name,
                        json.dumps(tiles),
                    ),
                )
                conn.commit()

                epsg_codes = get_site_utm_epsg_codes(conn, self.config.site_id)
                epsg_codes.append(3035)

                commands = []

                lpis_csv = f"{self.lpis_table}.csv"
                lpis_csv = os.path.join(self.lpis_path, lpis_csv)

                try_rm_file(lpis_csv)

                lpis_gpkg = f"{self.lpis_table}.gpkg"
                lpis_gpkg_working = os.path.join(self.working_path, lpis_gpkg)
                lpis_gpkg = os.path.join(self.lpis_path, lpis_gpkg)

                try_rm_file(lpis_gpkg_working)

                sql = SQL(
                    """
select *
from {}
inner join {} using (ori_crop)
where "GeomValid"
  and not is_deleted;"""
                ).format(Identifier(self.lpis_table), Identifier(self.lut_table))
                sql = sql.as_string(conn)

                command = ExportParcelsCsvCommand(
                    sql, lpis_csv, self.get_ogr_connection_string()
                )
                commands.append((command, 5))

                srid = get_site_srid(conn, self.lpis_table)
                srs = f"EPSG:{srid}"
                command = ExportParcelsGpkgCommand(
                    srs, sql, lpis_gpkg_working, self.get_ogr_connection_string()
                )
                commands.append((command, 12))

                for epsg_code in epsg_codes:
                    wkt = get_esri_wkt(epsg_code)

                    for resolution in [10, 20]:
                        if resolution == 10 and epsg_code == 3035:
                            continue

                        buf = resolution // 2
                        output = f"{self.lpis_table}_{epsg_code}_buf_{buf}m.shp"
                        output = os.path.join(self.lpis_path, output)
                        prj = f"{self.lpis_table}_{epsg_code}_buf_{buf}m.prj"
                        prj = os.path.join(self.lpis_path, prj)

                        with open(prj, "wt") as f:
                            f.write(wkt)

                        sql = SQL(
                            'select "NewID", ST_Buffer(ST_Transform(wkb_geometry, {}), -{}) from {} where "GeomValid" and not is_deleted order by "NewID"'
                        )
                        sql = sql.format(
                            Literal(epsg_code),
                            Literal(buf),
                            Identifier(self.lpis_table),
                        )
                        sql = sql.as_string(conn)

                        try_rm_file(output)

                        command = ExportParcelsShpCommand(
                            sql, output, self.get_ogr_connection_string()
                        )
                        commands.append((command, 23))

        q = queue.Queue()

        def work(w):
            (c, cost) = w
            try:
                c.run()
            except Exception as e:
                logging.error(e)
            q.put(cost)

        futures = [self.pool.submit(work, w) for w in commands]

        total = sum([cost for (_, cost) in commands])
        progress = 0
        sys.stdout.write("Exporting data: 0.00%")
        sys.stdout.flush()
        for i in range(len(commands)):
            progress += q.get()
            sys.stdout.write(f"\rExporting data: {100.0 * progress / total:.2f}%")
            sys.stdout.flush()
        sys.stdout.write("\n")
        sys.stdout.flush()

        [f.result() for f in futures]

        if self.working_path != self.lpis_path:
            print("Moving exported table")
            shutil.copy2(gpkg_working, gpkg)

        with self.get_connection() as conn, conn.cursor() as cursor:
            query = SQL(
                """
with site_geometry as materialized (
    select ST_Transform(geog::geometry, Find_SRID('public', %s, 'wkb_geometry')) as geom
    from site
    where id = %s
)
select count(*) filter (where "S1Pix" = 0),
       count(*) filter (where "S2Pix" = 0),
       count(*) filter (where not ST_Intersects(wkb_geometry, site_geometry.geom))
from {}, site_geometry
where not is_deleted;"""
            ).format(Identifier(self.lpis_table))
            logging.debug(query.as_string(conn))
            cursor.execute(query, (self.lpis_table, self.config.site_id))
            s1_zero_pixels, s2_zero_pixels, outside_site = cursor.fetchone()
            if s1_zero_pixels:
                logging.warning(f"{s1_zero_pixels} parcels have 0 S1 pixels")
            if s2_zero_pixels:
                logging.warning(f"{s2_zero_pixels} parcels have 0 S2 pixels")
            if outside_site:
                logging.warning(f"{outside_site} parcels are outside the site")

    def get_tile_parcel_counts(self, srid):
        print("Counting parcels")
        with self.get_connection() as conn, conn.cursor() as cursor:
            query = SQL(
                """
with tiles as (
    select tile_id, ST_Transform(geog::geometry, %s) as geom
    from shape_tiles_s2
    where tile_id = any(%s)
)
select tile_id, (
    select count(*)
    from {} lpis
    where not lpis.is_deleted
     and "GeomValid"
     and ST_Intersects(lpis.wkb_geometry, tiles.geom)
) as count
from tiles;"""
            ).format(Identifier(self.lpis_table))
            logging.debug(query.as_string(conn))
            tiles = [t.tile_id for t in self.tiles]
            cursor.execute(query, (srid, tiles))

            counts = {}
            for r in cursor:
                counts[r[0]] = r[1]

            conn.commit()
            return counts

    def get_overlapping_parcels(self, srid, q, tile):
        try:
            with self.get_connection() as conn:
                with conn.cursor() as cursor:
                    query = SQL(
                        """
with tile as (
    select ST_Transform(geog::geometry, %s) as geom
    from shape_tiles_s2
    where tile_id = %s
)
select "NewID"
from {} lpis, tile
where "GeomValid"
and not is_deleted
and exists (
    select 1
    from {} t
    where t."NewID" != lpis."NewID"
    and t."GeomValid"
    and not t.is_deleted
    and ST_Intersects(t.wkb_geometry, tile.geom)
    and ST_Intersects(t.wkb_geometry, lpis.wkb_geometry)
    having sum(ST_Area(ST_Intersection(t.wkb_geometry, lpis.wkb_geometry))) / nullif(lpis."Area_meters", 0) > 0.1
)
and ST_Intersects(lpis.wkb_geometry, tile.geom);"""
                    )
                    query = query.format(
                        Identifier(self.lpis_table), Identifier(self.lpis_table)
                    )
                    logging.debug(
                        "%s, %s, %s", query.as_string(conn), srid, tile.tile_id
                    )
                    cursor.execute(query, (srid, tile.tile_id))

                    q.put(tile)
                    return [r[0] for r in cursor]
        except Exception as e:
            logging.error("%s, %s", e, tile.tile_id)
            sys.exit(1)

    def get_duplicate_parcels(self, srid, q, tile):
        try:
            with self.get_connection() as conn, conn.cursor() as cursor:
                query = SQL(
                    """
    with tile as (
        select ST_Transform(geog::geometry, %s) as geom
        from shape_tiles_s2
        where tile_id = %s
    )
    select "NewID"
    from (
        select "NewID",
                count(*) over(partition by wkb_geometry) as count
        from {}, tile
        where "GeomValid"
        and ST_Intersects(wkb_geometry, tile.geom)
        and not is_deleted
    ) t where count > 1;"""
                )
                query = query.format(Identifier(self.lpis_table))
                logging.debug(query.as_string(conn))
                cursor.execute(query, (srid, tile.tile_id))

                q.put(tile)
                return [r[0] for r in cursor]
        except Exception as e:
            logging.error(e)
            sys.exit(1)

    def update_parcel_flags(self, overlaps, duplicates):
        print("Updating parcel flags")
        with (
            tempfile.TemporaryFile(mode="w+") as flags,
            self.get_connection() as conn,
            conn.cursor() as cursor,
        ):
            for parcel in overlaps | duplicates:
                flags.write(f"{parcel}\t{parcel in overlaps}\t{parcel in duplicates}\n")
            flags.seek(0)

            cursor.execute(
                "create temp table parcel_flags "
                "(id int primary key, overlap boolean not null, duplic boolean not null) on commit drop"
            )
            cursor.copy_expert("copy parcel_flags from stdin", flags)
            cursor.execute("analyze parcel_flags")
            query = SQL(
                """
merge into {} as lpis
using parcel_flags as flags
on lpis."NewID" = flags.id
when matched and (lpis."Overlap", lpis."Duplic") <> (flags.overlap, flags.duplic) then
    update set "Overlap" = flags.overlap,
               "Duplic" = flags.duplic
when not matched by source and (
    lpis."Overlap" or lpis."Duplic"
) then
    update set "Overlap" = false,
               "Duplic" = false;"""
            ).format(Identifier(self.lpis_table))
            logging.debug(query.as_string(conn))
            cursor.execute(query)

    def compute_tile_bounds(self):
        print("Computing tile bounds")
        output_path = os.path.join(self.lpis_path, "tile_bounds.json")

        site_epsg = self.site_geom.GetSpatialReference().GetAuthorityCode(None)
        site_wkt = f"SRID={site_epsg};{self.site_geom.ExportToWkt()}"

        with tempfile.NamedTemporaryFile(mode="wt", suffix=".csv") as f:
            writer = csv.writer(f, quoting=csv.QUOTE_MINIMAL)
            for tile in self.tiles:
                writer.writerow(
                    [tile.tile_id, tile.epsg_code, tile.tile_extent.ExportToWkt()]
                )
            f.flush()

            subprocess.check_call(
                [
                    str(Path(__file__).parent / "compute-tile-bounds.py"),
                    "--site-geom",
                    site_wkt,
                    "--tiles",
                    f.name,
                    "--output",
                    output_path,
                ]
            )


def get_lpis_path(conn, site_id):
    with conn.cursor() as cursor:
        query = SQL(
            """
select value
from sp_get_parameters('processor.lpis.path')
where site_id is null or site_id = %s
order by site_id;"""
        )
        cursor.execute(query, (site_id,))

        path = cursor.fetchone()[0]
        conn.commit()

        return path


def main():
    gdal.UseExceptions()
    gdal.SetConfigOption("OGR_PG_STRING_TYPE", "TEXT")

    parser = argparse.ArgumentParser(description="Imports an LPIS or LUT")
    parser.add_argument(
        "-c",
        "--config-file",
        default="/etc/sen2agri/sen2agri.conf",
        help="configuration file location",
    )
    parser.add_argument("--year", help="year", type=int, default=date.today().year)
    parser.add_argument("--lpis", help="LPIS dataset")
    parser.add_argument("--lut", help="LUT dataset")
    parser.add_argument("--export", help="export dataset", action="store_true")
    parser.add_argument("--parcel-id-cols", nargs="+", help="parcel id columns")
    parser.add_argument("--holding-id-cols", nargs="+", help="holding id columns")
    parser.add_argument("--crop-code-col", help="crop code column")

    required_args = parser.add_argument_group("required named arguments")
    required_args.add_argument(
        "-s", "--site-id", type=int, required=True, help="site ID to filter by"
    )
    parser.add_argument(
        "-m",
        "--mode",
        help="run mode",
        default="update",
        choices=["update", "replace", "incremental"],
    )
    parser.add_argument("-d", "--debug", help="debug mode", action="store_true")
    parser.add_argument("--working-path", help="working path")
    parser.add_argument(
        "--parcel-id-offset", help="offset for parcel renumbering", type=int, default=0
    )
    parser.add_argument(
        "--holding-id-offset",
        help="offset for holding renumbering",
        type=int,
        default=0,
    )

    args = parser.parse_args()

    if args.debug:
        level = logging.DEBUG
    else:
        level = logging.INFO

    if args.mode == "replace":
        mode = MODE_REPLACE
    elif args.mode == "incremental":
        mode = MODE_INCREMENTAL
    else:
        mode = MODE_UPDATE

    logging.basicConfig(level=level, format="%(levelname)s: %(message)s")

    config = Config(args)
    data_preparation = DataPreparation(config, args.year, args.working_path)

    if args.lut is not None:
        data_preparation.prepare_lut(args.lut)

    if args.lpis is not None:
        data_preparation.prepare_lpis_staging(
            mode,
            args.parcel_id_cols,
            args.holding_id_cols,
            args.crop_code_col,
            args.lpis,
            args.parcel_id_offset,
            args.holding_id_offset,
        )
        data_preparation.prepare_lpis()
        data_preparation.compute_tile_bounds()

    if args.lpis or args.lut or args.export:
        data_preparation.export_lpis(
            full_vacuum=args.lpis is not None and mode == MODE_REPLACE
        )


if __name__ == "__main__":
    main()
