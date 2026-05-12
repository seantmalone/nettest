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
  const restBanner = document.getElementById("rest-error-banner");

  let liveSeries = {};
  const MAX_LIVE_POINTS = 1200;
  // W4: rolling x-axis window for the live latency chart. Picked to roughly
  // match the loss heatmap's 30-minute window divided by 6 — still gives
  // enough horizontal density to see per-second twitches but the two
  // stacked charts are within an order of magnitude of each other.
  const LIVE_LATENCY_WINDOW_MS = 5 * 60_000;

  const statusPills = new Map();
  let currentRange = "live";
  const RANGE_MS = { "5m": 5 * 60_000, "15m": 15 * 60_000, "1h": 3_600_000, "24h": 86_400_000, "7d": 7 * 86_400_000 };
  const intervals = [];
  // W6: freeze toggle pauses live-buffer eviction in pushPoint() without
  // switching away from live mode — so you can pin a moment for triage.
  let frozen = false;

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
    if (k.startsWith("http/")) {
      // http probe targets show up as "url:https://host" — strip both the
      // type prefix and the URL scheme so the legend reads "http·host".
      let target = k.slice("http/".length).replace(/^url:/, "").replace(/^https?:\/\//, "");
      return "http·" + target;
    }
    if (k.startsWith("stream/")) {
      // stream targets are "stream/stream:https://host/path" — peel both
      // the duplicate stream: prefix and the URL scheme so the legend
      // shows just the host.
      let target = k.slice("stream/".length).replace(/^stream:/, "").replace(/^https?:\/\//, "");
      return "stream·" + target;
    }
    return k;
  }

  // Even more compact for heatmap Y labels: strip common DNS query suffixes.
  function heatmapLabel(k) {
    return shortLabel(k).replace(/\/(google\.com|dnscheck\.example\.com)$/, "");
  }

  // Pill labels drop the trailing /queryDomain too — what matters in a row
  // of pills is which probe + which server, not which name the DNS query
  // was resolving.
  function pillLabel(k) {
    return shortLabel(k).replace(/\/[^·/]+$/, "");
  }

  // Centralized writer: always rebuilds className so an earlier modifier
  // (e.g. "error") can't bleed through when a later call only updates text.
  // W2 was that checkWsStaleness() set textContent only, leaving a red pill
  // that literally said "live".
  function setWsStatus(text, modifier) {
    wsStatus.textContent = text;
    wsStatus.className = `ws-pill${modifier ? " ws-" + modifier : ""}`;
  }

  // REST endpoint failure tracking. Each entry: { count, lastErr, nextAt }.
  // The banner aggregates active failures so the operator sees "one place
  // to look" instead of a row of ws-error pill flashes.
  const restFailures = new Map();
  function markRestFailure(endpoint, err) {
    const prev = restFailures.get(endpoint) || { count: 0, lastErr: null, nextAt: 0 };
    prev.count += 1;
    prev.lastErr = err && err.message ? err.message : String(err);
    restFailures.set(endpoint, prev);
    renderRestBanner();
  }
  function clearRestFailure(endpoint) {
    if (restFailures.delete(endpoint)) renderRestBanner();
  }
  function renderRestBanner() {
    if (!restBanner) return;
    if (restFailures.size === 0) {
      restBanner.hidden = true;
      restBanner.innerHTML = "";
      return;
    }
    const parts = [];
    for (const [ep, info] of restFailures) {
      parts.push(`<span class="rb-detail">${ep}: ${info.lastErr}${info.count > 1 ? ` (×${info.count})` : ""}</span>`);
    }
    restBanner.innerHTML = `<span class="rb-title">REST error</span>${parts.join(" · ")}`;
    restBanner.hidden = false;
  }

  // Exponential-backoff scheduler for REST pollers — wraps a fetcher fn so
  // persistent 500s don't flood devtools at 30s/5s/10s forever. After a
  // success the delay resets to the configured base.
  function makeBackoff(name, fn, baseMs, maxMs) {
    let nextDelay = baseMs;
    let timer = null;
    let stopped = false;
    async function tick() {
      timer = null;
      if (stopped) return;
      try {
        await fn();
        clearRestFailure(name);
        nextDelay = baseMs;
      } catch (err) {
        markRestFailure(name, err);
        nextDelay = Math.min(maxMs, Math.max(baseMs, nextDelay * 2));
      }
      if (!stopped) timer = setTimeout(tick, nextDelay);
    }
    return {
      start: () => { stopped = false; if (timer == null) timer = setTimeout(tick, 0); },
      stop: () => { stopped = true; if (timer != null) { clearTimeout(timer); timer = null; } },
      kick: () => { if (!stopped) { if (timer != null) clearTimeout(timer); timer = setTimeout(tick, 0); } },
    };
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
    // Cap by point count always, but only evict by time-window when not
    // frozen — freeze lets the operator pin the moment they're looking at.
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
      // W10: pill click affordance is otherwise invisible — title attr
      // makes the behavior discoverable via hover.
      pill.setAttribute("title", "Click to focus this trace · Shift-click to compare");
      pill.addEventListener("click", (e) => {
        e.stopPropagation();
        togglePillFocus(k, pill, e.shiftKey);
      });
      statusRow.appendChild(pill);
      statusPills.set(k, pill);
    }
    const sev = severity || "ok";
    setPillContent(pill, `${pillLabel(k)} ${fmtMs(duration_ms)}`, sev);
    if (isNew) reorderPills();
    return pill;
  }

  // Latency-chart trace isolation. The focus state lives on pill.dataset.focused
  // and is read by renderLatency() so every re-render preserves it; using
  // Plotly.restyle() alone gets clobbered by the next 1Hz renderAll tick.
  //
  // W7: focus is multi-select (shift-click adds; click on a non-focused pill
  // replaces; click on the only focused pill toggles it off). The "Show all"
  // button surfaces whenever at least one pill is focused.
  function focusedPillKeys() {
    const out = new Set();
    for (const [k, p] of statusPills.entries()) {
      if (p.dataset.focused === "true") out.add(k);
    }
    return out;
  }
  const showAllBtn = document.getElementById("show-all-btn");
  function syncShowAll() {
    if (!showAllBtn) return;
    const any = Array.from(statusPills.values()).some(p => p.dataset.focused === "true");
    showAllBtn.hidden = !any;
  }
  function clearTraceFocus() {
    let cleared = false;
    for (const p of statusPills.values()) {
      if (p.dataset.focused === "true") { p.dataset.focused = "false"; cleared = true; }
    }
    if (cleared) { syncShowAll(); renderLatency(); }
  }
  function togglePillFocus(k, pill, additive) {
    if (additive) {
      // Shift-click: toggle this pill independently of the others.
      pill.dataset.focused = pill.dataset.focused === "true" ? "false" : "true";
    } else {
      // Plain click: if this is the only focused pill, clear; otherwise
      // replace the focus set with just this pill.
      const focused = focusedPillKeys();
      if (focused.size === 1 && focused.has(k)) {
        pill.dataset.focused = "false";
      } else {
        for (const p of statusPills.values()) p.dataset.focused = "false";
        pill.dataset.focused = "true";
      }
    }
    syncShowAll();
    renderLatency();
  }
  if (showAllBtn) {
    showAllBtn.addEventListener("click", clearTraceFocus);
  }
  // Click anywhere that isn't a pill / show-all clears focus.
  document.addEventListener("click", (e) => {
    if (e.target.closest(".status-pill")) return;
    if (e.target.closest("#show-all-btn")) return;
    clearTraceFocus();
  });

  function refreshHealthFromPills() {
    let crit = 0, warn = 0;
    const critNames = [];
    for (const [k, pill] of statusPills.entries()) {
      if (pill.dataset.sev === "crit") { crit++; critNames.push(pillLabel(k)); }
      else if (pill.dataset.sev === "warn") warn++;
    }
    updateHealthBar(crit, warn, statusPills.size, critNames);
  }

  function updateHealthBar(critCount, warnCount, totalProbes, critNames) {
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
      // Inline the failing probe names so the operator doesn't have to
      // scan the pill row to identify what's broken. Cap to 6 names to
      // keep the bar readable on narrow viewports.
      let names = "";
      if (critNames && critNames.length) {
        const shown = critNames.slice(0, 6).join(", ");
        const more = critNames.length > 6 ? `, +${critNames.length - 6} more` : "";
        names = `: ${shown}${more}`;
      }
      healthText.textContent = `${critCount} critical${names}`;
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

  // Authoritative snapshot from the DB. Used for initial paint + a fallback
  // (with exponential backoff) while the WS handler keeps pills live in
  // between. Also the only place that prunes pills whose probe/target
  // stopped reporting. Returns a Promise so makeBackoff() can drive it.
  function refreshStatus() {
    return fetch("/api/status")
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
      });
  }

  function refreshSysinfo() {
    if (!sysinfoRow) return Promise.resolve();
    return fetch("/api/sysinfo")
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
      });
  }

  // W12: include both from= and to= so the export exactly matches the
  // plotted window. Live mode exports the rolling 5-min latency window so
  // "Export CSV" returns what's actually on screen, not a stale 1h slab.
  function updateExportLink() {
    if (!exportLink) return;
    const now = Date.now();
    let fromMs, toMs = now, hintText;
    if (currentRange === "live") {
      fromMs = now - LIVE_LATENCY_WINDOW_MS;
      hintText = `last ${fmtDuration(LIVE_LATENCY_WINDOW_MS)} (live)`;
    } else {
      fromMs = now - RANGE_MS[currentRange];
      hintText = `last ${currentRange}`;
    }
    exportLink.href = `/api/export.csv?from=${fromMs}&to=${toMs}`;
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
      .then(rows => { clearRestFailure("results"); return rows; })
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
      .catch(err => markRestFailure("results", err));
  }

  if (rangeNav) {
    rangeNav.addEventListener("click", (e) => {
      const btn = e.target.closest("button[data-range]");
      if (btn) setRange(btn.dataset.range);
    });
  }

  // W6: Freeze button — pauses the rolling x-axis window so the operator
  // can pin "the moment things broke" without flipping out of Live. New
  // results still flow into liveSeries (capped by MAX_LIVE_POINTS) so when
  // unfreezing the chart re-anchors to "now".
  const freezeBtn = document.getElementById("freeze-btn");
  if (freezeBtn) {
    freezeBtn.addEventListener("click", () => {
      frozen = !frozen;
      freezeBtn.classList.toggle("active", frozen);
      freezeBtn.setAttribute("aria-pressed", frozen ? "true" : "false");
      freezeBtn.textContent = frozen ? "Frozen" : "Freeze";
      allDirty = true;
      renderAll();
    });
  }

  // W6: ?from=…&to=… deep-link support. When both are present at load
  // time we paint that fixed window once via the same /api/results path
  // setRange uses. The values are integer ms-epoch.
  function applyDeepLink() {
    const params = new URLSearchParams(location.search);
    const fromS = params.get("from");
    const toS = params.get("to");
    if (!fromS || !toS) return false;
    const from = parseInt(fromS, 10), to = parseInt(toS, 10);
    if (!Number.isFinite(from) || !Number.isFinite(to) || to <= from) return false;
    currentRange = "custom";
    if (rangeNav) {
      rangeNav.querySelectorAll("button").forEach(b => {
        b.classList.remove("active"); b.setAttribute("aria-pressed", "false");
      });
    }
    fetch(`/api/results?from=${from}&to=${to}`)
      .then(r => r.ok ? r.json() : Promise.reject(new Error(`HTTP ${r.status}`)))
      .then(rows => {
        clearRestFailure("results");
        liveSeries = {};
        for (const row of rows) {
          const k = key(row.probe, row.target);
          const series = liveSeries[k] || (liveSeries[k] = []);
          const ts = row.ts != null ? new Date(row.ts) : new Date(row.ts_bucket);
          const ok = row.ts != null ? row.ok : (row.ok_count || 0) > 0;
          const dur = row.ts != null ? row.duration_ms : row.p50_ms;
          series.push({ ts, duration_ms: dur, ok, metrics: row.metrics || {} });
        }
        allDirty = true;
        renderAll();
        if (exportHint) exportHint.textContent = `(${new Date(from).toLocaleString()} – ${new Date(to).toLocaleString()})`;
        if (exportLink) exportLink.href = `/api/export.csv?from=${from}&to=${to}`;
      })
      .catch(err => markRestFailure("results", err));
    return true;
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

  // Explicit palette for latency lines — avoids Plotly's default green/red
  // which would visually conflict with the ok/crit severity colors used
  // throughout the rest of the UI.
  const LINE_COLORS = [
    "#58a6ff", "#a78bfa", "#34d399", "#fb923c",
    "#e879f9", "#22d3ee", "#facc15", "#94a3b8",
  ];

  // Latency-chart threshold reference lines, in y-data units (ms). The log
  // axis makes these read as evenly-spaced horizontals.
  const LATENCY_REF_SHAPES = [
    { type: "line", xref: "paper", yref: "y", x0: 0, x1: 1, y0: 10,  y1: 10,
      line: { color: "rgba(62,207,142,0.30)", width: 1, dash: "dot" } },
    { type: "line", xref: "paper", yref: "y", x0: 0, x1: 1, y0: 100, y1: 100,
      line: { color: "rgba(234,179,8,0.30)",  width: 1, dash: "dot" } },
    { type: "line", xref: "paper", yref: "y", x0: 0, x1: 1, y0: 500, y1: 500,
      line: { color: "rgba(239,68,68,0.30)",  width: 1, dash: "dot" } },
  ];

  // Wi-Fi RSSI threshold bands as Plotly rects — anchors the raw dBm number
  // to human meaning: excellent / fair / poor.
  const WIFI_BAND_SHAPES = [
    { type: "rect", xref: "paper", yref: "y", x0: 0, x1: 1, y0: -60, y1: -30,
      fillcolor: "rgba(62,207,142,0.06)", line: { width: 0 }, layer: "below" },
    { type: "rect", xref: "paper", yref: "y", x0: 0, x1: 1, y0: -70, y1: -60,
      fillcolor: "rgba(234,179,8,0.06)",  line: { width: 0 }, layer: "below" },
    { type: "rect", xref: "paper", yref: "y", x0: 0, x1: 1, y0: -100, y1: -70,
      fillcolor: "rgba(239,68,68,0.06)",  line: { width: 0 }, layer: "below" },
  ];

  function renderLatency() {
    const focused = focusedPillKeys();
    const focusActive = focused.size > 0;
    // W7 focus: when at least one pill is focused, hidden traces dim to
    // 0.15 AND their legend entries get a "·" prefix so the legend reads
    // as what's drawn rather than advertising hidden series. Plotly has
    // no real "dim legend item" so we differentiate via the label prefix.
    const traces = Object.entries(liveSeries).map(([name, pts], i) => {
      const isHidden = focusActive && !focused.has(name);
      const label = shortLabel(name);
      const t = {
        x: pts.map(p => p.ts), y: pts.map(p => p.duration_ms),
        name: isHidden ? `· ${label}` : label,
        mode: "lines", type: "scattergl",
        line: { color: LINE_COLORS[i % LINE_COLORS.length], width: 1.5 },
      };
      if (focusActive) t.opacity = isHidden ? 0.15 : 1;
      return t;
    });
    // W4/W14: pin the live x-axis to a 5-minute rolling window so:
    //   (a) it lines up better with the loss heatmap (30min) — same order
    //   (b) re-layouts don't happen on every tick (no autorange refit).
    // Ranged modes (1h / 24h / 7d) keep autorange so historic data fills.
    const xaxis = { gridcolor: "rgba(255,255,255,0.08)" };
    if (currentRange === "live" && !frozen) {
      const now = Date.now();
      xaxis.range = [new Date(now - LIVE_LATENCY_WINDOW_MS), new Date(now)];
      xaxis.type = "date";
    }
    Plotly.react("latency", traces, {
      ...baseLayout,
      margin: { l: 55, r: 10, t: 10, b: 70 },
      yaxis: { type: "log", title: "ms", dtick: 1, gridcolor: "rgba(255,255,255,0.08)" },
      xaxis,
      legend: { orientation: "h", y: -0.3, x: 0, xanchor: "left", font: { size: 10 } },
      shapes: LATENCY_REF_SHAPES,
    }, { displayModeBar: "hover", responsive: true }).then(attachLatencyClickHandler);
  }

  // W13: Plotly fires plotly_click on a clicked trace point. We attach the
  // handler once after the first react() (Plotly clears handlers on every
  // react, so re-attach is idempotent). The keys() of liveSeries match the
  // trace index, so we resolve probe/target from curveNumber.
  let _latencyClickAttached = false;
  function attachLatencyClickHandler() {
    const el = document.getElementById("latency");
    if (!el || _latencyClickAttached) return;
    _latencyClickAttached = true;
    el.on("plotly_click", (ev) => {
      if (!ev || !ev.points || !ev.points.length) return;
      const pt = ev.points[0];
      const traceNames = Object.keys(liveSeries);
      const seriesKey = traceNames[pt.curveNumber];
      if (!seriesKey) return;
      const ts = (pt.x instanceof Date) ? pt.x.getTime() : new Date(pt.x).getTime();
      openDrillDown(seriesKey, ts);
    });
  }

  function openDrillDown(seriesKey, tsMs) {
    const panel = document.getElementById("drill-down");
    const title = document.getElementById("drill-title");
    const body = document.getElementById("drill-body");
    if (!panel || !body) return;
    const [probe, target] = seriesKey.split(/\/(.+)/);
    // Pad the query window ±15s around the clicked point so we catch the
    // exact row even if the timestamp resolution differs slightly.
    const from = tsMs - 15_000;
    const to = tsMs + 15_000;
    if (title) title.textContent = `${pillLabel(seriesKey)} @ ${new Date(tsMs).toLocaleTimeString()}`;
    body.innerHTML = `<div class="drill-empty">Loading…</div>`;
    panel.hidden = false;
    panel.setAttribute("aria-hidden", "false");
    requestAnimationFrame(() => panel.classList.remove("drill-hidden"));
    fetch(`/api/results?probe=${encodeURIComponent(probe)}&target=${encodeURIComponent(target)}&from=${from}&to=${to}`)
      .then(r => r.ok ? r.json() : Promise.reject(new Error(`HTTP ${r.status}`)))
      .then(rows => {
        if (!rows.length) {
          body.innerHTML = `<div class="drill-empty">No matching results in ±15s window</div>`;
          return;
        }
        // Pick the row closest to the clicked timestamp.
        rows.sort((a, b) => Math.abs((a.ts ?? a.ts_bucket) - tsMs) - Math.abs((b.ts ?? b.ts_bucket) - tsMs));
        const r = rows[0];
        const metrics = r.metrics || {};
        const metricsRows = Object.entries(metrics)
          .map(([k, v]) => `<tr><th>${k}</th><td>${v == null ? "—" : (typeof v === "object" ? JSON.stringify(v) : v)}</td></tr>`)
          .join("");
        body.innerHTML = `
          <table>
            <tr><th>Probe</th><td>${probe}</td></tr>
            <tr><th>Target</th><td>${target}</td></tr>
            <tr><th>Timestamp</th><td>${r.ts != null ? new Date(r.ts).toLocaleString() : new Date(r.ts_bucket).toLocaleString()}</td></tr>
            <tr><th>OK</th><td>${r.ok != null ? String(!!r.ok) : "—"}</td></tr>
            <tr><th>Duration</th><td>${r.duration_ms != null ? fmtMs(r.duration_ms) : "—"}</td></tr>
            ${r.error ? `<tr><th>Error</th><td class="col-err">${escapeHtml(r.error)}</td></tr>` : ""}
            ${metricsRows ? `<tr><th colspan="2" style="padding-top:10px">Metrics</th></tr>${metricsRows}` : ""}
          </table>
        `;
      })
      .catch(err => { body.innerHTML = `<div class="drill-empty">Error: ${escapeHtml(err.message)}</div>`; });
  }
  function closeDrillDown() {
    const panel = document.getElementById("drill-down");
    if (!panel) return;
    panel.classList.add("drill-hidden");
    panel.setAttribute("aria-hidden", "true");
    setTimeout(() => { panel.hidden = true; }, 200);
  }
  function escapeHtml(s) {
    return String(s).replace(/[&<>"']/g, c =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
  }
  document.getElementById("drill-close")?.addEventListener("click", closeDrillDown);
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape") closeDrillDown();
  });

  function renderLossHeatmap() {
    const targets = Object.keys(liveSeries).sort();
    if (targets.length === 0) return;
    const now = Date.now();
    const bucketMs = 30000;
    const buckets = 60;
    const x = [];
    for (let i = 0; i < buckets; i++) x.push(new Date(now - (buckets - i - 1) * bucketMs));
    // W4: emit null for buckets that have no samples so the heatmap renders
    // those cells in the layout's plot_bgcolor rather than the colorscale's
    // zero color — "no signal" is now visually distinct from "0% loss".
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
      return row.map((fail, i) => cnt[i] ? (fail / cnt[i]) * 100 : null);
    });
    Plotly.react("loss-heatmap",
      // zmax: 10 (not 50) — for this tool, 5% loss is already bad and the
      // top-of-scale should signal "broken" rather than "literally 50%".
      // Any loss >= 10% saturates to full red.
      [{
        x, y: targets.map(heatmapLabel), z,
        type: "heatmap", colorscale: "Reds", zmin: 0, zmax: 10,
        hoverongaps: false,
      }],
      {
        ...baseLayout,
        // W5: automargin lets Plotly size the left gutter to the longest
        // label rather than truncating at a fixed 150px. We still set a
        // small explicit margin so the gutter has padding when labels are
        // short, then automargin will grow as needed.
        margin: { l: 60, r: 10, t: 10, b: 30 },
        // Dark grey plot bg so null-data cells (gaps in the heatmap) read
        // as "no signal", clearly different from the white-ish zero end of
        // the Reds colorscale that means "healthy".
        plot_bgcolor: "#1a1f26",
        xaxis: { gridcolor: "rgba(255,255,255,0.08)" },
        yaxis: { gridcolor: "rgba(255,255,255,0.08)", automargin: true },
      },
      { displayModeBar: "hover", responsive: true });
  }

  function renderHttpTiming() {
    const httpCard = document.getElementById("http-card");
    const httpPlot = document.getElementById("http-timing");
    const httpPlaceholder = document.getElementById("http-placeholder");
    const httpEntries = Object.entries(liveSeries).filter(([k]) => k.startsWith("http/"));
    // W9: collapse the HTTP card when no data so it doesn't reserve ~287px
    // of empty real estate.
    if (httpEntries.length === 0) {
      if (httpCard) httpCard.classList.add("empty");
      if (httpPlaceholder) httpPlaceholder.hidden = false;
      if (httpPlot) httpPlot.hidden = true;
      return;
    }
    if (httpCard) httpCard.classList.remove("empty");
    if (httpPlaceholder) httpPlaceholder.hidden = true;
    if (httpPlot) httpPlot.hidden = false;
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
    // <3 points reads as "not enough yet"; we show a styled empty-state
    // <p> in place of the chart rather than overlaying text on an empty
    // dark rectangle.
    if (totalPts < 3) {
      // W9: also collapse the entire card height when there's no data
      // so empty wifi/http/stream cards don't waste vertical real estate.
      if (wifiCard) wifiCard.classList.add("empty");
      if (wifiPlaceholder) wifiPlaceholder.hidden = false;
      if (wifiPlot) wifiPlot.hidden = true;
      return;
    }
    if (wifiCard) wifiCard.classList.remove("empty");
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
      shapes: WIFI_BAND_SHAPES,
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

  function renderAllImmediate() {
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

  // W14: coalesce render calls to one every 250ms so high-cadence probes
  // (10 probes × 1Hz) don't trigger 10 Plotly.react passes per second.
  // The 1s setInterval still drives idle ticks; this throttle only kicks
  // in when WS messages stack up between intervals.
  const RENDER_THROTTLE_MS = 250;
  let renderTimer = null;
  let lastRenderTs = 0;
  function renderAll() {
    const now = Date.now();
    const since = now - lastRenderTs;
    if (since >= RENDER_THROTTLE_MS) {
      if (renderTimer != null) { clearTimeout(renderTimer); renderTimer = null; }
      lastRenderTs = now;
      renderAllImmediate();
    } else if (renderTimer == null) {
      renderTimer = setTimeout(() => {
        renderTimer = null;
        lastRenderTs = Date.now();
        renderAllImmediate();
      }, RENDER_THROTTLE_MS - since);
    }
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

  // Absolute HH:MM:SS clock format — used for the grouped-event first–last
  // span where relative timestamps would be ambiguous.
  function fmtEventClock(ts) {
    const d = new Date(ts);
    return d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
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
  // W11: track both first-seen (_ts_first) and the full list of
  // occurrences (_items) so the collapsed row shows "first–last (×N)"
  // and the operator can expand to see individual events.
  function groupEvents(events) {
    const out = [];
    for (const ev of events) {
      const k = `${ev.kind}|${ev.severity}|${ev.target ?? ""}`;
      const prev = out[out.length - 1];
      if (prev && prev._key === k) {
        prev._count = (prev._count || 1) + 1;
        prev._items.push(ev);
        prev.ts_end = ev.ts_end;
        prev.summary = ev.summary;
      } else {
        out.push({ ...ev, _key: k, _count: 1, _ts_first: ev.ts_end, _items: [ev] });
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
    return fetch(`/api/events?from=${now - eventsWindowMs()}&to=${now}`)
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
          // W11: when grouped, show first–last span instead of just last.
          // Single events keep the relative "just now" / "Nm ago" form.
          time.textContent = e._count > 1
            ? `${fmtEventClock(e._ts_first)}–${fmtEventClock(e.ts_end)}`
            : fmtEventTime(e.ts_end);

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
          // W11: when more than one occurrence, render a <details> below
          // the row that, when expanded, lists each occurrence with its
          // own timestamp and summary so the operator can audit the burst.
          if (e._count > 1) {
            const det = document.createElement("details");
            det.className = "ev-occurrences";
            const sum = document.createElement("summary");
            sum.textContent = `${e._count} occurrences`;
            det.appendChild(sum);
            const ol = document.createElement("ol");
            for (const occ of e._items) {
              const oi = document.createElement("li");
              oi.className = "ev-occ";
              oi.textContent = `${fmtEventClock(occ.ts_end)}  ${occ.summary}`;
              ol.appendChild(oi);
            }
            det.appendChild(ol);
            li.appendChild(det);
          }
          eventsList.appendChild(li);
        }
      });
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
      sysinfoPoller.kick();
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
  // in 10+ seconds. Above 60s we flip the modifier to "stale" (yellow) and
  // format the duration with fmtDuration() so the operator reads "live · 4h
  // 49m ago" as the obviously-wrong-state it is, not "live · 17368s ago".
  function checkWsStaleness() {
    if (!wsLive) return;
    const staleness = Date.now() - lastMessageTs;
    if (staleness > 60_000) {
      setWsStatus(`no data · ${fmtDuration(staleness)} ago`, "stale");
    } else if (staleness > 10_000) {
      setWsStatus(`live · ${Math.round(staleness / 1000)}s ago`, "live");
    } else {
      setWsStatus("live", "live");
    }
  }

  // Wrapped pollers with exponential backoff so persistent 500s back off
  // from 30s → 60s → 120s → 5min instead of pounding the server forever.
  const statusPoller = makeBackoff("status", () => refreshStatus(),     30_000, 300_000);
  const eventsPoller = makeBackoff("events", () => refreshEvents(),      5_000, 300_000);
  const sysinfoPoller = makeBackoff("sysinfo", () => refreshSysinfo(),  10_000, 300_000);

  function startIntervals() {
    if (intervals.length) return;
    statusPoller.start();
    eventsPoller.start();
    sysinfoPoller.start();
    intervals.push(setInterval(renderAll, 1000));
    intervals.push(setInterval(checkWsStaleness, 1000));
  }

  function stopIntervals() {
    for (const id of intervals) clearInterval(id);
    intervals.length = 0;
    statusPoller.stop();
    eventsPoller.stop();
    sysinfoPoller.stop();
  }

  document.addEventListener("visibilitychange", () => {
    if (document.hidden) {
      stopIntervals();
    } else {
      startIntervals();
      // Kick each poller to fetch immediately rather than waiting out the
      // current backoff window — the user just came back to the tab.
      statusPoller.kick();
      eventsPoller.kick();
      sysinfoPoller.kick();
      allDirty = true;
      renderAll();
    }
  });

  const deepLinked = applyDeepLink();
  if (!deepLinked) updateExportLink();
  startIntervals();
  connectWs();
})();
