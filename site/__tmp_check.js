
const canvas = document.getElementById("canvas");
const ctx = canvas.getContext("2d");
let dpr = window.devicePixelRatio || 1;
let data = [];
let allData = [];
let rects = [];
let hovered = null;
let selected = null;
let colorMode = "tailwind";
let sourceFilter = "all";

const MODES = {
  composite: { field: "ai_composite_index", metricKey: "ai_composite_index", label: "AI Composite Index", high: "Stronger net AI position", low: "Weaker net AI position" },
  tailwind: { field: "tailwind", metricKey: "ai_revenue_tailwind", label: "AI Revenue Tailwind", high: "More direct demand", low: "Little direct demand" },
  pricing: { field: "pricing_power_risk", metricKey: "pricing_power_risk", label: "Pricing Power Risk", high: "More price pressure", low: "Less price pressure" },
  channel: { field: "channel_control_risk", metricKey: "channel_control_risk", label: "Channel Control Risk", high: "More interface risk", low: "Less interface risk" },
  leverage: { field: "leverage", metricKey: "ai_operating_leverage", label: "AI Operating Leverage", high: "More internal lift", low: "Less internal lift" },
  moat: { field: "moat", metricKey: "data_distribution_moat", label: "Data / Distribution Moat", high: "Stronger moat", low: "Weaker moat" },
  infrastructure: { field: "infrastructure", metricKey: "ai_infrastructure_exposure", label: "AI Infrastructure Exposure", high: "More infra-linked", low: "Less infra-linked" },
};

function greenRedCSS(t, a) {
  const hue = 125 * Math.max(0, Math.min(1, t));
  return `hsla(${hue}, 66%, 45%, ${a})`;
}

function modeValue(d) {
  return d?.[MODES[colorMode].field];
}

function modeMetricKey() {
  return MODES[colorMode].metricKey;
}

function colorForScore(v, a = 1) {
  if (v == null) return `rgba(120,120,120,${a})`;
  return greenRedCSS(1 - v / 10, a);
}

function formatCap(v) {
  return v == null ? "?" : `$${Math.round(v).toLocaleString()}B`;
}

function formatRevenue(v) {
  return v == null ? "?" : `$${Math.round(v).toLocaleString()}B`;
}

function formatEmployees(v) {
  return v == null ? "?" : v.toLocaleString();
}

function formatNumber(v, digits = 2) {
  return v == null ? "?" : Number(v).toFixed(digits);
}

function activeMetricStats(d) {
  const key = modeMetricKey();
  return {
    mean: d.metric_means?.[key],
    stddev: d.metric_stddevs?.[key],
    range: d.metric_ranges?.[key],
  };
}

function splitBalanced(sortedItems) {
  const total = sortedItems.reduce((s, it) => s + it.size, 0);
  const target = total / 2;
  const left = [];
  const right = [];
  let acc = 0;
  for (const item of sortedItems) {
    if (acc < target || left.length === 0) {
      left.push(item);
      acc += item.size;
    } else {
      right.push(item);
    }
  }
  if (!right.length && left.length > 1) right.push(left.pop());
  return [left, right];
}

function binaryTreemap(items, x, y, w, h) {
  if (!items.length || w <= 0 || h <= 0) return [];
  if (items.length === 1) return [{ ...items[0], rx: x, ry: y, rw: w, rh: h }];

  const sorted = items.slice().sort((a, b) => b.size - a.size);
  const [leftItems, rightItems] = splitBalanced(sorted);
  const total = sorted.reduce((s, it) => s + it.size, 0);
  const leftSum = leftItems.reduce((s, it) => s + it.size, 0);
  const ratio = total > 0 ? leftSum / total : 0.5;

  if (w >= h) {
    const leftW = Math.max(1, w * ratio);
    const rightW = Math.max(1, w - leftW);
    return [
      ...binaryTreemap(leftItems, x, y, leftW, h),
      ...binaryTreemap(rightItems, x + leftW, y, rightW, h),
    ];
  }
  const topH = Math.max(1, h * ratio);
  const bottomH = Math.max(1, h - topH);
  return [
    ...binaryTreemap(leftItems, x, y, w, topH),
    ...binaryTreemap(rightItems, x, y + topH, w, bottomH),
  ];
}

function layout() {
  const width = document.getElementById("treemap-shell").clientWidth;
  const height = Math.max(620, Math.min(window.innerHeight - 120, width * 0.72));
  canvas.width = width * dpr;
  canvas.height = height * dpr;
  canvas.style.height = `${height}px`;

  const sectors = [];
  const grouped = new Map();
  for (const d of data) {
    if (!grouped.has(d.sector)) grouped.set(d.sector, []);
    grouped.get(d.sector).push({ ...d, size: Math.max(1, d.market_cap || 1) });
  }
  for (const [sector, items] of grouped.entries()) {
    sectors.push({ title: sector, items, size: items.reduce((s, d) => s + d.size, 0) });
  }
  sectors.sort((a, b) => b.size - a.size);

  const sectorRects = binaryTreemap(sectors, 0, 0, width, height);
  rects = [];
  for (const sr of sectorRects) {
    rects.push({ kind: "sector", title: sr.title, rx: sr.rx, ry: sr.ry, rw: sr.rw, rh: sr.rh });
    const padX = sr.rw > 140 ? 10 : 4;
    const padTop = sr.rh > 90 ? 22 : 8;
    const padBottom = 4;
    const inner = binaryTreemap(
      sr.items,
      sr.rx + padX,
      sr.ry + padTop,
      Math.max(6, sr.rw - padX * 2),
      Math.max(6, sr.rh - padTop - padBottom),
    );
    for (const r of inner) rects.push({ kind: "company", ...r });
  }
}

function drawText(text, x, y, maxWidth, font, color) {
  ctx.font = font;
  ctx.fillStyle = color;
  if (ctx.measureText(text).width <= maxWidth) {
    ctx.fillText(text, x, y);
    return;
  }
  let trimmed = text;
  while (trimmed.length > 4 && ctx.measureText(`${trimmed}...`).width > maxWidth) trimmed = trimmed.slice(0, -1);
  ctx.fillText(`${trimmed}...`, x, y);
}

function draw() {
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  ctx.clearRect(0, 0, canvas.width, canvas.height);
  ctx.fillStyle = "#f7f1e7";
  ctx.fillRect(0, 0, canvas.width, canvas.height);

  for (const r of rects) {
    if (r.kind === "sector") {
      ctx.fillStyle = "rgba(98, 81, 60, 0.08)";
      ctx.fillRect(r.rx, r.ry, r.rw, r.rh);
      drawText(r.title.toUpperCase(), r.rx + 8, r.ry + 16, Math.max(30, r.rw - 12), "600 11px Georgia", "rgba(60,48,34,0.76)");
      continue;
    }

    const val = modeValue(r);
    const isActive = (hovered && hovered.slug === r.slug) || (selected && selected.slug === r.slug);
    ctx.fillStyle = colorForScore(val, isActive ? 0.95 : 0.82);
    ctx.fillRect(r.rx, r.ry, r.rw, r.rh);
    ctx.strokeStyle = "rgba(255,255,255,0.65)";
    ctx.lineWidth = isActive ? 2 : 1;
    ctx.strokeRect(r.rx, r.ry, r.rw, r.rh);

    if (r.rw < 54 || r.rh < 38) continue;
    const titleSize = Math.max(11, Math.min(34, Math.min(r.rw, r.rh) / 4.5));
    const subSize = Math.max(10, titleSize * 0.45);
    const textColor = "rgba(255,255,255,0.96)";
    drawText(r.ticker, r.rx + 8, r.ry + titleSize + 2, r.rw - 14, `700 ${titleSize}px Georgia`, textColor);
    drawText(r.title, r.rx + 8, r.ry + titleSize + subSize + 12, r.rw - 14, `400 ${subSize}px Georgia`, "rgba(255,255,255,0.86)");
    drawText(`${MODES[colorMode].label}: ${val}/10`, r.rx + 8, r.ry + titleSize + subSize + 28, r.rw - 14, `400 ${Math.max(10, subSize - 1)}px Georgia`, "rgba(255,255,255,0.84)");
  }
}

function hitTest(mx, my) {
  for (let i = rects.length - 1; i >= 0; i--) {
    const r = rects[i];
    if (r.kind !== "company") continue;
    if (mx >= r.rx && mx <= r.rw + r.rx && my >= r.ry && my <= r.rh + r.ry) return r;
  }
  return null;
}

function tooltipHighlight(d) {
  const v = modeValue(d);
  return `<span style="color:${colorForScore(v, 1)};font-weight:700;">${MODES[colorMode].label}: ${v}/10</span>`;
}

function currentFocus() {
  return selected || hovered || data[0] || null;
}

function sourceLabel(d) {
  const src = d?.filing_source || "unknown";
  if (src === "sec_10k") return "sec_10k";
  if (src === "seed") return "seed";
  return src;
}

function shareClassLabel(d) {
  if (!Array.isArray(d?.share_classes) || d.share_classes.length <= 1) return "";
  return `Share classes: ${d.share_classes.join(", ")}`;
}

function renderMetricCard(label, score, mean, stddev, range) {
  return `
    <div class="metric-card">
      <div class="metric-head">
        <span class="metric-name">${label}</span>
        <span class="metric-score" style="color:${colorForScore(score, 1)}">${score ?? "?"}/10</span>
      </div>
      <div class="metric-meta">
        <div>Mean<strong>${formatNumber(mean)}</strong></div>
        <div>Stddev<strong>${formatNumber(stddev)}</strong></div>
        <div>Range<strong>${range ?? "?"}</strong></div>
      </div>
    </div>
  `;
}

function sampleDisagreementNote(d) {
  const candidates = [
    { label: "AI Revenue Tailwind", stddev: d.metric_stddevs?.ai_revenue_tailwind ?? 0, range: d.metric_ranges?.ai_revenue_tailwind ?? 0 },
    { label: "Pricing Power Risk", stddev: d.metric_stddevs?.pricing_power_risk ?? 0, range: d.metric_ranges?.pricing_power_risk ?? 0 },
    { label: "Channel Control Risk", stddev: d.metric_stddevs?.channel_control_risk ?? 0, range: d.metric_ranges?.channel_control_risk ?? 0 },
    { label: "AI Operating Leverage", stddev: d.metric_stddevs?.ai_operating_leverage ?? 0, range: d.metric_ranges?.ai_operating_leverage ?? 0 },
    { label: "Data / Distribution Moat", stddev: d.metric_stddevs?.data_distribution_moat ?? 0, range: d.metric_ranges?.data_distribution_moat ?? 0 },
    { label: "AI Infrastructure Exposure", stddev: d.metric_stddevs?.ai_infrastructure_exposure ?? 0, range: d.metric_ranges?.ai_infrastructure_exposure ?? 0 },
  ];
  const top = candidates.sort((a, b) => (b.stddev - a.stddev) || (b.range - a.range))[0];
  if (!top || (top.stddev === 0 && top.range === 0)) {
    return "Samples were fully aligned across all six metrics.";
  }
  const tone =
    top.stddev >= 1 || top.range >= 3 ? "This is the clearest disagreement area across samples." :
    top.stddev >= 0.5 || top.range >= 2 ? "This is the main place where model judgments moved around a bit." :
    "Only mild disagreement showed up, and it was concentrated here.";
  return `${top.label} was the least stable metric (stddev ${formatNumber(top.stddev)}, range ${top.range}). ${tone}`;
}

function updateDetailPanel() {
  const d = currentFocus();
  const panel = document.getElementById("panelContent");
  if (!d) {
    panel.innerHTML = `<div class="panel-sub">No company selected yet.</div>`;
    return;
  }
  const sourceText = selected && selected.slug === d.slug ? "Pinned selection" : hovered && hovered.slug === d.slug ? "Hover preview" : "Top company";
  panel.innerHTML = `
    <div class="panel-title">${d.title}</div>
    <div class="panel-sub">${d.ticker} ? ${d.sector} / ${d.industry}<br>${shareClassLabel(d) || sourceText}</div>
    <div class="panel-links">
      <a href="${d.url}" target="_blank" rel="noreferrer">Open SEC Filing</a>
      <a href="${d.company_url}" target="_blank" rel="noreferrer">Company Site</a>
      ${selected ? '<button type="button" id="clearSelection">Clear Pin</button>' : ""}
    </div>
    <div class="panel-grid">
      <span class="label">Filing source</span><span class="value">${sourceLabel(d)}</span>
      <span class="label">Share classes</span><span class="value">${Array.isArray(d.share_classes) ? d.share_classes.join(", ") : d.ticker}</span>
      <span class="label">Filing date</span><span class="value">${d.filing_date || "n/a"}</span>
      <span class="label">Market cap</span><span class="value">${formatCap(d.market_cap)}</span>
      <span class="label">Revenue</span><span class="value">${formatRevenue(d.revenue)}</span>
      <span class="label">Employees</span><span class="value">${formatEmployees(d.employees)}</span>
      <span class="label">Confidence</span><span class="value">${d.confidence ?? "?"}</span>
      <span class="label">Consistency</span><span class="value">${d.consistency ?? "?"}</span>
      <span class="label">Samples</span><span class="value">${d.sample_size ?? "?"}</span>
      <span class="label">Composite disruption</span><span class="value">${formatNumber(d.disruption)}</span>
      <span class="label">AI composite index</span><span class="value">${formatNumber(d.ai_composite_index)}</span>
      <span class="label">Net score</span><span class="value">${formatNumber(d.net_ai_pressure)}</span>
    </div>
    <div class="metric-list">
      ${renderMetricCard("AI Revenue Tailwind", d.tailwind, d.metric_means?.ai_revenue_tailwind, d.metric_stddevs?.ai_revenue_tailwind, d.metric_ranges?.ai_revenue_tailwind)}
      ${renderMetricCard("Pricing Power Risk", d.pricing_power_risk, d.metric_means?.pricing_power_risk, d.metric_stddevs?.pricing_power_risk, d.metric_ranges?.pricing_power_risk)}
      ${renderMetricCard("Channel Control Risk", d.channel_control_risk, d.metric_means?.channel_control_risk, d.metric_stddevs?.channel_control_risk, d.metric_ranges?.channel_control_risk)}
      ${renderMetricCard("AI Operating Leverage", d.leverage, d.metric_means?.ai_operating_leverage, d.metric_stddevs?.ai_operating_leverage, d.metric_ranges?.ai_operating_leverage)}
      ${renderMetricCard("Data / Distribution Moat", d.moat, d.metric_means?.data_distribution_moat, d.metric_stddevs?.data_distribution_moat, d.metric_ranges?.data_distribution_moat)}
      ${renderMetricCard("AI Infrastructure Exposure", d.infrastructure, d.metric_means?.ai_infrastructure_exposure, d.metric_stddevs?.ai_infrastructure_exposure, d.metric_ranges?.ai_infrastructure_exposure)}
    </div>
    <div class="panel-section">
      <h3>Sample Disagreement Note</h3>
      <div class="panel-summary">${sampleDisagreementNote(d)}</div>
    </div>
    <div class="panel-section">
      <h3>Source Note</h3>
      <div class="panel-summary">${d.filing_source_note || "No source note."}</div>
    </div>
    <div class="panel-section">
      <h3>Summary</h3>
      <div class="panel-summary">${d.summary || "No summary available."}</div>
    </div>
    <div class="panel-section">
      <h3>Evidence</h3>
      <div class="evidence-list">${(d.evidence || []).map(item => `<div>${item}</div>`).join("")}</div>
    </div>
  `;
  const clearBtn = document.getElementById("clearSelection");
  if (clearBtn) {
    clearBtn.addEventListener("click", () => {
      selected = null;
      updateDetailPanel();
      draw();
    });
  }
}

function showTooltip(d, mx, my) {
  const metricStats = activeMetricStats(d);
  const tt = document.getElementById("tooltip");
  tt.querySelector(".tt-title").textContent = `${d.title} (${d.ticker})`;
  tt.querySelector(".tt-sub").textContent = `${d.sector} / ${d.industry}${shareClassLabel(d) ? ` | ${shareClassLabel(d)}` : ""}`;
  tt.querySelector(".tt-highlight").innerHTML = tooltipHighlight(d);
  tt.querySelector(".tt-stats").innerHTML = `
    <span class="label">Filing source</span><span class="value">${sourceLabel(d)}</span>
    <span class="label">Market cap</span><span class="value">${formatCap(d.market_cap)}</span>
    <span class="label">Revenue</span><span class="value">${formatRevenue(d.revenue)}</span>
    <span class="label">Employees</span><span class="value">${formatEmployees(d.employees)}</span>
    <span class="label">Pricing risk</span><span class="value">${d.pricing_power_risk ?? "?"}</span>
    <span class="label">Channel risk</span><span class="value">${d.channel_control_risk ?? "?"}</span>
    <span class="label">Confidence</span><span class="value">${d.confidence ?? "?"}</span>
    <span class="label">Consistency</span><span class="value">${d.consistency ?? "?"}</span>
    <span class="label">Samples</span><span class="value">${d.sample_size ?? "?"}</span>
    <span class="label">Active stddev</span><span class="value">${formatNumber(metricStats.stddev)}</span>
    <span class="label">Active range</span><span class="value">${metricStats.range ?? "?"}</span>
    <span class="label">Net score</span><span class="value">${formatNumber(d.net_ai_pressure)}</span>
    <span class="label">AI composite</span><span class="value">${formatNumber(d.ai_composite_index)}</span>
  `;
  const sourceNote = d.filing_source_note ? `Source note: ${d.filing_source_note}` : "";
  tt.querySelector(".tt-summary").textContent = [d.summary || "", sourceNote].filter(Boolean).join("  |  ");
  let tx = mx + 16;
  let ty = my - 14;
  if (tx + 360 > window.innerWidth) tx = mx - 376;
  if (ty + 220 > window.innerHeight) ty = window.innerHeight - 232;
  tt.style.left = `${tx}px`;
  tt.style.top = `${ty}px`;
  tt.classList.add("visible");
}

function hideTooltip() {
  document.getElementById("tooltip").classList.remove("visible");
}

function weightedAverage(records, accessor) {
  let weighted = 0;
  let total = 0;
  for (const d of records) {
    const v = accessor(d);
    if (v == null || d.market_cap == null) continue;
    weighted += v * d.market_cap;
    total += d.market_cap;
  }
  return total ? weighted / total : 0;
}

function scoreTiers() {
  return [
    { label: "0-2", lo: 0, hi: 2 },
    { label: "3-4", lo: 3, hi: 4 },
    { label: "5-6", lo: 5, hi: 6 },
    { label: "7-8", lo: 7, hi: 8 },
    { label: "9-10", lo: 9, hi: 10 },
  ];
}

function renderTiers(items) {
  return items.map(t => `
    <div class="tier-row">
      <span class="tier-color" style="background:${colorForScore((t.lo + t.hi) / 2, 0.9)}"></span>
      <span class="tier-name">${t.label}</span>
      <span class="tier-value">${formatCap(t.cap)}</span>
    </div>
  `).join("");
}

function renderHbars(items) {
  return items.map(item => `
    <div class="hbar-row">
      <span class="hbar-label">${item.label}</span>
      <div class="hbar-track"><div class="hbar-fill" style="width:${item.pct}%;background:${item.color};"></div></div>
      <span class="hbar-value">${item.value}</span>
    </div>
  `).join("");
}

function updateStats() {
  if (!data.length) {
    document.getElementById("block1").innerHTML = "<h3>Total Market Cap</h3><div class='stat-big'>0</div><div class='stat-label'>No companies for current source filter</div>";
    document.getElementById("block2").innerHTML = "<h3>Mode Average</h3><div class='stat-big'>0.0</div><div class='stat-label'>No data</div>";
    document.getElementById("block3").innerHTML = "<h3>Cap By Score</h3><div class='stat-label'>No data</div>";
    document.getElementById("block4").innerHTML = "<h3>Score Tiers</h3><div class='stat-label'>No data</div>";
    document.getElementById("block5").innerHTML = "<h3>Top Sectors</h3><div class='stat-label'>No data</div>";
    document.getElementById("block6").innerHTML = "<h3>By Revenue Band</h3><div class='stat-label'>No data</div>";
    document.getElementById("block7").innerHTML = "<h3>Avg Consistency</h3><div class='stat-big'>0.00</div><div class='stat-label'>No data</div>";
    document.getElementById("block8").innerHTML = "<h3>Mode Volatility</h3><div class='stat-big'>0.00</div><div class='stat-label'>No data</div>";
    return;
  }
  const totalCap = data.reduce((s, d) => s + (d.market_cap || 0), 0);
  const avg = weightedAverage(data, modeValue);
  const modeMeta = MODES[colorMode];
  const activeKey = modeMetricKey();
  const avgConsistency = data.length ? data.reduce((s, d) => s + (d.consistency || 0), 0) / data.length : 0;
  const avgStddev = data.length ? data.reduce((s, d) => s + (d.metric_stddevs?.[activeKey] || 0), 0) / data.length : 0;
  const avgRange = data.length ? data.reduce((s, d) => s + (d.metric_ranges?.[activeKey] || 0), 0) / data.length : 0;

  document.getElementById("block1").innerHTML = `
    <h3>Total Market Cap</h3>
    <div class="stat-big">${formatCap(totalCap)}</div>
    <div class="stat-label">${data.length} companies in the demo set</div>
  `;

  document.getElementById("block2").innerHTML = `
    <h3>${modeMeta.label}</h3>
    <div class="stat-big" style="color:${colorForScore(avg, 1)}">${avg.toFixed(1)}</div>
    <div class="stat-label">market-cap weighted average</div>
  `;

  const hist = Array.from({ length: 11 }, () => 0);
  for (const d of data) {
    const v = modeValue(d);
    if (v != null && d.market_cap) hist[Math.round(v)] += d.market_cap;
  }
  const histMax = Math.max(...hist, 1);
  document.getElementById("block3").innerHTML = `
    <h3>Cap By Score</h3>
    <div class="histogram">${hist.map((v, i) => `<div class="bar" style="height:${Math.max(4, (v / histMax) * 100)}%;background:${colorForScore(i, 0.9)}"></div>`).join("")}</div>
    <div class="hist-labels"><span>0</span><span>5</span><span>10</span></div>
  `;

  const tiers = scoreTiers().map(t => {
    let cap = 0;
    for (const d of data) {
      const v = modeValue(d);
      if (v != null && d.market_cap && v >= t.lo && v <= t.hi) cap += d.market_cap;
    }
    return { ...t, cap };
  });
  document.getElementById("block4").innerHTML = `<h3>Score Tiers</h3>${renderTiers(tiers)}`;

  const bySector = [...new Set(data.map(d => d.sector))]
    .map(label => {
      const items = data.filter(d => d.sector === label);
      return { label, avg: weightedAverage(items, modeValue) };
    })
    .sort((a, b) => b.avg - a.avg)
    .slice(0, 5);
  document.getElementById("block5").innerHTML = `<h3>Top Sectors</h3>${renderHbars(bySector.map(item => ({
    label: item.label.slice(0, 10),
    pct: item.avg * 10,
    color: colorForScore(item.avg, 0.9),
    value: item.avg.toFixed(1),
  })))} `;

  const revenueBands = [
    { label: "<$50B", lo: 0, hi: 50 },
    { label: "$50-150B", lo: 50, hi: 150 },
    { label: "$150-300B", lo: 150, hi: 300 },
    { label: "$300B+", lo: 300, hi: Infinity },
  ].map(band => {
    const items = data.filter(d => d.revenue != null && d.revenue >= band.lo && d.revenue < band.hi);
    return { label: band.label, avg: weightedAverage(items, modeValue) };
  });
  document.getElementById("block6").innerHTML = `<h3>By Revenue Band</h3>${renderHbars(revenueBands.map(item => ({
    label: item.label,
    pct: item.avg * 10,
    color: colorForScore(item.avg, 0.9),
    value: item.avg.toFixed(1),
  })))} `;

  document.getElementById("block7").innerHTML = `
    <h3>Avg Consistency</h3>
    <div class="stat-big">${avgConsistency.toFixed(2)}</div>
    <div class="stat-label">cross-sample agreement across companies</div>
  `;
  document.getElementById("block8").innerHTML = `
    <h3>Mode Volatility</h3>
    <div class="stat-big">${avgStddev.toFixed(2)}</div>
    <div class="stat-label">avg stddev ? avg range ${avgRange.toFixed(2)}</div>
  `;
}

function passesSourceFilter(d) {
  if (sourceFilter === "all") return true;
  if (sourceFilter === "sec_10k") return d.filing_source === "sec_10k";
  return true;
}

function applyFiltersAndRender() {
  data = allData.filter(passesSourceFilter);
  if (selected && !data.some(d => d.slug === selected.slug)) selected = null;
  if (hovered && !data.some(d => d.slug === hovered.slug)) hovered = null;
  updateStats();
  updateDetailPanel();
  layout();
  draw();
}

function drawGradientLegend() {
  const c = document.getElementById("gradientLegend");
  const gctx = c.getContext("2d");
  for (let x = 0; x < c.width; x++) {
    const t = x / (c.width - 1);
    gctx.fillStyle = greenRedCSS(1 - t, 1);
    gctx.fillRect(x, 0, 1, c.height);
  }
  document.getElementById("legendLow").textContent = MODES[colorMode].low;
  document.getElementById("legendHigh").textContent = MODES[colorMode].high;
}

document.getElementById("colorToggle").addEventListener("click", (e) => {
  const btn = e.target.closest("button[data-mode]");
  if (!btn) return;
  colorMode = btn.dataset.mode;
  document.querySelectorAll("#colorToggle button").forEach(b => b.classList.remove("active"));
  btn.classList.add("active");
  updateStats();
  updateDetailPanel();
  drawGradientLegend();
  draw();
});

document.getElementById("sourceToggle").addEventListener("click", (e) => {
  const btn = e.target.closest("button[data-source]");
  if (!btn) return;
  sourceFilter = btn.dataset.source;
  document.querySelectorAll("#sourceToggle button").forEach(b => b.classList.remove("active"));
  btn.classList.add("active");
  applyFiltersAndRender();
});

canvas.addEventListener("mousemove", (e) => {
  const rect = canvas.getBoundingClientRect();
  const hit = hitTest(e.clientX - rect.left, e.clientY - rect.top);
  if (hit !== hovered) {
    hovered = hit;
    updateDetailPanel();
    draw();
  }
  if (hovered) {
    showTooltip(hovered, e.clientX, e.clientY);
    canvas.style.cursor = "pointer";
  } else {
    hideTooltip();
    canvas.style.cursor = "default";
  }
});

canvas.addEventListener("mouseleave", () => {
  hovered = null;
  hideTooltip();
  updateDetailPanel();
  draw();
});

canvas.addEventListener("click", (e) => {
  const rect = canvas.getBoundingClientRect();
  selected = hitTest(e.clientX - rect.left, e.clientY - rect.top);
  updateDetailPanel();
  draw();
});

window.addEventListener("resize", () => {
  dpr = window.devicePixelRatio || 1;
  layout();
  draw();
});

fetch(`data.json?v=${Date.now()}`, { cache: "no-store" })
  .then(r => r.json())
  .then(rows => {
    allData = rows;
    data = rows.slice();
    selected = data[0] || null;
    updateStats();
    updateDetailPanel();
    drawGradientLegend();
    layout();
    draw();
  })
  .catch((err) => {
    const panel = document.getElementById("panelContent");
    panel.innerHTML = `<div class="panel-sub">Data load failed. Open this page via local server at http://127.0.0.1:8000/ .</div>`;
    console.error("Failed to load data.json:", err);
  });
