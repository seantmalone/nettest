(function () {
  const wsStatus = document.getElementById("ws-status");
  const eventsList = document.getElementById("events-list");
  const statusRow = document.getElementById("status-row");

  let liveSeries = {};
  const MAX_LIVE_POINTS = 1200;

  function key(probe, target) { return `${probe}/${target}`; }

  function pushPoint(r) {
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

  function refreshStatus() {
    fetch("/api/status").then(r => r.json()).then(rows => {
      statusRow.innerHTML = "";
      for (const row of rows) {
        const pill = document.createElement("span");
        const sev = row.ok ? "ok" : "crit";
        pill.className = `status-pill ${sev}`;
        const dur = row.duration_ms == null ? "—" : `${row.duration_ms.toFixed(0)}ms`;
        pill.textContent = `${row.probe}/${row.target}: ${dur}`;
        statusRow.appendChild(pill);
      }
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
    if (wifiEntries.length === 0) return;
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
    if (entries.length === 0) return;
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

  function refreshEvents() {
    const now = Date.now();
    fetch(`/api/events?from=${now - 24 * 3600 * 1000}&to=${now}`).then(r => r.json()).then(events => {
      eventsList.innerHTML = "";
      for (const e of events.slice(-50).reverse()) {
        const li = document.createElement("li");
        li.className = e.severity;
        const time = new Date(e.ts_end).toLocaleTimeString();
        li.textContent = `${time} [${e.severity}] ${e.kind}: ${e.summary}`;
        eventsList.appendChild(li);
      }
    });
  }

  function connectWs() {
    const proto = location.protocol === "https:" ? "wss" : "ws";
    const ws = new WebSocket(`${proto}://${location.host}/ws/live`);
    ws.onopen = () => { wsStatus.textContent = "live"; };
    ws.onclose = () => { wsStatus.textContent = "disconnected"; setTimeout(connectWs, 2000); };
    ws.onmessage = (msg) => {
      const r = JSON.parse(msg.data);
      pushPoint(r);
    };
  }

  setInterval(refreshStatus, 2000);
  setInterval(renderAll, 1000);
  setInterval(refreshEvents, 5000);
  refreshStatus();
  refreshEvents();
  connectWs();
})();
