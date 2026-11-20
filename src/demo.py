"""Step 6: export data for the interactive demo page in docs/ (served by GitHub Pages).

The page is static: every model a visitor can pick (outcome x comparison group x radius x
window x COVID months) is fit here in advance, along with per-site series and a
crash-density basemap. No server and no Python in the browser.
"""
import argparse
import itertools
import json
import re

import numpy as np
import pandas as pd
from PIL import Image

from config import EXTENDED_WINDOW, MAIN_WINDOW, PROCESSED, RAW, ROOT, TICKETS_START
from estimate import COVID, Spec, did, event_study, load_panel
from geo import to_meters

DATA = ROOT / "docs" / "data"
OUTCOMES = {"crashes": "All crashes", "injury": "Injury crashes",
            "pedbike": "Pedestrian or cyclist crashes"}
COMPARISONS = {"control": "Future camera sites", "redlight": "Red-light intersections"}
RADII = {"100": 100, "201": 201, "300": 300}
WINDOWS = {"2022": MAIN_WINDOW, "2024": EXTENDED_WINDOW}
COVID_MONTHS = {"keep": (), "drop": COVID}
SERIES_START, SERIES_END = "2018-01", "2025-12"
BEFORE, AFTER = ("2018-01", "2020-12"), ("2021-03", "2022-12")
GROUP_LABELS = {
    "treated": "Park-zone camera running since before 2018 (treated)",
    "treated_school": "School-zone camera (analyzed separately)",
    "treated_other": "Park-zone camera with gaps in operation (not in main analysis)",
    "control": "Future camera site, live 2023 or later (comparison)",
    "redlight": "Red-light-camera intersection (alternative comparison)",
}


def r(x, nd=1):
    return None if x is None or not np.isfinite(x) else round(float(x), nd)


def tidy(address: str) -> str:
    """Retired cameras' addresses come from the violations data in capitals."""
    if address != address.upper():
        return address
    return re.sub(r"(\d)(St|Nd|Rd|Th)\b", lambda m: m.group(1) + m.group(2).lower(),
                  address.title())


def camera_status() -> dict:
    """Per speed site: whether the go-live date is known, and when it was removed.

    Cameras known only from violation records have no recorded go-live date (their first
    record is the start of the data, July 2014) and stop when they were removed.
    """
    cams = pd.read_csv(PROCESSED / "cameras.csv", parse_dates=["start", "end"])
    status = {}
    for site_id, g in cams[cams["kind"] == "speed"].groupby("site_id"):
        live_known = g.loc[g["start"].idxmin(), "source"] == "locations file"
        removed = None
        if (g["source"] != "locations file").all():
            last = g["end"].max()
            if pd.notna(last) and last < pd.Timestamp(f"{SERIES_END}-01"):
                removed = last.strftime("%Y-%m")
        status[site_id] = (live_known, removed)
    return status


def spec_grid(panel: pd.DataFrame) -> dict:
    grid = {}
    combos = list(itertools.product(OUTCOMES, COMPARISONS, RADII, WINDOWS, COVID_MONTHS))
    for i, (o, c, rad, w, cv) in enumerate(combos, 1):
        key = "|".join([o, c, rad, w, cv])
        spec = Spec(key, outcome=o, radius=RADII[rad], comparison=c, window=WINDOWS[w],
                    drop=COVID_MONTHS[cv])
        res = did(panel, spec)
        es, p_pre = event_study(panel, spec)
        grid[key] = {
            "pct": r(res["pct_change"], 2), "lo": r(res["ci_low"], 2), "hi": r(res["ci_high"], 2),
            "p": r(res["p_value"], 4), "pretrend_p": r(p_pre, 4),
            "treated": int(res["treated_sites"]), "comparison": int(res["comparison_sites"]),
            "events": int(res["events"]),
            "es": [[q, r(v), r(lo), r(hi)] for q, v, lo, hi
                   in es[["quarter", "pct", "ci_low", "ci_high"]].itertuples(index=False)],
        }
        print(f"  {i:>2}/{len(combos)} {key:<32} {res['pct_change']:+6.1f}%", flush=True)
    return grid


def basemap() -> dict:
    """Crash density as a gray, alpha-weighted PNG: the street grid, readable on light
    and dark pages alike."""
    c = pd.read_parquet(RAW / "crashes.parquet", columns=["latitude", "longitude"])
    c = c[c["latitude"].between(41.60, 42.05) & c["longitude"].between(-87.95, -87.50)]
    xy = to_meters(c["longitude"], c["latitude"])
    x0, x1 = np.percentile(xy[:, 0], [0.05, 99.95])
    y0, y1 = np.percentile(xy[:, 1], [0.05, 99.95])
    step = 50.0
    density, _, _ = np.histogram2d(xy[:, 0], xy[:, 1],
                                   bins=[np.arange(x0, x1 + step, step),
                                         np.arange(y0, y1 + step, step)])
    level = np.log1p(density) / np.log1p(np.percentile(density[density > 0], 99.5))
    alpha = (np.clip(level, 0, 1) ** 0.8 * 210).astype(np.uint8).T[::-1]  # north up
    rgba = np.zeros((*alpha.shape, 4), dtype=np.uint8)
    rgba[..., :3] = (138, 137, 132)
    rgba[..., 3] = alpha
    Image.fromarray(rgba, "RGBA").save(DATA / "basemap.png", optimize=True)
    return {"x0": x0, "x1": x1, "y0": y0, "y1": y1,
            "width": int(alpha.shape[1]), "height": int(alpha.shape[0])}


def site_data(panel: pd.DataFrame, bounds: dict) -> list:
    sites = pd.read_csv(PROCESSED / "sites.csv", parse_dates=["first_live"])
    sites = sites[(sites["kind"] == "speed") | (sites["group"] == "redlight")]

    p = panel[(panel["month"] >= pd.Period(SERIES_START, "M"))
              & (panel["month"] <= pd.Period(SERIES_END, "M"))].copy()
    p["quarter"] = p["month"].dt.asfreq("Q").astype(str)
    cols = [f"{o}_r201" for o in OUTCOMES]
    quarterly = p.groupby(["site_id", "quarter"])[cols].sum()
    def window_mean(lo, hi):
        w = p[(p["month"] >= pd.Period(lo, "M")) & (p["month"] <= pd.Period(hi, "M"))]
        return w.groupby("site_id")[cols].mean()
    before, after = window_mean(*BEFORE), window_mean(*AFTER)

    vio = pd.read_csv(PROCESSED / "violations_monthly.csv")
    vio = vio.groupby(["site_id", "month"])["violations"].sum().unstack(fill_value=0)
    months = [str(m) for m in pd.period_range(SERIES_START, SERIES_END, freq="M")]
    vio = vio.reindex(columns=months, fill_value=0)

    status = camera_status()
    out = []
    for s in sites.itertuples():
        q = quarterly.loc[s.site_id]
        live_known, removed = status.get(s.site_id, (True, None))
        item = {
            "id": s.site_id, "group": s.group, "zone": s.zone,
            "label": GROUP_LABELS.get(s.group, f"Excluded: {s.exclusion}"),
            "address": tidy(s.address), "cameras": int(s.n_cameras),
            "live": s.first_live.strftime("%Y-%m"), "live_known": bool(live_known),
            "removed": removed,
            "u": r((s.x - bounds["x0"]) / (bounds["x1"] - bounds["x0"]), 4),
            "v": r((bounds["y1"] - s.y) / (bounds["y1"] - bounds["y0"]), 4),
            "q": {o: q[f"{o}_r201"].astype(int).tolist() for o in OUTCOMES},
            "before": {o: r(before.loc[s.site_id, f"{o}_r201"], 2) for o in OUTCOMES},
            "after": {o: r(after.loc[s.site_id, f"{o}_r201"], 2) for o in OUTCOMES},
        }
        if s.kind == "speed" and s.site_id in vio.index:
            first = s.first_live.strftime("%Y-%m")
            last = removed or SERIES_END
            item["violations"] = [int(v) if first <= m <= last else None
                                  for m, v in zip(months, vio.loc[s.site_id])]
        out.append(item)
    return out


def main(reuse_grid: bool = False) -> None:
    DATA.mkdir(parents=True, exist_ok=True)
    panel = load_panel()
    bounds = basemap()
    sites = site_data(panel, bounds)
    print(f"demo: {len(sites)} sites, basemap {bounds['width']}x{bounds['height']}")
    if reuse_grid and (DATA / "demo.json").exists():
        grid = json.loads((DATA / "demo.json").read_text())["grid"]
        print("demo: reusing the 72 precomputed models in demo.json")
    else:
        grid = spec_grid(panel)

    # Open on the busiest treated site whose camera is still operating.
    treated = [s for s in sites if s["group"] == "treated" and s["live_known"] and not s["removed"]]
    default_site = max(treated, key=lambda s: sum(s["q"]["crashes"]))["id"]
    payload = {
        "meta": {
            "policy_month": str(pd.Period(TICKETS_START, "M")),
            "quarters": [str(q) for q in pd.period_range(SERIES_START, SERIES_END, freq="Q")],
            "months_start": SERIES_START, "basemap": bounds, "default_site": default_site,
            "before": list(BEFORE), "after": list(AFTER),
            "default": "crashes|control|201|2022|keep",
        },
        "options": {"outcome": OUTCOMES, "comparison": COMPARISONS,
                    "radius": {k: f"{v} m" for k, v in RADII.items()},
                    "window": {"2022": "2018–2022", "2024": "2018–2024"},
                    "covid": {"keep": "Keep 2020", "drop": "Drop Mar–Dec 2020"}},
        "grid": grid,
        "sites": sites,
    }
    (DATA / "demo.json").write_text(json.dumps(payload, separators=(",", ":")))
    main_est = grid[payload["meta"]["default"]]
    print(f"demo -> {DATA} (default spec {main_est['pct']:+.2f}%, "
          f"{(DATA / 'demo.json').stat().st_size / 1024:.0f} KB json, "
          f"{(DATA / 'basemap.png').stat().st_size / 1024:.0f} KB basemap)")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reuse-grid", action="store_true",
                        help="keep the precomputed models; only rebuild sites and basemap")
    main(parser.parse_known_args()[0].reuse_grid)
