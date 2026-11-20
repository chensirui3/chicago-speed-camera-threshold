"""Step 1: download raw data from the City of Chicago open data portal.

Files are cached in data/raw/ and skipped if present; pass --refresh to re-download.
A manifest records when each file was pulled, because the portal's crash records are
amended over time and re-downloads can shift results slightly.
"""
import argparse
import io
import json
import time
from datetime import datetime, timezone

import pandas as pd
import requests

from config import CRASH_END, CRASH_START, DATASETS, RAW, SOCRATA

PAGE = 100_000
CRASH_COLUMNS = [
    "crash_record_id", "crash_date", "latitude", "longitude", "posted_speed_limit",
    "first_crash_type", "trafficway_type", "crash_type", "most_severe_injury",
    "injuries_total", "injuries_fatal", "injuries_incapacitating",
    "injuries_non_incapacitating", "prim_contributory_cause", "sec_contributory_cause",
    "crash_hour", "crash_day_of_week", "report_type", "street_name",
]


def fetch_csv(dataset: str, params: dict, retries: int = 5) -> pd.DataFrame:
    url = f"{SOCRATA}/{dataset}.csv"
    for attempt in range(retries):
        try:
            r = requests.get(url, params=params, timeout=300)
            r.raise_for_status()
            return pd.read_csv(io.StringIO(r.text), low_memory=False)
        except (requests.RequestException, pd.errors.ParserError) as err:
            wait = 2 ** attempt * 5
            print(f"  retry {attempt + 1}/{retries} in {wait}s ({err})")
            time.sleep(wait)
    raise RuntimeError(f"failed to fetch {dataset} with {params}")


def fetch_paged(dataset: str, params: dict, order: str) -> pd.DataFrame:
    pages, offset = [], 0
    while True:
        page = fetch_csv(dataset, {**params, "$order": order, "$limit": PAGE, "$offset": offset})
        pages.append(page)
        print(f"  {dataset}: {offset + len(page):,} rows")
        if len(page) < PAGE:
            return pd.concat(pages, ignore_index=True)
        offset += PAGE


def main(refresh: bool) -> None:
    RAW.mkdir(parents=True, exist_ok=True)
    manifest_path = RAW / "MANIFEST.json"
    manifest = json.loads(manifest_path.read_text()) if manifest_path.exists() else {}

    jobs = {
        "speed_cameras": lambda: fetch_csv(
            DATASETS["speed_cameras"],
            {"$select": "location_id,address,first_approach,second_approach,"
                        "go_live_date,latitude,longitude", "$limit": 10_000}),
        "redlight_cameras": lambda: fetch_csv(
            DATASETS["redlight_cameras"],
            {"$select": "intersection,first_approach,second_approach,third_approach,"
                        "go_live_date,latitude,longitude", "$limit": 10_000}),
        # Every camera that ever logged a violation, with its location and active dates.
        # This is the only record of cameras since retired from the locations list.
        "violation_cameras": lambda: fetch_csv(
            DATASETS["speed_violations"],
            {"$select": "camera_id,address,avg(latitude) as latitude,"
                        "avg(longitude) as longitude,min(violation_date) as first_day,"
                        "max(violation_date) as last_day,count(*) as days",
             "$group": "camera_id,address", "$limit": 10_000}),
        "speed_violations": lambda: fetch_paged(
            DATASETS["speed_violations"],
            {"$select": "camera_id,address,violation_date,violations"},
            order="violation_date,camera_id"),
        "crashes": lambda: fetch_paged(
            DATASETS["crashes"],
            {"$select": ",".join(CRASH_COLUMNS),
             "$where": f"crash_date >= '{CRASH_START}T00:00:00' "
                       f"AND crash_date < '{CRASH_END}T00:00:00'"},
            order="crash_record_id"),
    }

    for name, job in jobs.items():
        out = RAW / f"{name}.parquet"
        if out.exists() and not refresh:
            print(f"{name}: cached ({out.name})")
            continue
        print(f"{name}: downloading")
        df = job()
        df.to_parquet(out, index=False)
        source = DATASETS.get(name, DATASETS["speed_violations"])
        manifest[name] = {
            "dataset_id": source,
            "url": f"https://data.cityofchicago.org/d/{source}",
            "rows": len(df),
            "downloaded_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        }
        manifest_path.write_text(json.dumps(manifest, indent=2))
        print(f"{name}: {len(df):,} rows -> {out.name}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--refresh", action="store_true", help="re-download cached files")
    main(parser.parse_args().refresh)
