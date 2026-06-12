# Copyright (C) 2019 CS ROMANIA — GPL v3 or later
"""
sentinel1_l2_pipeline.py
========================
Full Python translation of the Sentinel-1 Level-2 pipeline.

Source files translated
-----------------------
  PersistenceManager.java + all Repository classes
  Sentinel1Level2Worker.java
  Sentinel1Level2Job.java
  Sentinel1L2ProcessorV1.java

Dependencies
------------
  pip install sqlalchemy psycopg2-binary shapely pyproj

Quick-start
-----------
  export POSTGRES_DSN="postgresql+psycopg2://user:pass@host/sen4cap"
  python sentinel1_l2_pipeline.py
"""

from __future__ import annotations

import argparse
import logging
import os
import platform
import queue
import re
import shutil
import socket
import subprocess
import threading
import traceback
import uuid
import json
import zipfile
from concurrent.futures import ThreadPoolExecutor
from copy import copy
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Callable, Dict, List, Optional, Set, Tuple

import sys 

from enum import Enum, auto, IntEnum

try:
    from shapely import wkt as shapely_wkt
    from shapely.geometry.base import BaseGeometry
    HAS_SHAPELY = True
except ImportError:
    HAS_SHAPELY = False

try:
    from sqlalchemy import create_engine, text
    from sqlalchemy.orm import sessionmaker
    HAS_SQLALCHEMY = True
except ImportError:
    HAS_SQLALCHEMY = False


try:
    from configparser import ConfigParser
except ImportError:
    from ConfigParser import ConfigParser


class MainScriptConfig(object):
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

# ===========================================================================
# Enumerations
# ===========================================================================

class MasterChoice(Enum):
    S1A = "S1A"; S1B = "S1B"; S1C = "S1C"; OLDEST = "OLDEST"; NEWEST = "NEWEST"

class Polarisation(Enum):
    VV = "VV"; VH = "VH"

class Status(IntEnum):
    PROCESSING        = 7
    PROCESSED         = 5
    PROCESSING_FAILED = 6
    FAILED            = 3
    ABORTED           = 4
    DOWNLOADED        = 2
    IGNORED           = 41
    
class JobStartType(IntEnum):
    TRIGGERED = 1
    SCHEDULED = 2
    
class ActivityStatus(IntEnum):
    PENDING_START = 2
    RUNNING       = 4
    FINISHED      = 6
    ERROR         = 8
    CANCELLED     = 7

class TileProcessingStatus(IntEnum):   
    PROCESSING = 1
    DONE       = 2
    FAILED     = 3
    
class Satellite(IntEnum):
    Sentinel1 = 3; Sentinel2 = 1

class ProductType(IntEnum):
    L2A_AMP  = 10
    L2A_COHE = 11

    def suffix(self) -> str:
        return self.name.replace("L2A_", "")


# ===========================================================================
# Configuration keys
# ===========================================================================

class ConfigurationKeys:
    S1_PROCESSOR_ENABLED              = "s1.processor.enabled"
    S1_PROCESSOR_VERSION              = "s1.processor.version"
    S1_PROCESSOR_OUTPUT_PATH          = "s1.processor.output_path"
    S1_PROCESSOR_PARALLELISM          = "s1.processor.parallelism"
    S1_PROCESSOR_INTERVAL             = "s1.processor.interval"
    S1_PROCESSOR_REVERSE_ACQUISITION_DATE = "s1.processor.reverse_acquisition_date"
    S1_PROCESSOR_WAIT_FOR_ORBIT_FILES = "s1.processor.wait_for_orbit_files"
    S1_PROCESSOR_DAYS_BACK            = "s1.processor.days_back"
    S1_PROCESSOR_MTF_INTERVAL         = "s1.processor.mtf_interval"
    S1_PROCESSOR_COHERENCE_ENABLED    = "s1.processor.coherence_enabled"
    S1_PROCESSOR_AMPLITUDE_ENABLED    = "s1.processor.amplitude_enabled"
    S1_PROCESSOR_POLARISATIONS        = "s1.processor.polarisations"
    S1_PROCESSOR_MASTER               = "s1.processor.master"
    S1_PROCESSOR_RESOLVE_LINKS        = "s1.processor.resolve_links"
    S1_PROCESSOR_WORK_DIR             = "s1.processor.work_dir"
    S1_PROCESSOR_MIN_S2_INTERSECTION  = "s1.processor.min_s2_intersection"
    S1_PROCESSOR_OVERWRITE            = "s1.processor.overwrite"
    S1_PROCESSOR_PROJECTION           = "s1.processor.projection"
    S1_PROCESSOR_MIN_MEMORY           = "s1.processor.min_memory"
    S1_PROCESSOR_MIN_DISK             = "s1.processor.min_disk"
    S1_PROCESSOR_KEEP_INTERMEDIATE    = "s1.processor.keep_intermediate"
    S1_PROCESSOR_OUTPUT_FORMAT        = "s1.processor.output_format"
    S1_PROCESSOR_OUTPUT_EXTENSION     = "s1.processor.output_extension"
    S1_PROCESSOR_CROP_ENABLED         = "s1.processor.crop_enabled"
    S1_PROCESSOR_CONVERT_INT16        = "s1.processor.convert_int16"
    S1_PROCESSOR_COMPRESS_ENABLED     = "s1.processor.compress_enabled"
    S1_PROCESSOR_RESOLUTION_METERS    = "s1.processor.resolution_meters"
    S1_PROCESSOR_RESOLUTION_DEGREES   = "s1.processor.resolution_degrees"
    S1_PROCESSOR_DEM_NAME             = "s1.processor.dem_name"
    S1_PROCESSOR_DEM_NODATA           = "s1.processor.dem_nodata"
    S1_PROCESSOR_DEM_LOCAL_PATH       = "s1.processor.dem_local_path"
    S1_PROCESSOR_PARALLEL_STEPS       = "s1.processor.parallel_steps"
    S1_PROCESSOR_MONITOR_DISK         = "s1.processor.monitor_disk_interval"
    SNAP_USE_DOCKER                   = "snap.use_docker"
    GDAL_USE_DOCKER                   = "gdal.use_docker"
    DOCKER_SNAP_IMAGE                 = "docker.snap_image"
    DOCKER_GDAL_IMAGE                 = "docker.gdal_image"
    SNAP_HOME_PATH                    = "snap.home_path"
    IGNORE_PREVIOUS_ORBIT_FAILURE     = "s1.processor.ignore_previous_orbit_failure"
    S1_DOWNLOAD_OFFSET                = "s1.download.offset"


# ===========================================================================
# Config store
# ===========================================================================

class Config:
    """
    Thin wrapper over a key/value store (mirrors the Java Config utility).
    Values are seeded via Config.setup() and can be overridden per-site.
    """
    _global:   Dict[str, str] = {}
    _per_site: Dict[int, Dict[str, str]] = {}
    _features: Dict[Tuple[int, str], bool] = {}

    @classmethod
    def setup(cls, global_settings: Dict[str, str],
              per_site: Optional[Dict[int, Dict[str, str]]] = None):
        cls._global.update(global_settings)
        if per_site:
            for sid, vals in per_site.items():
                cls._per_site.setdefault(sid, {}).update(vals)

    @classmethod
    def get_setting(cls, key: str, default: str = "") -> str:
        return cls._global.get(key, default)

    @classmethod
    def get_setting_for_site(cls, site_id: int, key: str, default: str = "") -> str:
        return cls._per_site.get(site_id, {}).get(key, cls._global.get(key, default))

    @classmethod
    def set_setting(cls, site_id: int, key: str, value: str):
        cls._per_site.setdefault(site_id, {})[key] = value

    @classmethod
    def get_as_integer(cls, key: str, default: int = 0) -> int:
        try:
            return int(cls._global.get(key, default))
        except (ValueError, TypeError):
            return default

    @classmethod
    def get_as_integer_for_site(cls, site_id: int, key: str, default: int = 0) -> int:
        try:
            return int(cls.get_setting_for_site(site_id, key, str(default)))
        except (ValueError, TypeError):
            return default

    @classmethod
    def get_as_boolean(cls, site_id: int, key: str, default: bool = False) -> bool:
        val = cls.get_setting_for_site(site_id, key, str(default))
        return val.lower() in ("true", "1", "yes")

    @classmethod
    def is_feature_enabled(cls, site_id: int, key: str) -> bool:
        val = cls.get_setting_for_site(site_id, key, "false")
        return val.lower() in ("true", "1", "yes")


# ===========================================================================
# Domain dataclasses
# ===========================================================================

class Site:
    __slots__ = ("id", "name", "short_name", "enabled", "geog")
    def __init__(self, id=0, name="", short_name="", enabled=True, geog=None):
        self.id=id; self.name=name; self.short_name=short_name
        self.enabled=enabled; self.geog=geog
    def get_id(self): return self.id
    def get_name(self): return self.name
    def get_short_name(self): return self.short_name
    def is_enabled(self): return self.enabled


class Season:
    __slots__ = ("id", "site_id", "start_date", "end_date", "enabled")
    def __init__(self, id=0, site_id=0, start_date=None, end_date=None, enabled=True):
        self.id=id; self.site_id=site_id; self.start_date=start_date
        self.end_date=end_date; self.enabled=enabled
    def get_start_date(self): return self.start_date
    def get_end_date(self): return self.end_date


class DownloadProduct:
    def __init__(self):
        self.id=0; self.product_name=""; self.full_path=""
        self.original_path=None; self.status_id=Status.PROCESSING
        self.status_reason=None; self.no_of_retries=0; self.footprint=None
        self.orbit_id=0; self.orbit_type=""; self.product_date=None
        self.site_id=0; self.satellite_id=Satellite.Sentinel1; self.tiles=None

    def get_product_name(self): return self.product_name
    def get_full_path(self):    return self.full_path
    def get_status_id(self):    return self.status_id
    def get_no_of_retries(self):   return self.no_of_retries
    def get_status_reason(self):return self.status_reason
    def get_footprint(self):    return self.footprint
    def get_orbit_id(self):     return self.orbit_id
    def get_orbit_type(self):   return self.orbit_type
    def get_product_date(self): return self.product_date
    def get_site_id(self):      return self.site_id
    def get_id(self):           return self.id
    def get_satellite_id(self): return self.satellite_id
    def set_full_path(self,v):  self.full_path=v
    def set_original_path(self,v): self.original_path=v
    def set_status_id(self,v):  self.status_id=v
    def set_status_reason(self,v): self.status_reason=v
    def set_no_of_retries(self,v): self.no_of_retries=v
    def set_id(self,v):         self.id=v
    def duplicate(self):        return copy(self)


class HighLevelProduct:
    def __init__(self):
        self.id=0; self.product_name=""; self.full_path=None
        self.inserted=None; self.created=None; self.product_type=None
        self.processor_id=0; self.orbit_type=""; self.satellite=Satellite.Sentinel1
        self.site_id=0; self.relative_orbit=0; self.download_product_id=0
        self.footprint=None; self.quick_look_path=None; self.product_details=None
        self.archived=False; self.tiles=None

    def get_product_name(self): return self.product_name
    def get_product_details(self): return self.product_details
    def get_full_path(self):    return self.full_path
    def get_id(self):           return self.id
    def set_inserted(self,v):   self.inserted=v
    def set_full_path(self,v):  self.full_path=v
    def set_archived(self,v):   self.archived=v
    def set_created(self,v):    self.created=v
    def set_processor_id(self,v): self.processor_id=v
    def set_satellite(self,v):  self.satellite=v
    def set_site_id(self,v):    self.site_id=v
    def set_relative_orbit(self,v): self.relative_orbit=v
    def set_orbit_type(self,v): self.orbit_type=v
    def set_download_product_id(self,v): self.download_product_id=v
    def set_product_type(self,v): self.product_type=v
    def set_footprint(self,v):  self.footprint=v
    def set_quick_look_path(self,v): self.quick_look_path=v
    def set_product_details(self,v): self.product_details=v
    def set_tiles(self,v):      self.tiles=v


class ProductDetails:
    def __init__(self):
        self.id=0; self.min_value=0.0; self.max_value=0.0
        self.mean_value=0.0; self.std_dev_value=0.0; self.histogram=None


class DownloadProductTile:
    def __init__(self):
        self.id                   = 0
        self.download_product_id  = 0
        self.orbit_id             = 0
        self.tile_id              = ""
        self.satellite_id         = Satellite.Sentinel1   # ← was string "Sentinel1"
        self.retry_count          = 0
        self.cloud_coverage       = -1
        self.snow_coverage        = -1
        self.node                 = ""
        self.status               = TileProcessingStatus.PROCESSING
        self.status_timestamp     = None
        self.failed_reason        = None
        
    def get_status(self):         return self.status
    def get_retry_count(self):    return self.retry_count
    def set_status(self,v):       self.status=v
    def set_failed_reason(self,v):  self.failed_reason=v
    def set_status_timestamp(self,v): self.status_timestamp=v
    def set_retry_count(self,v):  self.retry_count=v
    def duplicate(self):          return copy(self)


class S2Tile:
    def __init__(self, id="", extent=None):
        self.id=id; self.extent=extent
    def get_id(self): return self.id


class Job:
    def __init__(self, id=0, site_id=0, processor_id=0,
                 parameters=None, status=ActivityStatus.RUNNING,
                 start_type_id=JobStartType.TRIGGERED):
        self.id               = id
        self.site_id          = site_id
        self.processor_id     = processor_id
        self.parameters       = parameters
        self.status           = status
        self.start_type_id    = start_type_id
        self.submit_timestamp = None
        self.start_timestamp  = None
        self.end_timestamp    = None
        self.status_timestamp = None
        self.tasks: List[Task] = []

    def get_id(self):         return self.id
    def get_parameters(self): return self.parameters
    def add_task(self, task): self.tasks.append(task)

class Task:
    def __init__(self, id=0, job_id=0, name="", parameters=None,
                 status=ActivityStatus.PENDING_START, module_short_name="",
                 parent_id=None, preceding_task_ids=None):
        self.id                 = id
        self.job_id             = job_id
        self.name               = name
        self.module_short_name  = module_short_name
        self.parameters         = parameters
        self.status             = status
        self.parent_id          = parent_id
        self.preceding_task_ids: List[int] = preceding_task_ids or []
        self.submit_timestamp   = None
        self.start_timestamp    = None
        self.end_timestamp      = None
        self.status_timestamp   = None
        self.steps: List[Step] = []

    def get_id(self):                return self.id
    def get_module_short_name(self): return self.module_short_name

class Step:
    def __init__(self, name="", task_id=0, parameters=None,
                 status=ActivityStatus.PENDING_START):
        self.name=name; self.task_id=task_id; self.parameters=parameters
        self.status=status; self.exit_code=0
        self.start_timestamp=datetime.now()
        self.end_timestamp=None; self.status_timestamp=None
    def get_name(self): return self.name
    def get_task_id(self): return self.task_id


# ===========================================================================
# ProcessFlag
# ===========================================================================

class ProcessFlag:
    AMPLITUDE = 1; COHERENCE = 2; OVERWRITE = 4

    @staticmethod
    def is_set(flags: int, flag: int) -> bool:   return bool(flags & flag)
    @staticmethod
    def is_reset(flags: int, flag: int) -> bool: return not bool(flags & flag)
    @staticmethod
    def reset_bit(flags: int, flag: int) -> int: return flags & ~flag


# ===========================================================================
# ProcessorRuntimeConfiguration
# ===========================================================================

class ProcessorRuntimeConfiguration:
    def __init__(self, site_id: int):
        self._s = site_id

    def days_back(self) -> int:
        return Config.get_as_integer_for_site(self._s, ConfigurationKeys.S1_PROCESSOR_DAYS_BACK, 6)
    def overwrite_existing_products(self) -> bool:
        return Config.get_as_boolean(self._s, ConfigurationKeys.S1_PROCESSOR_OVERWRITE, False)
    def should_replace_links(self) -> bool:
        return Config.get_as_boolean(self._s, "s1.processor.replace_links", False)
    def copy_products_locally(self) -> bool:
        return Config.get_as_boolean(self._s, "s1.processor.copy_locally", False)
    def intersection_threshold(self) -> float:
        return float(Config.get_setting_for_site(self._s, "s1.processor.intersection_threshold", "0.0"))
    def processor_id(self) -> int:
        return Config.get_as_integer_for_site(self._s, "s1.processor.processor_id", 1)
    def processor(self) -> str:
        return Config.get_setting_for_site(self._s, "s1.processor.short_name", "s1_l2a")
    def step_timeout(self) -> int:           # minutes
        return Config.get_as_integer_for_site(self._s, "s1.processor.step_timeout_minutes", 60)
    def amplitude_enabled(self) -> bool:
        return Config.get_as_boolean(self._s, ConfigurationKeys.S1_PROCESSOR_AMPLITUDE_ENABLED, True)
    def coherence_enabled(self) -> bool:
        return Config.get_as_boolean(self._s, ConfigurationKeys.S1_PROCESSOR_COHERENCE_ENABLED, True)
    def output_format(self) -> str:
        return Config.get_setting_for_site(self._s, ConfigurationKeys.S1_PROCESSOR_OUTPUT_FORMAT, "GeoTIFF")
    def output_extension(self) -> str:
        return Config.get_setting_for_site(self._s, ConfigurationKeys.S1_PROCESSOR_OUTPUT_EXTENSION, ".tif")
    def keep_intermediate(self) -> bool:
        return Config.get_as_boolean(self._s, ConfigurationKeys.S1_PROCESSOR_KEEP_INTERMEDIATE, False)
    def resolution_in_meters(self) -> str:
        return Config.get_setting_for_site(self._s, ConfigurationKeys.S1_PROCESSOR_RESOLUTION_METERS, "10")
    def resolution_in_degrees(self) -> str:
        return Config.get_setting_for_site(self._s, ConfigurationKeys.S1_PROCESSOR_RESOLUTION_DEGREES, "0.0001")
    def dem_name(self) -> str:
        return Config.get_setting_for_site(self._s, ConfigurationKeys.S1_PROCESSOR_DEM_NAME, "SRTM 1Sec HGT")
    def dem_no_data_value(self) -> float:
        return float(Config.get_setting_for_site(self._s, ConfigurationKeys.S1_PROCESSOR_DEM_NODATA, "-32768"))
    def projection_wkt(self) -> str:
        return Config.get_setting_for_site(self._s, ConfigurationKeys.S1_PROCESSOR_PROJECTION, "WGS84(DD)")
    def has_parallel_steps(self) -> bool:
        return Config.get_as_boolean(self._s, ConfigurationKeys.S1_PROCESSOR_PARALLEL_STEPS, False)
    def monitor_disk_activity_interval(self) -> int:
        return Config.get_as_integer_for_site(self._s, ConfigurationKeys.S1_PROCESSOR_MONITOR_DISK, 0)
    def should_crop_no_data(self) -> bool:
        return Config.get_as_boolean(self._s, "s1.processor.crop_nodata", False)

    @staticmethod
    def get(site_id: int) -> "ProcessorRuntimeConfiguration":
        return ProcessorRuntimeConfiguration(site_id)


# ===========================================================================
# File utilities
# ===========================================================================

HOST       = socket.gethostname()
IS_WINDOWS = platform.system() == "Windows"
_PRODUCT_DATE_FMT = "%Y%m%dT%H%M%S"
_EXCLUDED_EXTENSIONS = {
    ".mtd", ".nc", ".NC", ".tif", ".TIF",
    ".tiff", ".TIFF", ".log", ".png", ".PNG",
}


def _is_path_accessible(p: Path) -> bool:
    return p.exists() and os.access(p, os.R_OK)

def _is_path_writeable(p: Path) -> bool:
    return p.exists() and os.access(p, os.W_OK)

def _get_extension(fp: str) -> str:
    return Path(fp).suffix.lower()

def _copy_tree(src: Path, dst: Path) -> int:
    count = 0
    dst.mkdir(parents=True, exist_ok=True)
    for item in src.rglob("*"):
        if item.is_file():
            t = dst / item.relative_to(src)
            t.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(item, t)
            count += 1
    return count

def _delete_tree(p: Path):
    if p.exists():
        shutil.rmtree(p)

def _decompress_zip(zp: Path, dest: Path):
    with zipfile.ZipFile(zp, "r") as zf:
        zf.extractall(dest)

def _resolve_symlinks(p: Path) -> Path:
    return p.resolve()

def _ensure_exists(p: Path):
    p.mkdir(parents=True, exist_ok=True)

def _link(target: Path, link: Path):
    if link.exists() or link.is_symlink():
        link.unlink()
    link.symlink_to(target)

def _as_unix_path(p: Path) -> str:
    if IS_WINDOWS:
        return "/" + str(p.absolute()).replace(":", "").replace("\\", "/") + "/"
    return str(p)


# ===========================================================================
# Sentinel-1 product name helper
# ===========================================================================

S1_PATTERN = re.compile(
    r"(S1[A-D])_(SM|IW|EW|WV)_(SLC|GRD|RAW|OCN)([FHM_])_([0-2])([AS])"
    r"(SH|SV|DH|DV)_(\d{8}T\d{6})_(\d{8}T\d{6})_(\d{6})_([0-9A-F]{6})_([0-9A-F]{4})(?:\.SAFE)?"
)


class Sentinel1ProductHelper:
    def __init__(self, product_name: str):
        self._name  = product_name
        self._match = S1_PATTERN.match(product_name)

    def get_orbit(self) -> str:
        """Zero-padded 3-digit relative orbit (mirrors Java helper)."""
        if not self._match:
            return "000"
        abs_orbit = int(self._match.group(10))
        sat = self._match.group(1)
        rel = ((abs_orbit - 73) % 175 + 1) if sat.endswith("A") \
              else ((abs_orbit - 27) % 175 + 1)
        return f"{rel:03d}"

    def get_sensing_date(self) -> str:
        return self._match.group(8) if self._match else ""

    def get_name(self) -> str:
        return self._name

    def get_metadata_file_name(self) -> str:
        return "manifest.safe"

    @staticmethod
    def create(name: str) -> "Sentinel1ProductHelper":
        return Sentinel1ProductHelper(name)


# ===========================================================================
# JobHelper
# ===========================================================================

class JobHelper:
    """
    Thin façade over PersistenceManager for Job/Task/Step CRUD.
    Mirrors the Java JobHelper service class.
    """
    _pm: Optional["PersistenceManager"] = None

    @classmethod
    def set_persistence_manager(cls, pm: "PersistenceManager"):
        cls._pm = pm

    @classmethod
    def create_job(cls, site: Site, processor_short_name: str,
                   parameters: str) -> Job:
        now = datetime.now()
        job = Job(
            site_id          = site.get_id(),
            parameters       = parameters,
            status           = ActivityStatus.RUNNING,
            start_type_id    = JobStartType.TRIGGERED,
        )
        job.submit_timestamp = now
        job.start_timestamp  = now
        job.status_timestamp = now
        if cls._pm:
            job = cls._pm.save_job(job)
        return job

    @classmethod
    def create_task(cls, job: Job, name: str,
                    parameters: Optional[str],
                    parent_id: Optional[int] = None,
                    preceding_task_ids: Optional[List[int]] = None) -> Task:
        now = datetime.now()
        task = Task(
            job_id              = job.get_id(),
            name                = name,
            module_short_name   = name,          # mirrors Java: setModuleShortName(name)
            parameters          = parameters,
            status              = ActivityStatus.PENDING_START,
            parent_id           = parent_id,
            preceding_task_ids  = preceding_task_ids or [],
        )
        task.submit_timestamp = now
        task.start_timestamp  = now
        task.status_timestamp = now
        if cls._pm:
            task = cls._pm.save_task(task)
        job.add_task(task)                       # mirrors Java: job.addTask(task)
        return task

    @classmethod
    def get_task_or_create(cls, job: Job, name: str) -> Optional[Task]:
        if cls._pm:
            t = cls._pm.get_task(job.get_id(), name)
            return t or cls.create_task(job, name, job.get_parameters())
        return None

    @classmethod
    def create_step(cls, task: Task, name: str,
                    arguments: Optional[List[str]] = None) -> Step:
        step = Step(name=name, task_id=task.get_id(),
                    parameters=" ".join(arguments) if arguments else None,
                    status=ActivityStatus.PENDING_START)
        if cls._pm:
            step = cls._pm.save_step(step)
        return step

    @classmethod
    def update(cls, entity, activity_status: ActivityStatus,
               exit_code: Optional[int] = None):
        if entity is None:
            return
        entity.status = activity_status
        if exit_code is not None and hasattr(entity, "exit_code"):
            entity.exit_code = exit_code
        entity.status_timestamp = datetime.now()
        if cls._pm:
            if isinstance(entity, Job):
                cls._pm.save_job(entity)
            elif isinstance(entity, Task):
                cls._pm.save_task(entity)
            elif isinstance(entity, Step):
                entity.end_timestamp = datetime.now()
                cls._pm.save_step(entity)


# ===========================================================================
# PersistenceManager  (PostgreSQL / SQLAlchemy)
# ===========================================================================

class PersistenceManager:
    """
    Translated from PersistenceManager.java + all companion Repository classes.

    Uses SQLAlchemy Core with raw SQL that mirrors the native queries from the
    Spring Data repositories (SiteRepository, SeasonRepository,
    DownloadProductRepository, ProductRepository, StepRepository, etc.).

    Parameters
    ----------
    dsn : str
        SQLAlchemy connection string, e.g.
        "postgresql+psycopg2://user:pass@localhost/sen4cap"
    """

    def __init__(self, dsn: str):
        if not HAS_SQLALCHEMY:
            raise RuntimeError(
                "sqlalchemy + psycopg2 required: "
                "pip install sqlalchemy psycopg2-binary")
        self._engine = create_engine(dsn, pool_pre_ping=True, future=True)
        self._logger = logging.getLogger(self.__class__.__name__)

    # --- internal helpers ---

    def _fetch_all(self, sql: str, params: dict = None) -> List[dict]:
        with self._engine.connect() as conn:
            res = conn.execute(text(sql), params or {})
            keys = list(res.keys())
            return [dict(zip(keys, row)) for row in res.fetchall()]

    def _fetch_one(self, sql: str, params: dict = None) -> Optional[dict]:
        rows = self._fetch_all(sql, params)
        return rows[0] if rows else None

    def _execute(self, sql: str, params: dict = None):
        with self._engine.connect() as conn:
            conn.execute(text(sql), params or {})
            conn.commit()

    # ------------------------------------------------------------------
    # Site  (SiteRepository)
    # ------------------------------------------------------------------

    def get_site_by_id(self, site_id: int) -> Optional[Site]:
        row = self._fetch_one(
            "SELECT id, name, short_name, "
            "st_astext(geog) AS geog, enabled "
            "FROM public.site WHERE id = :id",
            {"id": site_id})
        return self._to_site(row) if row else None

    def get_enabled_sites(self) -> List[Site]:
        rows = self._fetch_all(
            "SELECT id, name, short_name, "
            "st_astext(ST_MakeValid(ST_SnapToGrid(cast(geog as geometry),0.001))) "
            "AS geog, enabled "
            "FROM public.site WHERE enabled = true ORDER BY id")
        return [self._to_site(r) for r in rows]

    def save_site(self, site: Site) -> Site:
        self._execute(
            "UPDATE public.site SET name=:n, short_name=:sn, enabled=:en "
            "WHERE id=:id",
            {"n": site.name, "sn": site.short_name,
             "en": site.enabled, "id": site.id})
        return site

    @staticmethod
    def _to_site(r: dict) -> Site:
        return Site(id=r["id"], name=r["name"], short_name=r["short_name"],
                    enabled=r["enabled"], geog=r.get("geog"))

    # ------------------------------------------------------------------
    # Season  (SeasonRepository)
    # ------------------------------------------------------------------

    def get_enabled_seasons(self, site_id: int) -> List[Season]:
        rows = self._fetch_all(
            "SELECT id, site_id, start_date, end_date, enabled "
            "FROM public.season "
            "WHERE site_id = :sid AND enabled = true ORDER BY id",
            {"sid": site_id})
        return [Season(id=r["id"], site_id=r["site_id"],
                       start_date=r["start_date"], end_date=r["end_date"],
                       enabled=r["enabled"]) for r in rows]

    # ------------------------------------------------------------------
    # DownloadProduct  (DownloadProductRepository)
    # ------------------------------------------------------------------

    def save(self, product: DownloadProduct) -> DownloadProduct:
        """Update status fields for an existing downloader_history row."""
        st = product.status_id.value \
             if isinstance(product.status_id, Status) else product.status_id
        self._execute(
            "UPDATE downloader_history "
            "SET full_path=:fp, status_id=:st, "
            "    status_reason=:sr, no_of_retries=:nr "
            "WHERE id=:id",
            {"fp": product.full_path, "st": st,
             "sr": product.status_reason, "nr": product.no_of_retries,
             "id": product.id})
        return product

    def get_downloaded_products(
            self, site_id: int, satellite: Satellite,
            cutoff_date: date, start_date: date,
            end_date: date, latest_first: bool) -> List[DownloadProduct]:
        order = "DESC" if latest_first else "ASC"
        
        rows = self._fetch_all(
            f"""SELECT id, product_name, full_path, status_id, status_reason,
                       no_of_retries, orbit_id, product_date, site_id, satellite_id
                FROM downloader_history
                WHERE site_id = :sid
                  AND satellite_id = :sat
                  AND status_id IN
                      ('2','7','6','5')
                  AND product_date >= :sd AND product_date <= :ed
                  AND product_date <= :cut
                ORDER BY product_date {order}""",
            {"sid": site_id, "sat": satellite.value,
             "sd": start_date, "ed": end_date, "cut": cutoff_date})
        return [self._to_dld(r) for r in rows]

    def get_stalled_products(self, site_id: int,
                              days_back: int) -> List[DownloadProduct]:
        """
        Translated from DownloadProductRepository.findPreviouslyNotIntersected.
        Products marked 'processed' that have no L2 outputs yet.
        """
        rows = self._fetch_all(
            """SELECT dh.id, dh.product_name, dh.full_path, dh.status_id,
                      dh.status_reason, dh.no_of_retries, dh.orbit_id,
                      dh.product_date, dh.site_id, dh.satellite_id
               FROM downloader_history dh
               WHERE dh.site_id = :sid
                 AND dh.status_id = '5'
                 AND NOT EXISTS (
                     SELECT 1 FROM product p
                     WHERE p.downloader_history_id = dh.id)
                 AND dh.product_date >= NOW()
                     - CAST(:days || ' days' AS INTERVAL)""",
            {"sid": site_id, "days": days_back})
        return [self._to_dld(r) for r in rows]

    def get_products(self, site_id: int, satellite_value: int,
                     status: Status,
                     reason_contains: str) -> List[DownloadProduct]:
        rows = self._fetch_all(
            """SELECT id, product_name, full_path, status_id, status_reason,
                      no_of_retries, orbit_id, product_date, site_id, satellite_id
               FROM downloader_history
               WHERE site_id=:sid AND satellite_id=:sat
                 AND status_id=:st
                 AND status_reason ILIKE :reason""",
            {"sid": site_id, "sat": satellite_value,
             "st": status.value,
             "reason": f"%{reason_contains}%"})
        return [self._to_dld(r) for r in rows]

    def get_intersecting_products(
            self, site_id: int, product_name: str,
            days_back: int, threshold: float) -> List[DownloadProduct]:
        """
        Translated from DownloadProductRepository.findIntersectingProducts.
        Finds S1 products that spatially overlap the reference product
        within a time window.
        """
        rows = self._fetch_all(
            """SELECT dh.id, dh.product_name, dh.full_path, dh.status_id,
                      dh.status_reason, dh.no_of_retries, dh.orbit_id,
                      dh.product_date, dh.site_id, dh.satellite_id
               FROM downloader_history dh
               JOIN downloader_history ref
                    ON ref.product_name = :pname AND ref.site_id = :sid
               WHERE dh.site_id = :sid
                 AND dh.id <> ref.id
                 AND dh.satellite_id = ref.satellite_id
                 AND dh.status_id IN
                     ('2','5','7','6')
                 AND dh.product_date BETWEEN
                     ref.product_date - CAST(:days || ' days' AS INTERVAL) AND
                     ref.product_date + CAST(:days || ' days' AS INTERVAL)
                 AND ST_Area(ST_Intersection(
                         dh.footprint::geometry,
                         ref.footprint::geometry))
                     / NULLIF(ST_Area(ref.footprint::geometry), 0)
                     >= :thresh""",
            {"pname": product_name, "sid": site_id,
             "days": days_back, "thresh": threshold})
        return [self._to_dld(r) for r in rows]

    def get_produced_products(self,
                               download_product_id: int) -> List[HighLevelProduct]:
        rows = self._fetch_all(
            "SELECT id, name, full_path "
            "FROM product WHERE downloader_history_id = :id",
            {"id": download_product_id})
        out = []
        for r in rows:
            p = HighLevelProduct()
            p.id = r["id"]; p.product_name = r["name"]
            p.full_path = r["full_path"]
            out.append(p)
        return out

    @staticmethod
    def _to_dld(r: dict) -> DownloadProduct:
        p = DownloadProduct()
        p.id           = r["id"]
        p.product_name = r["product_name"]
        p.full_path    = r.get("full_path", "")
        p.status_reason= r.get("status_reason")
        p.no_of_retries   = r.get("no_of_retries", 0)
        p.orbit_id     = r.get("orbit_id", 0)
        p.product_date = r.get("product_date")
        p.site_id      = r["site_id"]
        try:
            p.status_id = Status(r["status_id"])
        except ValueError:
            p.status_id = Status.PROCESSING
        try:
            p.satellite_id = Satellite(r["satellite_id"])
        except ValueError:
            p.satellite_id = Satellite.Sentinel1
        return p

    # ------------------------------------------------------------------
    # DownloadProductTile  (DownloadProductTileRepository)
    # ------------------------------------------------------------------

    def get_download_product_tile(self, product_id: int,
                                   tile_id: str) -> Optional[DownloadProductTile]:
        row = self._fetch_one(
            "SELECT * FROM l1_tile_history "
            "WHERE downloader_history_id=:pid AND tile_id=:tid",
            {"pid": product_id, "tid": tile_id})
        return self._to_tile(row) if row else None

    def get_download_product_tiles_by_product(
            self, product_id: int) -> List[DownloadProductTile]:
        rows = self._fetch_all(
            "SELECT * FROM l1_tile_history WHERE downloader_history_id=:pid",
            {"pid": product_id})
        return [self._to_tile(r) for r in rows]

    def save_download_product_tile(
            self, tile: DownloadProductTile) -> DownloadProductTile:
        st  = tile.status.value \
              if isinstance(tile.status, TileProcessingStatus) else int(tile.status)
        sat = tile.satellite_id.value \
              if isinstance(tile.satellite_id, Satellite) else int(tile.satellite_id)

        existing = self.get_download_product_tile(
            tile.download_product_id, tile.tile_id)
        if existing:
            self._execute(
                "UPDATE l1_tile_history "
                "SET status_id=:st, status_timestamp=:ts, "
                "    failed_reason=:fr, retry_count=:rc "
                "WHERE downloader_history_id=:pid AND tile_id=:tid",
                {"st": st, "ts": tile.status_timestamp,
                 "fr": tile.failed_reason, "rc": tile.retry_count,
                 "pid": tile.download_product_id, "tid": tile.tile_id})
        else:
            self._execute(
                "INSERT INTO l1_tile_history "
                "(downloader_history_id, orbit_id, tile_id, satellite_id, "
                " retry_count, cloud_coverage, snow_coverage, node_id, "
                " status_id, status_timestamp) "
                "VALUES (:pid,:oid,:tid,:sat,:rc,:cc,:sc,:node_id,:st,:ts)",
                {"pid":     tile.download_product_id,
                 "oid":     tile.orbit_id,
                 "tid":     tile.tile_id,
                 "sat":     sat,            
                 "rc":      tile.retry_count,
                 "cc":      tile.cloud_coverage,
                 "sc":      tile.snow_coverage,
                 "node_id": tile.node,
                 "st":      st,             
                 "ts":      tile.status_timestamp})
        return tile
        
    @staticmethod
    def _to_tile(r: dict) -> DownloadProductTile:
        t = DownloadProductTile()
        t.id                  = r.get("id", 0)
        t.download_product_id = r.get("downloader_history_id", 0)
        t.orbit_id            = r.get("orbit_id", 0)
        t.tile_id             = r.get("tile_id", "")
        t.retry_count         = r.get("retry_count", 0)
        t.cloud_coverage      = r.get("cloud_coverage", -1)
        t.snow_coverage       = r.get("snow_coverage", -1)
        t.node_id             = r.get("node_id", "")
        t.status_timestamp    = r.get("status_timestamp")
        t.failed_reason       = r.get("failed_reason")
        try:
            t.satellite_id = Satellite(r.get("satellite_id", 3))
        except ValueError:
            t.satellite_id = Satellite.Sentinel1
        try:
            t.status = TileProcessingStatus(r.get("status_id", 1))
        except ValueError:
            t.status = TileProcessingStatus.PROCESSING
        
        return t

    # ------------------------------------------------------------------
    # HighLevelProduct  (ProductRepository)
    # ------------------------------------------------------------------

    def save_product(self, product: HighLevelProduct) -> HighLevelProduct:
        if product.id:
            self._execute(
                "UPDATE product "
                "SET full_path=:fp, inserted=:ins, created=:cr, "
                "    quick_look_path=:ql "
                "WHERE id=:id",
                {"fp": product.full_path, "ins": product.inserted,
                 "cr": product.created, "ql": product.quick_look_path,
                 "id": product.id})
        else:
            row = self._fetch_one(
                "INSERT INTO product "
                "(name, full_path, created_timestamp, inserted_timestamp, processor_id, "
                " product_type_id, satellite_id, site_id, orbit_type_id, "
                " orbit_id, downloader_history_id) "
                "VALUES (:pn,:fp,:cr,:ins,:proc,:pt,:sat,:sid,:ot,:ro,:dhi) "
                "RETURNING id",
                {"pn": product.product_name, "fp": product.full_path,
                 "cr": product.created, "ins": product.inserted,
                 "proc": product.processor_id,
                 "pt": product.product_type,
                 "sat": product.satellite.value
                       if product.satellite else 1,
                 "sid": product.site_id,
                 "ot": product.orbit_type,
                 "ro": product.relative_orbit,
                 "dhi": product.download_product_id})
            if row:
                product.id = row["id"]
        return product

    # ------------------------------------------------------------------
    # ProductDetails  (NonMappedEntitiesRepository → product_stats)
    # ------------------------------------------------------------------

    def save_product_details(self,
                              details: ProductDetails) -> ProductDetails:
        if details.id and self._fetch_one(
                "SELECT id FROM product_stats WHERE id=:id",
                {"id": details.id}):
            self._execute(
                "UPDATE product_stats "
                "SET min_val=:mn, max_val=:mx, mean_val=:me, std_dev=:sd "
                "WHERE id=:id",
                {"mn": details.min_value, "mx": details.max_value,
                 "me": details.mean_value, "sd": details.std_dev_value,
                 "id": details.id})
        else:
            self._execute(
                "INSERT INTO product_stats (id,min_val,max_val,mean_val,std_dev) "
                "VALUES (:id,:mn,:mx,:me,:sd)",
                {"id": details.id, "mn": details.min_value,
                 "mx": details.max_value, "me": details.mean_value,
                 "sd": details.std_dev_value})
        return details

    # ------------------------------------------------------------------
    # S2 Tiles  (NonMappedEntitiesRepository)
    # Mirrors PersistenceManager.getIntersectingS2Tiles()
    # ------------------------------------------------------------------

    def get_intersecting_s2_tiles(
            self, extent_or_site_id,
            min_intersection: float) -> List[S2Tile]:
        if isinstance(extent_or_site_id, str):
            if min_intersection > 0.99:
                rows = self._fetch_all(
                    "SELECT id, st_astext(geom) AS extent FROM public.shape "
                    "WHERE ST_Intersects(geom, ST_GeomFromText(:wkt,4326))",
                    {"wkt": extent_or_site_id})
            else:
                rows = self._fetch_all(
                    "SELECT id, st_astext(geom) AS extent FROM public.shape "
                    "WHERE ST_Area(ST_Intersection("
                    "    geom, ST_GeomFromText(:wkt,4326)))"
                    "  / NULLIF(ST_Area(geom),0) >= :th",
                    {"wkt": extent_or_site_id, "th": min_intersection})
        else:
            rows = self._fetch_all(
                "SELECT s.id, st_astext(s.geom) AS extent "
                "FROM public.shape s "
                "JOIN public.site_tiles st ON s.id = st.tile_id "
                "WHERE st.site_id = :sid",
                {"sid": extent_or_site_id})
        return [S2Tile(id=r["id"], extent=r.get("extent")) for r in rows]

    def get_site_tiles(self, site: Site,
                       satellite: Satellite) -> Optional[Set[str]]:
        row = self._fetch_one(
            "SELECT tiles FROM public.site_tiles "
            "WHERE site_id=:sid AND satellite_id=:sat",
            {"sid": site.id, "sat": satellite.value})
        if row and row.get("tiles"):
            val = row["tiles"]
            return set(val) if isinstance(val, (list, set)) \
                   else set(val.split(","))
        return None

    # ------------------------------------------------------------------
    # Job / Task / Step  (JobRepository, NonMappedEntitiesRepository, StepRepository)
    # ------------------------------------------------------------------

    def save_job(self, job: Job) -> Job:
        st      = job.status.value if isinstance(job.status, ActivityStatus) else job.status
        stype   = job.start_type_id.value \
                  if isinstance(job.start_type_id, JobStartType) else job.start_type_id
        if job.id:
            self._execute(
                "UPDATE public.job "
                "SET status_id=:st, end_timestamp=:et, status_timestamp=:stt "
                "WHERE id=:id",
                {"st": st, "et": job.end_timestamp,
                 "stt": job.status_timestamp, "id": job.id})
        else:
            row = self._fetch_one(
                "INSERT INTO public.job "
                "(site_id, processor_id, parameters, status_id, start_type_id, "
                " submit_timestamp, start_timestamp, status_timestamp) "
                "VALUES (:sid,:proc,:params,:st,:stype,:sub,:sta,:stt) "
                "RETURNING id",
                {"sid":   job.site_id,
                 "proc":  job.processor_id,
                 "params":job.parameters,
                 "st":    st,
                 "stype": stype,
                 "sub":   job.submit_timestamp,
                 "sta":   job.start_timestamp,
                 "stt":   job.status_timestamp})
            if row:
                job.id = row["id"]
        return job

    def save_task(self, task: Task) -> Task:
        st = task.status.value if isinstance(task.status, ActivityStatus) else task.status
        if task.id:
            self._execute(
                "UPDATE public.task "
                "SET status_id=:st, end_timestamp=:et, status_timestamp=:stt "
                "WHERE id=:id",
                {"st": st, "et": task.end_timestamp,
                 "stt": task.status_timestamp, "id": task.id})
        else:
            row = self._fetch_one(
                "INSERT INTO public.task "
                "(job_id, module_short_name, parameters, status_id, "
                " submit_timestamp, start_timestamp, status_timestamp) "
                "VALUES (:jid,:msn,:params,:st,:sub,:sta,:stt) "
                "RETURNING id",
                {"jid":  task.job_id,
                 "msn":  task.module_short_name,
                 "params": task.parameters,
                 "st":   st,
                 "sub":  task.submit_timestamp,
                 "sta":  task.start_timestamp,
                 "stt":  task.status_timestamp})
            if row:
                task.id = row["id"]
        return task

    def get_task(self, job_id: int, name: str) -> Optional["Task"]:
        sql = """ SELECT id, job_id, module_short_name, parameters, submit_timestamp, start_timestamp,
                end_timestamp, status_id, status_timestamp, preceding_task_ids
            FROM public.task WHERE job_id = :job_id AND module_short_name = :name
        """

        row = self._fetch_one(sql, {
            "job_id": job_id,
            "name": name
        })

        if not row:
            return None

        task = Task()
        task.id = row["id"]
        task.job_id = row["job_id"]
        task.module_short_name = row["module_short_name"]
        task.parameters = row["parameters"]
        task.submit_timestamp = row["submit_timestamp"]
        task.start_timestamp = row["start_timestamp"]
        task.end_timestamp = row["end_timestamp"]
        task.status = ActivityStatus(row["status_id"])
        task.status_timestamp = row["status_timestamp"]
        preceding = row["preceding_task_ids"]
        task.preceding_tasks = list(preceding) if preceding is not None else None

        return task

    def save_step(self, step: Step) -> Step:
        st = step.status.value \
             if isinstance(step.status, ActivityStatus) else step.status
        existing = self._fetch_one(
            "SELECT name FROM public.step "
            "WHERE task_id=:tid AND name=:nm",
            {"tid": step.task_id, "nm": step.name})
        if existing:
            self._execute(
                "UPDATE public.step "
                "SET status_id=:st, exit_code=:ec, "
                "    start_timestamp=:sts, end_timestamp=:ets "
                "WHERE name=:nm AND task_id=:tid",
                {"st": st, "ec": step.exit_code,
                 "sts": step.start_timestamp, "ets": step.end_timestamp,
                 "nm": step.name, "tid": step.task_id})
        else:
            self._execute(
                "INSERT INTO public.step "
                "(name, task_id, parameters, status_id, exit_code, "
                " start_timestamp, end_timestamp) "
                "VALUES (:nm,:tid,:params,:st,:ec,:sts,:ets)",
                {"nm": step.name, "tid": step.task_id,
                 "params": step.parameters, "st": st,
                 "ec": step.exit_code,
                 "sts": step.start_timestamp,
                 "ets": step.end_timestamp})
        return step

    def save_log(self, step_name: str, task_id: int, node_name: str,
                 duration_ms: int, log: str, error: str) -> int:
        """Translated from StepRepository.saveLog()."""
        log   = (log   or "").replace("\x00", "")
        error = (error or "").replace("\x00", "")
        try:
            self._execute(
                "INSERT INTO public.step_resource_log "
                "(step_name, task_id, node_name, entry_timestamp, "
                " duration_ms, stdout_text, stderr_text) "
                "VALUES (:sn,:tid,:node,:ts,:dur,:out,:err)",
                {"sn": step_name, "tid": task_id, "node": node_name,
                 "ts": datetime.now(), "dur": duration_ms,
                 "out": log, "err": error})
            return 1
        except Exception as ex:
            self._logger.error("save_log failed: %s", ex)
            return 0


# ===========================================================================
# ProductLog (inner utility – mirrors Java inner static class)
# ===========================================================================

class ProductLog:
    _handlers: Dict[str, logging.FileHandler] = {}
    _parent:   Optional[logging.Logger] = None

    @classmethod
    def initialize(cls, parent: logging.Logger):
        cls._parent = parent

    @classmethod
    def setup_handler(cls, name: str, folder: Path):
        h = logging.FileHandler(str(folder / "output.log"))
        h.setLevel(logging.DEBUG)
        cls._handlers[name] = h

    @classmethod
    def _log(cls, name: str, level: int, msg: str):
        if cls._parent:
            cls._parent.log(level, msg)
        h = cls._handlers.get(name)
        if h:
            h.emit(logging.LogRecord(name, level, "", 0, msg, (), None))

    @classmethod
    def debug(cls, n, m): cls._log(n, logging.DEBUG, m)
    @classmethod
    def info(cls, n, m):  cls._log(n, logging.INFO,  m)
    @classmethod
    def warn(cls, n, m):  cls._log(n, logging.WARNING, m)
    @classmethod
    def error(cls, n, m): cls._log(n, logging.ERROR, m)

    @classmethod
    def cleanup(cls, name: str):
        h = cls._handlers.pop(name, None)
        if h:
            h.close()


# ===========================================================================
# Sentinel1Level2Worker
# ===========================================================================

class Sentinel1Level2Worker:
    def __init__(self, cfg: ProcessorRuntimeConfiguration, target_path: Path):
        self._cfg         = cfg
        self._target_path = target_path
        self._logger      = logging.getLogger(self.__class__.__name__)
        ProductLog.initialize(self._logger)

        tmp_str = Config.get_setting(ConfigurationKeys.S1_PROCESSOR_WORK_DIR)
        self._tmp_path = Path(tmp_str) if tmp_str else target_path

        self._errors: List[str] = []
        self._completion_callback: Optional[Callable] = None

    def set_completion_callback(self, cb: Callable):
        self._completion_callback = cb

    # ------------------------------------------------------------------
    def create_products(
        self,
        job: Job,
        download_product_id: int,
        site: Site,
        polarisation: Polarisation,
        orbit_type: str,
        master_product: Path,
        slave_product: Optional[Path],
        use_master_band: bool,
        flag: int,
        timeout_minutes: int,
    ) -> Optional[str]:
        """
        Returns None on success, semicolon-joined error string on failure.
        """
        self._errors.clear()

        work_dir  = Config.get_setting(ConfigurationKeys.S1_PROCESSOR_WORK_DIR,"/mnt/archive/s1_preprocessing_work_dir")

        helper       = Sentinel1ProductHelper.create(master_product.name)
        rel_orbit    = helper.get_orbit()
        master_date  = helper.get_sensing_date()
        master_dt    = datetime.strptime(master_date, _PRODUCT_DATE_FMT) \
                       if master_date else datetime.now()

        slave_date   = ""
        if slave_product:
            slave_date = Sentinel1ProductHelper.create(
                slave_product.name).get_sensing_date()
        
        site_id     = site.get_id()
        name        = self._build_product_name(
            site_id, master_date, slave_date, polarisation, rel_orbit)
        product_folder = self._tmp_path / name
        product_folder_name  = product_folder.name
        status               = False
        ext                  = self._cfg.output_extension()
        process_flag         = flag
        products: List[HighLevelProduct] = []
        try:
            # ---------- decide which outputs to generate ----------
            for pt, fbit, enabled in [
                (ProductType.L2A_COHE, ProcessFlag.COHERENCE,
                 self._cfg.coherence_enabled()),
                (ProductType.L2A_AMP,  ProcessFlag.AMPLITUDE,
                 self._cfg.amplitude_enabled()),
            ]:
                if not enabled or ProcessFlag.is_reset(process_flag, fbit):
                    continue
                p = HighLevelProduct()
                p.product_name        = name + "_" + pt.suffix()
                p.download_product_id = download_product_id
                p.product_type        = pt.value
                p.processor_id        = self._cfg.processor_id()
                p.orbit_type          = orbit_type
                p.satellite           = Satellite.Sentinel1
                p.full_path           = str(
                    self._target_path / name / (p.product_name + ext))
                if Path(p.full_path).exists() and \
                        ProcessFlag.is_reset(process_flag, ProcessFlag.OVERWRITE):
                    self._logger.warning(
                        "Product '%s' exists; will not re-process.", p.product_name)
                    process_flag = ProcessFlag.reset_bit(process_flag, fbit)
                else:
                    products.append(p)
        
                print("Processing product name = {}, type = {}, full_path = {}".format(p.product_name, p.product_type, p.full_path))
    
                self._logger.debug(
                    "Flags — AMP=%d COH=%d OVR=%d",
                    ProcessFlag.is_set(process_flag, ProcessFlag.AMPLITUDE),
                    ProcessFlag.is_set(process_flag, ProcessFlag.COHERENCE),
                    ProcessFlag.is_set(process_flag, ProcessFlag.OVERWRITE))

                product_folder.mkdir(parents=True, exist_ok=True)
                ProductLog.setup_handler(product_folder_name, product_folder)
                ProductLog.debug(
                    product_folder_name,
                    f"Master: {master_product.name}  "
                    f"Slave: {slave_product.name if slave_product else 'n/a'}")

                steps = self._build_execution_steps(
                    job, polarisation, master_product, slave_product,
                    pt.value, use_master_band, name, work_dir, p.full_path)

                for step_name, commands in steps.items():
                    task = JobHelper.get_task_or_create(job, step_name)
                    if task:
                        JobHelper.update(task, ActivityStatus.RUNNING)

                    # Skip steps disabled by process flag
                    if (step_name == "Amplitude" and
                            ProcessFlag.is_reset(process_flag, ProcessFlag.AMPLITUDE)):
                        ProductLog.debug(product_folder_name,
                                         f"Step {step_name} skipped (amplitude reset)")
                        if task:
                            JobHelper.update(task, ActivityStatus.CANCELLED)
                        continue
                    if (step_name == "Coherence" and
                            ProcessFlag.is_reset(process_flag, ProcessFlag.COHERENCE)):
                        ProductLog.debug(product_folder_name,
                                         f"Step {step_name} skipped (coherence reset)")
                        if task:
                            JobHelper.update(task, ActivityStatus.CANCELLED)
                        continue

                    cmd_info = commands[0]   # one command per step with the new jar
                    db_step  = JobHelper.create_step(
                        task, cmd_info["step_name"]) if task else None
                    if db_step:
                        JobHelper.update(db_step, ActivityStatus.RUNNING)

                    args = cmd_info["args"]
                    ProductLog.info(product_folder_name,
                                    f"Invoking processor: {' '.join(args)}")
                    self._logger.info("Executing %s: %s", step_name, " ".join(args))
                    
                    try:
                        result = subprocess.run(
                            args, capture_output=True, text=True,
                            timeout=timeout_minutes * 60)
                        stdout = result.stdout or ""
                        stderr = result.stderr or ""
                        out    = stdout + stderr

                        if result.returncode != 0:
                            msg = (f"Step {step_name} failed "
                                   f"[exit={result.returncode}]: {out[:500]}")
                            ProductLog.error(product_folder_name, msg)
                            self._errors.append(msg)
                            status = False
                            if db_step:
                                JobHelper.update(db_step, ActivityStatus.ERROR,
                                                 result.returncode)
                            if task:
                                JobHelper.update(task, ActivityStatus.ERROR)
                            if task and JobHelper._pm:
                                JobHelper._pm.save_log(
                                    step_name, task.get_id(), HOST, 0, stdout, stderr)
                            break   # no point running Coherence if Amplitude failed

                        # Success
                        ProductLog.info(product_folder_name,
                                        f"Step {step_name} completed successfully")
                        self._logger.info("Step %s finished OK", step_name)
                        status = True
                        if db_step:
                            JobHelper.update(db_step, ActivityStatus.FINISHED, 0)
                        if task:
                            JobHelper.update(task, ActivityStatus.FINISHED)
                        if task and JobHelper._pm:
                            JobHelper._pm.save_log(
                                step_name, task.get_id(), HOST, 0, stdout, "")

                    except subprocess.TimeoutExpired:
                        msg = (f"Step {step_name} timed out after {timeout_minutes} min")
                        ProductLog.error(product_folder_name, msg)
                        self._errors.append(msg)
                        status = False
                        if db_step:
                            JobHelper.update(db_step, ActivityStatus.ERROR, -1)
                        if task:
                            JobHelper.update(task, ActivityStatus.ERROR)
                        break

            if not products:
                self._logger.warning(
                    "Product pair (pol %s) already processed in %s",
                    polarisation.name, self._target_path / name)
                return None

            # Post-processing: attach metadata + statistics to each product
            if status:
                for p in products:
                    p_path = Path(p.full_path) if p.full_path else None
                    if p_path and p_path.exists():
                        p.inserted = datetime.now()
                        p.created  = master_dt
                        p.site_id  = site_id
                        p.relative_orbit = int(rel_orbit)
                        self._attach_statistics(p, p_path)
                    else:
                        msg = f"Expected output not found: {p.full_path}"
                        self._logger.warning(msg)
                        self._errors.append(msg)
                        status = False

        except Exception:
            msg = traceback.format_exc()
            ProductLog.error(product_folder_name, msg)
            self._errors.append(msg)
            status = False
        finally:
            self._cleanup_and_move(
                product_folder_name, name, status,
                product_folder, products,
                master_product, slave_product)

        return None if not self._errors else ";".join(self._errors)

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _build_product_name(site_id: int, master_date: str, slave_date: str,
                             polarisation: Polarisation,
                             rel_orbit: str) -> str:
        if not master_date or not rel_orbit or not polarisation:
            raise ValueError("Inconsistent product name: master_date, "
                             "rel_orbit and polarisation are required")

        name = f"SEN4CAP_L2A_S{site_id}_V{master_date}"
        if slave_date:
            name += f"_{slave_date}"
        name += f"_{polarisation.name}_{rel_orbit}"
        return name
    
    def _build_execution_steps(
        self,
        job: Job,
        polarisation: Polarisation,
        master_product: Path,
        slave_product: Optional[Path],
        product_type : ProductType,
        use_master_band: bool,
        target_name: str,
        work_dir: str, 
        out_s1l2 : str,
    ) -> Dict[str, List[dict]]:
        """
        Builds a single execution step invoking the external Java processor jar,
        which encapsulates all SNAP/GDAL processing internally.
        One step per enabled product type (AMP / COHE).
        """
        steps: Dict[str, List[dict]] = {}

        jar_path  = Config.get_setting("s1.processor.jar_path",
                                       "/app/app.jar")
        java_bin  = Config.get_setting("s1.processor.java_bin", "java")

        dem_name  = self._cfg.dem_name()
        dem_nodata= self._cfg.dem_no_data_value()
        spacing   = self._cfg.resolution_in_meters()
        keep_inter= "y" if self._cfg.keep_intermediate() else "n"

        # Projection: prefer snap-wkt; fall back to gdal-srs if it looks like EPSG
        projection = self._cfg.projection_wkt()
        if projection.upper().startswith("EPSG:"):
            proj_args = ["--gdal-srs", projection]
        else:
            proj_args = ["--snap-wkt", projection]

        # Tiles: optional CSV of S2 tile IDs for cropping
        tiles_csv = Config.get_setting("s1.processor.tiles", "")

        def _base_args(mode: str) -> List[str]:
            args = [
                java_bin, "-jar", jar_path,
                "--first",  str(master_product),
                "--second", str(slave_product) if slave_product else str(master_product),
                "--polarisation", polarisation.name,
                "--mode",         mode,
                "--work-dir",     work_dir,
                "--out",          out_s1l2,
                "--dem",          dem_name,
                "--dem-no-data-value", str(dem_nodata),
                "--pixel-spacing-meters", str(spacing),
                "--keep-inter",   keep_inter,
            ]
            args += proj_args
            if tiles_csv:
                args += ["--tiles", tiles_csv]
            return args

        print ("product_type = {}, L2A_AMP = {}, enabled = {}".format(product_type, ProductType.L2A_AMP, self._cfg.amplitude_enabled()))
        print ("product_type = {}, L2A_COHE = {}, enabled = {}".format(product_type, ProductType.L2A_COHE, self._cfg.coherence_enabled()))
        
        if product_type == ProductType.L2A_AMP.value and self._cfg.amplitude_enabled():
            steps["Amplitude"] = [{
                "args":        _base_args("amp"),
                "step_name":   "Amplitude",
                "min_disk_mb": 0,
            }]
        elif product_type == ProductType.L2A_COHE.value and self._cfg.coherence_enabled():
            steps["Coherence"] = [{
                "args":        _base_args("cohe"),
                "step_name":   "Coherence",
                "min_disk_mb": 0,
            }]

        return steps
    
    def _wrap_in_docker(
        self,
        arguments: List[str],
        master_parent: Path,
        slave_parent: Path,
        is_snap: bool,
    ) -> List[str]:
        """
        Translates createUnit() Docker-wrapping logic.
        Produces: docker run [opts] <image> [translated-args]
        """
        args = ["docker", "run", "-i"]
        if not IS_WINDOWS and self._uid and self._gid:
            args += ["-u", f"{self._uid}:{self._gid}"]
        args += ["--rm", "--volume-driver", "cifs"]
        home = Path.home()
        args += ["-v", f"{home}:{home}"]
        target_str   = _as_unix_path(self._target_path)
        container_tmp= str(self._tmp_path).replace("\\", "/")
        args += ["-v", f"{target_str}:/mnt/target"]
        tmp_str = _as_unix_path(_resolve_symlinks(self._tmp_path))
        args += ["-v", f"{tmp_str}:{container_tmp}"]
        args += ["-v",
                 f"{_as_unix_path(master_parent)}:/mnt/master_parent"]
        args += ["-v",
                 f"{_as_unix_path(slave_parent)}:/mnt/slave_parent"]

        if is_snap:
            snap_home = Config.get_setting(ConfigurationKeys.SNAP_HOME_PATH)
            if snap_home:
                sh = Path(snap_home); sh.mkdir(parents=True, exist_ok=True)
                args += ["-v", f"{_as_unix_path(sh)}:/home/.snap/"]
            dem_name = Config.get_setting(ConfigurationKeys.S1_PROCESSOR_DEM_NAME)
            dem_path = Config.get_setting(
                ConfigurationKeys.S1_PROCESSOR_DEM_LOCAL_PATH)
            if dem_name and dem_path and Path(dem_path).exists():
                args += ["-v",
                         f"{dem_path}:/home/.snap/auxdata/dem/{dem_name}"]
            image = Config.get_setting(ConfigurationKeys.DOCKER_SNAP_IMAGE,
                                       "lnicola/snap:8-ubuntu-20.04")
        else:
            image = Config.get_setting(ConfigurationKeys.DOCKER_GDAL_IMAGE,
                                       "osgeo/gdal:ubuntu-full-3.4.1")
        args.append(image)

        # Remap host paths to container mount-points
        mp = _as_unix_path(master_parent)
        sp = _as_unix_path(slave_parent)
        modified = [
            a.replace("\\", "/")
             .replace(target_str, "/mnt/target/")
             .replace(container_tmp + "/", container_tmp + "/")
             .replace(mp, "/mnt/master_parent/")
             .replace(sp, "/mnt/slave_parent/")
             .replace("///", "/").replace("//", "/")
            for a in arguments
        ]
        if "&&" in arguments:
            q = '"' if IS_WINDOWS else ""
            args += ["/bin/bash", "-c", q + " ".join(modified) + q]
        else:
            args += modified
        return args

    def _attach_statistics(self, product: HighLevelProduct, path: Path):
        """
        Reads band statistics from a GeoTIFF via gdalinfo -stats.
        Populates ProductDetails if successful (mirrors createProductMetadata).
        """
        try:
            result = subprocess.run(
                ["gdalinfo", "-stats", str(path)],
                capture_output=True, text=True, timeout=120)
            if result.returncode != 0:
                return
            details = ProductDetails()
            for line in result.stdout.splitlines():
                l = line.strip()
                if   l.startswith("STATISTICS_MINIMUM="): details.min_value    = float(l.split("=")[1])
                elif l.startswith("STATISTICS_MAXIMUM="): details.max_value    = float(l.split("=")[1])
                elif l.startswith("STATISTICS_MEAN="):    details.mean_value   = float(l.split("=")[1])
                elif l.startswith("STATISTICS_STDDEV="):  details.std_dev_value= float(l.split("=")[1])
            product.product_details = details
        except Exception as ex:
            self._logger.debug("gdalinfo failed for %s: %s", path, ex)

    def _cleanup_and_move(
        self,
        folder_name: str,
        product_name: str,
        status: bool,
        product_folder: Path,
        products: List[HighLevelProduct],
        master_product: Path,
        slave_product: Optional[Path],
    ):
        """Translated from cleanupAndMove()."""
        ProductLog.debug(folder_name,
                         f"Product {product_name} "
                         f"{'completed' if status else 'failed'}")
        ProductLog.cleanup(folder_name)

        if not self._cfg.keep_intermediate():
            self._cleanup_folder(product_folder)

        moved = False
        if status and self._tmp_path != self._target_path:
            try:
                shutil.move(str(product_folder), str(self._target_path))
                moved = True
                self._logger.debug("Moved %s → %s",
                                   product_folder, self._target_path)
            except Exception as ex:
                self._logger.error("Cannot move %s to %s: %s",
                                   product_folder, self._target_path, ex)

        if self._completion_callback:
            for p in products:
                if p:
                    try:
                        if moved and p.full_path:
                            p.full_path = p.full_path.replace(
                                str(self._tmp_path), str(self._target_path))
                        size_mb = 0.0
                        if p.full_path and Path(p.full_path).exists():
                            size_mb = (Path(p.full_path).stat().st_size
                                       / (1024 * 1024))
                        self._completion_callback(p, status, size_mb)
                    except Exception as cex:
                        self._logger.warning(
                            "Callback for %s failed: %s", p.product_name, cex)

        if self._errors:
            self._logger.error(
                "Errors for %s:\n%s", product_name,
                "\n".join(self._errors))

    def _cleanup_folder(self, folder: Path):
        """
        Translated from the Java cleanup() walk-and-delete:
        keeps files whose extension is in _EXCLUDED_EXTENSIONS,
        removes everything else, then removes empty directories.
        """
        if not folder.exists():
            return
        for item in list(folder.rglob("*")):
            if item.is_file() and item.suffix not in _EXCLUDED_EXTENSIONS:
                try:
                    item.unlink()
                except OSError as e:
                    self._logger.error("Cannot delete %s: %s", item, e)
        for d in sorted(folder.rglob("*"), reverse=True):
            if d.is_dir():
                try:
                    d.rmdir()
                except OSError:
                    pass


# ===========================================================================
# OrbitListener
# ===========================================================================

class OrbitListener:
    def __init__(self,
                 processing_orbits: Set[Tuple[int, Polarisation]],
                 faulty_orbits:     Set[Tuple[int, Polarisation]]):
        self._processing = processing_orbits
        self._faulty     = faulty_orbits

    def product_completed(self, orbit_id: int, polarisation: Polarisation):
        """Called after a task finishes (success or failure)."""
        self._processing.discard((orbit_id, polarisation))

    def accept(self, orbit_id: int, polarisation: Polarisation):
        """Called to flag a faulty orbit/polarisation pair."""
        self._faulty.add((orbit_id, polarisation))


# ===========================================================================
# QueueMonitor
# ===========================================================================

class QueueMonitor(threading.Thread):
    """
    Translated from Sentinel1Level2Job.QueueMonitor.
    Drains a blocking queue while enforcing orbit exclusivity:
    no two tasks from the same (orbitId, polarisation) pair run concurrently.
    """
    POLL_INTERVAL = 10  # seconds

    def __init__(self, task_queue: queue.Queue,
                 executor: ThreadPoolExecutor,
                 processing_orbits: Set[Tuple[int, Polarisation]],
                 max_threads: int):
        super().__init__(name="s1-queue-monitor", daemon=True)
        self._queue      = task_queue
        self._executor   = executor
        self._processing = processing_orbits
        self._max_threads= max_threads
        self._active     = 0
        self._lock       = threading.Lock()
        self._logger     = logging.getLogger(self.__class__.__name__)

    def run(self):
        while True:
            # Wait for a free thread slot
            while self._active >= self._max_threads:
                threading.Event().wait(self.POLL_INTERVAL)
            try:
                try:
                    key, runnable = self._queue.get(
                        timeout=self.POLL_INTERVAL)
                except queue.Empty:
                    continue

                product, polarisation = key
                orbit_key = (product.get_orbit_id(), polarisation)

                self._logger.info(
                    "Running for %s (orbit=%d pol=%s) – queue: %d",
                    product.get_product_name(), product.get_orbit_id(),
                    polarisation.name, self._queue.qsize())


                # If orbit/pol is busy, look for another schedulable task
                if orbit_key in self._processing:
                    buffer   = [(key, runnable)]
                    scheduled= False
                    while not self._queue.empty():
                        try:
                            nk, nr = self._queue.get_nowait()
                            np, npol = nk
                            nok = (np.get_orbit_id(), npol)
                            if nok not in self._processing:
                                for item in buffer:
                                    self._queue.put(item)
                                key, runnable    = nk, nr
                                product, polarisation = nk
                                orbit_key        = nok
                                buffer           = []
                                scheduled        = True
                                break
                            else:
                                buffer.append((nk, nr))
                        except queue.Empty:
                            break
                    for item in buffer:
                        self._queue.put(item)
                    if not scheduled:
                        self._queue.put((key, runnable))
                        threading.Event().wait(self.POLL_INTERVAL)
                        continue

                # Feature-flag check (mirrors Java check before executor.submit)
                if not Config.is_feature_enabled(
                        product.get_site_id(),
                        ConfigurationKeys.S1_PROCESSOR_ENABLED):
                    self._logger.info(
                        "S1 processing disabled for site %d; skipping %s",
                        product.get_site_id(), product.get_product_name())
                    continue

                self._processing.add(orbit_key)
                self._logger.info(
                    "Dispatching %s (orbit=%d pol=%s) – queue: %d",
                    product.get_product_name(), product.get_orbit_id(),
                    polarisation.name, self._queue.qsize())

                def _task(r=runnable):
                    try:
                        r()
                    finally:
                        with self._lock:
                            self._active -= 1
                        self._queue.task_done()
                        
                with self._lock:
                    self._active += 1
                self._executor.submit(_task)

            except Exception as ex:
                self._logger.error("QueueMonitor error: %s", ex)


# ===========================================================================
# Sentinel1L2ProcessorV1
# ===========================================================================

class Sentinel1L2ProcessorV1:
    """
    Translated from Sentinel1L2ProcessorV1.java.
    Handles amplitude/coherence processing for a single acquisition.
    """

    def __init__(self, pm: PersistenceManager):
        self._pm      = pm
        self._logger  = logging.getLogger(self.__class__.__name__)
        self._flags:   Dict[str, int] = {}
        self._cfgs:    Dict[int, ProcessorRuntimeConfiguration] = {}

    def get_version(self) -> int:
        return 1

    def process_acquisition(
        self,
        product: DownloadProduct,
        master:  MasterChoice,
        enabled_polarisations: Set[Polarisation],
        site: Site,
        target_root: Path,
        overwrite:   bool,
        orbit_consumer: Optional[OrbitListener] = None,
        discard_backscatter: bool = False,
    ):
        status = Status.PROCESSING
        error: Optional[str] = None
        pname = product.get_product_name()
        cfg   = self._cfgs.setdefault(
            site.get_id(),
            ProcessorRuntimeConfiguration.get(site.get_id()))

        try:
            if product.get_full_path().endswith("$value"):
                self._logger.error(
                    "Product %s path looks not downloaded. Skipping.", pname)
                self._update_fields(
                    product, Status.FAILED,
                    "Product not downloaded successfully")
                return

            self._update_fields(product, Status.PROCESSING, None)

            intersecting = self._get_intersecting(
                site.get_id(), product, cfg.days_back())
            if not intersecting:
                intersecting = self._get_intersecting(
                    site.get_id(), product, 2 * cfg.days_back())
                flags = ProcessFlag.AMPLITUDE
            else:
                flags = ProcessFlag.AMPLITUDE | ProcessFlag.COHERENCE

            if overwrite or cfg.overwrite_existing_products():
                flags |= ProcessFlag.OVERWRITE

            self._flags[pname] = flags

            if not intersecting:
                self._logger.info("No previous products for %s.", pname)
                self._update_fields(
                    product, Status.PROCESSING_FAILED, "No previous product")
                return

            if self._already_processed(
                    product, len(intersecting),
                    len(enabled_polarisations)):
                self._update_fields(product, Status.PROCESSED, None)
                return

            for i, iprod in enumerate(intersecting):
                fp = iprod.get_full_path()
                if not fp:
                    self._logger.error(
                        "Product [%s].full_path is None", pname)
                    return
                if fp.endswith("$value"):
                    self._logger.error(
                        "Intersecting product %s path not downloaded.",
                        iprod.get_product_name())
                    status = Status.PROCESSING_FAILED
                    break
                if not _is_path_accessible(Path(fp)):
                    self._logger.error(
                        "Product '%s' not readable at '%s'", pname, fp)
                    return

                master_p, slave_p = self._choose_master_slave(
                    master, product, iprod)

                if cfg.should_replace_links():
                    try:
                        self._copy_locally(Path(master_p.get_full_path()))
                        self._copy_locally(Path(slave_p.get_full_path()))
                    except IOError as ex:
                        self._logger.error(
                            "Cannot copy locally: %s", ex)
                        try:
                            self._restore_link(
                                Path(master_p.get_full_path()))
                            self._restore_link(
                                Path(slave_p.get_full_path()))
                        except IOError:
                            status = Status.PROCESSING_FAILED
                            continue

                self._ensure_uncompressed(master_p, site)
                self._ensure_uncompressed(slave_p, site)

                try:
                    for pol in enabled_polarisations:
                        flag = self._flags[pname]
                        if i != 0:
                            flag = ProcessFlag.reset_bit(
                                flag, ProcessFlag.AMPLITUDE)
                        is_master_current = (
                            product == master_p
                            or pname.startswith(master.name))
                        try:
                            msg = self._process_pair(
                                site, master_p, slave_p,
                                target_root, pol,
                                is_master_current, flag)
                            if msg:
                                status, error = Status.PROCESSING_FAILED, msg
                            else:
                                status = Status.PROCESSED
                        except Exception as e:
                            status = Status.PROCESSING_FAILED
                            error  = (f"Failed pair [{pname},"
                                      f"{iprod.get_product_name()}]: {e}")
                        if status == Status.PROCESSING_FAILED:
                            break
                finally:
                    self._cleanup_product(master_p)
                    self._cleanup_product(slave_p)

                if cfg.should_replace_links():
                    try:
                        self._replace_with_link(
                            Path(master_p.get_full_path()))
                        self._replace_with_link(
                            Path(slave_p.get_full_path()))
                    except IOError as ex:
                        self._logger.error(
                            "Cannot replace with symlink: %s", ex)

                if not ProcessFlag.is_set(
                        self._flags[pname], ProcessFlag.COHERENCE):
                    break

            self._update_fields(product, status, error)

        except Exception as ex:
            self._logger.error("Error processing %s: %s", pname, ex)
        finally:
            self._flags.pop(pname, None)
            if orbit_consumer:
                for pol in enabled_polarisations:
                    orbit_consumer.product_completed(
                        product.get_orbit_id(), pol)

    # Completion callback (called by Sentinel1Level2Worker)
    def apply(self, product: HighLevelProduct,
              status: bool, size_mb: float) -> None:
        name = product.get_product_name()
        if status:
            try:
                details = product.get_product_details()
                product.set_inserted(datetime.now())
                product = self._pm.save_product(product)
                if details:
                    details.id = product.get_id()
                    self._pm.save_product_details(details)
                self._logger.info("Created product %s", name)
            except Exception as e:
                self._logger.error("Cannot persist %s: %s", name, e)
        else:
            self._logger.error("Failed to create product %s", name)

    # --- private ---

    def _process_pair(self, site, master_p, slave_p,
                      target_root, pol, use_master_band,
                      process_flag) -> Optional[str]:
        cfg  = self._cfgs[site.get_id()]
        job  = JobHelper.create_job(
            site, cfg.processor(),
            json.dumps({"master": master_p.get_product_name()}))
        error: Optional[str] = None
        th:   Optional[DownloadProductTile] = None

        try:
            worker = Sentinel1Level2Worker(cfg, target_root)
            worker.set_completion_callback(self.apply)

            master_is_current = not (
                master_p.get_product_date() < slave_p.get_product_date())
            dld_id  = (master_p.get_id() if master_is_current
                       else slave_p.get_id())
            tile_id = ((slave_p.get_product_name()
                        if master_is_current
                        else master_p.get_product_name())
                       + "_" + pol.name)

            th = self._pm.get_download_product_tile(dld_id, tile_id)
            if th is None:
                th = DownloadProductTile()
                th.download_product_id = dld_id
                th.orbit_id            = master_p.get_orbit_id()
                th.tile_id             = tile_id
                th.satellite           = "Sentinel1"
                th.cloud_coverage      = -1
                th.snow_coverage       = -1
                th.node_id             = HOST
            else:
                th.set_retry_count(th.get_retry_count() + 1)

            th.set_status(TileProcessingStatus.PROCESSING)
            th.set_status_timestamp(datetime.now())
            th = self._pm.save_download_product_tile(th)

            msg = worker.create_products(
                job, dld_id, site, pol,
                master_p.get_orbit_type(),
                Path(master_p.get_full_path()),
                Path(slave_p.get_full_path()),
                use_master_band, process_flag, cfg.step_timeout())

            if msg:
                error = (f"Intersecting: {slave_p.get_product_name()}, "
                         f"pol: {pol.name}, error: {msg}")
                JobHelper.update(job, ActivityStatus.ERROR)
                th.set_status(TileProcessingStatus.FAILED)
                th.set_failed_reason(msg)
            else:
                JobHelper.update(job, ActivityStatus.FINISHED)
                th.set_status(TileProcessingStatus.DONE)
                th.set_failed_reason(None)

        except Exception as ex:
            self._logger.error("Failed pair {%s, %s}: %s",
                               master_p.get_product_name(),
                               slave_p.get_product_name(), ex)
            error = (f"Intersecting: {slave_p.get_product_name()}, "
                     f"pol: {pol.name}, error: {ex}")
            JobHelper.update(job, ActivityStatus.ERROR)
            if th:
                th.set_status(TileProcessingStatus.FAILED)
                th.set_failed_reason(traceback.format_exc())
        finally:
            if th:
                th.set_status_timestamp(datetime.now())
                self._pm.save_download_product_tile(th)

        return error

    def _already_processed(self, product, intersections,
                             polarisations) -> bool:
        produced = self._pm.get_produced_products(product.get_id())
        if not produced:
            return False
        expected = (intersections + 1) * polarisations
        if len(produced) < expected:
            self._logger.warning(
                "Product %s: expected %d outputs, found %d",
                product.get_product_name(), expected, len(produced))
            return False
        return True

    def _update_fields(self, product, status, reason):
        parts: List[str] = []
        if status == Status.PROCESSED:
            product.set_no_of_retries(0)
            product.set_status_reason(None)
            product.set_status_id(status)
        elif status == Status.PROCESSING_FAILED:
            product.set_no_of_retries(product.get_no_of_retries() + 1)
            tiles = self._pm.get_download_product_tiles_by_product(
                product.get_id())
            total  = len(tiles)
            failed = sum(1 for t in tiles
                         if t.get_status() == TileProcessingStatus.FAILED)
            if failed == total:
                product.set_status_id(status)
                parts.append(f"All {total} intersections failed")
            else:
                product.set_status_id(Status.PROCESSED)
                parts.append(f"Succeeded:{total-failed} failed:{failed}")
        else:
            product.set_status_id(status)

        if reason:
            ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            ex = product.get_status_reason() or ""
            ex += f"[{ts}] {reason};"
            ex = ex.replace("\x00", " ")
            ms = ex.split(";")
            if len(ms) > 3:
                ex = ";".join(ms[1:3])
            parts.append(f" ({ex})")
            self._logger.warning("Product %s not processed [%s]",
                                 product.get_product_name(), ex)
        if parts:
            product.set_status_reason("".join(parts))
        self._pm.save(product)

    def _choose_master_slave(self, config, p1, p2):
        is_s1a = p1.get_product_name().startswith("S1A")
        coh_on = ProcessFlag.is_set(
            self._flags.get(p1.get_product_name(), 0), ProcessFlag.COHERENCE)
        if coh_on and is_s1a and p2.get_product_name().startswith("S1A"):
            self._logger.warning("Both from same sensor [%s]",
                                 p1.get_product_name())
        if coh_on:
            if config == MasterChoice.S1A:
                return (p1, p2) if is_s1a else (p2, p1)
            elif config in (MasterChoice.S1B, MasterChoice.S1C):
                return (p2, p1) if is_s1a else (p1, p2)
            elif config == MasterChoice.OLDEST:
                return p2, p1
            else:
                return p1, p2
        return p2, p1

    def _get_intersecting(self, site_id, product, days_back):
        cfg = self._cfgs.get(product.get_site_id())
        results = self._pm.get_intersecting_products(
            site_id, product.get_product_name(), days_back,
            cfg.intersection_threshold() if cfg else 0.0)
        if results:
            orbit = Sentinel1ProductHelper.create(
                product.get_product_name()).get_orbit()
            results = [p for p in results
                       if Sentinel1ProductHelper.create(
                           p.get_product_name()).get_orbit() == orbit]
            fp = product.get_footprint()
            if fp and HAS_SHAPELY:
                results.sort(
                    key=lambda p: (p.get_footprint().intersection(fp).area
                                   if p.get_footprint() else 0),
                    reverse=True)
        return results or []

    def _is_zipped(self, product) -> bool:
        return _get_extension(product.get_full_path()) == ".zip"

    def _ensure_uncompressed(self, product, site):
        if product.original_path is None:
            try:
                wd = (Path(Config.get_setting(
                    ConfigurationKeys.S1_PROCESSOR_WORK_DIR)
                    or "/mnt/archive/s1_preprocessing_work_dir")
                      / site.get_short_name()
                      / str(uuid.uuid4()))
                _ensure_exists(wd)
                if not _is_path_writeable(wd):
                    raise IOError(f"Folder '{wd}' not writable.")
                cfg = self._cfgs.get(site.get_id())
                if self._is_zipped(product):
                    orig = product.get_full_path()
                    _decompress_zip(Path(orig), wd)
                    product.set_original_path(orig)
                    product.set_full_path(
                        str(wd / product.get_product_name()))
                elif cfg and cfg.copy_products_locally():
                    orig = product.get_full_path()
                    _copy_tree(Path(orig), wd)
                    product.set_original_path(orig)
                    product.set_full_path(
                        str(wd / product.get_product_name()))
            except Exception as ex:
                self._logger.error("Cannot uncompress/copy %s: %s",
                                   product.get_product_name(), ex)

    def _cleanup_product(self, product):
        if product and product.original_path:
            try:
                t = (Path(product.get_full_path()).parent
                     / product.get_product_name())
                _delete_tree(t)
                product.set_full_path(product.original_path)
                product.set_original_path(None)
            except Exception as e:
                self._logger.error("Cleanup failed for %s: %s",
                                   product.get_product_name(), e)

    def _copy_locally(self, lnk: Path):
        if not lnk.is_symlink():
            raise IOError(f"{lnk} is not a symlink")
        real = lnk.resolve()
        if not real.exists():
            raise IOError(f"Target of {lnk} not found")
        bak = lnk.parent / (lnk.name + ".bak")
        lnk.rename(bak)
        _copy_tree(real, lnk.parent / lnk.name)

    def _replace_with_link(self, folder: Path):
        bak = Path(str(folder) + ".bak")
        if bak.exists():
            _delete_tree(folder)
            self._restore_link(folder)

    def _restore_link(self, original: Path):
        Path(str(original) + ".bak").rename(original)


# ===========================================================================
# Sentinel1Level2Job
# ===========================================================================

class Sentinel1Level2Job:
    """
    Translated from Sentinel1Level2Job.java.

    Discovers eligible Sentinel-1 products, checks S1A/S1B sensor mix,
    builds an orbit-interleaved processing queue, and dispatches each
    (product × polarisation) task to Sentinel1L2ProcessorV1 via a
    thread pool guarded by QueueMonitor.
    """

    _running_jobs:      Set[str] = set()
    _running_jobs_lock: threading.Lock = threading.Lock()

    def __init__(self, pm: PersistenceManager):
        self._pm     = pm
        self._logger = logging.getLogger(self.__class__.__name__)
        self.id      = "S1 Pre-processing"

        JobHelper.set_persistence_manager(pm)

        self._target_tpl   = Config.get_setting(
            ConfigurationKeys.S1_PROCESSOR_OUTPUT_PATH,
            "/mnt/output/s1/{site}")
        max_threads        = max(1, Config.get_as_integer(
            ConfigurationKeys.S1_PROCESSOR_PARALLELISM, 2))
        self._max_threads  = max_threads

        self._faulty_orbits:    Set[Tuple[int, Polarisation]] = set()
        self._processing_orbits:Set[Tuple[int, Polarisation]] = set()
        self._orbit_consumer   = OrbitListener(
            self._processing_orbits, self._faulty_orbits)

        self._task_queue: queue.Queue = queue.Queue()
        self._executor   = ThreadPoolExecutor(
            max_workers=max_threads, thread_name_prefix="s1-worker")
        self._monitor    = QueueMonitor(
            self._task_queue, self._executor,
            self._processing_orbits, max_threads)

        self._logger.info(
            "Sentinel-1 pre-processing will use at most %d threads",
            max_threads)

    # ------------------------------------------------------------------
    def execute_for_site(self, site: Site):
        if not site.is_enabled():
            self._logger.info("Site '%s' disabled.", site.get_short_name())
            return
        if not Config.is_feature_enabled(
                site.get_id(), ConfigurationKeys.S1_PROCESSOR_ENABLED):
            self._logger.info("S1 pre-processing disabled for '%s'.",
                              site.get_short_name())
            return

        with self._running_jobs_lock:
            if site.get_name() in self._running_jobs:
                self._logger.warning(
                    "Job already running for '%s'.", site.get_name())
                return
            self._running_jobs.add(site.get_name())

        try:
            if not self._task_queue.empty():
                self._logger.warning(
                    "%d acquisitions pending. Exiting.",
                    self._task_queue.qsize())
                return
            self._process_site(site)
        except Exception as ex:
            self._logger.error("Exception for site %s: %s",
                               site.get_name(), ex)
        finally:
            with self._running_jobs_lock:
                self._running_jobs.discard(site.get_name())

    # ------------------------------------------------------------------
    def _process_site(self, site: Site):
        version = int(Config.get_setting(
            ConfigurationKeys.S1_PROCESSOR_VERSION, "1"))
        latest_first = Config.get_setting(
            ConfigurationKeys.S1_PROCESSOR_REVERSE_ACQUISITION_DATE,
            "false").lower() == "true"

        seasons = self._pm.get_enabled_seasons(site.get_id())
        if not seasons:
            self._logger.warning("No season for '%s'.", site.get_short_name())
            return
        seasons.sort(key=lambda s: s.get_start_date())

        wait_days = int(Config.get_setting(
            ConfigurationKeys.S1_PROCESSOR_WAIT_FOR_ORBIT_FILES, "0"))
        cutoff    = date.today() - timedelta(days=wait_days)

        products = self._pm.get_downloaded_products(
            site.get_id(), Satellite.Sentinel1, cutoff,
            self._get_start_date(seasons),
            self._get_end_date(seasons),
            latest_first)

        self._check_s1_interval(site, products)

        pair_days  = Config.get_as_integer_for_site(
            site.get_id(), ConfigurationKeys.S1_PROCESSOR_DAYS_BACK, 6)
        bks_offset = Config.get_as_integer_for_site(
            site.get_id(), ConfigurationKeys.S1_PROCESSOR_MTF_INTERVAL, 0)
        coh_on     = Config.get_setting_for_site(
            site.get_id(),
            ConfigurationKeys.S1_PROCESSOR_COHERENCE_ENABLED,
            "true").lower() == "true"

        if coh_on:
            stall_days = pair_days if version == 1 \
                         else max(pair_days, bks_offset)
            stalled    = self._pm.get_stalled_products(
                site.get_id(), stall_days)
            if stalled:
                self._logger.debug(
                    "%d stalled products.", len(stalled))
                products.extend(stalled)

        products.extend(self._pm.get_products(
            site.get_id(), Satellite.Sentinel1.value,
            Status.PROCESSING_FAILED, "Cannot construct DataBuffer"))

        if not products:
            self._logger.info(
                "No eligible S1 products for '%s'.", site.get_name())
            return

        initial = len(products)
        missing, accessible = [], []
        for p in products:
            try:
                (accessible if Path(p.get_full_path()).exists()
                 else missing).append(p)
            except Exception as ex:
                self._logger.warning("Path check for %s: %s",
                                     p.get_product_name(), ex)
        if missing:
            if len(missing) == initial:
                self._logger.error(
                    "No product locally available for '%s'. Aborting.",
                    site.get_short_name())
                return
            self._logger.warning(
                "%d products not found: %s", len(missing),
                ",".join(p.get_product_name() for p in missing))

        products = accessible
        products.sort(
            key=lambda p: p.get_product_date() or datetime.min)

        site_root = Path(self._target_tpl.replace(
            "{site}", site.get_short_name()))
        try:
            target_root = (
                _resolve_symlinks(site_root)
                if Config.get_as_boolean(
                    site.get_id(),
                    ConfigurationKeys.S1_PROCESSOR_RESOLVE_LINKS, False)
                else site_root)
            _ensure_exists(target_root)
            if not _is_path_writeable(target_root):
                raise IOError(f"'{target_root}' is not writable.")
            tmp_str = Config.get_setting(
                ConfigurationKeys.S1_PROCESSOR_WORK_DIR, "")
            if tmp_str:
                tmp_p = _resolve_symlinks(Path(tmp_str))
                _ensure_exists(tmp_p)
                if not _is_path_writeable(tmp_p):
                    raise IOError(f"Work folder '{tmp_p}' is not writable.")
        except IOError as ex:
            self._logger.error("Cannot prepare output folder: %s", ex)
            return

        pol_str = Config.get_setting_for_site(
            site.get_id(),
            ConfigurationKeys.S1_PROCESSOR_POLARISATIONS, "")
        enabled_pols: Set[Polarisation] = set()
        for tok in (pol_str.split(";") if pol_str else []):
            try:
                enabled_pols.add(Polarisation[tok.strip()])
            except KeyError:
                self._logger.warning("Unknown polarisation '%s'.", tok)
        if not enabled_pols:
            enabled_pols = set(Polarisation)

        master = MasterChoice[Config.get_setting_for_site(
            site.get_id(), ConfigurationKeys.S1_PROCESSOR_MASTER, "NEWEST")]

        # Orbit-interleaved ordering (mirrors Java split-and-alternate logic)
        orbit_ids = list(dict.fromkeys(p.get_orbit_id() for p in products))
        by_orbit: Dict[int, List[DownloadProduct]] = {
            oid: [] for oid in orbit_ids}
        for p in products:
            by_orbit[p.get_orbit_id()].append(p)

        count = len(products)
        interleaved: List[DownloadProduct] = []
        level = 0
        while len(interleaved) < count:
            for oid in orbit_ids:
                lst = by_orbit[oid]
                if level < len(lst):
                    interleaved.append(lst[level])
            level += 1

        effective_max = min(
            len(orbit_ids) * len(enabled_pols), self._max_threads)
        self._logger.info(
            "Found %d products (%s). Up to %d parallel jobs.",
            count,
            ", ".join(
                f"orbit {o}:{len(by_orbit[o])}" for o in orbit_ids),
            effective_max)

        # self._logger.info(
        #     "The products are : %s",
        #     ", ".join(p.product_name for p in products)
        # )

        if not self._monitor.is_alive():
            try:
                self._monitor.start()
            except RuntimeError:
                self._monitor = QueueMonitor(
                    self._task_queue, self._executor,
                    self._processing_orbits, effective_max)
                self._monitor.start()

        # Enqueue tasks
        for prd in interleaved:
            for pol in enabled_pols:
                product = prd.duplicate()
                product.set_id(prd.get_id())

                def make_task(
                    prod=product, pol_=pol,
                    site_=site, troot=target_root,
                    v=version, m=master,
                    ep=frozenset({pol}),
                ):
                    def task():
                        try:
                            # self._logger.warning(
                            #         "Within task for site %s.",
                            #         site_.get_short_name())
                                    
                            updated = self._pm.get_site_by_id(
                                site_.get_id())
                            if updated is None:
                                self._logger.warning(
                                    "Site '%s' deleted.",
                                    site_.get_short_name())
                                return
                            if not updated.is_enabled():
                                self._logger.warning(
                                    "Site '%s' disabled.",
                                    updated.get_short_name())
                                return

                            self._check_path(prod)

                            if prod.get_status_id() == Status.ABORTED:
                                self._logger.warning(
                                    "Product %s aborted: %s",
                                    prod.get_product_name(),
                                    prod.get_status_reason())
                                self._pm.save(prod)
                                return

                            orbit_key = (prod.get_orbit_id(), pol_)
                            processor = self._create_processor(v)
                            discard_bs = (
                                v == 2
                                and Config.get_setting(
                                    ConfigurationKeys
                                    .IGNORE_PREVIOUS_ORBIT_FAILURE,
                                    "false").lower() != "true"
                                and orbit_key in self._faulty_orbits)

                            processor.process_acquisition(
                                prod, m, set(ep), updated,
                                troot, False,
                                self._orbit_consumer, discard_bs)
                        except Exception:
                            self._logger.error(
                                "Cannot process '%s' (pol %s):\n%s",
                                prod.get_product_name(), pol_.name,
                                traceback.format_exc())
                        finally:
                            self._orbit_consumer.product_completed(
                                prod.get_orbit_id(), pol_)
                    return task

                self._task_queue.put(
                    ((product, pol), make_task()))

        # wait for the queue to drain:
        self._task_queue.join()   # requires tasks to call task_queue.task_done()

    # ------------------------------------------------------------------
    def _check_s1_interval(
            self, site: Site,
            products: List[DownloadProduct]):
        """Translated from checkS1Interval()."""
        if not products:
            return
        sensors = {p.get_product_name()[:3] for p in products}
        if len(sensors) == 1:
            self._logger.warning(
                "Site '%s': single-satellite. days_back=12, master=NEWEST.",
                site.get_short_name())
            Config.set_setting(
                site.get_id(),
                ConfigurationKeys.S1_PROCESSOR_DAYS_BACK, "12")
            Config.set_setting(
                site.get_id(),
                ConfigurationKeys.S1_PROCESSOR_MASTER, "NEWEST")
            return

        grouped:       Dict[str, str]  = {}
        single_sensor: Dict[str, bool] = {}
        for p in products:
            m = S1_PATTERN.match(p.get_product_name())
            if not m:
                continue
            abs_orbit = int(m.group(10))
            sat = p.get_product_name()[:3]
            rel = f"{((abs_orbit-73)%175+1) if sat.endswith('A') else (abs_orbit-27)%175+1:03d}"
            prev = grouped.get(rel)
            grouped[rel] = sat
            if prev is None:
                single_sensor[rel] = True
            else:
                single_sensor[rel] = (
                    single_sensor.get(rel, True) and sat == prev)

        all_single  = all(single_sensor.values())
        none_single = not any(single_sensor.values())

        if all_single:
            self._logger.warning(
                "Site '%s': per-orbit single-satellite. "
                "days_back=12, master=NEWEST.",
                site.get_short_name())
            Config.set_setting(
                site.get_id(),
                ConfigurationKeys.S1_PROCESSOR_DAYS_BACK, "12")
            Config.set_setting(
                site.get_id(),
                ConfigurationKeys.S1_PROCESSOR_MASTER, "NEWEST")
        elif none_single:
            if Config.get_as_integer_for_site(
                    site.get_id(),
                    ConfigurationKeys.S1_PROCESSOR_DAYS_BACK, 12) == 12:
                self._logger.warning(
                    "Site '%s': reverting to days_back=6, master=S1C.",
                    site.get_short_name())
                Config.set_setting(
                    site.get_id(),
                    ConfigurationKeys.S1_PROCESSOR_DAYS_BACK, "6")
                Config.set_setting(
                    site.get_id(),
                    ConfigurationKeys.S1_PROCESSOR_MASTER, "S1C")
        else:
            self._logger.warning(
                "Site '%s': mixed orbits – coherence may not be computed "
                "for single-satellite orbits.", site.get_short_name())

    def _get_start_date(self, seasons: List[Season]) -> date:
        offset = max(
            Config.get_as_integer(ConfigurationKeys.S1_DOWNLOAD_OFFSET, 6),
            Config.get_as_integer(
                ConfigurationKeys.S1_PROCESSOR_MTF_INTERVAL, 0))
        return seasons[0].get_start_date() - timedelta(days=offset)

    def _get_end_date(self, seasons: List[Season]) -> date:
        return seasons[-1].get_end_date() + timedelta(days=1)

    def _check_path(self, product: DownloadProduct):
        """Translated from checkPath()."""
        fp = product.get_full_path()
        if not fp:
            raise IOError(
                f"Product [{product.get_product_name()}].full_path is NULL")
        p = Path(fp)
        if not _is_path_accessible(p):
            if p.is_symlink():
                real = p.resolve()
                if not _is_path_accessible(real):
                    raise IOError(
                        f"Product '{product.get_product_name()}' "
                        f"not readable at '{fp}'")
                _link(real, p)   # re-create dangling symlink
            else:
                raise IOError(
                    f"Product '{product.get_product_name()}' "
                    f"not readable at '{fp}'")

        helper = Sentinel1ProductHelper.create(product.get_product_name())
        if fp.lower().endswith((".zip", ".gz", ".tar")):
            return
        meta = p / helper.get_metadata_file_name()
        if not meta.exists():
            msg = (f"Product {product.get_product_name()} "
                   f"incomplete (metadata not found)")
            self._logger.warning(msg)
            product.set_status_id(Status.ABORTED)
            product.set_status_reason(msg)
        else:
            product.set_status_reason(None)

    def _create_processor(self, version: int) -> Sentinel1L2ProcessorV1:
        if version == 1:
            return Sentinel1L2ProcessorV1(self._pm)
        raise ValueError(f"Unsupported processor version: {version}")


def main():
    parser = argparse.ArgumentParser(
        description="Extracts radar input data for the S4C L4B processor"
    )
    parser.add_argument(
        "-c",
        "--config-file",
        default="/mnt/tao/cfg/sen4cap/sen2agri.conf",
        help="configuration file location",
    )
    
    args = parser.parse_args()
    
    mainScriptConfig = MainScriptConfig(args)

    logging.basicConfig(
        level=logging.DEBUG,
        format="%(asctime)s [%(threadName)s] %(levelname)-8s %(name)s – %(message)s",
    )

    # 1. Global configuration
    Config.setup({
        ConfigurationKeys.S1_PROCESSOR_ENABLED:              "false",
        ConfigurationKeys.S1_PROCESSOR_VERSION:              "1",
        ConfigurationKeys.S1_PROCESSOR_OUTPUT_PATH:          "/mnt/output/s1/{site}",
        ConfigurationKeys.S1_PROCESSOR_PARALLELISM:          "2",
        ConfigurationKeys.S1_PROCESSOR_DAYS_BACK:            "6",
        ConfigurationKeys.S1_PROCESSOR_MTF_INTERVAL:         "0",
        ConfigurationKeys.S1_PROCESSOR_COHERENCE_ENABLED:    "true",
        ConfigurationKeys.S1_PROCESSOR_AMPLITUDE_ENABLED:    "true",
        ConfigurationKeys.S1_PROCESSOR_POLARISATIONS:        "VV;VH",
        ConfigurationKeys.S1_PROCESSOR_MASTER:               "S1C",
        ConfigurationKeys.S1_PROCESSOR_WORK_DIR:             "/mnt/tmp/s1_work",
        ConfigurationKeys.S1_PROCESSOR_WAIT_FOR_ORBIT_FILES: "0",
        ConfigurationKeys.S1_DOWNLOAD_OFFSET:                "6",
        ConfigurationKeys.S1_PROCESSOR_OUTPUT_FORMAT:        "GeoTIFF",
        ConfigurationKeys.S1_PROCESSOR_OUTPUT_EXTENSION:     ".tif",
        "snap.gpt_path":    "gpt",
        "snap.graphs_dir":  "/opt/sen4cap/graphs",
         "s1.processor.jar_path":  "/app/app.jar",
        "s1.processor.java_bin":  "java",
        "s1.processor.tiles":     "",        # e.g. "32UNU,32UMU" to crop to tiles
    })

    # 2. Enable feature flags for site 1
    Config.set_setting(19, ConfigurationKeys.S1_PROCESSOR_ENABLED, "true")

    # 3. Connect to PostgreSQL (override via env var POSTGRES_DSN)
    # dsn = os.environ.get(
    #     "POSTGRES_DSN",
    #     "postgresql+psycopg2://sen4cap:sen4cap@localhost/sen4cap",
    # )

    dsn = f"postgresql+psycopg2://{mainScriptConfig.user}:{mainScriptConfig.password}@{mainScriptConfig.host}:{mainScriptConfig.port}/{mainScriptConfig.dbname}"
    
    pm = PersistenceManager(dsn)

    # 4. Execute
    site = pm.get_site_by_id(19)
    if site:
        job = Sentinel1Level2Job(pm)
        job.execute_for_site(site)
    else:
        logging.getLogger(__name__).error(
            "Site id=1 not found in database.")

# ===========================================================================
# Entry point
# ===========================================================================
if __name__ == "__main__":
    main()

