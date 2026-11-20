"""Step 5: figures for the README, each in a light and a dark version.

Colors are the first three slots of a validated categorical palette (blue, orange, aqua),
checked for colorblind separation in both modes. Text always uses ink colors, never a
series color.
"""
import json
from dataclasses import replace
from types import SimpleNamespace

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import matplotlib.ticker as mticker  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
from matplotlib.colors import LinearSegmentedColormap  # noqa: E402

from config import FIGURES, PROCESSED, RAW, TABLES  # noqa: E402
from estimate import SPECS, load_panel, sample  # noqa: E402
from geo import to_meters  # noqa: E402

MINUS = "−"
THEMES = [
    SimpleNamespace(suffix="", surface="#fcfcfb", ink="#0b0b0b", ink2="#52514e",
                    muted="#898781", grid="#e1e0d9", axis="#c3c2b7", neutral="#c9c8c1",
                    band=(0.043, 0.043, 0.043, 0.05),
                    blue="#2a78d6", orange="#eb6834", aqua="#1baf7a"),
    SimpleNamespace(suffix="-dark", surface="#1a1a19", ink="#f0efec", ink2="#c3c2b7",
                    muted="#898781", grid="#2c2c2a", axis="#383835", neutral="#55544f",
                    band=(0.941, 0.937, 0.925, 0.06),
                    blue="#3987e5", orange="#d95926", aqua="#199e70"),
]
plt.rcParams.update({
    "font.family": "sans-serif",
    "font.sans-serif": ["Segoe UI", "Helvetica Neue", "Arial", "DejaVu Sans"],
    "font.size": 10.5,
    "savefig.dpi": 200,
})
SOURCE = "Source: City of Chicago Data Portal (traffic crashes, speed camera locations and violations)."
POLICY_Q = "2021Q1"  # warnings from Jan 15, $35 tickets from Mar 1


# --- shared chrome ---------------------------------------------------------------------

def style(ax, t, grid="y"):
    ax.set_facecolor(t.surface)
    for side in ("top", "right", "left"):
        ax.spines[side].set_visible(False)
    ax.spines["bottom"].set_color(t.axis)
    ax.spines["bottom"].set_linewidth(0.8)
    ax.tick_params(colors=t.axis, labelcolor=t.ink2, labelsize=9.5, length=0, pad=6)
    if grid:
        ax.grid(axis=grid, color=t.grid, linewidth=0.8)
        ax.set_axisbelow(True)


def heading(fig, t, title, subtitle, x=0.065):
    h = fig.get_figheight()
    top = 1 - 0.22 / h
    fig.text(x, top, title, color=t.ink, fontsize=14.5, fontweight="semibold", va="top")
    fig.text(x, top - 0.36 / h, subtitle, color=t.ink2, fontsize=10.5, va="top",
             linespacing=1.4)


def footer(fig, t, text=SOURCE, x=0.065):
    fig.text(x, 0.12 / fig.get_figheight(), text, color=t.muted, fontsize=8.5, va="bottom")


def signed_pct(v, _=None):
    if abs(v) < 0.5:
        return "0%"
    return f"{'+' if v > 0 else MINUS}{abs(v):.0f}%"


def compact(v, _=None):
    return f"{v / 1000:.0f}K" if v >= 1000 else f"{v:.0f}"


def quarter_axis(ax, t, quarters):
    years = sorted({q[:4] for q in quarters})
    pos = {q: i for i, q in enumerate(quarters)}
    starts = [pos[f"{y}Q1"] for y in years if f"{y}Q1" in pos]
    ax.set_xticks([s + 1.5 for s in starts], [y for y in years if f"{y}Q1" in pos])
    for s in starts[1:]:
        ax.axvline(s - 0.5, color=t.grid, lw=0.8, zorder=0)
    ax.set_xlim(-0.6, len(quarters) - 0.4)


def policy_band(ax, t, x, label=True, y=None):
    ax.axvspan(x - 0.5, x + 0.5, color=t.band, lw=0, zorder=0)
    if label:
        ax.text(x, ax.get_ylim()[1] if y is None else y, "6 mph\nthreshold", ha="center",
                va="bottom", fontsize=8.5, color=t.ink2, linespacing=1.2)


def save(fig, name, t):
    FIGURES.mkdir(parents=True, exist_ok=True)
    fig.savefig(FIGURES / f"{name}{t.suffix}.png", facecolor=t.surface)
    plt.close(fig)


# --- figures ---------------------------------------------------------------------------

def event_study(t, results):
    panels = [("All crashes", "event_study_main.csv", "All crashes (main)"),
              ("Injury crashes", "event_study_injury.csv", "Injury crashes")]
    fig, axes = plt.subplots(2, 1, figsize=(9, 8.2), sharex=True)
    fig.patch.set_facecolor(t.surface)
    fig.subplots_adjust(left=0.085, right=0.97, top=0.82, bottom=0.095, hspace=0.32)

    for ax, (label, path, spec_name) in zip(axes, panels):
        style(ax, t)
        es = pd.read_csv(TABLES / path)
        did = results.set_index("spec").loc[spec_name]
        q = es["quarter"].tolist()
        x = np.arange(len(q))
        i_p = q.index(POLICY_Q)

        ax.axhline(0, color=t.axis, lw=1, zorder=1)
        # Pooled post-period estimate and its CI, as a wash behind the quarterly dots.
        x_post = [i_p + 0.5, len(q) - 0.5]
        ax.fill_between(x_post, did["ci_low"], did["ci_high"], color=t.blue, alpha=0.10,
                        lw=0, zorder=1)
        ax.plot(x_post, [did["pct_change"]] * 2, color=t.blue, lw=2, solid_capstyle="round",
                zorder=2)

        ax.vlines(x, es["ci_low"], es["ci_high"], color=t.blue, lw=1.5, zorder=3)
        solid = es["quarter"] != POLICY_Q
        ax.plot(x[solid], es.loc[solid, "pct"], "o", ms=7, mfc=t.blue, mec=t.surface, mew=1.5,
                zorder=4)
        ax.plot(x[~solid], es.loc[~solid, "pct"], "o", ms=7, mfc=t.surface, mec=t.blue,
                mew=1.6, zorder=4)

        lo, hi = es["ci_low"].min(), es["ci_high"].max()
        span = hi - lo
        ax.set_ylim(lo - 0.06 * span, hi + 0.22 * span)
        ax.yaxis.set_major_locator(mticker.MultipleLocator(20 if span < 110 else 40))
        ax.yaxis.set_major_formatter(mticker.FuncFormatter(signed_pct))
        quarter_axis(ax, t, q)
        policy_band(ax, t, i_p, label=False)

        ax.set_title(label, loc="left", fontsize=11.5, fontweight="semibold", color=t.ink,
                     pad=10)
        ci = f"95% CI {signed_pct(did['ci_low'])} to {signed_pct(did['ci_high'])}"
        ax.text(len(q) - 0.45, ax.get_ylim()[1], f"After: {signed_pct(did['pct_change'])}\n{ci}",
                ha="right", va="top", fontsize=9.5, color=t.ink, linespacing=1.35)
        ax.text(i_p, ax.get_ylim()[1], "6 mph\nthreshold", ha="center", va="top",
                fontsize=8.5, color=t.ink2, linespacing=1.2)

    heading(fig, t, "No detectable drop in crashes near cameras after the 6 mph threshold",
            "Crashes within 1/8 mile of 51 park-zone camera sites vs. 56 future camera sites. "
            "Dots: each quarter's gap minus\nthe 2018–2020 average gap, with 95% CIs. Blue "
            "line and band: the pooled estimate for Mar 2021 – Dec 2022.")
    footer(fig, t, "Poisson regression with site and month fixed effects; standard errors "
                   "clustered by site. Hollow dot: Jan–Mar 2021\n(warnings, then tickets). "
                   + SOURCE)
    save(fig, "event_study", t)


def violations(t, sites):
    vio = pd.read_csv(PROCESSED / "violations_monthly.csv")
    main_sites = sites.loc[sites["group"] == "treated", "site_id"]
    s = (vio[vio["site_id"].isin(main_sites)].groupby("month")["violations"].sum()
            .loc["2018-01":"2025-12"])
    idx = pd.PeriodIndex(s.index, freq="M")
    x = idx.to_timestamp()

    fig, ax = plt.subplots(figsize=(9, 4.9))
    fig.patch.set_facecolor(t.surface)
    fig.subplots_adjust(left=0.085, right=0.97, top=0.76, bottom=0.12)
    style(ax, t)
    ax.axvspan(pd.Timestamp("2021-01-15"), pd.Timestamp("2021-03-01"), color=t.band, lw=0)
    ax.fill_between(x, 0, s.to_numpy(), color=t.blue, alpha=0.10, lw=0)
    ax.plot(x, s.to_numpy(), color=t.blue, lw=2, solid_joinstyle="round")
    ax.set_ylim(0, s.max() * 1.18)
    ax.yaxis.set_major_formatter(mticker.FuncFormatter(compact))
    ax.set_xlim(x[0] - pd.Timedelta(days=20), x[-1] + pd.Timedelta(days=20))

    before = s.loc["2019-01":"2019-12"].mean()
    peak = s.loc["2021-03"]
    late = s.loc["2025-01":"2025-12"].mean()
    # Yearly averages as short segments over their year; the March 2021 value as a dot.
    for year, val in [("2019", before), ("2025", late)]:
        a, b = pd.Timestamp(f"{year}-01-01"), pd.Timestamp(f"{year}-12-01")
        ax.plot([a, b], [val, val], color=t.ink2, lw=1.5, solid_capstyle="round", zorder=4)
        ax.text(a + (b - a) / 2, val + s.max() * 0.06, f"{year} average:\n{val / 1000:.0f}K a month",
                ha="center", va="bottom", fontsize=9.5, color=t.ink, linespacing=1.3)
    when = pd.Timestamp("2021-03-01")
    ax.plot([when], [peak], "o", ms=7, mfc=t.blue, mec=t.surface, mew=1.5, zorder=4)
    ax.text(when + pd.Timedelta(days=45), peak + s.max() * 0.04, f"Mar 2021: {peak / 1000:.0f}K",
            ha="left", va="bottom", fontsize=9.5, color=t.ink)

    heading(fig, t, f"Violations at these cameras jumped {peak / before:.1f}x in March 2021, "
                    "then fell for four years",
            "Monthly speed-camera violations at the 51 park-zone sites in the main analysis. "
            "Shaded: the Jan 15 – Mar 1, 2021\nwarning period before $35 tickets at 6 mph over.")
    footer(fig, t)
    save(fig, "violations", t)


def raw_trends(t, panel):
    spec = replace(SPECS[0], drop_transition=False)
    df = sample(panel, spec)
    df["quarter"] = df["month"].dt.asfreq("Q").astype(str)
    df["arm"] = np.where(df["treated"] == 1, "treated", "comparison")
    q = df.groupby(["quarter", "arm"])["y"].mean().unstack()
    base = q.loc[q.index < POLICY_Q].mean()
    idx = 100 * q / base
    quarters = idx.index.tolist()
    x = np.arange(len(quarters))

    fig, ax = plt.subplots(figsize=(9, 4.9))
    fig.patch.set_facecolor(t.surface)
    fig.subplots_adjust(left=0.07, right=0.97, top=0.76, bottom=0.12)
    style(ax, t)
    ax.axhline(100, color=t.axis, lw=1)
    n = df.groupby("arm")["site_id"].nunique()
    series = [("treated", t.blue, f"Park-zone camera sites ({n['treated']})"),
              ("comparison", t.orange, f"Future camera sites ({n['comparison']})")]
    for arm, color, _ in series:
        ax.plot(x, idx[arm], color=color, lw=2, solid_joinstyle="round")
    # The lines converge at the right edge, so identity rides on the legend, not end labels.
    handles = [plt.Line2D([], [], color=c, lw=2, label=l) for _, c, l in series]
    leg = ax.legend(handles=handles, loc="lower left", frameon=False, fontsize=9.5,
                    labelcolor=t.ink2, handlelength=1.6)
    leg.set_zorder(5)

    lo, hi = idx.min().min(), idx.max().max()
    ax.set_ylim(lo - 0.15 * (hi - lo), hi + 0.12 * (hi - lo))
    quarter_axis(ax, t, quarters)
    policy_band(ax, t, quarters.index(POLICY_Q))
    ax.text(quarters.index("2020Q2"), ax.get_ylim()[1], "COVID\nstay-at-home", ha="center",
            va="bottom", fontsize=8.5, color=t.ink2, linespacing=1.2)

    heading(fig, t, "Crashes at camera and comparison sites largely moved together",
            "Average crashes per site per month within 1/8 mile, by quarter, indexed to each "
            "group's 2018–2020 average (= 100).", x=0.07)
    footer(fig, t, x=0.07)
    save(fig, "raw_trends", t)


def forest(t, results):
    res = results[results["spec"] != "Crashes coded as speeding"].copy()  # too few to plot
    blocks = list(dict.fromkeys(res["block"]))
    rows, y, labels, headers = [], 0, [], []
    for b in blocks:
        headers.append((y, b))
        y += 1
        for r in res[res["block"] == b].itertuples():
            rows.append((y, r))
            y += 1
        y += 0.4
    fig_h = 1.6 + 0.29 * y
    fig, ax = plt.subplots(figsize=(9, fig_h))
    fig.patch.set_facecolor(t.surface)
    fig.subplots_adjust(left=0.37, right=0.97, top=1 - 1.15 / fig_h, bottom=0.55 / fig_h)
    style(ax, t, grid="x")
    ax.axvline(0, color=t.axis, lw=1, zorder=1)

    headline = {"All crashes (main)", "Injury crashes"}
    for yy, r in rows:
        color = t.blue if r.spec in headline else t.ink2
        ax.hlines(yy, r.ci_low, r.ci_high, color=color, lw=1.5, zorder=2)
        ax.plot(r.pct_change, yy, "o", ms=6.5, mfc=color, mec=t.surface, mew=1.4, zorder=3)
    ax.set_yticks([yy for yy, _ in rows], [r.spec for _, r in rows])
    for tick, (_, r) in zip(ax.get_yticklabels(), rows):
        tick.set_color(t.ink if r.spec in headline else t.ink2)
    for yy, b in headers:
        ax.text(-0.005, yy, b.upper(), transform=ax.get_yaxis_transform(), ha="right",
                va="center", fontsize=8.5, color=t.muted, fontweight="semibold")
    ax.set_ylim(y - 0.2, -0.8)
    ax.set_xlim(-55, 50)
    ax.xaxis.set_major_locator(mticker.MultipleLocator(10))
    ax.xaxis.set_major_formatter(mticker.FuncFormatter(signed_pct))
    ax.tick_params(axis="x", labelsize=9)

    heading(fig, t, "No total-crash estimate differs from zero; injury and pedestrian "
                    "estimates lean negative",
            "% change in crashes at camera sites relative to comparison sites after Mar 2021, "
            "with 95% confidence intervals.", x=0.02)
    footer(fig, t, "Main analysis in blue. \"Crashes coded as speeding\" (96 events) is "
                   "omitted: its interval spans −46% to +87%.", x=0.02)
    save(fig, "robustness", t)


def dose_response(t):
    rows = pd.read_csv(TABLES / "dose_response.csv")
    slopes = pd.read_csv(TABLES / "dose_response_slope.csv")
    panels = [("All crashes", "crashes_r201"), ("Injury crashes", "injury_r201")]
    labels = ["Smallest jump", "Middle", "Largest jump"]

    fig, axes = plt.subplots(1, 2, figsize=(9, 4.6), sharey=True)
    fig.patch.set_facecolor(t.surface)
    fig.subplots_adjust(left=0.15, right=0.97, top=0.66, bottom=0.2, wspace=0.12)
    for ax, (title, outcome) in zip(axes, panels):
        style(ax, t, grid="x")
        ax.axvline(0, color=t.axis, lw=1, zorder=1)
        for period, dy, face, color, lw in [("actual", -0.13, t.blue, t.blue, 1.6),
                                             ("placebo", 0.13, t.surface, t.muted, 1.2)]:
            r = rows[(rows["outcome"] == outcome) & (rows["period"] == period)]
            yy = r["third"].to_numpy() - 1 + dy
            ax.hlines(yy, r["ci_low"], r["ci_high"], color=color, lw=lw, zorder=2)
            ax.plot(r["pct_change"], yy, "o", ms=7, mfc=face, mec=color if period == "placebo"
                    else t.surface, mew=1.4, zorder=3)
        s = slopes[(slopes["outcome"] == outcome) & (slopes["period"] == "actual")].iloc[0]
        ax.set_title(title, loc="left", fontsize=11.5, fontweight="semibold", color=t.ink, pad=8)
        ax.text(0, -0.13, f"Slope: {signed_pct(s['per_doubling_pct'])} per doubling of the jump "
                          f"(p = {s['p_value']:.3f})", transform=ax.transAxes, fontsize=9,
                color=t.ink2, va="top")
        ax.xaxis.set_major_locator(mticker.MultipleLocator(20))
        ax.xaxis.set_major_formatter(mticker.FuncFormatter(signed_pct))
        ax.set_xlim(-45, 65)
    axes[0].set_yticks([0, 1, 2], labels)
    axes[0].set_ylim(2.55, -0.55)
    handles = [plt.Line2D([], [], marker="o", ms=7, mfc=t.blue, mec=t.surface, color=t.blue,
                          lw=1.6, label="After the Mar 2021 change"),
               plt.Line2D([], [], marker="o", ms=7, mfc=t.surface, mec=t.muted, color=t.muted,
                          lw=1.2, label="Placebo: fake Mar 2019 change")]
    fig.legend(handles=handles, loc="upper left", bbox_to_anchor=(0.15, 0.785), ncol=2,
               frameon=False, fontsize=9.5, labelcolor=t.ink2, handlelength=1.8)

    jumps = rows[(rows["outcome"] == "crashes_r201") & (rows["period"] == "actual")]
    ranges = ", ".join(f"{a:.1f}–{b:.1f}x" for a, b in zip(jumps["jump_min"], jumps["jump_max"]))
    heading(fig, t, "Injury crashes fell most where the new threshold bit hardest",
            "% change at camera sites vs. comparison sites, for thirds of the 51 sites by how much "
            "violations jumped\nfrom 2019 to Mar–May 2021. The placebo runs the same test on "
            "2018–2020, before any change.")
    footer(fig, t, f"Violation jumps by third: {ranges}. 95% confidence intervals. "
                   + SOURCE.replace(" (traffic crashes, speed camera locations and violations)", ""))
    save(fig, "dose_response", t)


def permutation(t):
    perm = pd.read_csv(TABLES / "permutation.csv").set_index("outcome")
    draws = pd.read_csv(TABLES / "permutation_draws.csv")
    panels = [("All crashes", "crashes_r201"), ("Injury crashes", "injury_r201"),
              ("Pedestrian or cyclist", "pedbike_r201")]

    fig, axes = plt.subplots(1, 3, figsize=(9, 3.9))
    fig.patch.set_facecolor(t.surface)
    fig.subplots_adjust(left=0.04, right=0.98, top=0.66, bottom=0.17, wspace=0.12)
    for ax, (title, outcome) in zip(axes, panels):
        style(ax, t, grid=None)
        d = draws[outcome]
        obs = perm.loc[outcome, "pct_change"]
        lo, hi = min(d.min(), obs), max(d.max(), obs)
        bins = np.linspace(lo - 0.02 * (hi - lo), hi + 0.02 * (hi - lo), 31)
        ax.hist(d, bins=bins, color=t.neutral, rwidth=0.82, zorder=1)
        ax.axvline(obs, color=t.blue, lw=2, zorder=3)
        top = ax.get_ylim()[1] * 1.28
        ax.set_ylim(0, top)
        right = obs < (lo + hi) / 2
        ax.text(obs + (0.03 if right else -0.03) * (hi - lo), top * 0.97,
                f"Actual: {signed_pct(obs)}\np = {perm.loc[outcome, 'p_permutation']:.2f}",
                ha="left" if right else "right", va="top", fontsize=9.5, color=t.ink,
                linespacing=1.35)
        ax.set_yticks([])
        ax.xaxis.set_major_locator(mticker.MaxNLocator(4))
        ax.xaxis.set_major_formatter(mticker.FuncFormatter(signed_pct))
        ax.set_title(title, loc="left", fontsize=11, fontweight="semibold", color=t.ink, pad=6)

    heading(fig, t, "Against 1,000 random reassignments, no estimate stands out at p < 0.05",
            "Gray: estimates after randomly reshuffling which 51 of the 107 sites count as "
            "treated. Blue: the real estimate.\nThe p-value is the share of shuffles at least as "
            "far from zero.", x=0.04)
    footer(fig, t, "Same Poisson model with site and month fixed effects. "
                   + SOURCE.replace(" (traffic crashes, speed camera locations and violations)", ""),
           x=0.04)
    save(fig, "permutation", t)


def site_map(t, sites):
    crashes = pd.read_parquet(RAW / "crashes.parquet", columns=["latitude", "longitude"])
    crashes = crashes[crashes["latitude"].between(41.60, 42.05)
                      & crashes["longitude"].between(-87.95, -87.50)]
    xy = to_meters(crashes["longitude"], crashes["latitude"])
    x0, x1 = np.percentile(xy[:, 0], [0.05, 99.95])
    y0, y1 = np.percentile(xy[:, 1], [0.05, 99.95])
    bins = [np.arange(x0, x1 + 120, 120), np.arange(y0, y1 + 120, 120)]
    density, xe, ye = np.histogram2d(xy[:, 0], xy[:, 1], bins=bins)
    # A light, recessive ramp so the site dots carry the figure.
    ramp = ([t.surface, "#e4e3dd", "#b5b4ad"] if t.suffix == ""
            else [t.surface, "#2e2e2b", "#5c5b56"])
    cmap = LinearSegmentedColormap.from_list("street", ramp)

    w = 6.6
    h = w * (y1 - y0) / (x1 - x0) * 0.86 + 1.3
    fig, ax = plt.subplots(figsize=(w, h))
    fig.patch.set_facecolor(t.surface)
    fig.subplots_adjust(left=0.02, right=0.98, top=1 - 1.15 / h, bottom=0.35 / h)
    ax.set_facecolor(t.surface)
    ax.imshow(np.log1p(density.T), origin="lower", extent=[xe[0], xe[-1], ye[0], ye[-1]],
              cmap=cmap, vmin=0, vmax=np.log1p(np.percentile(density[density > 0], 99.5)),
              interpolation="bilinear", aspect="equal")
    ax.set_axis_off()

    other = sites[(sites["kind"] == "speed") & ~sites["group"].isin(["treated", "control"])]
    layers = [
        (other, "o", 4.5, t.surface, t.ink2, f"Other camera sites ({len(other)}), not in main analysis"),
        (sites[sites["group"] == "redlight"], "o", 5, t.aqua, t.surface,
         f"Red-light intersections ({(sites['group'] == 'redlight').sum()}), alt. comparison"),
        (sites[sites["group"] == "control"], "o", 7.5, t.orange, t.surface,
         f"Future camera sites ({(sites['group'] == 'control').sum()}), comparison"),
        (sites[sites["group"] == "treated"], "o", 7.5, t.blue, t.surface,
         f"Park-zone camera sites ({(sites['group'] == 'treated').sum()}), treated"),
    ]
    handles = []
    for df, marker, size, face, edge, label in layers:
        ax.plot(df["x"], df["y"], marker, ms=size, mfc=face, mec=edge, mew=1.2, ls="none")
        handles.append(plt.Line2D([], [], marker=marker, ms=size, mfc=face, mec=edge, mew=1.2,
                                  ls="none", label=label))
    # The city's irregular southwest edge leaves the lower-left corner empty.
    leg = ax.legend(handles=handles[::-1], loc="lower left", frameon=False, fontsize=9,
                    labelcolor=t.ink2, borderaxespad=0.2, handletextpad=0.4)
    leg.set_zorder(5)

    heading(fig, t, "Where the study sites are",
            "Gray shows where Chicago's 2018–2025 crashes happened, which traces the street "
            "grid.", x=0.04)
    footer(fig, t, SOURCE.replace(" (traffic crashes, speed camera locations and violations)",
                                  ""), x=0.04)
    save(fig, "map", t)


def main() -> None:
    results = pd.read_csv(TABLES / "did_results.csv")
    sites = pd.read_csv(PROCESSED / "sites.csv")
    panel = load_panel()
    for t in THEMES:
        event_study(t, results)
        violations(t, sites)
        raw_trends(t, panel)
        forest(t, results)
        dose_response(t)
        permutation(t)
        site_map(t, sites)
    print("figures ->", FIGURES)
    print(json.dumps(sorted(p.name for p in FIGURES.glob("*.png")), indent=1))


if __name__ == "__main__":
    main()
