// Interactive explorer for the speed-camera threshold study.
// Every number here was computed in advance by src/demo.py into data/demo.json;
// this file only draws. Colors come from CSS variables, so light and dark both work.

const d3 = window.d3;
const MINUS = "−";
const POLICY_Q = "2021Q1";

let DATA;
try {
  DATA = await fetch("data/demo.json").then((r) => {
    if (!r.ok) throw new Error(r.status);
    return r.json();
  });
} catch (err) {
  document.getElementById("hero").textContent = "";
  document.getElementById("verdict").textContent =
    "Couldn't load the data. Open this page through a web server (for example GitHub Pages), not as a local file.";
  throw err;
}

const OPTION_KEYS = ["outcome", "comparison", "radius", "window", "covid"];
const OPTION_LABELS = { outcome: "Outcome", comparison: "Compared with", radius: "Radius",
                        window: "Years", covid: "COVID months" };
const NOUN = { crashes: "crashes", injury: "injury crashes", pedbike: "pedestrian or cyclist crashes" };
const COMPARISON = { control: "future camera sites", redlight: "red-light intersections" };
const CLASS_LABEL = {
  treated: "Park-zone camera sites (treated)",
  control: "Future camera sites (comparison)",
  redlight: "Red-light intersections (alternative comparison)",
  other: "Other camera sites (not in main analysis)",
};
const CLASS_ORDER = ["treated", "control", "redlight", "other"];

const state = { site: DATA.meta.default_site };
const [o0, c0, r0, w0, v0] = DATA.meta.default.split("|");
Object.assign(state, { outcome: o0, comparison: c0, radius: r0, window: w0, covid: v0 });
readHash();

const sites = DATA.sites;
const siteById = new Map(sites.map((s) => [s.id, s]));
if (!siteById.has(state.site)) state.site = DATA.meta.default_site;
const siteClass = (s) => (["treated", "control", "redlight"].includes(s.group) ? s.group : "other");

// --- formatting ---------------------------------------------------------------------
const signed = (v, digits = 0) => {
  if (v == null) return "–";
  const s = Math.abs(v).toFixed(digits);
  if (Number(s) === 0) return `${(0).toFixed(digits)}%`;
  return `${v > 0 ? "+" : MINUS}${s}%`;
};
const fmtP = (p) => (p < 0.001 ? "< 0.001" : p.toFixed(p < 0.1 ? 3 : 2));
const fmtInt = d3.format(",");
const compact = (v) => (v >= 1000 ? `${d3.format(".0f")(v / 1000)}K` : `${v}`);
const quarterLabel = (q) => `${q.slice(0, 4)} Q${q.slice(5)}`;
const monthLabel = (ym) => d3.utcFormat("%b %Y")(new Date(`${ym}-01T00:00:00Z`));
const rate = (v) => (v == null ? "–" : v < 1 ? v.toFixed(2) : v.toFixed(1));
const cap = (s) => s.charAt(0).toUpperCase() + s.slice(1);
const esc = (s) => String(s).replace(/[&<>"']/g, (c) => `&#${c.charCodeAt(0)};`);

// --- URL state, so any view can be shared as a link ------------------------------------
function readHash() {
  const params = new URLSearchParams(location.hash.slice(1));
  for (const key of OPTION_KEYS) {
    const v = params.get(key);
    if (v && DATA.options[key][v] !== undefined) state[key] = v;
  }
  if (params.get("site")) state.site = params.get("site");
}
function writeHash() {
  const params = new URLSearchParams();
  for (const key of OPTION_KEYS) params.set(key, state[key]);
  params.set("site", state.site);
  history.replaceState(null, "", `#${params}`);
}

// --- tooltip ------------------------------------------------------------------------------
const tip = document.getElementById("tooltip");
function showTip(event, html) {
  tip.innerHTML = html;
  tip.hidden = false;
  moveTip(event);
}
function moveTip(event) {
  const pad = 14;
  const box = tip.getBoundingClientRect();
  let x = event.clientX + pad;
  let y = event.clientY + pad;
  if (x + box.width > innerWidth - 8) x = event.clientX - box.width - pad;
  if (y + box.height > innerHeight - 8) y = event.clientY - box.height - pad;
  tip.style.left = `${Math.max(8, x)}px`;
  tip.style.top = `${Math.max(8, y)}px`;
}
const hideTip = () => { tip.hidden = true; };

// --- controls -------------------------------------------------------------------------------
function buildControls() {
  const form = document.getElementById("controls");
  for (const key of OPTION_KEYS) {
    const fieldset = document.createElement("fieldset");
    fieldset.className = "seg";
    const legend = document.createElement("legend");
    legend.textContent = OPTION_LABELS[key];
    const opts = document.createElement("div");
    opts.className = "opts";
    for (const [value, text] of Object.entries(DATA.options[key])) {
      const label = document.createElement("label");
      const input = document.createElement("input");
      input.type = "radio";
      input.name = key;
      input.value = value;
      input.checked = state[key] === value;
      input.addEventListener("change", () => {
        state[key] = value;
        renderEstimate();
        if (key === "outcome") renderSite();
        writeHash();
      });
      const span = document.createElement("span");
      span.textContent = text;
      label.append(input, span);
      opts.append(label);
    }
    fieldset.append(legend, opts);
    form.append(fieldset);
  }
}

// --- the estimate ------------------------------------------------------------------------------
const currentEntry = () => DATA.grid[OPTION_KEYS.map((k) => state[k]).join("|")];

function renderEstimate() {
  const e = currentEntry();
  document.getElementById("hero").textContent = signed(e.pct, 1);
  document.getElementById("ci").textContent =
    `95% CI ${signed(e.lo, 1)} to ${signed(e.hi, 1)} · p = ${fmtP(e.p)} · ` +
    `${e.treated} camera sites vs. ${e.comparison} ${COMPARISON[state.comparison]} · ` +
    `${fmtInt(e.events)} ${NOUN[state.outcome]}`;

  const noun = cap(NOUN[state.outcome]);
  const versus = COMPARISON[state.comparison];
  const verdict = document.getElementById("verdict");
  if (e.lo > 0 || e.hi < 0) {
    verdict.textContent = `${noun} near cameras ${e.pct > 0 ? "rose" : "fell"} ` +
      `${Math.abs(e.pct).toFixed(0)}% relative to ${versus} after the change, and the 95% ` +
      `interval excludes zero.`;
  } else {
    verdict.textContent = `${noun} near cameras changed by ${signed(e.pct)} relative to ` +
      `${versus} after the change, but the 95% interval includes zero, so this can't be ` +
      `told apart from no change.`;
  }
  const caution = document.getElementById("caution");
  caution.hidden = !(e.pretrend_p < 0.05);
  caution.innerHTML = `<strong>Caution:</strong> before 2021, the two groups' trends already ` +
    `differed (pre-trend test p = ${fmtP(e.pretrend_p)}), so this version's estimate is unreliable.`;

  drawEventStudy(e);
  fillTable(document.getElementById("es-table"), ["Quarter", "Gap vs. 2018–2020", "95% CI"],
    e.es.map(([q, v, lo, hi]) => [quarterLabel(q), signed(v), `${signed(lo)} to ${signed(hi)}`]));
}

function windowQuarters() {
  const end = state.window === "2022" ? "2022Q4" : "2024Q4";
  return DATA.meta.quarters.filter((q) => q <= end);
}

function yearAxis(svg, x, qs, height, everyOther) {
  const years = [...new Set(qs.map((q) => q.slice(0, 4)))];
  years.forEach((year, i) => {
    const first = `${year}Q1`;
    const last = qs.filter((q) => q.startsWith(year)).at(-1);
    if (!qs.includes(first)) return;
    if (i > 0) {
      svg.insert("line", ":first-child").attr("class", "grid-v")
        .attr("x1", x(first)).attr("x2", x(first)).attr("y1", 0).attr("y2", height);
    }
    if (everyOther && i % 2) return;
    svg.append("text").attr("class", "axis-text").attr("text-anchor", "middle")
      .attr("x", (x(first) + x(last) + x.bandwidth()) / 2).attr("y", height + 18).text(year);
  });
}

function drawEventStudy(e) {
  const el = document.getElementById("es-chart");
  const W = Math.max(300, el.clientWidth);
  const H = W < 560 ? 250 : 310;
  const m = { top: 30, right: 6, bottom: 28, left: 50 };
  const qs = windowQuarters();
  const byQ = new Map(e.es.map((d) => [d[0], d]));
  const x = d3.scaleBand(qs, [m.left, W - m.right]);
  const xc = (q) => x(q) + x.bandwidth() / 2;
  const lo = Math.min(0, e.lo, d3.min(e.es, (d) => d[2]));
  const hi = Math.max(0, e.hi, d3.max(e.es, (d) => d[3]));
  const y = d3.scaleLinear([lo, hi], [H - m.bottom, m.top]).nice(6);

  const svg = d3.create("svg").attr("viewBox", `0 0 ${W} ${H}`);
  const ticks = y.ticks(6);
  svg.append("g").attr("class", "grid").selectAll("line").data(ticks).join("line")
    .attr("x1", m.left).attr("x2", W - m.right).attr("y1", y).attr("y2", y);
  svg.append("g").selectAll("text").data(ticks).join("text").attr("class", "axis-text")
    .attr("x", m.left - 8).attr("y", y).attr("dy", "0.32em").attr("text-anchor", "end")
    .text((d) => signed(d));
  yearAxis(svg, x, qs, H - m.bottom, W < 480);

  if (qs.includes(POLICY_Q)) {
    svg.append("rect").attr("class", "band").attr("x", x(POLICY_Q)).attr("width", x.bandwidth())
      .attr("y", m.top).attr("height", H - m.bottom - m.top);
    svg.append("text").attr("class", "band-label").attr("text-anchor", "middle")
      .attr("x", xc(POLICY_Q)).attr("y", m.top - 10).text("6 mph threshold");
  }
  svg.append("line").attr("class", "axis-line").attr("x1", m.left).attr("x2", W - m.right)
    .attr("y1", y(0)).attr("y2", y(0));

  const post = qs.filter((q) => q > POLICY_Q);
  const px0 = x(post[0]);
  const px1 = x(post.at(-1)) + x.bandwidth();
  svg.append("rect").attr("class", "pooled-band").attr("x", px0).attr("width", px1 - px0)
    .attr("y", y(e.hi)).attr("height", y(e.lo) - y(e.hi));
  svg.append("line").attr("class", "pooled-line").attr("x1", px0 + 3).attr("x2", px1 - 3)
    .attr("y1", y(e.pct)).attr("y2", y(e.pct));

  const cols = svg.append("g").selectAll("rect").data(qs).join("rect").attr("class", "hover-col")
    .attr("x", (q) => x(q)).attr("width", x.bandwidth()).attr("y", m.top)
    .attr("height", H - m.bottom - m.top);
  const pts = e.es.filter((d) => qs.includes(d[0]));
  svg.append("g").selectAll("line").data(pts).join("line").attr("class", "whisker")
    .attr("x1", (d) => xc(d[0])).attr("x2", (d) => xc(d[0]))
    .attr("y1", (d) => y(d[2])).attr("y2", (d) => y(d[3]));
  svg.append("g").selectAll("circle").data(pts).join("circle")
    .attr("class", (d) => (d[0] === POLICY_Q ? "dot hollow" : "dot"))
    .attr("cx", (d) => xc(d[0])).attr("cy", (d) => y(d[1])).attr("r", W < 560 ? 3.6 : 4.6);

  cols.on("pointerenter pointermove", function (event, q) {
    cols.classed("on", (d) => d === q);
    const d = byQ.get(q);
    const note = q === POLICY_Q ? "<br><span class='t-sub'>Warnings from Jan 15, tickets from Mar 1</span>" : "";
    showTip(event, d
      ? `<strong>${quarterLabel(q)}: ${signed(d[1])}</strong><br><span class="t-sub">95% CI ${signed(d[2])} to ${signed(d[3])}</span>${note}`
      : `<strong>${quarterLabel(q)}</strong><br><span class="t-sub">Months dropped in this version</span>`);
  }).on("pointerleave", () => { cols.classed("on", false); hideTip(); });

  el.replaceChildren(svg.node());
}

// --- map -------------------------------------------------------------------------------------
let ring;
const MAP_W = 1000;
const MAP_H = Math.round(MAP_W * DATA.meta.basemap.height / DATA.meta.basemap.width);
const MARK_R = { treated: 11, control: 11, redlight: 8.5, other: 8 };

function buildMap() {
  const svg = d3.create("svg").attr("viewBox", `0 0 ${MAP_W} ${MAP_H}`)
    .attr("role", "img").attr("aria-label", "Map of Chicago with every study site");
  svg.append("image").attr("href", "data/basemap.png").attr("width", MAP_W)
    .attr("height", MAP_H).attr("preserveAspectRatio", "none");
  const drawOrder = ["other", "redlight", "control", "treated"];
  const ordered = [...sites].sort((a, b) =>
    drawOrder.indexOf(siteClass(a)) - drawOrder.indexOf(siteClass(b)));
  const g = svg.append("g").selectAll("g").data(ordered).join("g")
    .attr("class", (s) => `site ${siteClass(s)}`)
    .attr("transform", (s) => `translate(${s.u * MAP_W},${s.v * MAP_H})`);
  g.append("circle").attr("class", "hit").attr("r", (s) => MARK_R[siteClass(s)] + 8);
  g.append("circle").attr("class", "mark").attr("r", (s) => MARK_R[siteClass(s)]);
  g.on("pointerenter pointermove", (event, s) => showTip(event,
      `<strong>${esc(s.address)}</strong><br><span class="t-sub">${esc(s.label)}</span>`))
    .on("pointerleave", hideTip)
    .on("click", (event, s) => selectSite(s.id));
  ring = svg.append("circle").attr("class", "selected-ring").attr("r", 19);
  document.getElementById("map").replaceChildren(svg.node());

  const counts = d3.rollup(sites, (v) => v.length, siteClass);
  const legend = document.getElementById("map-legend");
  for (const cls of CLASS_ORDER) {
    const li = document.createElement("li");
    li.innerHTML = `<span class="swatch ${cls}"></span>${CLASS_LABEL[cls]} · ${counts.get(cls) ?? 0}`;
    legend.append(li);
  }

  const select = document.getElementById("site-select");
  for (const cls of CLASS_ORDER) {
    const group = document.createElement("optgroup");
    group.label = CLASS_LABEL[cls];
    sites.filter((s) => siteClass(s) === cls)
      .sort((a, b) => a.address.localeCompare(b.address))
      .forEach((s) => group.append(new Option(s.address, s.id)));
    select.append(group);
  }
  select.addEventListener("change", () => selectSite(select.value));
}

function selectSite(id) {
  state.site = id;
  renderSite();
  writeHash();
}

// --- site panel ----------------------------------------------------------------------------------
function renderSite() {
  const s = siteById.get(state.site);
  const cls = siteClass(s);
  document.getElementById("site-select").value = s.id;
  ring.attr("transform", `translate(${s.u * MAP_W},${s.v * MAP_H})`).raise();

  document.getElementById("site-title").textContent = s.address;
  let when = s.group === "redlight" ? `red-light camera since ${monthLabel(s.live)}` :
    s.group === "control" ? `speed camera went live ${monthLabel(s.live)}` :
    s.live_known ? `first camera live ${monthLabel(s.live)}` :
    `in service by ${monthLabel(s.live)}`;
  if (s.removed) when += `, removed ${monthLabel(s.removed)}`;
  document.getElementById("site-meta").textContent =
    `${s.label} · ${s.cameras} camera${s.cameras > 1 ? "s" : ""} · ${when}`;

  const noun = NOUN[state.outcome];
  const b = s.before[state.outcome];
  const a = s.after[state.outcome];
  const change = b > 0 ? ` (${signed(100 * (a / b - 1))})` : "";
  document.getElementById("site-stat").textContent =
    `${cap(noun)} within 1/8 mile: ${rate(b)} a month in 2018–2020, ${rate(a)} in Mar 2021 – Dec 2022${change}.`;
  document.getElementById("site-chart-title").textContent = `${cap(noun)} per quarter`;

  drawSiteBars(s, cls);
  const vioBlock = document.getElementById("vio-block");
  vioBlock.hidden = !s.violations;
  if (s.violations) drawViolations(s, cls);

  fillTable(document.getElementById("site-table"), ["Quarter", cap(noun)],
    DATA.meta.quarters.map((q, i) => [quarterLabel(q), fmtInt(s.q[state.outcome][i])]));
}

function roundedBar(x, y, w, base) {
  const h = base - y;
  if (h <= 0) return "";
  const r = Math.min(2.5, w / 2, h);
  return `M${x},${base}V${y + r}Q${x},${y} ${x + r},${y}H${x + w - r}Q${x + w},${y} ${x + w},${y + r}V${base}Z`;
}

function drawSiteBars(s, cls) {
  const el = document.getElementById("site-chart");
  const W = Math.max(280, el.clientWidth);
  const H = 170;
  const m = { top: 22, right: 4, bottom: 24, left: 30 };
  const qs = DATA.meta.quarters;
  const vals = s.q[state.outcome];
  const x = d3.scaleBand(qs, [m.left, W - m.right]).paddingInner(0.28);
  const y = d3.scaleLinear([0, Math.max(3, d3.max(vals))], [H - m.bottom, m.top]).nice(4);

  const svg = d3.create("svg").attr("viewBox", `0 0 ${W} ${H}`);
  const ticks = y.ticks(4).filter(Number.isInteger);
  svg.append("g").attr("class", "grid").selectAll("line").data(ticks).join("line")
    .attr("x1", m.left).attr("x2", W - m.right).attr("y1", y).attr("y2", y);
  svg.append("g").selectAll("text").data(ticks).join("text").attr("class", "axis-text")
    .attr("x", m.left - 6).attr("y", y).attr("dy", "0.32em").attr("text-anchor", "end").text((d) => d);
  yearAxis(svg, x, qs, H - m.bottom, W < 520);

  const step = x.step();
  svg.append("rect").attr("class", "band").attr("x", x(POLICY_Q) - (step - x.bandwidth()) / 2)
    .attr("width", step).attr("y", m.top).attr("height", H - m.bottom - m.top);
  svg.append("text").attr("class", "band-label").attr("text-anchor", "middle")
    .attr("x", x(POLICY_Q) + x.bandwidth() / 2).attr("y", m.top - 8).text("6 mph");

  const liveQ = `${s.live.slice(0, 4)}Q${Math.ceil(Number(s.live.slice(5, 7)) / 3)}`;
  if (s.group === "control" && qs.includes(liveQ)) {
    const lx = x(liveQ) - (step - x.bandwidth()) / 2;
    svg.append("line").attr("class", "marker-line").attr("x1", lx).attr("x2", lx)
      .attr("y1", m.top - 2).attr("y2", H - m.bottom);
    svg.append("text").attr("class", "marker-label").attr("x", lx + 4).attr("y", m.top + 8)
      .text("camera on");
  }

  svg.append("g").selectAll("path").data(qs).join("path").attr("class", `bar ${cls}`)
    .attr("d", (q, i) => roundedBar(x(q), y(vals[i]), x.bandwidth(), y(0)));
  svg.append("line").attr("class", "axis-line").attr("x1", m.left).attr("x2", W - m.right)
    .attr("y1", y(0)).attr("y2", y(0));

  const cols = svg.append("g").selectAll("rect").data(qs).join("rect").attr("class", "hover-col")
    .attr("x", (q) => x(q) - (step - x.bandwidth()) / 2).attr("width", step)
    .attr("y", m.top).attr("height", H - m.bottom - m.top);
  cols.on("pointerenter pointermove", (event, q) => {
    cols.classed("on", (d) => d === q);
    const n = vals[qs.indexOf(q)];
    showTip(event, `<strong>${quarterLabel(q)}</strong><br><span class="t-sub">${n} ${n === 1 ? NOUN[state.outcome].replace(/es$/, "") : NOUN[state.outcome]}</span>`);
  }).on("pointerleave", () => { cols.classed("on", false); hideTip(); });

  el.replaceChildren(svg.node());
}

function drawViolations(s, cls) {
  const el = document.getElementById("vio-chart");
  const W = Math.max(280, el.clientWidth);
  const H = 150;
  const m = { top: 16, right: 6, bottom: 24, left: 36 };
  const start = new Date(`${DATA.meta.months_start}-01T00:00:00Z`);
  const months = s.violations.map((_, i) => d3.utcMonth.offset(start, i));
  const data = s.violations.map((v, i) => ({ date: months[i], v }));
  const x = d3.scaleUtc([months[0], months.at(-1)], [m.left, W - m.right]);
  const y = d3.scaleLinear([0, Math.max(10, d3.max(s.violations) ?? 10)], [H - m.bottom, m.top]).nice(4);

  const svg = d3.create("svg").attr("viewBox", `0 0 ${W} ${H}`);
  const ticks = y.ticks(4);
  svg.append("g").attr("class", "grid").selectAll("line").data(ticks).join("line")
    .attr("x1", m.left).attr("x2", W - m.right).attr("y1", y).attr("y2", y);
  svg.append("g").selectAll("text").data(ticks).join("text").attr("class", "axis-text")
    .attr("x", m.left - 6).attr("y", y).attr("dy", "0.32em").attr("text-anchor", "end").text(compact);
  const years = d3.utcYear.range(months[0], d3.utcMonth.offset(months.at(-1), 1));
  svg.append("g").selectAll("text").data(years.filter((d, i) => W >= 520 || i % 2 === 0)).join("text")
    .attr("class", "axis-text").attr("text-anchor", "middle")
    .attr("x", (d) => x(d3.utcMonth.offset(d, 6))).attr("y", H - m.bottom + 18)
    .text(d3.utcFormat("%Y"));

  const w0 = x(new Date("2021-01-15T00:00:00Z"));
  const w1 = x(new Date("2021-03-01T00:00:00Z"));
  svg.append("rect").attr("class", "band").attr("x", w0).attr("width", Math.max(2, w1 - w0))
    .attr("y", m.top).attr("height", H - m.bottom - m.top);

  const line = d3.line().defined((d) => d.v != null).x((d) => x(d.date)).y((d) => y(d.v));
  svg.append("path").attr("class", `line ${cls}`).attr("d", line(data));
  svg.append("line").attr("class", "axis-line").attr("x1", m.left).attr("x2", W - m.right)
    .attr("y1", y(0)).attr("y2", y(0));

  const cross = svg.append("line").attr("class", "crosshair").attr("y1", m.top)
    .attr("y2", H - m.bottom).attr("visibility", "hidden");
  const dot = svg.append("circle").attr("class", `cross-dot ${cls}`).attr("r", 4)
    .attr("visibility", "hidden");
  const bisect = d3.bisector((d) => d.date).center;
  svg.append("rect").attr("x", m.left).attr("width", W - m.left - m.right).attr("y", m.top)
    .attr("height", H - m.bottom - m.top).attr("fill", "transparent")
    .on("pointerenter pointermove", function (event) {
      const [px] = d3.pointer(event, this);
      const d = data[bisect(data, x.invert(px))];
      cross.attr("x1", x(d.date)).attr("x2", x(d.date)).attr("visibility", "visible");
      if (d.v != null) dot.attr("cx", x(d.date)).attr("cy", y(d.v)).attr("visibility", "visible");
      else dot.attr("visibility", "hidden");
      showTip(event, `<strong>${d3.utcFormat("%b %Y")(d.date)}</strong><br><span class="t-sub">` +
        (d.v == null ? "Camera not yet live" : `${fmtInt(d.v)} violations`) + "</span>");
    })
    .on("pointerleave", () => {
      cross.attr("visibility", "hidden");
      dot.attr("visibility", "hidden");
      hideTip();
    });

  el.replaceChildren(svg.node());
}

function fillTable(table, head, rows) {
  table.replaceChildren();
  const thead = table.createTHead().insertRow();
  head.forEach((h) => { const th = document.createElement("th"); th.textContent = h; thead.append(th); });
  const body = table.createTBody();
  rows.forEach((row) => {
    const tr = body.insertRow();
    row.forEach((cell) => { tr.insertCell().textContent = cell; });
  });
}

// --- go ----------------------------------------------------------------------------------------------
buildControls();
buildMap();
renderEstimate();
renderSite();

let frame;
new ResizeObserver(() => {
  cancelAnimationFrame(frame);
  frame = requestAnimationFrame(() => { renderEstimate(); renderSite(); });
}).observe(document.querySelector("main"));
