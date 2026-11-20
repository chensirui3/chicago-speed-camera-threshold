"""Step 4: difference-in-differences and event-study estimates.

Model: Poisson regression of monthly crash counts on site fixed effects, month fixed
effects, and treated x post. Site effects absorb permanent differences between places
(traffic volume, road design); month effects absorb citywide shocks (COVID, weather,
reporting changes). The treated x post coefficient is the change at camera sites relative
to comparison sites, read as a percent change: 100 * (exp(b) - 1). Standard errors are
clustered by site.
"""
import json
from dataclasses import asdict, dataclass, replace

import numpy as np
import pandas as pd
import statsmodels.api as sm
import statsmodels.formula.api as smf

from config import (ANTICIPATION_MONTHS, EXTENDED_WINDOW, MAIN_WINDOW, PROCESSED, RADIUS_M,
                    REFERENCE_QUARTER, SCHOOL_DISRUPTION, TABLES, TICKETS_START,
                    TRANSITION_MONTHS)

POLICY = str(pd.Period(TICKETS_START, "M"))


def months(start: str, end: str) -> tuple:
    return tuple(str(m) for m in pd.period_range(start, end, freq="M"))


COVID = months("2020-03", "2020-12")
ALL_PRE2018 = ("treated", "treated_school", "treated_other")


@dataclass(frozen=True)
class Spec:
    name: str
    outcome: str = "crashes"
    radius: int = RADIUS_M
    treated_groups: tuple = ("treated",)  # park-zone sites with continuously running cameras
    comparison: str = "control"           # "control" (future camera sites) or "redlight"
    comparison_zones: tuple = ()          # restrict comparison sites by zone type
    window: tuple = MAIN_WINDOW
    policy: str = POLICY                  # first treated month
    drop: tuple = ()                      # extra months to drop
    min_dist: float = 0                   # comparison sites this far from in-window cameras
    drop_transition: bool = True          # drop the Jan-Feb 2021 warning period
    block: str = "Main"

    @property
    def column(self) -> str:
        return f"{self.outcome}_r{self.radius}"


SPECS = [
    Spec("All crashes (main)"),
    Spec("Injury crashes", outcome="injury"),
    Spec("Fatal or serious-injury crashes", outcome="ksi"),
    Spec("Crashes coded as speeding", outcome="speed"),
    Spec("Radius 100 m", radius=100, block="Design"),
    Spec("Radius 300 m", radius=300, block="Design"),
    Spec("Drop COVID months (Mar-Dec 2020)", drop=COVID, block="Design"),
    Spec("Park-zone comparison sites only", comparison_zones=("park",), block="Design"),
    Spec("Comparison sites 1 km+ from cameras", min_dist=1000, block="Design"),
    Spec("Longer window, through 2024", window=EXTENDED_WINDOW, block="Design"),
    Spec("Red-light intersections as comparison", comparison="redlight", block="Design"),
    Spec("All pre-2018 sites, school zones included", treated_groups=ALL_PRE2018,
         block="Design"),
    Spec("Injury crashes, drop COVID months", outcome="injury", drop=COVID,
         block="Injury crashes"),
    Spec("Injury crashes, park-zone comparison only", outcome="injury",
         comparison_zones=("park",), block="Injury crashes"),
    Spec("Injury crashes, red-light comparison", outcome="injury", comparison="redlight",
         block="Injury crashes"),
    Spec("Injury crashes, through 2024", outcome="injury", window=EXTENDED_WINDOW,
         block="Injury crashes"),
    Spec("School-zone sites vs. school-zone comparison", treated_groups=("treated_school",),
         comparison_zones=("school",), drop=months(*SCHOOL_DISRUPTION), block="School zones"),
    Spec("School zones, injury crashes", outcome="injury", treated_groups=("treated_school",),
         comparison_zones=("school",), drop=months(*SCHOOL_DISRUPTION), block="School zones"),
    Spec("Placebo: pretend change in Mar 2019", window=("2018-01", "2020-02"),
         policy="2019-03", block="Placebo"),
    Spec("Placebo, injury crashes", outcome="injury", window=("2018-01", "2020-02"),
         policy="2019-03", block="Placebo"),
]


def load_panel() -> pd.DataFrame:
    panel = pd.read_parquet(PROCESSED / "panel.parquet")
    sites = pd.read_csv(PROCESSED / "sites.csv", parse_dates=["censor_date"])
    panel = panel.merge(sites[["site_id", "zone", "censor_date", "dist_window_camera_m"]],
                        on="site_id")
    panel["month"] = pd.PeriodIndex(panel["month"], freq="M")
    return panel


def sample(panel: pd.DataFrame, spec: Spec) -> pd.DataFrame:
    start, end = (pd.Period(m, "M") for m in spec.window)
    is_treated = panel["group"].isin(spec.treated_groups)
    is_comparison = panel["group"] == spec.comparison
    if spec.comparison_zones:
        is_comparison &= panel["zone"].isin(spec.comparison_zones)
    if spec.min_dist:
        is_comparison &= panel["dist_window_camera_m"] >= spec.min_dist
    df = panel[(is_treated | is_comparison)
               & (panel["month"] >= start) & (panel["month"] <= end)]

    # A site leaves the sample shortly before a new camera starts operating within
    # MIN_CONTROL_DIST_M of it (its own, for comparison sites).
    censor = df["censor_date"].dt.to_period("M") - ANTICIPATION_MONTHS
    df = df[censor.isna() | (df["month"] < censor)]

    months = df["month"].astype(str)
    drop = set(spec.drop) | (set(TRANSITION_MONTHS) if spec.drop_transition else set())
    df = df[~months.isin(drop)].copy()

    df["treated"] = df["group"].isin(spec.treated_groups).astype(int)
    df["post"] = (df["month"] >= pd.Period(spec.policy, "M")).astype(int)
    df["treat_post"] = df["treated"] * df["post"]
    df["y"] = df[spec.column]
    df["month_fe"] = df["month"].astype(str)
    # Sites with zero events carry no information in a Poisson fixed-effects model.
    return df[df.groupby("site_id")["y"].transform("sum") > 0]


def fit(df: pd.DataFrame, rhs: str):
    model = smf.glm(f"y ~ {rhs} + C(site_id) + C(month_fe)", data=df,
                    family=sm.families.Poisson())
    return model.fit(cov_type="cluster", cov_kwds={"groups": pd.factorize(df["site_id"])[0]})


def pct(b: float) -> float:
    return 100 * np.expm1(b)


def did(panel: pd.DataFrame, spec: Spec) -> dict:
    df = sample(panel, spec)
    res = fit(df, "treat_post")
    b, se = res.params["treat_post"], res.bse["treat_post"]
    return {
        "block": spec.block,
        "spec": spec.name,
        "pct_change": pct(b),
        "ci_low": pct(b - 1.96 * se),
        "ci_high": pct(b + 1.96 * se),
        "p_value": res.pvalues["treat_post"],
        "coef": b,
        "se": se,
        "treated_sites": df.loc[df["treated"] == 1, "site_id"].nunique(),
        "comparison_sites": df.loc[df["treated"] == 0, "site_id"].nunique(),
        "site_months": len(df),
        "events": int(df["y"].sum()),
        "outcome": spec.column,
        "comparison": spec.comparison,
    }


def event_study(panel: pd.DataFrame, spec: Spec) -> tuple[pd.DataFrame, float]:
    """Quarter-by-quarter treated/comparison gap, relative to the average pre-period gap.

    The model omits REFERENCE_QUARTER for identification. Because any single quarter is
    noisy (and 2020 quarters are COVID-distorted), estimates are then re-expressed relative
    to the mean of all pre-warning quarters, the same baseline the pooled DiD uses.
    """
    df = sample(panel, replace(spec, drop_transition=False))
    quarter = df["month"].dt.asfreq("Q")
    quarters = sorted(quarter.unique())
    first_policy_q = pd.Period(spec.policy, "M").asfreq("Q")
    pre = [str(q) for q in quarters if q < first_policy_q]  # includes the reference quarter
    # Specs that drop months (e.g. school closures) may not contain the default reference.
    ref = REFERENCE_QUARTER if REFERENCE_QUARTER in pre else pre[-1]
    terms = {}
    for q in quarters:
        if str(q) != ref:
            terms[str(q)] = f"ev_{q}"
            df[terms[str(q)]] = ((quarter == q) & (df["treated"] == 1)).astype(int)
    res = fit(df, " + ".join(terms.values()))
    params, cov = res.params, res.cov_params()
    rows = []
    for q in map(str, quarters):
        a = pd.Series(0.0, index=params.index)  # contrast: gap(q) - mean pre-period gap
        if q in terms:
            a[terms[q]] += 1
        for p in pre:
            if p in terms:
                a[terms[p]] -= 1 / len(pre)
        rows.append({"quarter": q, "coef": float(a @ params),
                     "se": float(np.sqrt(a @ cov @ a)), "pre": q in pre})
    out = pd.DataFrame(rows)
    out["pct"] = pct(out["coef"])
    out["ci_low"] = pct(out["coef"] - 1.96 * out["se"])
    out["ci_high"] = pct(out["coef"] + 1.96 * out["se"])

    # Joint test that all pre-warning quarters share the same gap (no pre-trend).
    pre_terms = [terms[p] for p in pre if p in terms]
    R = np.zeros((len(pre_terms), len(params)))
    for i, t in enumerate(pre_terms):
        R[i, params.index.get_loc(t)] = 1
    p_pre = float(res.wald_test(R, scalar=True).pvalue)
    return out, p_pre


def two_by_two(panel: pd.DataFrame, spec: Spec) -> pd.DataFrame:
    """Average monthly crashes per site, before vs. after, by group (no model)."""
    df = sample(panel, spec)
    df["arm"] = np.where(df["treated"] == 1, "treated", "comparison")
    t = (df.groupby(["arm", "post"])["y"].mean().unstack()
           .rename(columns={0: "before", 1: "after"}))
    t["change_pct"] = 100 * (t["after"] / t["before"] - 1)
    return t


def main() -> None:
    TABLES.mkdir(parents=True, exist_ok=True)
    panel = load_panel()

    results = pd.DataFrame([did(panel, s) for s in SPECS])
    results.to_csv(TABLES / "did_results.csv", index=False)

    main_spec = SPECS[0]
    named = {s.name: s for s in SPECS}
    pretrend = {}
    for name, spec in {
        "main": main_spec,
        "injury": named["Injury crashes"],
        "redlight": named["Red-light intersections as comparison"],
        "redlight_injury": named["Injury crashes, red-light comparison"],
        "all_pre2018": named["All pre-2018 sites, school zones included"],
        "school": named["School-zone sites vs. school-zone comparison"],
    }.items():
        es, pretrend[name] = event_study(panel, spec)
        es.to_csv(TABLES / f"event_study_{name}.csv", index=False)

    raw = two_by_two(panel, main_spec)
    raw.to_csv(TABLES / "raw_two_by_two.csv")
    raw_did = 100 * ((1 + raw.loc["treated", "change_pct"] / 100)
                     / (1 + raw.loc["comparison", "change_pct"] / 100) - 1)

    summary = {
        "main": results.iloc[0].to_dict(),
        "pretrend_p_values": pretrend,
        "raw_two_by_two": raw.reset_index().to_dict(orient="records"),
        "raw_ratio_of_ratios_pct": raw_did,
        "main_spec": {k: (list(v) if isinstance(v, tuple) else v)
                      for k, v in asdict(main_spec).items()},
    }
    (TABLES / "summary.json").write_text(json.dumps(summary, indent=2, default=float))

    with pd.option_context("display.width", 200, "display.max_columns", 20):
        print(results[["spec", "pct_change", "ci_low", "ci_high", "p_value",
                       "treated_sites", "comparison_sites", "events"]].round(3).to_string())
        print("\nPre-trend joint test p-values: "
              + ", ".join(f"{k} {v:.3f}" for k, v in pretrend.items()))
        print("\nRaw averages (crashes per site-month):\n" + raw.round(2).to_string())
        print(f"Raw ratio-of-ratios: {raw_did:.1f}%")


if __name__ == "__main__":
    main()
