#!/usr/bin/env python3

from __future__ import annotations

import argparse
import itertools
import json
import os
import re
import sys
from concurrent.futures import ThreadPoolExecutor
from enum import Enum
from functools import partial
from pathlib import Path
from urllib.parse import urljoin

import psycopg2
import psycopg2.extras
import requests
from psycopg2.sql import SQL


class ProductType(Enum):
    L2A = 1
    L3B = 3
    L1C = 7
    S1_L2A_AMP = 10
    S1_L2A_COHE = 11
    S4C_L4A = 12
    S4C_L4B = 13
    LPIS = 14
    S4C_L4C = 15
    S4C_MDB1 = 17
    S4C_MDB2 = 18
    S4C_MDB3 = 19
    S4C_MDB_L4A_OPT_MAIN = 20
    S4C_MDB_L4A_OPT_RE = 21
    S4C_MDB_L4A_SAR_MAIN = 22
    S4C_MDB_L4A_SAR_TEMP = 23
    S4C_HETEROGENEITY = 24
    FMASK = 25
    L2A_MSK = 26
    S4C_BARE_SOIL = 33
    S4C_CHANGE_DETECTION = 35
    L3B_NDVI = 36
    L3B_LAI = 37
    L3B_FAPAR = 38
    L3B_FCOVER = 39
    L3B_NDWI = 40
    L3B_BRIGH = 41
    S4C_TILLAGE = 44
    DUMMY = 99


MEDIA_TYPES = {
    ".tif": "image/tiff",
    ".tiff": "image/tiff",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".gpkg": "application/geopackage+sqlite3",
    ".shp": "application/vnd.shp",
    ".csv": "text/csv",
    ".xml": "application/xml",
    ".mtd": "application/xml",
    ".ipc": "application/vnd.apache.arrow.file",
    ".txt": "text/plain",
}


REPLACE_PATHS: list[tuple[str, str]] = []


L2A_MSK_ASSET_DEFS = (
    ("_10M_BIN.tif", "mask_10m_bin", ["data"], "10m binary mask raster"),
    ("_10M.tif", "mask_10m", ["data"], "10m mask raster"),
    ("_20M_BIN.tif", "mask_20m_bin", ["data"], "20m binary mask raster"),
    ("_20M.tif", "mask_20m", ["data"], "20m mask raster"),
)

L4A_ASSET_DEFS = (
    ("CropType.gpkg", "classification", ["data"], "Classification output"),
    ("CropType_LUT.csv", "lut", ["metadata"], "Crop lookup table"),
    ("Crop_types_summary", "crop_summary", ["data"], "Crop type statistics"),
    (
        "Parcels_all_with_predictions",
        "predictions_all",
        ["data"],
        "All parcel predictions",
    ),
    (
        "Parcels_classified_with_predictions",
        "predictions_classified",
        ["data"],
        "Classified parcel predictions",
    ),
    (
        "Confusion_matrix",
        "confusion_matrix",
        ["data"],
        "Classification confusion matrix",
    ),
    ("Accuracy_metrics_plot", "accuracy_plot", ["overview"], "Accuracy metrics plot"),
    ("Accuracy_metrics", "accuracy_metrics", ["data"], "Accuracy metrics"),
    (
        "before_smote",
        "training_pre_smote",
        ["data"],
        "Training features before SMOTE",
    ),
    ("after_smote", "training", ["data"], "Training features after SMOTE"),
    ("validation", "validation", ["data"], "Validation dataset"),
)

L4C_ASSET_DEFS = (
    (("CatchCrop", ".csv"), "catch_crop", ["data"], "Catch crop practice results"),
    (("CatchCrop", ".xml"), "catch_crop_plot", ["metadata"], "Catch crop plot data"),
    (("Fallow", ".csv"), "fallow", ["data"], "Fallow land results"),
    (("Fallow", ".xml"), "fallow_plot", ["metadata"], "Fallow land plot data"),
    (("NFC", ".csv"), "nfc", ["data"], "Nitrogen-fixing crops results"),
    (("NFC", ".xml"), "nfc_plot", ["metadata"], "Nitrogen-fixing crops plot data"),
    (("_NA_", ".csv"), "na", ["data"], "Unspecified practice results"),
    (("_NA_", ".xml"), "na_plot", ["metadata"], "Unspecified practice plot data"),
)

BARE_SOIL_ASSET_DEFS = (
    (
        "BSmodelS1featuresimportance.png",
        "importance_s1",
        ["overview"],
        "S1 feature importance plot",
    ),
    (
        "BSmodelS2featuresimportance.png",
        "importance_s2",
        ["overview"],
        "S2 feature importance plot",
    ),
    ("CalibrationS1", "training_s1", ["data"], "S1 training features"),
    ("CalibrationS2", "training_s2", ["data"], "S2 training features"),
    ("MarkersAll", "markers_all", ["data"], "Combined bare soil markers"),
    ("MarkersS1", "markers_s1", ["data"], "S1 bare soil markers"),
    ("MarkersS2", "markers_s2", ["data"], "S2 bare soil markers"),
    ("S1results", "results_s1", ["data"], "S1 bare soil detection results"),
    ("S2results", "results_s2", ["data"], "S2 bare soil detection results"),
)


def is_auxiliary_file(path: Path) -> bool:
    return path.suffix.lower() in {
        ".shx",
        ".dbf",
        ".prj",
        ".cpg",
        ".idx",
    } or path.name.lower().endswith(".aux.xml")


def guess_media_type(path: Path) -> str:
    return MEDIA_TYPES.get(path.suffix.lower(), "application/octet-stream")


def make_asset(path: Path, roles: list[str], title: str) -> dict:
    p_str = str(path)
    url_path = p_str
    for src, dst in REPLACE_PATHS:
        url_path = url_path.replace(src, dst)
    return {
        "href": p_str,
        "type": guess_media_type(path),
        "roles": roles,
        "title": title,
        "alternate": {"s3": {"href": f"http://s3.waw4-1.cloudferro.com{url_path}"}},
    }


def read_l2a(root: Path) -> dict:
    entries = list(root.glob("*"))
    metadata = next((e for e in entries if e.name == "MTD_MSIL2A.xml"), None)
    if not metadata:
        granule = next((e for e in entries if e.name.startswith("SENTINEL2")), None)
        if granule:
            metadata = next(granule.glob("*_MTD_ALL.xml"), None)
    if metadata:
        return {
            "metadata": make_asset(
                metadata, roles=["metadata"], title="Product manifest"
            )
        }
    return {}


def read_from_defs(root: Path, defs: tuple) -> dict:
    assets = {}
    if m := next(root.glob("*MTD*.xml"), None):
        assets["metadata"] = make_asset(m, roles=["metadata"], title="Product manifest")

    for f in sorted(root.rglob("*")):
        if not f.is_file() or is_auxiliary_file(f):
            continue
        for pat, key, roles, title in defs:
            matched = (
                all(p in f.name for p in pat)
                if isinstance(pat, tuple)
                else pat in f.name
            )
            if matched:
                assets[key] = make_asset(f, roles=roles, title=title)
                break
    return assets


def read_s1_l2a(path: Path, title: str) -> dict:
    assets = {}
    m = path.with_suffix(".mtd")
    if m.is_file():
        assets["metadata"] = make_asset(m, roles=["metadata"], title="Product manifest")
    if path.is_file():
        assets["data"] = make_asset(path, roles=["data"], title=title)
    return assets


def read_s1_l2a_amp(root: Path) -> dict:
    return read_s1_l2a(root, "Amplitude raster")


def read_s1_l2a_cohe(root: Path) -> dict:
    return read_s1_l2a(root, "Coherence raster")


def read_l3b(root: Path) -> dict:
    parts = root.name.split("_")
    metadata = root.joinpath(f"{parts[0]}_{parts[1]}_MTD_{parts[5]}.xml")
    tile = next(root.glob("TILES/*"), None)
    if not tile:
        return {}
    assets = {}
    if metadata.is_file():
        assets["metadata"] = make_asset(
            metadata, roles=["metadata"], title="Product manifest"
        )
    for image in itertools.chain(
        tile.glob("IMG_DATA/*.TIF"), tile.glob("QI_DATA/*.TIF")
    ):
        kind = image.name.split("_")[2]
        assets[kind] = make_asset(image, roles=["data"], title=f"{kind} raster")
    parts = tile.name.split("_")
    preview = tile.joinpath(f"{parts[0]}_{parts[1]}_PVI_{parts[2]}_{parts[3]}.jpg")
    if preview.is_file():
        assets["thumbnail"] = make_asset(
            preview, roles=["thumbnail"], title="Thumbnail"
        )
    return assets


def read_s4c_l4b(root: Path) -> dict:
    assets = {}
    if m := next(root.glob("*MTD*.xml"), None):
        assets["metadata"] = make_asset(m, roles=["metadata"], title="Product manifest")
    if shp := next(root.rglob("*.shp"), None):
        assets["mowing"] = make_asset(
            shp, roles=["data"], title="Grassland mowing detection"
        )
    return assets


def read_s4c_tillage(root: Path) -> dict:
    assets = {}
    if m := next(root.glob("*MTD*.xml"), None):
        assets["metadata"] = make_asset(m, roles=["metadata"], title="Product manifest")
    if csv := next(root.rglob("tillage_detection.csv"), None):
        assets["tillage"] = make_asset(
            csv, roles=["data"], title="Tillage detection results"
        )
    return assets


def read_s4c_heterogeneity(root: Path) -> dict:
    assets = {}
    if m := next(root.glob("*MTD*.xml"), None):
        assets["metadata"] = make_asset(m, roles=["metadata"], title="Product manifest")

    for f in sorted(root.rglob("*")):
        if not f.is_file() or is_auxiliary_file(f):
            continue
        if "HeteDecision" in f.name:
            assets["decision_s2"] = make_asset(
                f, roles=["data"], title="S2 heterogeneity decision table"
            )
        elif m := re.search(r"L4D_Hete(S[12])_.*_(\d+)\.csv", f.name):
            sat, month = m.group(1).lower(), m.group(2)
            assets[f"hete_{sat}_m{month}"] = make_asset(
                f, roles=["data"], title=f"{sat.upper()} heterogeneity month {month}"
            )
        elif m := re.search(
            r"L4D_Cl(S[12])_\d+_([A-Z0-9]{5})_(\d+)_Connect\.tif", f.name
        ):
            sat, tile, month = m.group(1).lower(), m.group(2).lower(), m.group(3)
            assets[f"clusters_connect_{sat}_{tile}_m{month}"] = make_asset(
                f,
                roles=["data"],
                title=f"{sat.upper()} connected clusters tile {tile.upper()} month {month}",
            )
        elif m := re.search(r"L4D_Cl(S[12])_\d+_([A-Z0-9]{5})_(\d+)\.tif", f.name):
            sat, tile, month = m.group(1).lower(), m.group(2).lower(), m.group(3)
            assets[f"clusters_{sat}_{tile}_m{month}"] = make_asset(
                f,
                roles=["data"],
                title=f"{sat.upper()} clusters tile {tile.upper()} month {month}",
            )
        elif m := re.search(r"L4D_Cl(S[12])_\d+_([A-Z0-9]{5})_(\d+)\.csv", f.name):
            sat, tile, month = m.group(1).lower(), m.group(2).lower(), m.group(3)
            assets[f"clusters_metrics_{sat}_{tile}_m{month}"] = make_asset(
                f,
                roles=["data"],
                title=f"{sat.upper()} cluster metrics tile {tile.upper()} month {month}",
            )
    return assets


def read_s4c_mdb(root: Path) -> dict:
    assets = {}
    if m := next(root.glob("*MTD*.xml"), None):
        assets["metadata"] = make_asset(m, roles=["metadata"], title="Product manifest")
    if ipc := next(root.glob("*.ipc"), None):
        assets["data"] = make_asset(ipc, roles=["data"], title="Marker database table")
    return assets


READERS = {
    ProductType.L2A: read_l2a,
    ProductType.L2A_MSK: partial(read_from_defs, defs=L2A_MSK_ASSET_DEFS),
    ProductType.S1_L2A_AMP: read_s1_l2a_amp,
    ProductType.S1_L2A_COHE: read_s1_l2a_cohe,
    ProductType.S4C_L4A: partial(read_from_defs, defs=L4A_ASSET_DEFS),
    ProductType.S4C_L4B: read_s4c_l4b,
    ProductType.S4C_L4C: partial(read_from_defs, defs=L4C_ASSET_DEFS),
    ProductType.S4C_TILLAGE: read_s4c_tillage,
    ProductType.S4C_BARE_SOIL: partial(read_from_defs, defs=BARE_SOIL_ASSET_DEFS),
    ProductType.S4C_HETEROGENEITY: read_s4c_heterogeneity,
    **{
        pt: read_s4c_mdb
        for pt in (
            ProductType.S4C_MDB1,
            ProductType.S4C_MDB2,
            ProductType.S4C_MDB3,
            ProductType.S4C_MDB_L4A_OPT_MAIN,
            ProductType.S4C_MDB_L4A_OPT_RE,
            ProductType.S4C_MDB_L4A_SAR_MAIN,
            ProductType.S4C_MDB_L4A_SAR_TEMP,
        )
    },
    **{
        pt: read_l3b
        for pt in (
            ProductType.L3B,
            ProductType.L3B_NDVI,
            ProductType.L3B_LAI,
            ProductType.L3B_FAPAR,
            ProductType.L3B_FCOVER,
            ProductType.L3B_NDWI,
            ProductType.L3B_BRIGH,
        )
    },
}


def build_item(row):
    product_type = ProductType(row["product_type_id"])

    item = {
        "stac_version": "1.0.0",
        "stac_extensions": [],
        "type": "Feature",
        "id": row["name"],
        "collection": product_type.name,
        "geometry": row["geom"],
        "bbox": row["geom"]["bbox"] if row["geom"] else None,
        "properties": {
            "datetime": row["created_timestamp"].isoformat(),
        },
        "assets": {},
        "links": [],
    }

    assets = {}
    full_path = Path(row["full_path"])
    if reader := READERS.get(product_type):
        assets = reader(full_path)

    if (
        "thumbnail" not in assets
        and (ql := row.get("quicklook_image"))
        and (thumb := full_path / ql).is_file()
    ):
        assets["thumbnail"] = make_asset(thumb, roles=["thumbnail"], title="Thumbnail")

    item["assets"] = assets

    return item


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dsn", required=True, help="PostgreSQL DSN")
    ap.add_argument("--stac-url", help="STAC server URL")
    ap.add_argument("--product-id", type=int, help="Product filter")
    ap.add_argument("--product-type-id", type=int, help="Product type filter")
    ap.add_argument(
        "--delete",
        action="store_true",
        help="Delete products from STAC before ingestion",
    )
    ap.add_argument(
        "--replace-path",
        action="append",
        default=[],
        help="Path replacement for URLs (SOURCE:TARGET)",
    )
    args = ap.parse_args()

    global REPLACE_PATHS
    REPLACE_PATHS = [tuple(p.split(":", 1)) for p in args.replace_path]

    conn = psycopg2.connect(args.dsn)
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    query = SQL("""
        select
            id,
            product_type_id,
            site_id,
            full_path,
            created_timestamp,
            inserted_timestamp,
            name,
            quicklook_image,
            ST_AsGeoJSON(geog, options => 1) :: json AS geom
        from product
    """)

    filters = []
    params = []

    if args.product_type_id:
        filters.append(SQL("product_type_id = %s"))
        params.append(args.product_type_id)
    if args.product_id:
        filters.append(SQL("id = %s"))
        params.append(args.product_id)
    if filters:
        query += SQL(" where ") + SQL(" and ").join(filters)
    query += SQL(" order by id")

    cur.execute(
        query,
        params,
    )
    session = requests.Session()

    def process_item(r):
        item = build_item(r)

        if args.stac_url:
            collection = item["collection"]
            url = urljoin(args.stac_url, f"collections/{collection}/items")
            if args.delete:
                session.delete(f"{url}/{item['id']}")
            response = session.post(url, json=item)
            if not response:
                print(f"{item['id']}: {response.text}", file=sys.stderr)
                return False
            else:
                print(f"{url}/{item['id']}")
                return True
        else:
            with open(f"{item['id']}.json", "w") as file:
                json.dump(item, file)
            return True

    with ThreadPoolExecutor(max_workers=os.cpu_count()) as executor:
        results = list(executor.map(process_item, cur))

    if not all(results):
        sys.exit(1)


if __name__ == "__main__":
    main()
