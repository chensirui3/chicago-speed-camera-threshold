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

from config import (ANTICIPATION_MONTHS, DOSE_AFTER, DOSE_BEFORE, EXTENDED_WINDOW,
                    MAIN_WINDOW, PERMUTATION_SEED, PERMUTATIONS, PROCESSED, RADIUS_M,
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
    Spec("Pedestrian or cyclist crashes", outcome="pedbike"),
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
    Spec("Pedestrian or cyclist, drop COVID months", outcome="pedbike", drop=COVID,
         block="Pedestrians and cyclists"),
    Spec("Pedestrian or cyclist, red-light comparison", outcome="pedbike",
         comparison="redlight", block="Pedestrians and cyclists"),
    Spec("Pedestrian or cyclist, through 2024", outcome="pedbike", window=EXTENDED_WINDOW,
         block="Pedestrians and cyclists"),
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


# --- Dose-response ---------------------------------------------------------------------

def site_dose() -> pd.Series:
    """Log of each site's violation jump: mean monthly violations in DOSE_AFTER over
    mean monthly violations in DOSE_BEFORE, summed over the site's cameras."""
    vio = pd.read_csv(PROCESSED / "violations_monthly.csv")
    monthly = vio.groupby(["site_id", "month"])["violations"].sum().unstack(fill_value=0)
    before = monthly.loc[:, DOSE_BEFORE[0]:DOSE_BEFORE[1]].mean(axis=1)
    after = monthly.loc[:, DOSE_AFTER[0]:DOSE_AFTER[1]].mean(axis=1)
    ok = (before > 0) & (after > 0)
    return np.log(after[ok] / before[ok]).rename("dose")


def dose_response(panel: pd.DataFrame, spec: Spec, dose: pd.Series) -> tuple[pd.DataFrame, dict]:
    """If the threshold made roads safer, crashes should fall most where it bit hardest.

    Treated sites are split into thirds by violation jump, each compared with the same
    comparison sites. A continuous version gives the change in the effect per doubling
    of the jump.
    """
    df = sample(panel, spec)
    d = dose.reindex(df.loc[df["treated"] == 1, "site_id"].unique()).dropna()
    df = df[(df["treated"] == 0) | df["site_id"].isin(d.index)].copy()
    third = pd.qcut(d, 3, labels=False)  # 0 = smallest jump
    df["third"] = df["site_id"].map(third)
    terms = []
    for k in range(3):
        terms.append(f"post_t{k}")
        df[terms[-1]] = ((df["third"] == k) & (df["post"] == 1)).astype(int)
    res = fit(df, " + ".join(terms))

    rows = []
    for k, term in enumerate(terms):
        b, se = res.params[term], res.bse[term]
        jump = np.exp(d[third == k])
        rows.append({"outcome": spec.column, "third": k + 1, "sites": len(jump),
                     "jump_min": jump.min(), "jump_median": jump.median(),
                     "jump_max": jump.max(), "pct_change": pct(b),
                     "ci_low": pct(b - 1.96 * se), "ci_high": pct(b + 1.96 * se),
                     "p_value": res.pvalues[term]})
    R = np.zeros((2, len(res.params)))
    for i, (first, second) in enumerate([(terms[0], terms[1]), (terms[1], terms[2])]):
        R[i, res.params.index.get_loc(first)] = 1
        R[i, res.params.index.get_loc(second)] = -1
    p_equal = float(res.wald_test(R, scalar=True).pvalue)

    df["dose_c"] = df["site_id"].map(d - d.mean()).fillna(0.0)
    df["treat_post_dose"] = df["treat_post"] * df["dose_c"]
    res2 = fit(df, "treat_post + treat_post_dose")
    s, se = res2.params["treat_post_dose"], res2.bse["treat_post_dose"]

    # Permutation check on the slope: shuffle the jumps among treated sites. A slope that
    # reflects ordinary differences between sites shows up often under shuffling.
    site, site_ids, time, y, post = codes(df)
    dose_c = pd.Series(site_ids).map(d - d.mean()).fillna(0.0).to_numpy()
    tp = df["treat_post"].to_numpy(float)
    s_fast = poisson_twfe(y, site, time, np.column_stack([tp, tp * dose_c[site]]))[1]
    if abs(s_fast - s) > 1e-6:
        raise RuntimeError(f"fast solver disagrees with GLM on the dose slope: {s_fast} vs {s}")
    on = np.flatnonzero(pd.Series(site_ids).isin(d.index).to_numpy())
    rng = np.random.default_rng(PERMUTATION_SEED)
    draws = []
    for _ in range(PERMUTATIONS):
        shuffled = dose_c.copy()
        shuffled[on] = rng.permutation(dose_c[on])
        draws.append(poisson_twfe(y, site, time,
                                  np.column_stack([tp, tp * shuffled[site]]))[1])
    p_perm = (np.sum(np.abs(draws) >= abs(s)) + 1) / (PERMUTATIONS + 1)

    slope = {"outcome": spec.column, "per_doubling_pct": pct(s * np.log(2)),
             "ci_low": pct((s - 1.96 * se) * np.log(2)),
             "ci_high": pct((s + 1.96 * se) * np.log(2)),
             "p_value": float(res2.pvalues["treat_post_dose"]),
             "p_permutation": float(p_perm), "p_equal_thirds": p_equal,
             "effect_at_mean_jump_pct": pct(res2.params["treat_post"])}
    return pd.DataFrame(rows), slope


# --- Permutation test ------------------------------------------------------------------

def poisson_twfe(y, site, time, X, tol=1e-10, max_iter=20_000) -> np.ndarray:
    """Coefficients of a Poisson model with site and time fixed effects and regressors X.

    Alternates the closed-form updates of each set of fixed effects with a Newton step on
    the coefficients. It gives the same estimates as the GLM (checked in main()) in a
    fraction of the time, which matters inside 1,000-draw permutation loops.
    """
    X = np.asarray(X, dtype=float).reshape(len(y), -1)
    n_s, n_t = site.max() + 1, time.max() + 1
    y_s = np.bincount(site, weights=y, minlength=n_s)
    y_t = np.bincount(time, weights=y, minlength=n_t)
    g, beta = np.zeros(n_t), np.zeros(X.shape[1])
    for _ in range(max_iter):
        g_old, xb = g, X @ beta
        a = np.log(y_s / np.bincount(site, weights=np.exp(g[time] + xb), minlength=n_s))
        g = np.log(y_t / np.bincount(time, weights=np.exp(a[site] + xb), minlength=n_t))
        mu = np.exp(a[site] + g[time] + xb)
        step = np.linalg.solve((X * mu[:, None]).T @ X, X.T @ (y - mu))
        beta = beta + step
        if np.max(np.abs(step)) < tol and np.max(np.abs(g - g_old)) < tol:
            return beta
    raise RuntimeError("poisson_twfe did not converge")


def codes(df: pd.DataFrame) -> tuple:
    """Integer codes for sites and months, plus the arrays the fast solver needs."""
    site, site_ids = pd.factorize(df["site_id"])
    time, _ = pd.factorize(df["month_fe"])
    return site, site_ids, time, df["y"].to_numpy(float), df["post"].to_numpy(float)


def permutation_test(panel: pd.DataFrame, spec: Spec, n: int = PERMUTATIONS,
                     seed: int = PERMUTATION_SEED) -> tuple[float, np.ndarray, float]:
    """Randomization inference: shuffle which sites count as treated, n times.

    The p-value is the share of shuffles whose estimate is at least as far from zero as
    the real one. It doesn't rely on the clustered standard errors' large-sample math.
    """
    df = sample(panel, spec)
    df = df[df.groupby("month_fe")["y"].transform("sum") > 0]
    site, site_ids, time, y, post = codes(df)
    treated = df.groupby("site_id")["treated"].first().reindex(site_ids).to_numpy(float)

    b_obs = poisson_twfe(y, site, time, treated[site] * post)[0]
    rng = np.random.default_rng(seed)
    draws = np.array([poisson_twfe(y, site, time, rng.permutation(treated)[site] * post)[0]
                      for _ in range(n)])
    p = (np.sum(np.abs(draws) >= abs(b_obs)) + 1) / (n + 1)
    return b_obs, draws, p


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
        "pedbike": named["Pedestrian or cyclist crashes"],
        "redlight": named["Red-light intersections as comparison"],
        "redlight_injury": named["Injury crashes, red-light comparison"],
        "redlight_pedbike": named["Pedestrian or cyclist, red-light comparison"],
        "all_pre2018": named["All pre-2018 sites, school zones included"],
        "school": named["School-zone sites vs. school-zone comparison"],
    }.items():
        es, pretrend[name] = event_study(panel, spec)
        es.to_csv(TABLES / f"event_study_{name}.csv", index=False)

    raw = two_by_two(panel, main_spec)
    raw.to_csv(TABLES / "raw_two_by_two.csv")
    raw_did = 100 * ((1 + raw.loc["treated", "change_pct"] / 100)
                     / (1 + raw.loc["comparison", "change_pct"] / 100) - 1)

    # Dose-response for the real change, and for a fake March 2019 change: a gradient that
    # already existed before 2021 would show up in the placebo too.
    dose = site_dose()
    dose_parts, slopes = [], []
    for period, spec in [("actual", main_spec), ("actual", named["Injury crashes"]),
                         ("placebo", named["Placebo: pretend change in Mar 2019"]),
                         ("placebo", named["Placebo, injury crashes"])]:
        rows, slope = dose_response(panel, spec, dose)
        dose_parts.append(rows.assign(period=period))
        slopes.append({"period": period, **slope})
    dose_table = pd.concat(dose_parts, ignore_index=True)
    dose_table.to_csv(TABLES / "dose_response.csv", index=False)
    slopes = pd.DataFrame(slopes)
    slopes.to_csv(TABLES / "dose_response_slope.csv", index=False)

    by_name = results.set_index("spec")
    perm_rows, draws = [], {}
    for spec in (main_spec, named["Injury crashes"], named["Pedestrian or cyclist crashes"]):
        b_obs, d, p = permutation_test(panel, spec)
        glm = by_name.loc[spec.name]
        if abs(b_obs - glm["coef"]) > 1e-6:
            raise RuntimeError(f"fast solver disagrees with GLM for {spec.name}: "
                               f"{b_obs} vs {glm['coef']}")
        perm_rows.append({"spec": spec.name, "outcome": spec.column,
                          "pct_change": pct(b_obs), "p_permutation": p,
                          "p_clustered": glm["p_value"], "permutations": len(d),
                          "share_below": float(np.mean(d < b_obs))})
        draws[spec.column] = pct(d)
    perm = pd.DataFrame(perm_rows)
    perm.to_csv(TABLES / "permutation.csv", index=False)
    pd.DataFrame(draws).to_csv(TABLES / "permutation_draws.csv", index=False)

    summary = {
        "main": results.iloc[0].to_dict(),
        "pretrend_p_values": pretrend,
        "raw_two_by_two": raw.reset_index().to_dict(orient="records"),
        "raw_ratio_of_ratios_pct": raw_did,
        "dose_response_slopes": slopes.to_dict(orient="records"),
        "permutation": perm.to_dict(orient="records"),
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
        print("\nDose-response by thirds of violation jump:\n"
              + dose_table.round(3).to_string(index=False))
        print("\nDose-response slope (per doubling of the jump):\n"
              + slopes.round(3).to_string(index=False))
        print("\nPermutation tests:\n" + perm.round(3).to_string(index=False))


if __name__ == "__main__":
    main()
