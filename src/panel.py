"""Step 3: count crashes near each site by month, and tally camera violations by month.

Each crash is assigned to its nearest camera (so overlapping buffers never double count),
then counted for that camera's site if it falls within the radius. Counts are kept for
several radii so robustness checks don't need a rebuild.
"""
import numpy as np
import pandas as pd
from scipy.spatial import cKDTree

from config import (CRASH_END, CRASH_START, PROCESSED, RADIUS_M, RAW, ROBUST_RADII_M,
                    SPEED_CAUSES)
from geo import to_meters

RADII = sorted({RADIUS_M, *ROBUST_RADII_M})
OUTCOMES = ["crashes", "injury", "ksi", "speed"]
# Generous box around Chicago; drops records geocoded to (0, 0) or outside the city.
LAT, LON = (41.60, 42.05), (-87.95, -87.50)


def load_crashes() -> pd.DataFrame:
    df = pd.read_parquet(RAW / "crashes.parquet")
    df["crash_date"] = pd.to_datetime(df["crash_date"])
    located = df["latitude"].between(*LAT) & df["longitude"].between(*LON)
    print(f"crashes: {len(df):,} total, {(~located).sum():,} without usable coordinates dropped")
    df = df[located].copy()

    xy = to_meters(df["longitude"], df["latitude"])
    df["x"], df["y"] = xy[:, 0], xy[:, 1]
    df["month"] = df["crash_date"].dt.to_period("M")
    df["crashes"] = 1
    df["injury"] = (df["injuries_total"].fillna(0) > 0).astype(int)
    df["ksi"] = ((df["injuries_fatal"].fillna(0) > 0)
                 | (df["injuries_incapacitating"].fillna(0) > 0)).astype(int)
    causes = df[["prim_contributory_cause", "sec_contributory_cause"]]
    df["speed"] = causes.isin(SPEED_CAUSES).any(axis=1).astype(int)
    return df


def nearest_site(crashes: pd.DataFrame, cams: pd.DataFrame) -> pd.DataFrame:
    """Attach each crash to its nearest camera's site, keeping those within the max radius."""
    tree = cKDTree(cams[["x", "y"]].to_numpy())
    dist, idx = tree.query(crashes[["x", "y"]].to_numpy(), distance_upper_bound=max(RADII))
    hit = np.isfinite(dist)
    out = crashes.loc[hit, ["month", *OUTCOMES]].copy()
    out["site_id"] = cams["site_id"].to_numpy()[idx[hit]]
    out["dist_m"] = dist[hit]
    return out


def count(assigned: pd.DataFrame) -> pd.DataFrame:
    parts = []
    for r in RADII:
        c = (assigned[assigned["dist_m"] <= r].groupby(["site_id", "month"])[OUTCOMES].sum()
             .add_suffix(f"_r{r}"))
        parts.append(c)
    return pd.concat(parts, axis=1)


def violations_monthly(cams: pd.DataFrame) -> pd.DataFrame:
    v = pd.read_parquet(RAW / "speed_violations.parquet")
    no_id = v["camera_id"].isna()
    if no_id.any():
        print(f"violations: {no_id.sum():,} rows without a camera ID dropped "
              f"({v.loc[no_id, 'violations'].sum():,.0f} violations)")
        v = v[~no_id].copy()
    v["month"] = pd.to_datetime(v["violation_date"]).dt.to_period("M")
    site_of = cams[cams["kind"] == "speed"].set_index("camera_id")["site_id"]
    v["site_id"] = v["camera_id"].map(site_of)
    missing = v.loc[v["site_id"].isna(), "camera_id"].unique()
    if len(missing):
        print(f"violations: {len(missing)} camera IDs not in the locations file "
              f"(retired cameras?): {', '.join(sorted(missing)[:10])}")
    monthly = (v.groupby(["camera_id", "site_id", "month"], dropna=False)
                .agg(violations=("violations", "sum"), days_reported=("violations", "size"))
                .reset_index())
    monthly["month"] = monthly["month"].astype(str)
    return monthly


def main() -> None:
    sites = pd.read_csv(PROCESSED / "sites.csv")
    cams = pd.read_csv(PROCESSED / "cameras.csv")
    crashes = load_crashes()

    # Speed sites: nearest among *all* speed cameras, so excluded sites still claim
    # their own crashes. Red-light sites: only the retained intersections.
    speed = nearest_site(crashes, cams[cams["kind"] == "speed"])
    keep_rl = sites.loc[(sites["kind"] == "redlight") & (sites["group"] == "redlight"), "site_id"]
    redlight = nearest_site(crashes, cams[cams["site_id"].isin(keep_rl)])
    counts = pd.concat([count(speed), count(redlight)])

    months = pd.period_range(CRASH_START, pd.Timestamp(CRASH_END) - pd.Timedelta(days=1), freq="M")
    grid = pd.MultiIndex.from_product([sites["site_id"], months], names=["site_id", "month"])
    # Zero-fill both missing site-months and radii with no crashes in an otherwise busy month.
    panel = counts.reindex(grid).fillna(0).astype(int).reset_index()
    panel = panel.merge(sites[["site_id", "kind", "group"]], on="site_id")
    panel["month"] = panel["month"].astype(str)
    panel.to_parquet(PROCESSED / "panel.parquet", index=False)

    vio = violations_monthly(cams)
    vio.to_csv(PROCESSED / "violations_monthly.csv", index=False)

    main_r = f"crashes_r{RADIUS_M}"
    by_group = panel.groupby("group")[main_r].sum()
    print(f"panel: {panel['site_id'].nunique()} sites x {len(months)} months; "
          f"crashes within {RADIUS_M} m by group: {by_group.to_dict()}")
    print(f"violations: {len(vio):,} camera-months")


if __name__ == "__main__":
    main()
