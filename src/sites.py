"""Step 2: build the camera universe, group cameras into sites, and assign study groups.

Camera universe
  The locations file lists current cameras only. Cameras retired since 2018 survive only in
  the violations data, so they are added from there; otherwise a "future camera" site
  could sit right next to a camera that operated throughout the study window.

Groups
  treated         park-zone sites whose cameras ran continuously from before 2018: the
                  threshold change was the only enforcement change they saw in 2018-2022.
  treated_school  school-zone sites. These cameras went dark during remote learning and
                  came back in early 2021, so they are analyzed separately.
  treated_other   other pre-2018 sites (park cameras with gaps, mixed zones).
  control         "future camera" sites: the city chose them for cameras that went live in
                  2023 or later, and no camera operated within MIN_CONTROL_DIST_M of them
                  during the main window.
  redlight        red-light-camera intersections (an alternative comparison group).
  excluded        everything else, with the reason recorded.
"""
import numpy as np
import pandas as pd
from scipy.spatial import cKDTree

from config import (CONTINUITY_TOLERANCE, CONTROL_LIVE_FROM, MAIN_WINDOW, MIN_CONTROL_DIST_M,
                    PROCESSED, RAW, SCHOOL_WEEKEND_SHARE, SITE_LINK_M, TICKETS_START,
                    TREATED_LIVE_BY)
from geo import single_linkage, to_meters

WIN_START = pd.Period(MAIN_WINDOW[0], "M").start_time
WIN_END = pd.Period(MAIN_WINDOW[1], "M").end_time


def camera_universe() -> pd.DataFrame:
    listed = pd.read_parquet(RAW / "speed_cameras.parquet").rename(
        columns={"location_id": "camera_id"})
    listed["start"] = pd.to_datetime(listed["go_live_date"])
    listed["end"] = pd.NaT
    listed["source"] = "locations file"

    seen = pd.read_parquet(RAW / "violation_cameras.parquet").dropna(subset=["camera_id"])
    seen = (seen.sort_values("days", ascending=False).groupby("camera_id")
                .agg(address=("address", "first"), latitude=("latitude", "mean"),
                     longitude=("longitude", "mean"), first_day=("first_day", "min"),
                     last_day=("last_day", "max"))
                .reset_index())
    retired = seen[~seen["camera_id"].isin(listed["camera_id"])].copy()
    retired["start"] = pd.to_datetime(retired["first_day"])
    retired["end"] = pd.to_datetime(retired["last_day"])
    retired["source"] = "violations only (retired)"

    cols = ["camera_id", "address", "latitude", "longitude", "start", "end", "source"]
    cams = pd.concat([listed[cols], retired[cols]], ignore_index=True)
    cams = cams.dropna(subset=["latitude", "longitude"]).reset_index(drop=True)
    xy = to_meters(cams["longitude"], cams["latitude"])
    cams["x"], cams["y"] = xy[:, 0], xy[:, 1]
    return cams.merge(camera_behavior(), on="camera_id", how="left")


def camera_behavior() -> pd.DataFrame:
    """Zone type (from weekend activity) and months active during the main window."""
    v = pd.read_parquet(RAW / "speed_violations.parquet").dropna(subset=["camera_id"])
    day = pd.to_datetime(v["violation_date"])
    v = pd.DataFrame({"camera_id": v["camera_id"], "weekend": day.dt.day_of_week >= 5,
                      "month": day.dt.to_period("M")})
    out = v.groupby("camera_id").agg(violation_days=("weekend", "size"),
                                     weekend_share=("weekend", "mean"))
    out["zone"] = np.where(out["violation_days"] < 30, "unknown",
                           np.where(out["weekend_share"] < SCHOOL_WEEKEND_SHARE,
                                    "school", "park"))
    in_win = v[(v["month"] >= pd.Period(MAIN_WINDOW[0], "M"))
               & (v["month"] <= pd.Period(MAIN_WINDOW[1], "M"))]
    out["active_months"] = in_win.groupby("camera_id")["month"].nunique()
    out["active_months"] = out["active_months"].fillna(0).astype(int)
    return out.reset_index()


def active_in_window(c: pd.DataFrame) -> pd.Series:
    return (c["start"] <= WIN_END) & (c["end"].isna() | (c["end"] >= WIN_START))


def neighbors(own: pd.DataFrame, pool: pd.DataFrame, radius: float) -> pd.DataFrame:
    """Cameras in pool within radius of any camera at the site, excluding the site's own."""
    pool = pool[~pool["camera_id"].isin(own["camera_id"])]
    if pool.empty:
        return pool
    tree = cKDTree(pool[["x", "y"]].to_numpy())
    idx = sorted({i for pt in own[["x", "y"]].to_numpy()
                  for i in tree.query_ball_point(pt, radius)})
    return pool.iloc[idx]


def nearest(own: pd.DataFrame, pool: pd.DataFrame) -> float:
    pool = pool[~pool["camera_id"].isin(own["camera_id"])]
    if pool.empty:
        return np.inf
    d, _ = cKDTree(pool[["x", "y"]].to_numpy()).query(own[["x", "y"]].to_numpy())
    return float(np.min(d))


def site_table(cams: pd.DataFrame) -> pd.DataFrame:
    cams["site_id"] = single_linkage(cams[["x", "y"]].to_numpy(), SITE_LINK_M)
    sites = cams.groupby("site_id").agg(
        first_camera=("camera_id", "min"),
        n_cameras=("camera_id", "size"),
        cameras=("camera_id", lambda s: " ".join(sorted(s))),
        address=("address", "first"),
        first_live=("start", "min"),
        lat=("latitude", "mean"), lon=("longitude", "mean"),
        x=("x", "mean"), y=("y", "mean"),
    )
    cams["site_id"] = cams["site_id"].map(sites["first_camera"])  # IDs: lowest camera ID
    return sites.set_index("first_camera").rename_axis("site_id").reset_index()


def zone_of(own: pd.DataFrame) -> str:
    zones = set(own["zone"].dropna()) - {"unknown"}
    return zones.pop() if len(zones) == 1 else ("mixed" if zones else "unknown")


def classify_speed(site, own: pd.DataFrame, cams: pd.DataFrame) -> dict:
    in_window = cams[active_in_window(cams)]
    near = neighbors(own, cams, MIN_CONTROL_DIST_M)
    row = {"zone": zone_of(own), "dist_window_camera_m": round(nearest(own, in_window)),
           "censor_date": pd.NaT, "exclusion": "", "min_active_months": np.nan}

    if site.first_live <= TREATED_LIVE_BY:
        original = own[own["start"] <= TREATED_LIVE_BY]
        row["zone"] = zone_of(original)  # a camera added later doesn't change the site type
        # First change in camera presence within the buffer zone after the panel starts:
        # an own camera retiring or being added, or a neighbor starting or stopping.
        events = pd.concat([
            own["end"], own.loc[own["start"] > TREATED_LIVE_BY, "start"],
            near.loc[near["start"] > TREATED_LIVE_BY, "start"],
            near.loc[near["end"] >= WIN_START, "end"],
        ]).dropna()
        censor = events.min() if len(events) else pd.NaT
        row["censor_date"] = censor
        # Continuity is judged over the months the site is actually in the panel.
        horizon = min(censor, WIN_END) if pd.notna(censor) else WIN_END
        expected = len(pd.period_range(MAIN_WINDOW[0], pd.Period(horizon, "M"), freq="M"))
        active = original["active_months"].fillna(0)
        row["min_active_months"] = int(active.min())
        continuous = bool((active >= expected - CONTINUITY_TOLERANCE).all())
        if pd.notna(censor) and censor < TICKETS_START:
            row["group"], row["exclusion"] = "excluded", "camera change nearby before Mar 2021"
        elif row["zone"] == "school":
            row["group"] = "treated_school"
        elif row["zone"] == "park" and continuous:
            row["group"] = "treated"
        else:
            row["group"] = "treated_other"
    elif site.first_live >= CONTROL_LIVE_FROM:
        # Leaves the panel when its own camera, or a new neighbor, starts operating.
        events = pd.concat([own["start"], near.loc[near["start"] > WIN_END, "start"]]).dropna()
        row["censor_date"] = events.min()
        if active_in_window(near).any():
            row["group"] = "excluded"
            row["exclusion"] = f"camera within {MIN_CONTROL_DIST_M} m operated in 2018-2022"
        else:
            row["group"] = "control"
    else:
        row["group"], row["exclusion"] = "excluded", "camera installed mid-window"
    return row


def speed_sites() -> tuple[pd.DataFrame, pd.DataFrame]:
    cams = camera_universe()
    sites = site_table(cams)
    rows = [{"site_id": s.site_id, **classify_speed(s, cams[cams["site_id"] == s.site_id], cams)}
            for s in sites.itertuples()]
    sites = sites.merge(pd.DataFrame(rows), on="site_id")
    sites["kind"] = "speed"
    return sites, cams


def redlight_sites(speed_cams: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    cams = pd.read_parquet(RAW / "redlight_cameras.parquet").dropna(subset=["latitude"])
    # No camera ID in the source (approaches share an intersection name): assign RL###.
    cams = cams.rename(columns={"intersection": "address"})
    cams = cams.sort_values(["address", "first_approach", "go_live_date"]).reset_index(drop=True)
    cams["camera_id"] = [f"RL{i:03d}" for i in range(len(cams))]
    cams["start"], cams["end"] = pd.to_datetime(cams["go_live_date"]), pd.NaT
    cams["source"] = "red-light locations file"
    xy = to_meters(cams["longitude"], cams["latitude"])
    cams["x"], cams["y"] = xy[:, 0], xy[:, 1]
    sites = site_table(cams)

    speed_in_window = speed_cams[active_in_window(speed_cams)]
    rows = []
    for s in sites.itertuples():
        own = cams[cams["site_id"] == s.site_id]
        near = neighbors(own, speed_cams, MIN_CONTROL_DIST_M)
        later = near.loc[near["start"] > WIN_END, "start"]
        row = {"site_id": s.site_id, "zone": "intersection", "exclusion": "",
               "dist_window_camera_m": round(nearest(own, speed_in_window)),
               "censor_date": later.min() if len(later) else pd.NaT}
        if s.first_live > TREATED_LIVE_BY:
            row["exclusion"] = "red-light camera installed after Jan 2018"
        elif active_in_window(near).any():
            row["exclusion"] = f"speed camera within {MIN_CONTROL_DIST_M} m in 2018-2022"
        row["group"] = "redlight" if not row["exclusion"] else "excluded"
        rows.append(row)
    sites = sites.merge(pd.DataFrame(rows), on="site_id")
    sites["kind"] = "redlight"
    return sites, cams


def main() -> None:
    PROCESSED.mkdir(parents=True, exist_ok=True)
    s_sites, s_cams = speed_sites()
    r_sites, r_cams = redlight_sites(s_cams)

    sites = pd.concat([s_sites, r_sites], ignore_index=True)
    cols = ["site_id", "kind", "group", "zone", "exclusion", "address", "n_cameras", "cameras",
            "first_live", "censor_date", "min_active_months", "dist_window_camera_m",
            "lat", "lon", "x", "y"]
    sites[cols].to_csv(PROCESSED / "sites.csv", index=False)

    cams = pd.concat([s_cams.assign(kind="speed"), r_cams.assign(kind="redlight")])
    cams[["camera_id", "site_id", "kind", "source", "address", "start", "end", "zone",
          "weekend_share", "active_months", "latitude", "longitude", "x", "y"]].to_csv(
        PROCESSED / "cameras.csv", index=False)

    n_retired = (s_cams["source"] != "locations file").sum()
    print(f"{len(s_cams)} speed cameras ({n_retired} retired, from violation records) -> "
          f"{len(s_sites)} sites; {len(r_cams)} red-light cameras -> {len(r_sites)} intersections")
    print(sites.groupby(["kind", "group"]).size().to_string())
    print("\nControl zones:", sites.loc[sites["group"] == "control", "zone"].value_counts().to_dict())
    excluded = sites[sites["group"] == "excluded"]
    print("\nExclusions:\n" + excluded.groupby(["kind", "exclusion"]).size().to_string())


if __name__ == "__main__":
    main()
