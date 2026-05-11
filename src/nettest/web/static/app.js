(function () {
  const wsStatus = document.getElementById("ws-status");
  const eventsList = document.getElementById("events-list");
  const statusRow = document.getElementById("status-row");
  const sysinfoRow = document.getElementById("sysinfo-row");
  const wifiCard = document.getElementById("wifi-card");
  const wifiPlot = document.getElementById("wifi");
  const wifiPlaceholder = document.getElementById("wifi-placeholder");
  const streamCard = document.getElementById("stream-card");
  const exportLink = document.getElementById("export-csv");
  const exportHint = document.getElementById("export-hint");
  const rangeNav = document.querySelector("header nav");
  const healthBar = document.getElementById("health-bar");
  const healthDot = healthBar ? healthBar.querySelector(".health-dot") : null;
  const healthText = healthBar ? healthBar.querySelector(".health-text") : null;

  let liveSeries = {};
  const MAX_LIVE_POINTS = 1200;

  const statusPills = new Map();
  let currentRange = "live";
  const RANGE_MS = { "1h": 3_600_000, "24h": 86_400_000, "7d": 7 * 86_400_000 };
  const intervals = [];

  // Render-skip state. Only chart sections whose contributing keys changed
  // since the last tick get re-drawn — idle ticks become no-ops.
  const dirtyKeys = new Set();
  let allDirty = true;

  function key(probe, target) { return `${probe}/${target}`; }

  function fmt(v) { return v == null || v === "" ? "—" : String(v); }

  function fmtMs(v) {
    if (v == null) return "—";
    return v < 10 ? `${v.toFixed(1)}ms` : `${v.toFixed(0)}ms`;
  }

  function fmtDuration(ms) {
    if (ms < 60_000) return `${Math.round(ms / 1000)}s`;
    if (ms < 3_600_000) return `${Math.round(ms / 60_000)}m`;
    if (ms < 86_400_000) return `${Math.round(ms / 3_600_000)}h`;
    return `${Math.round(ms / 86_400_000)}d`;
  }

  // Compact label for chart legends, status pills, x-axis labels:
  //   dns_cached/dns:1.1.1.3/google.com -> dns·1.1.1.3/google.com
  //   dns_uncached/dns:8.8.8.8/dnscheck.example.com -> udns·8.8.8.8/dnscheck.example.com
  //   ping/host:1.1.1.1 -> ping·1.1.1.1
  //   tcp/host:443 or tcp_connect/host:1.1.1.1:443 -> tcp·...
  //   traceroute/host:10.200.0.1 -> tr·10.200.0.1
  //   http/https://google.com -> http·google.com
  //   wifi/host:.local -> wifi·.local
  //   stream/https://... -> stream·...
  function shortLabel(k) {
    if (k.startsWith("dns_cached/dns:"))   return "dns·"   + k.slice("dns_cached/dns:".length);
    if (k.startsWith("dns_uncached/dns:")) return "udns·"  + k.slice("dns_uncached/dns:".length);
    if (k.startsWith("ping/host:"))        return "ping·"  + k.slice("ping/host:".length);
    if (k.startsWith("tcp/host:"))         return "tcp·"   + k.slice("tcp/host:".length);
    if (k.startsWith("tcp_connect/host:")) return "tcp·"   + k.slice("tcp_connect/host:".length);
    if (k.startsWith("traceroute/host:"))  return "tr·"    + k.slice("traceroute/host:".length);
    if (k.startsWith("wifi/host:"))        return "wifi·"  + k.slice("wifi/host:".length);
    if (k.startsWith("http/"))   return "http·"   + k.slice("http/".length).replace(/^https?:\/\//, "");
    if (k.startsWith("stream/")) return "stream·" + k.slice("stream/".length).replace(/^https?:\/\//, "");
    return k;
  }

  // Even more compact for heatmap Y labels: strip common DNS query suffixes.
  function heatmapLabel(k) {
    return shortLabel(k).replace(/\/(google\.com|dnscheck\.example\.com)$/, "");
  }

  function setWsStatus(text, modifier) {
    wsStatus.textContent = text;
    wsStatus.className = `ws-pill${modifier ? " ws-" + modifier : ""}`;
  }

  function pushPoint(r) {
    if (currentRange !== "live") return;
    const k = key(r.probe, r.target);
    const series = liveSeries[k] || (liveSeries[k] = []);
    series.push({
      ts: new Date(r.ts),
      duration_ms: r.duration_ms,
      ok: r.ok,
      metrics: r.metrics || {},
    });
    if (series.length > MAX_LIVE_POINTS) series.shift();
    dirtyKeys.add(k);
  }

  function setPillContent(pill, text, severity) {
    if (pill.dataset.text !== text) {
      pill.textContent = text;
      pill.dataset.text = text;
    }
    if (pill.dataset.sev !== severity) {
      pill.className = `status-pill ${severity}`;
      pill.dataset.sev = severity;
    }
  }

  // Order probe groups left-to-right by intuitive read order; unknown probes
  // sort to the end. dns_cached + dns_uncached share the "dns" group so they
  // sit adjacent in the row.
  const PROBE_ORDER = [
    "ping", "dns_cached", "dns_uncached", "tcp_connect",
    "http", "traceroute", "mtu", "wifi", "stream", "bandwidth",
  ];
  function probeOrderIdx(probe) {
    const i = PROBE_ORDER.indexOf(probe);
    return i === -1 ? PROBE_ORDER.length : i;
  }
  function probeGroup(probe) {
    if (probe.startsWith("dns")) return "dns";
    if (probe.startsWith("tcp")) return "tcp";
    return probe;
  }

  // Reattach pills in probe-group order and insert hairline separators between
  // groups. Runs after refreshStatus and after upsertPill creates a new pill;
  // in-place text/severity updates via the WS path don't trigger a reorder.
  function reorderPills() {
    const entries = Array.from(statusPills.entries()).sort(([a, pa], [b, pb]) => {
      const probeA = a.split("/")[0];
      const probeB = b.split("/")[0];
      const oa = probeOrderIdx(probeA);
      const ob = probeOrderIdx(probeB);
      if (oa !== ob) return oa - ob;
      return a.localeCompare(b);
    });
    statusRow.querySelectorAll(".pill-sep").forEach(s => s.remove());
    let prevGroup = null;
    for (const [k, pill] of entries) {
      const g = probeGroup(k.split("/")[0]);
      if (prevGroup != null && g !== prevGroup) {
        const sep = document.createElement("span");
        sep.className = "pill-sep";
        statusRow.appendChild(sep);
      }
      statusRow.appendChild(pill);
      prevGroup = g;
    }
  }

  function upsertPill(probe, target, duration_ms, severity) {
    const k = key(probe, target);
    let pill = statusPills.get(k);
    const isNew = !pill;
    if (isNew) {
      pill = document.createElement("span");
      pill.dataset.probe = probe;
      pill.addEventListener("click", (e) => {
        e.stopPropagation();
        togglePillFocus(k, pill);
      });
      statusRow.appendChild(pill);
      statusPills.set(k, pill);
    }
    const sev = severity || "ok";
    setPillContent(pill, `${shortLabel(k)} ${fmtMs(duration_ms)}`, sev);
    if (isNew) reorderPills();
    return pill;
  }

  // Latency-chart trace isolation. The focus state lives on pill.dataset.focused
  // and is read by renderLatency() so every re-render preserves it; using
  // Plotly.restyle() alone gets clobbered by the next 1Hz renderAll tick.
  function focusedPillKey() {
    for (const [k, p] of statusPills.entries()) {
      if (p.dataset.focused === "true") return k;
    }
    return null;
  }
  function clearTraceFocus() {
    let cleared = false;
    for (const p of statusPills.values()) {
      if (p.dataset.focused === "true") { p.dataset.focused = "false"; cleared = true; }
    }
    if (cleared) renderLatency();
  }
  function togglePillFocus(k, pill) {
    if (pill.dataset.focused === "true") { clearTraceFocus(); return; }
    for (const p of statusPills.values()) p.dataset.focused = "false";
    pill.dataset.focused = "true";
    renderLatency();
  }
  // Click anywhere that isn't a pill clears focus.
  document.addEventListener("click", (e) => {
    if (e.target.closest(".status-pill")) return;
    clearTraceFocus();
  });

  function refreshHealthFromPills() {
    let crit = 0, warn = 0;
    for (const pill of statusPills.values()) {
      if (pill.dataset.sev === "crit") crit++;
      else if (pill.dataset.sev === "warn") warn++;
    }
    updateHealthBar(crit, warn, statusPills.size);
  }

  function updateHealthBar(critCount, warnCount, totalProbes) {
    if (!healthBar || !healthDot || !healthText) return;
    if (totalProbes === 0) {
      healthBar.setAttribute("data-state", "ok");
      healthDot.textContent = "●";
      healthText.textContent = "Waiting for first probe…";
      return;
    }
    if (critCount > 0) {
      healthBar.setAttribute("data-state", "crit");
      healthDot.textContent = "✕";
      healthText.textContent = `${critCount} probe${critCount === 1 ? "" : "s"} critical`;
    } else if (warnCount > 0) {
      healthBar.setAttribute("data-state", "warn");
      healthDot.textContent = "⚠";
      healthText.textContent = `${warnCount} probe${warnCount === 1 ? "" : "s"} degraded`;
    } else {
      healthBar.setAttribute("data-state", "ok");
      healthDot.textContent = "●";
      healthText.textContent = "All probes OK";
    }
  }

  // Authoritative snapshot from the DB. Used for initial paint + a 30s
  // fallback while the WS handler keeps pills live in between. Also the
  // only place that prunes pills whose probe/target stopped reporting.
  function refreshStatus() {
    fetch("/api/status")
      .then(r => r.ok ? r.json() : Promise.reject(new Error(`HTTP ${r.status}`)))
      .then(rows => {
        const seen = new Set();
        for (const row of rows) {
          const sev = row.severity || (row.ok ? "ok" : "crit");
          upsertPill(row.probe, row.target, row.duration_ms, sev);
          seen.add(key(row.probe, row.target));
        }
        for (const [k, pill] of statusPills) {
          if (!seen.has(k)) {
            pill.remove();
            statusPills.delete(k);
          }
        }
        reorderPills();
        refreshHealthFromPills();
      })
      .catch(err => setWsStatus(`status error: ${err.message}`, "error"));
  }

  function refreshSysinfo() {
    if (!sysinfoRow) return;
    fetch("/api/sysinfo")
      .then(r => r.ok ? r.json() : Promise.reject(new Error(`HTTP ${r.status}`)))
      .then(info => {
        let ssidLabel;
        if (info.wifi_ssid && info.wifi_ssid !== "<redacted>") {
          ssidLabel = info.wifi_ssid;
        } else if (info.wifi_bssid) {
          ssidLabel = `(hidden) ${info.wifi_bssid}`;
        } else if (info.wifi_ssid === "<redacted>" || info.wifi_signal_dbm != null) {
          ssidLabel = "(SSID hidden by macOS)";
        } else {
          ssidLabel = null;
        }
        const wifi = info.wifi_signal_dbm == null
          ? fmt(ssidLabel)
          : `${fmt(ssidLabel)} (${info.wifi_signal_dbm} dBm)`;
        const items = [
          ["Host", fmt(info.host)],
          ["Wi-Fi", wifi],
          ["Local IP", fmt(info.local_ip)],
          ["Interface", fmt(info.default_iface)],
          ["Gateway", fmt(info.default_gateway)],
          ["Public IP", fmt(info.public_ip)],
        ];
        sysinfoRow.innerHTML = items
          .map(([k, v]) => `<span class="item"><span class="label">${k}:</span><span class="value">${v}</span></span>`)
          .join("");
      })
      .catch(err => setWsStatus(`sysinfo error: ${err.message}`, "error"));
  }

  function updateExportLink() {
    if (!exportLink) return;
    const now = Date.now();
    let fromMs;
    let hintText;
    if (currentRange === "live") {
      fromMs = now - 3_600_000;
      hintText = "last 1h";
    } else {
      fromMs = now - RANGE_MS[currentRange];
      hintText = `last ${currentRange}`;
    }
    exportLink.href = `/api/export.csv?from=${fromMs}`;
    if (exportHint) exportHint.textContent = `(${hintText})`;
  }

  function setRange(range) {
    if (range === currentRange) return;
    currentRange = range;
    if (rangeNav) {
      rangeNav.querySelectorAll("button").forEach(btn => {
        const active = btn.dataset.range === range;
        btn.classList.toggle("active", active);
        btn.setAttribute("aria-pressed", active ? "true" : "false");
      });
    }
    updateExportLink();
    // The events panel should reflect whatever window the user just chose.
    refreshEvents();
    if (range === "live") {
      liveSeries = {};
      allDirty = true;
      renderAll();
      return;
    }
    const now = Date.now();
    const from = now - RANGE_MS[range];
    fetch(`/api/results?from=${from}&to=${now}`)
      .then(r => r.ok ? r.json() : Promise.reject(new Error(`HTTP ${r.status}`)))
      .then(rows => {
        liveSeries = {};
        for (const row of rows) {
          const k = key(row.probe, row.target);
          const series = liveSeries[k] || (liveSeries[k] = []);
          if (row.ts != null) {
            series.push({
              ts: new Date(row.ts),
              duration_ms: row.duration_ms,
              ok: row.ok,
              metrics: row.metrics || {},
            });
          } else {
            series.push({
              ts: new Date(row.ts_bucket),
              duration_ms: row.p50_ms,
              ok: (row.ok_count || 0) > 0,
              metrics: {},
            });
          }
        }
        allDirty = true;
        renderAll();
      })
      .catch(err => setWsStatus(`range fetch error: ${err.message}`, "error"));
  }

  if (rangeNav) {
    rangeNav.addEventListener("click", (e) => {
      const btn = e.target.closest("button[data-range]");
      if (btn) setRange(btn.dataset.range);
    });
  }

  // Digit keys 1-4 switch range. Skipped while typing into inputs/textareas
  // and when modifier keys are held so browser shortcuts still fire.
  const KEY_TO_RANGE = { "1": "live", "2": "1h", "3": "24h", "4": "7d" };
  document.addEventListener("keydown", (e) => {
    if (e.metaKey || e.ctrlKey || e.altKey) return;
    const tag = e.target && e.target.tagName;
    if (tag === "INPUT" || tag === "TEXTAREA" || (e.target && e.target.isContentEditable)) return;
    const range = KEY_TO_RANGE[e.key];
    if (range) { e.preventDefault(); setRange(range); }
  });

  const baseLayout = {
    paper_bgcolor: "transparent", plot_bgcolor: "transparent",
    font: { color: "#e6edf3", size: 11 },
  };

  function renderLatency() {
    const focused = focusedPillKey();
    const traces = Object.entries(liveSeries).map(([name, pts]) => {
      const t = {
        x: pts.map(p => p.ts), y: pts.map(p => p.duration_ms),
        name: shortLabel(name), mode: "lines", type: "scattergl",
      };
      if (focused) t.opacity = name === focused ? 1 : 0.15;
      return t;
    });
    Plotly.react("latency", traces, {
      ...baseLayout,
      margin: { l: 55, r: 10, t: 10, b: 70 },
      yaxis: { type: "log", title: "ms", dtick: 1, gridcolor: "rgba(255,255,255,0.08)" },
      xaxis: { gridcolor: "rgba(255,255,255,0.08)" },
      legend: { orientation: "h", y: -0.3, x: 0, xanchor: "left", font: { size: 10 } },
    }, { displayModeBar: false, responsive: true });
  }

  function renderLossHeatmap() {
    const targets = Object.keys(liveSeries).sort();
    if (targets.length === 0) return;
    const now = Date.now();
    const bucketMs = 30000;
    const buckets = 60;
    const x = [];
    for (let i = 0; i < buckets; i++) x.push(new Date(now - (buckets - i - 1) * bucketMs));
    const z = targets.map(t => {
      const pts = liveSeries[t];
      const row = new Array(buckets).fill(0);
      const cnt = new Array(buckets).fill(0);
      for (const p of pts) {
        const idx = Math.floor((p.ts.getTime() - (now - buckets * bucketMs)) / bucketMs);
        if (idx >= 0 && idx < buckets) {
          cnt[idx]++;
          if (!p.ok) row[idx]++;
        }
      }
      return row.map((fail, i) => cnt[i] ? (fail / cnt[i]) * 100 : 0);
    });
    Plotly.react("loss-heatmap",
      [{ x, y: targets.map(heatmapLabel), z, type: "heatmap", colorscale: "Reds", zmin: 0, zmax: 50 }],
      {
        ...baseLayout,
        margin: { l: 150, r: 10, t: 10, b: 30 },
        xaxis: { gridcolor: "rgba(255,255,255,0.08)" },
        yaxis: { gridcolor: "rgba(255,255,255,0.08)", automargin: false },
      },
      { displayModeBar: false, responsive: true });
  }

  function renderHttpTiming() {
    const httpEntries = Object.entries(liveSeries).filter(([k]) => k.startsWith("http/"));
    if (httpEntries.length === 0) return;
    const xLabels = httpEntries.map(([k]) => shortLabel(k));
    // Average over a time window rather than a fixed count of results, so the
    // chart compares apples-to-apples across targets with different probe
    // cadences. Live mode uses last 60s; ranged views use the range itself.
    const windowMs = currentRange === "live" ? 60_000 : RANGE_MS[currentRange];
    const cutoffMs = Date.now() - windowMs;
    const avg = (pts, k) => {
      const vals = pts
        .filter(p => p.ts.getTime() > cutoffMs)
        .map(p => p.metrics?.[k])
        .filter(v => v != null);
      return vals.length ? vals.reduce((a, b) => a + b, 0) / vals.length : 0;
    };
    const traces = ["dns_ms", "connect_ms", "tls_ms", "ttfb_ms"].map(k => ({
      x: xLabels,
      y: httpEntries.map(([_, pts]) => avg(pts, k)),
      name: k, type: "bar",
    }));
    const titleEl = document.getElementById("http-title");
    if (titleEl) titleEl.textContent = `HTTP timing breakdown (avg last ${fmtDuration(windowMs)})`;
    Plotly.react("http-timing", traces, {
      ...baseLayout,
      margin: { l: 55, r: 10, t: 10, b: 70 },
      barmode: "stack",
      xaxis: { gridcolor: "rgba(255,255,255,0.08)" },
      yaxis: { title: "ms", gridcolor: "rgba(255,255,255,0.08)" },
      legend: { orientation: "h", y: -0.3, x: 0, xanchor: "left", font: { size: 10 } },
    }, { displayModeBar: false, responsive: true });
  }

  function renderWifi() {
    const wifiEntries = Object.entries(liveSeries).filter(([k]) => k.startsWith("wifi/"));
    const totalPts = wifiEntries.reduce((s, [, pts]) => s + pts.length, 0);
    if (totalPts < 3) {
      if (wifiPlaceholder) wifiPlaceholder.hidden = false;
      if (wifiPlot) wifiPlot.hidden = true;
      return;
    }
    if (wifiPlaceholder) wifiPlaceholder.hidden = true;
    if (wifiPlot) wifiPlot.hidden = false;
    const traces = wifiEntries.map(([name, pts]) => ({
      x: pts.map(p => p.ts),
      y: pts.map(p => p.metrics?.rssi_dbm ?? null),
      name: shortLabel(name), mode: "lines",
    }));
    Plotly.react("wifi", traces, {
      ...baseLayout,
      margin: { l: 55, r: 10, t: 10, b: 30 },
      xaxis: { autorange: true, gridcolor: "rgba(255,255,255,0.08)" },
      yaxis: { autorange: true, title: "dBm", gridcolor: "rgba(255,255,255,0.08)" },
    }, { displayModeBar: false, responsive: true });
  }

  function renderStream() {
    const entries = Object.entries(liveSeries).filter(([k]) => k.startsWith("stream/"));
    if (entries.length === 0) {
      if (streamCard) streamCard.hidden = true;
      return;
    }
    if (streamCard) streamCard.hidden = false;
    const traces = entries.map(([name, pts]) => ({
      x: pts.map(p => p.ts),
      y: pts.map(p => p.metrics?.throughput_mbps ?? 0),
      name: shortLabel(name), fill: "tozeroy", mode: "lines",
    }));
    Plotly.react("stream-throughput", traces, {
      ...baseLayout,
      margin: { l: 55, r: 10, t: 10, b: 30 },
      xaxis: { gridcolor: "rgba(255,255,255,0.08)" },
      yaxis: { title: "Mbps", gridcolor: "rgba(255,255,255,0.08)" },
    }, { displayModeBar: false, responsive: true });
  }

  function renderAll() {
    const renderEverything = allDirty;
    allDirty = false;
    const hadAnyDirty = renderEverything || dirtyKeys.size > 0;
    let httpDirty = renderEverything;
    let wifiDirty = renderEverything;
    let streamDirty = renderEverything;
    if (!renderEverything) {
      for (const k of dirtyKeys) {
        if (k.startsWith("http/")) httpDirty = true;
        else if (k.startsWith("wifi/")) wifiDirty = true;
        else if (k.startsWith("stream/")) streamDirty = true;
      }
    }
    dirtyKeys.clear();
    if (!hadAnyDirty) return;
    // Latency + heatmap show all series, so any new key dirties both.
    renderLatency();
    renderLossHeatmap();
    if (httpDirty) renderHttpTiming();
    if (wifiDirty) renderWifi();
    if (streamDirty) renderStream();
  }

  function fmtEventTime(ts) {
    const d = new Date(ts);
    const now = new Date();
    const sameDay = d.getFullYear() === now.getFullYear()
      && d.getMonth() === now.getMonth()
      && d.getDate() === now.getDate();
    if (!sameDay) return d.toLocaleString();
    const diffMs = now.getTime() - d.getTime();
    if (diffMs < 45_000) return "just now";
    if (diffMs < 3_600_000) return `${Math.floor(diffMs / 60_000)}m ago`;
    return d.toLocaleTimeString();
  }

  // Normalize backend severity ("critical") to badge class ("crit").
  function badgeClass(sev) {
    if (sev === "critical") return "crit";
    return sev || "ok";
  }

  // Collapse consecutive same-(kind, severity, target) events into one
  // representative with a count. Backend events don't carry an explicit
  // target field — the ?? '' makes the key resolve to kind|severity| so
  // a burst of latency_spike warns groups regardless of probe target.
  // The group adopts the LATEST occurrence's ts_end + summary so the
  // displayed time is "just now" rather than the oldest in the burst.
  function groupEvents(events) {
    const out = [];
    for (const ev of events) {
      const k = `${ev.kind}|${ev.severity}|${ev.target ?? ""}`;
      const prev = out[out.length - 1];
      if (prev && prev._key === k) {
        prev._count = (prev._count || 1) + 1;
        prev.ts_end = ev.ts_end;
        prev.summary = ev.summary;
      } else {
        out.push({ ...ev, _key: k, _count: 1 });
      }
    }
    return out;
  }

  function eventsWindowMs() {
    // Live mode shows the last hour of events so the panel isn't empty in a
    // healthy stretch; ranged modes match the chart window so the user sees
    // exactly the period they're investigating.
    return currentRange === "live" ? 3_600_000 : (RANGE_MS[currentRange] || 86_400_000);
  }

  function refreshEvents() {
    const now = Date.now();
    fetch(`/api/events?from=${now - eventsWindowMs()}&to=${now}`)
      .then(r => r.ok ? r.json() : Promise.reject(new Error(`HTTP ${r.status}`)))
      .then(events => {
        const grouped = groupEvents(events);
        eventsList.innerHTML = "";
        if (grouped.length === 0) {
          const li = document.createElement("li");
          li.className = "event-empty";
          li.textContent = "No events in this window";
          eventsList.appendChild(li);
          return;
        }
        for (const e of grouped.slice(-50).reverse()) {
          const sev = badgeClass(e.severity);
          const li = document.createElement("li");
          li.className = `event-item severity-${sev}`;

          const time = document.createElement("span");
          time.className = "ev-time";
          time.textContent = fmtEventTime(e.ts_end);

          const badge = document.createElement("span");
          badge.className = `ev-badge ${sev}`;
          badge.textContent = sev;

          const body = document.createElement("span");
          body.className = "ev-body";
          body.textContent = `${e.kind}: ${e.summary}`;

          li.append(time, badge, body);
          if (e._count > 1) {
            const count = document.createElement("span");
            count.className = "ev-count";
            count.textContent = `×${e._count}`;
            li.appendChild(count);
          }
          eventsList.appendChild(li);
        }
      })
      .catch(err => setWsStatus(`events error: ${err.message}`, "error"));
  }

  let wsAttempt = 0;
  let reconnectTimer = null;
  let wsLive = false;
  let lastMessageTs = Date.now();

  function reconnectDelayMs() {
    const base = Math.min(30_000, 1000 * Math.pow(2, wsAttempt));
    const jitter = base * 0.2 * (Math.random() * 2 - 1);
    return Math.max(500, base + jitter);
  }

  function connectWs() {
    reconnectTimer = null;
    const proto = location.protocol === "https:" ? "wss" : "ws";
    let ws;
    try {
      ws = new WebSocket(`${proto}://${location.host}/ws/live`);
    } catch (err) {
      scheduleReconnect();
      return;
    }
    ws.onopen = () => {
      wsLive = true; lastMessageTs = Date.now();
      setWsStatus("live", "live"); wsAttempt = 0;
      // A reconnect can follow an interface flip — refresh sysinfo immediately
      // so the displayed IP/gateway match the path we're actually on now.
      refreshSysinfo();
    };
    ws.onclose = () => { wsLive = false; scheduleReconnect(); };
    ws.onerror = () => { /* onclose will follow */ };
    ws.onmessage = (msg) => {
      lastMessageTs = Date.now();
      let m;
      try { m = JSON.parse(msg.data); } catch { return; }
      if (m.kind === "result") {
        pushPoint(m);
        // WS-driven pill update: avoids the 2s polling latency the old
        // setInterval(refreshStatus, 2000) had. The 30s refreshStatus
        // fallback still runs to prune pills whose probe disappeared.
        upsertPill(m.probe, m.target, m.duration_ms, m.severity);
        refreshHealthFromPills();
      } else if (m.kind === "event") {
        refreshEvents();
      }
    };
  }

  function scheduleReconnect() {
    if (reconnectTimer != null) return;
    const delay = reconnectDelayMs();
    wsAttempt++;
    setWsStatus(`disconnected — retrying in ${Math.round(delay / 1000)}s`, "error");
    reconnectTimer = setTimeout(connectWs, delay);
  }

  // The ws-status text shows "live · Ns ago" when no WS message has arrived
  // in 10+ seconds. Only textContent is touched so the className stays at
  // ws-pill ws-live — the pill color doesn't flicker, only the text.
  function checkWsStaleness() {
    if (!wsLive) return;
    const staleness = Date.now() - lastMessageTs;
    if (staleness > 10_000) {
      const t = `live · ${Math.round(staleness / 1000)}s ago`;
      if (wsStatus.textContent !== t) wsStatus.textContent = t;
    } else if (wsStatus.textContent !== "live") {
      wsStatus.textContent = "live";
    }
  }

  function startIntervals() {
    if (intervals.length) return;
    // Status pills are now driven by the WS onmessage handler; this 30s
    // poll is just a fallback in case the WS is disconnected, and it
    // also handles pruning pills whose probe stopped reporting.
    intervals.push(setInterval(refreshStatus, 30000));
    intervals.push(setInterval(renderAll, 1000));
    intervals.push(setInterval(refreshEvents, 5000));
    // Sysinfo at 10s so an interface flip during diagnosis surfaces fast;
    // also retriggered explicitly on WS reconnect (see connectWs.onopen).
    intervals.push(setInterval(refreshSysinfo, 10_000));
    intervals.push(setInterval(checkWsStaleness, 1000));
  }

  function stopIntervals() {
    for (const id of intervals) clearInterval(id);
    intervals.length = 0;
  }

  document.addEventListener("visibilitychange", () => {
    if (document.hidden) {
      stopIntervals();
    } else {
      startIntervals();
      refreshStatus();
      refreshEvents();
      refreshSysinfo();
      allDirty = true;
      renderAll();
    }
  });

  updateExportLink();
  refreshSysinfo();
  refreshStatus();
  refreshEvents();
  startIntervals();
  connectWs();
})();
