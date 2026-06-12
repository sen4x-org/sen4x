#!/usr/bin/env python

import argparse
import pandas as pd
import numpy as np
from pyarrow import ipc
import re
import time

class Config(object):
    def __init__(self, args):
        self.coh_thr = args.coh_thr
        self.ndvi_thr = 0.25  # Fixed in v2 (hardcoded in filter_detections_by_ndvi)
        self.s2_window_days = args.s2_window_days
        self.amp_db_thr_vv = args.amp_db_thr_vv
        self.amp_db_thr_vh = args.amp_db_thr_vh
        self.cr_thr = args.cr_thr
        self.s1_window_days = args.s1_window_days
        self.poi = [args.start_date, args.end_date]
        # Empty set means "all orbits accepted"; populated set filters to those values only
        self.valid_orb_nrs = set(args.orb_nrs) if args.orb_nrs else set()


def _parse_columns(column_names, cols_var):
    """
    Pre-classify all variable columns into coh_vv / amp / s2 buckets
    by scanning column names once, avoiding repeated .str.contains on
    the melted (huge) DataFrame.

    Returns three lists of column names for each data type.
    """
    coh_cols, amp_cols, s2_cols = [], [], []
    for col in cols_var:
        if "mean_COHE_VV" in col:
            coh_cols.append(col)
        elif "mean_AMP" in col:
            amp_cols.append(col)
        elif "NDVI" in col and ("mean" in col or "valid_pixels" in col):
            s2_cols.append(col)
    return coh_cols, amp_cols, s2_cols


def _melt_subset(mdb_df, id_col, value_cols, value_name):
    """
    Melt only the relevant subset of columns instead of the full DataFrame,
    which is the primary source of memory/CPU waste in the original code.
    """
    return pd.melt(
        mdb_df[["NewID"] + value_cols],
        id_vars=[id_col],
        value_vars=value_cols,
        var_name="variable",
        value_name=value_name,
    )


def _extract_coh_vv(mdb_df, coh_cols, valid_orb_nrs):
    """Extract and parse S1 coherence VV timeseries."""
    df = _melt_subset(mdb_df, "NewID", coh_cols, "coh_vv")
    df = df.dropna(subset=["coh_vv"])

    # Vectorised string parsing — split once, reuse parts
    parts = df["variable"].str.split("_", expand=False)
    df["date"] = pd.to_datetime(parts.str[0], format="%Y%m%d", errors="coerce")
    df["orb_nr"] = pd.to_numeric(parts.str[-1], errors="coerce")

    if valid_orb_nrs:
        df = df[df["orb_nr"].isin(valid_orb_nrs)]
    return df[["NewID", "date", "orb_nr", "coh_vv"]]


def _extract_amp(mdb_df, amp_cols, valid_orb_nrs):
    """Extract and parse S1 amplitude timeseries."""
    df = _melt_subset(mdb_df, "NewID", amp_cols, "amp_dB")
    df = df.dropna(subset=["amp_dB"])

    parts = df["variable"].str.split("_", expand=False)
    df["date"] = pd.to_datetime(parts.str[0], format="%Y%m%d", errors="coerce")
    df["orb_nr"] = pd.to_numeric(parts.str[-1], errors="coerce").astype("Int64")
    df["pol"] = parts.str[3]

    if valid_orb_nrs:
        df = df[df["orb_nr"].isin(valid_orb_nrs)]
    return df[["NewID", "date", "orb_nr", "pol", "amp_dB"]]


def _extract_s2(mdb_df, s2_cols):
    """Extract and parse S2/NDVI timeseries."""
    df = _melt_subset(mdb_df, "NewID", s2_cols, "value")
    df = df.dropna(subset=["value"])

    parts = df["variable"].str.split("_", expand=False)
    df["date"] = pd.to_datetime(parts.str[0], format="%Y%m%d", errors="coerce")
    # Reconstruct the sub-variable name (everything after the date prefix)
    df["var"] = df["variable"].str.split("_", n=1).str[1]

    df = df[["NewID", "value", "date", "var"]].pivot(
        index=["NewID", "date"], columns="var", values="value"
    ).reset_index()

    df["frac_valid_NDVI"] = (
        df["valid_pixels_cnt_NDVI"]
        / (df["valid_pixels_cnt_NDVI"] + df["invalid_pixels_cnt_NDVI"])
    )
    df["mean_NDVI"] = df["mean_NDVI"] / 1000
    return df


def _build_amp_wide(mdb1_amp):
    """
    Build a wide-format amplitude table with separate VV and VH columns,
    plus the Cross-Ratio (CR = linear VH / linear VV) required by v2.
    """
    amp_vv = (
        mdb1_amp[mdb1_amp["pol"] == "VV"]
        .rename(columns={"amp_dB": "amp_vv_dB"})
        [["NewID", "date", "orb_nr", "amp_vv_dB"]]
    )
    amp_vh = (
        mdb1_amp[mdb1_amp["pol"] == "VH"]
        .rename(columns={"amp_dB": "amp_vh_dB"})
        [["NewID", "date", "orb_nr", "amp_vh_dB"]]
    )
    amp_wide = amp_vv.merge(amp_vh, on=["NewID", "date", "orb_nr"], how="left")
    amp_wide["CR"] = (
        10 ** (amp_wide["amp_vh_dB"] / 10) / 10 ** (amp_wide["amp_vv_dB"] / 10)
    )
    return amp_wide


class TillageProcessor:
    """Utility class for tillage detection processing."""

    @staticmethod
    def detect_event_coh(df, var_column, ID_column, diff_thresh, groupby=[]):
        df = df.sort_values(by=[ID_column] + groupby + ["date"])
        grp = df.groupby([ID_column] + groupby)[var_column]
        df[f"{var_column}_diff_to_prev"] = -grp.diff(1)
        df[f"{var_column}_diff_to_next"] = -grp.diff(-1)
        df["event"] = (
            (df[f"{var_column}_diff_to_prev"] > diff_thresh)
            | (df[f"{var_column}_diff_to_next"] > diff_thresh)
        )
        return df

    @staticmethod
    def filter_detections_by_ndvi(df_out_detections, s2_timeseries, ndvi_thr,
                                   s2_window_days, field_id_column="NewID"):
        """
        Vectorised NDVI filter. In v2 ndvi_thr is hardcoded to 0.25 in the
        util function, but we keep it as a parameter here for transparency;
        Config always passes 0.25.
        """
        filtered_detections = df_out_detections.copy()
        filtered_detections["max_ndvi_after_det"] = np.nan

        detections = filtered_detections[filtered_detections["event"]].copy()
        if detections.empty:
            return filtered_detections

        # Add window boundary to detections
        detections = detections.assign(
            date_plus_window=detections["date"] + pd.Timedelta(days=s2_window_days)
        )

        # Cross-join detections with s2 on the same field, then filter by date window.
        # Using a merge on field ID followed by a boolean date mask is much faster
        # than Python-level iteration.
        s2_sub = s2_timeseries[[field_id_column, "date", "mean_NDVI"]].rename(
            columns={"date": "s2_date"}
        )

        merged = detections[[field_id_column, "date", "date_plus_window"]].merge(
            s2_sub, on=field_id_column, how="left"
        )

        # Keep only s2 rows that fall strictly within the detection window
        in_window = (merged["s2_date"] > merged["date"]) & (
            merged["s2_date"] <= merged["date_plus_window"]
        )
        merged = merged[in_window]

        # Max NDVI per (field, detection_date)
        max_ndvi = (
            merged.groupby([field_id_column, "date"])["mean_NDVI"]
            .max()
            .reset_index(name="max_ndvi_after_det")
        )

        # Map max NDVI back via a merge on the full filtered_detections DataFrame.
        # This avoids any index mismatch: the merge on (field_id_column, "date")
        # correctly aligns rows regardless of how indices were reset by prior operations.
        filtered_detections = filtered_detections.merge(
            max_ndvi, on=[field_id_column, "date"], how="left",
            suffixes=("", "_new")
        )
        if "max_ndvi_after_det_new" in filtered_detections.columns:
            mask = filtered_detections["max_ndvi_after_det_new"].notna()
            filtered_detections.loc[mask, "max_ndvi_after_det"] = (
                filtered_detections.loc[mask, "max_ndvi_after_det_new"]
            )
            filtered_detections.drop(columns=["max_ndvi_after_det_new"], inplace=True)

        # Invalidate detections where NDVI is above threshold
        suppress = (
            filtered_detections["event"]
            & (filtered_detections["max_ndvi_after_det"] >= ndvi_thr)
            & filtered_detections["max_ndvi_after_det"].notna()
        )
        filtered_detections.loc[suppress, "event"] = False

        return filtered_detections

    @staticmethod
    def filter_detections_by_cr(df_out_detections, s1_timeseries, cr_thr,
                                 s1_window_days, field_id_column="NewID"):
        """
        Vectorised CR filter (new in v2).

        Invalidates detections where:
          - max CR within s1_window_days after detection >= cr_thr, AND
          - max_ndvi_after_det is NaN (no NDVI recovery observed).

        s1_timeseries must contain columns: field_id_column, 'date', 'CR'.
        """
        detections = df_out_detections[df_out_detections["event"]].copy()
        detections["max_cr_after_det"] = np.nan

        detections["date_plus_window"] = (
            detections["date"] + pd.Timedelta(days=s1_window_days)
        )

        merged = detections.reset_index().rename(columns={"index": "det_idx"}).merge(
            s1_timeseries[[field_id_column, "date", "CR"]],
            on=field_id_column,
            suffixes=("_det", "_s1"),
        )

        merged = merged.loc[
            (merged["date_s1"] > merged["date_det"])
            & (merged["date_s1"] <= merged["date_plus_window"])
        ]

        detections["max_cr_after_det"] = (
            merged.groupby("det_idx")["CR"]
            .max()
            .reindex(detections.index)
        )

        out = df_out_detections.merge(
            detections[["max_cr_after_det"]],
            left_index=True, right_index=True, how="left",
        )

        out.loc[
            out["event"]
            & (out["max_cr_after_det"] >= cr_thr)
            & out["max_ndvi_after_det"].isna(),
            "event",
        ] = False

        return out

    @staticmethod
    def filter_periods(df_detections, POI):
        """
        Filter detections to the period of interest only.
        Note: exclude_periods support was removed in v2.
        """
        POI_dt = [pd.to_datetime(d) for d in POI]
        df_out = df_detections.copy()
        dates = df_out["date"]
        outside_poi = (dates < POI_dt[0]) | (dates > POI_dt[1])
        df_out.loc[outside_poi, "event"] = False
        return df_out

    @staticmethod
    def flag_ploughing(df_detections, s1_timeseries_wide, threshold_vv_dB,
                       threshold_vh_dB):
        """
        Replaces identify_tillage() from v1.

        Flags detected events as ploughing based on both VV and VH backscatter.
        s1_timeseries_wide must contain: NewID, date, orb_nr, amp_vv_dB, amp_vh_dB.
        Produces boolean columns detection_VV and detection_VH.
        """
        s1_sub = s1_timeseries_wide[
            ["NewID", "date", "amp_vv_dB", "amp_vh_dB", "orb_nr"]
        ].copy()

        df_detect_ws1 = df_detections.merge(
            s1_sub, on=["NewID", "date", "orb_nr"], how="left"
        )

        df_detect_ws1["detection_VV"] = np.where(
            df_detect_ws1["event"] & (df_detect_ws1["amp_vv_dB"] > threshold_vv_dB),
            True, False,
        )
        df_detect_ws1["detection_VH"] = np.where(
            df_detect_ws1["event"] & (df_detect_ws1["amp_vh_dB"] > threshold_vh_dB),
            True, False,
        )

        return df_detect_ws1

    @staticmethod
    def summarize_detections(out_ploughing):
        """
        Counts consecutive detections and calculates the fraction of detections
        considered ploughing, reported separately for VV and VH polarisations.
        """
        df_out = out_ploughing.sort_values(["NewID", "date"])

        prev_event = df_out.groupby("NewID")["event"].shift(1)
        df_out["true_run"] = (df_out["event"] != prev_event).cumsum()

        # Use groupby size directly instead of transform, then mask non-events
        run_sizes = df_out.groupby("true_run")["event"].transform("size")
        df_out["consecutive_true"] = np.where(df_out["event"], run_sizes, 0)

        summary_detections = df_out[df_out["event"]].copy()

        frac_ploughing = (
            summary_detections.groupby("true_run")[["detection_VV", "detection_VH"]]
            .mean()
            .rename(columns={
                "detection_VV": "frac_ploughing_VV",
                "detection_VH": "frac_ploughing_VH",
            })
        )

        summary_detections = summary_detections.drop_duplicates(
            ["NewID", "true_run"], keep="first"
        )
        summary_detections = summary_detections.merge(frac_ploughing, on="true_run")
        summary_detections.set_index("date", inplace=True)

        return summary_detections[
            ["NewID", "consecutive_true", "frac_ploughing_VV", "frac_ploughing_VH"]
        ]


def handle_batch_record(config, cols_var, mdb_df, tillage_results_all):
    # --- Pre-classify columns once per batch ---
    coh_cols, amp_cols, s2_cols = _parse_columns(mdb_df.columns.tolist(), cols_var)

    # --- Melt only the relevant column subsets ---
    mdb1_cohe_vv = _extract_coh_vv(mdb_df, coh_cols, config.valid_orb_nrs)
    mdb1_amp = _extract_amp(mdb_df, amp_cols, config.valid_orb_nrs)
    mdb1_s2 = _extract_s2(mdb_df, s2_cols)

    # --- Build wide-format amplitude table with CR column (new in v2) ---
    mdb1_amp_wide = _build_amp_wide(mdb1_amp)

    # --- Detection pipeline (v2 order) ---
    # 1. Coherence change detection
    out_detections = TillageProcessor.detect_event_coh(
        mdb1_cohe_vv, "coh_vv", "NewID", config.coh_thr, groupby=["orb_nr"]
    )
    # 2. Filter to period of interest (no exclude_periods in v2)
    out_filt_poi = TillageProcessor.filter_periods(out_detections, config.poi)
    # 3. Suppress detections followed by NDVI recovery
    out_filt_ndvi = TillageProcessor.filter_detections_by_ndvi(
        out_filt_poi, mdb1_s2, ndvi_thr=config.ndvi_thr,
        s2_window_days=config.s2_window_days,
    )
    # 4. Suppress detections followed by high CR (new in v2)
    out_filt_ndvi_cr = TillageProcessor.filter_detections_by_cr(
        out_filt_ndvi, mdb1_amp_wide,
        cr_thr=config.cr_thr, s1_window_days=config.s1_window_days,
    )
    # 5. Flag ploughing using VV and VH thresholds (replaces identify_tillage)
    out_ploughing = TillageProcessor.flag_ploughing(
        out_filt_ndvi_cr, mdb1_amp_wide,
        threshold_vv_dB=config.amp_db_thr_vv,
        threshold_vh_dB=config.amp_db_thr_vh,
    )
    # 6. Summarise
    tillage_results = TillageProcessor.summarize_detections(out_ploughing)

    # --- Accumulate results in a list (avoids O(n²) pd.concat in a loop) ---
    tillage_results_all.append(tillage_results)
    return tillage_results_all


def handle_ipc_file(config, input_file):
    # Use a list for accumulation; concat once at the end
    tillage_results_list = []

    reader = ipc.open_file(input_file)
    column_names = reader.schema.names
    print("Having a number of {} columns ...".format(len(column_names)))
    cols_var = [col for col in column_names if re.match(r"^[0-9]", col)]
    all_column_names = ["NewID"] + cols_var

    for i in range(reader.num_record_batches):
        time1 = time.time()
        b = reader.get_batch(i)
        schema = b.schema

        columns_to_select = []
        for name in all_column_names:
            idx = schema.get_field_index(name)
            if idx == -1:
                print(f"Column {name} not found")
                continue
            columns_to_select.append(b.column(idx))

        rb = b.from_arrays(columns_to_select, all_column_names)
        batch_pd = rb.to_pandas()

        tillage_results_list = handle_batch_record(config, cols_var, batch_pd, tillage_results_list)

        time2 = time.time()
        print("Execution for batch {}/{} took: {} s".format(i + 1, reader.num_record_batches, time2 - time1))

    # Single concat at the end — O(n) instead of O(n²)
    return pd.concat(tillage_results_list) if tillage_results_list else pd.DataFrame()

def handle_csv_file(config, input_file):

    tillage_results_list = []
    # Read only the header first
    header = pd.read_csv(input_file, nrows=0).columns.tolist()
    cols_var = [col for col in header if re.match(r"^[0-9]", col)]
    all_column_names = ["NewID"] + cols_var

    print("Having a number of {} selected columns ...".format(len(all_column_names)))

    chunk_size = 1000

    # Read CSV in chunks
    reader = pd.read_csv(input_file, usecols=all_column_names, chunksize=chunk_size)
    for i, batch_pd in enumerate(reader):
        time1 = time.time()
        tillage_results_list = handle_batch_record(config, cols_var, batch_pd, tillage_results_list)
        time2 = time.time()
        print("Execution for batch {} took: {} s".format(i + 1, time2 - time1))

    return pd.concat(tillage_results_list) if tillage_results_list else pd.DataFrame()

def handle_file(config, input, output):
    lcinput = input.lower()
    if lcinput.endswith('.ipc'):
        print("Handling ipc file {}".format(input))
        tillage_results = handle_ipc_file(config, input)
    elif lcinput.endswith('.csv'):
        print("Handling csv file {}".format(input))
        tillage_results = handle_csv_file(config, input)
    else:
        print("Invalid file type received as input (unknown extension for {})".format(input))
        import sys; sys.exit(1)

    tillage_results = tillage_results.reset_index()
    tillage_results = tillage_results[
        ["NewID", "date", "consecutive_true", "frac_ploughing_VV", "frac_ploughing_VH"]
    ]
    tillage_results.to_csv(output, index=False)


def main():
    parser = argparse.ArgumentParser(
        description="Extracts radar input data for the S4C L4B processor"
    )
    parser.add_argument("-c", "--config-file",
                        default="/mnt/tao/cfg/sen4cap/sen2agri.conf")
    parser.add_argument("--coh-thr", type=float, default=0.2)
    parser.add_argument("--s2-window-days", type=int, default=10)
    parser.add_argument("--amp-db-thr-vv", type=float, default=-4,
                        help="VV amplitude threshold in dB for ploughing flag")
    parser.add_argument("--amp-db-thr-vh", type=float, default=-10,
                        help="VH amplitude threshold in dB for ploughing flag")
    parser.add_argument("--cr-thr", type=float, default=0.5,
                        help="Cross-Ratio threshold for CR-based false positive filter")
    parser.add_argument("--s1-window-days", type=int, default=7,
                        help="Days after detection to search for S1 CR observations")
    parser.add_argument("--start-date", required=True)
    parser.add_argument("--end-date", required=True)
    parser.add_argument(
        "--orb-nrs",
        type=int,
        nargs="*",
        default=None,
        metavar="ORB_NR",
        help="Orbit numbers to include (e.g. --orb-nrs 161 37 88 110). "
             "Pass --orb-nrs with no values to include all orbits.",
    )
    parser.add_argument("--mdb1-filename")
    parser.add_argument("--output")

    args = parser.parse_args()
    config = Config(args)

    handle_file(config, args.mdb1_filename, args.output)


if __name__ == "__main__":
    main()
