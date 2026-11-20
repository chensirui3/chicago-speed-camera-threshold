"""Study parameters.

Every analytic choice lives here so it can be read, questioned, and changed in one place.
"""
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw"
PROCESSED = ROOT / "data" / "processed"
FIGURES = ROOT / "output" / "figures"
TABLES = ROOT / "output" / "tables"

# --- Sources: City of Chicago open data portal (Socrata) -------------------------------
SOCRATA = "https://data.cityofchicago.org/resource"
DATASETS = {
    "crashes": "85ca-t3if",           # Traffic Crashes - Crashes
    "speed_cameras": "4i42-qv3h",     # Speed Camera Locations
    "speed_violations": "hhkd-xvj4",  # Speed Camera Violations (daily count per camera)
    "redlight_cameras": "thvf-6diy",  # Red Light Camera Locations
}

# Crash reporting is citywide from Sept 2017, so the panel starts in Jan 2018.
CRASH_START = "2018-01-01"
CRASH_END = "2026-01-01"  # exclusive

# --- Policy timeline -------------------------------------------------------------------
# Before 2021 cameras only ticketed drivers roughly 10+ mph over the limit (news reports
# differ on 10 vs. 11). Warning notices for 6+ mph over began Jan 15, 2021; $35 tickets
# began Mar 1, 2021, with a one-time warning still mailed to first-time violators.
WARNINGS_START = pd.Timestamp("2021-01-15")
TICKETS_START = pd.Timestamp("2021-03-01")
TRANSITION_MONTHS = ["2021-01", "2021-02"]  # warning period: dropped from pooled DiD

# --- Geography -------------------------------------------------------------------------
SITE_LINK_M = 150         # cameras closer than this form one site (e.g. both directions)
RADIUS_M = 201            # 1/8 mile: the buffer CDOT uses in its own camera evaluations
ROBUST_RADII_M = [100, 300]
MIN_CONTROL_DIST_M = 500  # comparison sites must be this far from any camera live in-window

# --- Groups ----------------------------------------------------------------------------
TREATED_LIVE_BY = pd.Timestamp("2018-01-31")    # cameras already operating when panel starts
CONTROL_LIVE_FROM = pd.Timestamp("2023-01-01")  # "future camera" sites: no camera until 2023+
ANTICIPATION_MONTHS = 1  # drop site-months this close to a camera change within the buffer

# Park-zone cameras run every day; school-zone cameras only on school days. A camera whose
# violations almost never fall on a weekend is a school-zone camera.
SCHOOL_WEEKEND_SHARE = 0.05
# School-zone cameras went dark during remote learning (spring 2020 - spring 2021), the
# same moment the threshold changed, so the main analysis uses park-zone cameras that ran
# continuously: violations logged in every month of the main window, give or take this many.
CONTINUITY_TOLERANCE = 2
# School-zone analysis skips the closure and phased-reopening period entirely.
SCHOOL_DISRUPTION = ("2020-03", "2021-08")

# --- Windows ---------------------------------------------------------------------------
MAIN_WINDOW = ("2018-01", "2022-12")      # every comparison site is camera-free throughout
EXTENDED_WINDOW = ("2018-01", "2024-12")  # comparison sites drop out as their cameras go live
REFERENCE_QUARTER = "2020Q4"  # omitted event-study quarter; plots re-center on the pre mean

# --- Extra checks ----------------------------------------------------------------------
# Dose-response: how hard the new threshold bit at a site, measured as the jump in its
# monthly violations from 2019 to the first three months of $35 tickets (before drivers
# had much time to adapt).
DOSE_BEFORE = ("2019-01", "2019-12")
DOSE_AFTER = ("2021-03", "2021-05")
# Permutation test: reshuffle which sites count as treated this many times.
PERMUTATIONS = 1000
PERMUTATION_SEED = 20210301

# Crash causes treated as "speed-related" (primary or secondary cause)
SPEED_CAUSES = {
    "EXCEEDING AUTHORIZED SPEED LIMIT",
    "EXCEEDING SAFE SPEED FOR CONDITIONS",
}
