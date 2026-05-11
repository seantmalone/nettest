(function () {
  const wsStatus = document.getElementById("ws-status");
  const eventsList = document.getElementById("events-list");
  const statusRow = document.getElementById("status-row");
  const wifiCard = document.getElementById("wifi");
  const streamCard = document.getElementById("stream-throughput");
  const exportLink = document.getElementById("export-csv");
  const exportHint = document.getElementById("export-hint");
  const rangeNav = document.querySelector("header nav");

  let liveSeries = {};
  const MAX_LIVE_POINTS = 1200;

  const statusPills = new Map();
  let currentRange = "live";
  const RANGE_MS = { "1h": 3_600_000, "24h": 86_400_000, "7d": 7 * 86_400_000 };
  const intervals = [];

  function key(probe, target) { return `${probe}/${target}`; }

  function setWsStatus(text, modifier) {
    wsStatus.textContent = text;
    wsStatus.className = modifier ? `ws-${modifier}` : "";
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

  function refreshStatus() {
    fetch("/api/status")
      .then(r => r.ok ? r.json() : Promise.reject(new Error(`HTTP ${r.status}`)))
      .then(rows => {
        const seen = new Set();
        for (const row of rows) {
          const k = key(row.probe, row.target);
          seen.add(k);
          let pill = statusPills.get(k);
          if (!pill) {
            pill = document.createElement("span");
            statusRow.appendChild(pill);
            statusPills.set(k, pill);
          }
          const dur = row.duration_ms == null ? "—" : `${row.duration_ms.toFixed(0)}ms`;
          const sev = row.severity || (row.ok ? "ok" : "crit");
          setPillContent(pill, `${row.probe}/${row.target}: ${dur}`, sev);
        }
        for (const [k, pill] of statusPills) {
          if (!seen.has(k)) {
            pill.remove();
            statusPills.delete(k);
          }
        }
      })
      .catch(err => setWsStatus(`status error: ${err.message}`, "error"));
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
    if (range === "live") {
      liveSeries = {};
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

  const baseLayout = {
    paper_bgcolor: "transparent", plot_bgcolor: "transparent",
    font: { color: "#e6edf3" }, margin: { l: 40, r: 10, t: 30, b: 30 },
  };

  function renderLatency() {
    const traces = Object.entries(liveSeries).map(([name, pts]) => ({
      x: pts.map(p => p.ts), y: pts.map(p => p.duration_ms),
      name, mode: "lines", type: "scattergl",
    }));
    Plotly.react("latency", traces,
      { ...baseLayout, title: "Latency over time" },
      { displayModeBar: false });
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
      [{ x, y: targets, z, type: "heatmap", colorscale: "Reds", zmin: 0, zmax: 50 }],
      { ...baseLayout, title: "Packet loss % (target × time)" },
      { displayModeBar: false });
  }

  function renderHttpTiming() {
    const httpEntries = Object.entries(liveSeries).filter(([k]) => k.startsWith("http/"));
    if (httpEntries.length === 0) return;
    const targets = httpEntries.map(([k]) => k);
    const avg = (pts, k) => {
      const vals = pts.slice(-20).map(p => p.metrics?.[k]).filter(v => v != null);
      return vals.length ? vals.reduce((a, b) => a + b, 0) / vals.length : 0;
    };
    const traces = ["dns_ms", "connect_ms", "tls_ms", "ttfb_ms"].map(k => ({
      x: targets,
      y: httpEntries.map(([_, pts]) => avg(pts, k)),
      name: k, type: "bar",
    }));
    Plotly.react("http-timing", traces,
      { ...baseLayout, title: "HTTP timing breakdown (avg last 20)", barmode: "stack" },
      { displayModeBar: false });
  }

  function renderWifi() {
    const wifiEntries = Object.entries(liveSeries).filter(([k]) => k.startsWith("wifi/"));
    if (wifiEntries.length === 0) {
      if (wifiCard) wifiCard.classList.add("hidden");
      return;
    }
    if (wifiCard) wifiCard.classList.remove("hidden");
    const traces = wifiEntries.map(([name, pts]) => ({
      x: pts.map(p => p.ts),
      y: pts.map(p => p.metrics?.rssi_dbm ?? null),
      name, mode: "lines",
    }));
    Plotly.react("wifi", traces,
      { ...baseLayout, title: "Wi-Fi signal (dBm)" },
      { displayModeBar: false });
  }

  function renderStream() {
    const entries = Object.entries(liveSeries).filter(([k]) => k.startsWith("stream/"));
    if (entries.length === 0) {
      if (streamCard) streamCard.classList.add("hidden");
      return;
    }
    if (streamCard) streamCard.classList.remove("hidden");
    const traces = entries.map(([name, pts]) => ({
      x: pts.map(p => p.ts),
      y: pts.map(p => p.metrics?.throughput_mbps ?? 0),
      name, fill: "tozeroy", mode: "lines",
    }));
    Plotly.react("stream-throughput", traces,
      { ...baseLayout, title: "Streaming throughput (Mbps)" },
      { displayModeBar: false });
  }

  function renderAll() {
    renderLatency();
    renderLossHeatmap();
    renderHttpTiming();
    renderWifi();
    renderStream();
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

  function refreshEvents() {
    const now = Date.now();
    fetch(`/api/events?from=${now - 24 * 3600 * 1000}&to=${now}`)
      .then(r => r.ok ? r.json() : Promise.reject(new Error(`HTTP ${r.status}`)))
      .then(events => {
        eventsList.innerHTML = "";
        for (const e of events.slice(-50).reverse()) {
          const li = document.createElement("li");
          li.className = e.severity;
          li.textContent = `${fmtEventTime(e.ts_end)} [${e.severity}] ${e.kind}: ${e.summary}`;
          eventsList.appendChild(li);
        }
      })
      .catch(err => setWsStatus(`events error: ${err.message}`, "error"));
  }

  let wsAttempt = 0;
  let reconnectTimer = null;

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
    ws.onopen = () => { setWsStatus("live", "live"); wsAttempt = 0; };
    ws.onclose = () => { scheduleReconnect(); };
    ws.onerror = () => { /* onclose will follow */ };
    ws.onmessage = (msg) => {
      let m;
      try { m = JSON.parse(msg.data); } catch { return; }
      if (m.kind === "result") {
        pushPoint(m);
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

  function startIntervals() {
    if (intervals.length) return;
    intervals.push(setInterval(refreshStatus, 2000));
    intervals.push(setInterval(renderAll, 1000));
    intervals.push(setInterval(refreshEvents, 5000));
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
      renderAll();
    }
  });

  updateExportLink();
  refreshStatus();
  refreshEvents();
  startIntervals();
  connectWs();
})();
