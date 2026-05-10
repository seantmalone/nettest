# nettest — Network Diagnostic Utility Design

**Date:** 2026-05-10
**Status:** Design approved, ready for implementation planning
**Author:** Sean (with Claude)

## Problem

Sean's home network has intermittent failures — pages sometimes refuse to load, but eventually succeed after several retries. Standard tools (`ping`, `traceroute`, browser dev tools) only catch issues that happen to be present when run; the failures are too brief and irregular for one-shot diagnosis.

Goal: a continuously-running utility that probes the network at high frequency (multiple times per second on cheap probes), detects intermittent failure *patterns*, and presents results live so Sean can correlate failures with what he is observing in the browser. It must run on multiple machines (Mac and Windows) at different network locations to triangulate where in the path the problem lies.

## Goals

- Detect sub-second connectivity blips that current tools miss.
- Differentiate failure classes: LAN vs ISP vs DNS vs specific destination vs Wi-Fi.
- Run on Mac and Windows from a single Python codebase.
- Provide both a rich live terminal view and a richer web dashboard with historical charts.
- Persist all results for later analysis.
- Enable comparison across machines without depending on the network itself (each machine standalone).

## Non-Goals

- Not a centralized monitoring system — no agent/collector architecture (would itself fail when the network is broken, which is exactly when we need data).
- Not a continuous SaaS service — single-user, run-when-needed.
- Not a packet capture / DPI tool — operates at the application/socket layer.
- No alerting/paging integration in v1 (events are surfaced in-app only).

## Architecture

```
                    ┌─────────────────────────────────────────┐
                    │         nettest (single process)         │
                    │                                          │
  Config (YAML) ──▶ │  Scheduler ─▶ Probe Pool ─▶ Result Bus  │
                    │     ▲              │             │       │
                    │     │              ▼             ▼       │
                    │  Probes:      Pattern        Sinks:      │
                    │  - ping       Detector      - SQLite     │
                    │  - dns        (consumes     - JSONL      │
                    │  - http        results,    - TUI         │
                    │  - tcp         emits        - Web (WS)   │
                    │  - trace       events)                   │
                    │  - bandwidth                              │
                    │  - stream                                 │
                    │  - mtu                                    │
                    │  - wifi                                   │
                    └─────────────────────────────────────────┘
                                       │
                                       ▼
                              ./data/<host>/
                                ├─ results.db        (SQLite)
                                └─ YYYY-MM-DD.jsonl  (one per day)
```

- **Single asyncio process.** All probes run as coroutines on one event loop, scheduled at independent cadences.
- **Result bus.** In-memory fan-out (one `asyncio.Queue` per consumer). Decouples probes from outputs; new probes or new outputs are isolated changes.
- **Consumers:** storage sinks (SQLite + JSONL), pattern detector, TUI renderer, web server (WebSocket pusher).
- **Consumer registration interface:**
  ```python
  bus.subscribe(
      name: str,
      drop_policy: Literal["never", "drop_oldest"],
      max_depth: int = 1000,
  ) -> asyncio.Queue
  ```
- **Backpressure policy.** Storage and pattern detector subscribe with `drop_policy="never"`. UI consumers (TUI, WS) subscribe with `drop_policy="drop_oldest"`, `max_depth=1000`; drops increment a logged counter surfaced in the TUI status bar.

### Why one process

- I/O-bound workload — asyncio handles thousands of concurrent probes easily.
- Simpler deployment: one `pip install`, one process to launch on each machine.
- Lower failure surface than a multi-process design with IPC.
- Scheduler can crash-recover individual probes without restarting the whole tool.

## Probes

Every probe implements:

```python
class Probe:
    name: str
    interval_ms: int
    timeout_ms: int

    def __init__(self, config: ProbeConfig): ...

    async def run(
        self,
        target: Target,
        cancel: asyncio.Event,
    ) -> Result: ...
```

- `ProbeConfig` is the relevant slice of the parsed config (timeouts, resolver lists, packet sizes, etc.) — passed at construction so `run()` doesn't re-read config per call.
- `cancel` is set by the scheduler when the tool is shutting down or the probe is being paused; probes must observe it within their timeout window.
- The scheduler invokes each probe at its cadence per target. Probes are isolated — they don't know about storage, UI, or each other.

| Probe | Default cadence | What it measures | Implementation |
|---|---|---|---|
| `ping` | 250 ms | RTT (ms), success/timeout | `icmplib` (unprivileged ICMP datagram on Mac/Windows; Linux requires sysctl tweak or falls back to TCP-connect probe) |
| `dns_cached` | 250 ms | Resolve time for stable name (e.g. `google.com`) | Direct query via `dnspython` to each configured resolver |
| `dns_uncached` | 250 ms | Resolve time for `<uuid>.<probe-domain>` | Forces full recursive lookup; probe-domain configurable |
| `http` | 2 s | DNS, TCP, TLS, TTFB, total, status, size | `httpx` with timing event hooks |
| `tcp_connect` | 2 s | Time to open TCP socket to host:port | Stdlib `asyncio.open_connection` |
| `traceroute` | 60 s | Per-hop IP, RTT (3 samples), loss | `scapy` UDP traceroute, or system `traceroute`/`tracert` |
| `stream` | continuous, restart every 60 s | Throughput, stall events (>200 ms gap), jitter | `httpx` streaming GET against a configurable large-file URL (Cloudflare/Cachefly) |
| `mtu` | 5 min | Largest non-fragmented packet size | Binary-search ping with DF bit (1500→576) |
| `bandwidth` | 5 min | Mbps down (~10 MB) | Lighter throughput snapshot than `stream` |
| `wifi` | 1 s | RSSI, SSID, BSSID, channel, link rate, noise | Mac: `airport -I`; Windows: `netsh wlan show interfaces`; skipped on Ethernet |

**Targets** come from config. Cheap probes (ping/DNS) iterate all targets per cycle. Expensive probes (traceroute, bandwidth) stagger targets across cycles to amortize cost.

## Smart-default targets

Auto-detected at startup, plus fixed defaults:

- `auto:gateway` — default route address (catches LAN/Wi-Fi vs internet split)
- `auto:system` — OS DNS resolvers
- Public anycast resolvers: `1.1.1.1`, `8.8.8.8`, `9.9.9.9`
- HTTP targets: `https://www.google.com`, `https://www.cloudflare.com`, plus user's ISP homepage

Layered intentionally: a failure pattern that hits gateway → ISP DNS → public DNS → public HTTP narrows down which segment of the path is at fault.

## Result record

Every probe emits one `Result`:

```python
{
  "ts": "2026-05-10T18:42:31.241Z",   # UTC, ms precision
  "host": "sean-mbp",                  # machine hostname
  "probe": "http",
  "target": "https://google.com",
  "ok": true,
  "duration_ms": 89.4,
  "error": null,
  "metrics": {
    "dns_ms": 3.1, "connect_ms": 12.0, "tls_ms": 24.0,
    "ttfb_ms": 50.3, "status": 200, "size_bytes": 14823
  },
  "tags": []                           # populated by pattern detector
}
```

UTC in storage, local time in UI — important for cross-machine comparison across timezones.

## Storage

**Layout per machine:**

```
./data/<hostname>/
  results.db                 # SQLite, all results + events + rollups
  2026-05-10.jsonl           # daily JSONL, append-only
  2026-05-09.jsonl
  ...
  nettest.log                # tool's own diagnostic log
```

**Schema:**

```sql
CREATE TABLE results (
  id          INTEGER PRIMARY KEY,
  ts          INTEGER NOT NULL,        -- unix ms, UTC
  probe       TEXT NOT NULL,
  target      TEXT NOT NULL,
  ok          INTEGER NOT NULL,
  duration_ms REAL,
  error       TEXT,
  metrics     TEXT                     -- JSON blob
);
CREATE INDEX idx_results_ts          ON results(ts);
CREATE INDEX idx_results_probe_tgt_ts ON results(probe, target, ts);

CREATE TABLE events (
  id          INTEGER PRIMARY KEY,
  ts_start    INTEGER NOT NULL,
  ts_end      INTEGER NOT NULL,
  kind        TEXT NOT NULL,           -- micro_outage, dns_only_fail, gateway_loss, ...
  severity    TEXT NOT NULL,           -- info, warn, critical
  summary     TEXT NOT NULL,
  details     TEXT                     -- JSON
);
CREATE INDEX idx_events_ts ON events(ts_start);

CREATE TABLE rollups_1m (
  ts_bucket   INTEGER NOT NULL,        -- minute boundary, unix ms
  probe       TEXT NOT NULL,
  target      TEXT NOT NULL,
  count       INTEGER NOT NULL,
  ok_count    INTEGER NOT NULL,
  loss_pct    REAL NOT NULL,
  p50_ms      REAL,
  p95_ms      REAL,
  p99_ms      REAL,
  max_ms      REAL,
  PRIMARY KEY (ts_bucket, probe, target)
);

CREATE TABLE rollups_1h (
  ts_bucket   INTEGER NOT NULL,        -- hour boundary, unix ms
  probe       TEXT NOT NULL,
  target      TEXT NOT NULL,
  count       INTEGER NOT NULL,
  ok_count    INTEGER NOT NULL,
  loss_pct    REAL NOT NULL,
  p50_ms      REAL,
  p95_ms      REAL,
  p99_ms      REAL,
  max_ms      REAL,
  PRIMARY KEY (ts_bucket, probe, target)
);
```

**Rollup pipeline.** Per-minute rollups computed every 60 s from raw `results`. Per-hour rollups computed every 60 s from `rollups_1m` (cheap aggregation, never touches raw rows).

**Retention defaults:**
- `results` (raw): 7 days
- `rollups_1m`: 90 days
- `rollups_1h`: 365 days
- `events`: forever (small)
- JSONL files: kept until manually deleted

**Dashboard query strategy:** time range < 1 hr → raw `results`; 1 hr–24 hr → `rollups_1m`; > 24 hr → `rollups_1h`. Keeps long-range charts fast.

**JSONL format:** one line per `Result`, the verbatim JSON encoding of the `Result` record shown above — no extra framing, no header. New daily file rolls over at **UTC midnight** (matching the UTC `Result.ts` so SQLite and JSONL stay aligned and cross-machine timestamps are unambiguous).

**Writes are batched** every 100 ms or 50 records (whichever first) so we don't fsync per probe.

**Retention ordering invariant:** the rollup pipeline must compute the next minute's rollup *before* the retention task prunes raw rows from that minute's window. In practice this is trivial (rollups run every 60 s, retention runs once an hour, raw retention is 7 days), but the implementation must explicitly enforce ordering rather than relying on schedule luck — e.g., retention reads the latest `ts_bucket` from `rollups_1m` and refuses to delete `results` rows newer than that.

## Pattern detection

A consumer of the result bus that maintains a 30-second rolling window in memory and re-evaluates rules on each new result. Detected patterns become `events` rows and tag the contributing `results`.

**Default rules (all thresholds configurable):**

| Pattern | Trigger | Severity |
|---|---|---|
| `micro_outage` | ≥ 3 consecutive failures on same target within 2 s | warn |
| `correlated_loss` | ≥ 3 distinct targets fail within 1.5 s window | critical |
| `latency_spike` | latency > 5× rolling p95, ≥ 30 sample baseline | warn |
| `dns_only_fail` | ≥ 2 DNS failures with 0 other-probe failures in 2 s | warn |
| `stream_stall` | ≥ 2 stall events in `stream` probe within 1 minute | warn |
| `wifi_drop` | RSSI delta > 10 dB in < 5 s | info |
| `mtu_change` | working MTU size decreases | warn |

This is the differentiator. Raw stats tell you *something failed*; patterns tell you *what kind of something*, which is what Sean needs to debug an intermittent issue.

## TUI

**Framework:** Textual. True-color, mouse, Nerd Font icons, keybindings, animations, panels, tabs, snapshot-testable.

**Layout sections:**

1. **Header bar** — host, uptime, total probes, total fails, current time
2. **Health summary** — five status rows (LAN, Internet, DNS, Wi-Fi, Streaming) each with a colored dot and one-line plain-English status
3. **Targets panel** — one row per (probe, target): icon, last value, p95, loss%, 30-second sparkline. Color: green/yellow/red on `Last` and `Loss%` based on configurable thresholds.
4. **Events panel** — most recent 5–10 events, color-coded by severity, click-to-jump
5. **Footer** — keybinding hints

**Visual treatment:**

- Color palette (24-bit, monochrome fallback): healthy `#3ecf8e`, warn `#f5c344`, fail `#e5484d`. Sparklines use a green→yellow→red gradient per cell.
- Nerd Font icons (with ASCII fallbacks): 󰓅 ping, 󰇧 DNS, 󰖟 HTTP, 󰕾 stream, 󰖩 Wi-Fi, 󰒋 LAN, 󰓹 traceroute, 󰾆 MTU.
- Bold headers, dim secondary text, monospaced numbers right-aligned.
- Subtle pulse animation on the status dot of probes currently executing.
- Sparklines slide rather than redraw to avoid flicker.

**Interactivity:**

- Mouse + keyboard. Click any target row to expand inline (last 20 results, full timing breakdown).
- Tabs: `Live`, `Targets`, `Events`, `History`, `Config`. `History` shows ASCII-rendered hourly chart for the selected target.
- Detail view (`d`): rolling p50/p95/p99/max, full timing waterfall (HTTP), recent failure list with error strings.
- Live ticker bar at the bottom — scrolls each new event briefly before dropping it to the events panel.
- Toast notifications fade in/out at top-right for new critical events.
- Help overlay (`?`) lists all keybindings.

**Keybindings:**

| Key | Action |
|---|---|
| `q` | Quit |
| `p` | Pause/resume all probes — sets the cancel event on running probes, halts scheduling, and writes a `paused`/`resumed` event to the events log so the break is visible in history |
| `d` | Drill into selected row's detail view |
| `e` | Jump to events tab |
| `h` | Jump to history tab |
| `s` | Save snapshot (current full state as JSON) |
| `?` | Help overlay |

**Accessibility:**

- `--no-color` and `--ascii` for terminals/screen-readers without styling/Nerd Font support
- `--theme {dark,light,high-contrast}`
- `--beep-on critical` plays terminal bell on critical events (off by default)
- Resize-aware: layout collapses gracefully on narrow terminals (drops sparklines first, then events panel)

## Web Dashboard

**Stack:** FastAPI in the same process, single static HTML page, Plotly.js charts, WebSocket for live updates, REST for historical queries.

**Binding:**

- Default `0.0.0.0:8080` so other machines on the LAN can view it (Sean wants to compare across boxes from one place).
- `--bind 127.0.0.1` flag restricts to localhost.
- No auth — local network only. Logs a warning if the binding interface has a non-RFC1918 address.

**Page layout:**

- Top status row — same five health categories as TUI, with colored dots
- Live events feed (right column)
- Multi-line latency chart over time, all targets, selectable (Plotly)
- Packet loss heatmap (target × time, red intensity = loss) — single most useful view for spotting whole-network vs per-target patterns
- HTTP timing breakdown (stacked bars: dns/connect/tls/ttfb)
- Wi-Fi signal over time
- Stream throughput area chart, stalls highlighted

**Endpoints:**

| Method | Path | Purpose |
|---|---|---|
| GET | `/` | The page |
| GET | `/api/status` | Current snapshot (last result per probe/target) |
| GET | `/api/results?probe=&target=&from=&to=` | Paginated history (auto-uses rollups for long ranges) |
| GET | `/api/events?from=&to=` | Pattern events |
| GET | `/api/export.csv?...` | CSV export |
| WS | `/ws/live` | Live result + event stream |

## Configuration

**Three layers, in priority order:** CLI flags > config file > built-in defaults.

**Config file lookup:**

1. `./nettest.yaml` (project-local)
2. `~/.config/nettest/config.yaml` (Linux/Mac) or `%APPDATA%\nettest\config.yaml` (Windows)
3. `--config <path>` overrides both

**Config schema:** YAML, top-level keys `targets`, `probes`, `patterns`, `ui`, `storage`, `thresholds`. Full sample lives in repo `examples/nettest.yaml`. Defaults are embedded in code so the tool runs zero-config.

**Common CLI flags:**

```
nettest                       # run with defaults, TUI + web
nettest --config my.yaml      # alternate config
nettest --no-tui              # headless (web only)
nettest --no-web              # TUI only
nettest --duration 1h         # run for fixed time then exit
nettest --probes ping,dns     # only these probe types
nettest --quiet               # no TUI, no web, just write logs
nettest --replay results.db   # open historic data in TUI without running probes
nettest --snapshot            # one-shot: 30-second sample, print summary, exit
nettest --bind 127.0.0.1      # web localhost-only
nettest --ascii --no-color    # plain terminal mode
```

**Special modes:**

- `--snapshot` — quick "is something wrong right now?" check
- `--replay` — open a historical results.db in the TUI for after-the-fact investigation

## Cross-platform

| Concern | macOS | Windows | Linux |
|---|---|---|---|
| ICMP ping | Unprivileged datagram socket | `IcmpSendEcho` Win32 API via `icmplib` | Requires `net.ipv4.ping_group_range` sysctl or sudo; falls back to TCP-connect probe |
| Traceroute | UDP via `scapy`, falls back to system `traceroute` | `tracert` subprocess | Same as macOS; `mtr` if installed |
| Wi-Fi info | `airport -I` | `netsh wlan show interfaces` | `iw dev <iface> link` (skipped if no wireless) |
| MTU probe | `icmplib` with DF bit | Same | Same |
| Default gateway | `route -n get default` | `Get-NetRoute` / `route print` | `ip route show default` |
| System DNS resolvers | `scutil --dns` | `Get-DnsClientServerAddress` | `/etc/resolv.conf` |

**Distribution:**

- Primary: `pip install nettest` (PyPI). Pure-Python deps only.
- Secondary: PyInstaller single-binary release per OS, attached to GitHub releases (drop-and-run for non-Python users).
- Python 3.11+ required.

## Error handling

- **Probe failures are data, not errors.** A timeout/refused/unreachable becomes `Result(ok=false, error="timeout")` — logged and graphed, not raised.
- **Probe crashes** (unexpected exception in probe code) caught at the scheduler boundary, logged to `nettest.log`, and that probe enters exponential backoff (skip 1, then 2, then 4 cycles) before retry. Other probes keep running.
- **Sink failures** (disk full, DB locked) log a warning and degrade gracefully — JSONL keeps writing if SQLite fails, and vice versa. The tool never silently loses data.
- **Network completely down** is the *expected* state when investigating problems. Web dashboard binds to localhost regardless, so you can still view it. Tool keeps running and logging the outage.
- **Self-monitoring.** `nettest.log` records its own scheduling lag and queue depths. Surfaced in the TUI status bar as a warning if the tool falls behind real-time.

## Testing strategy

- **Unit tests** for every probe with mocked network: `respx` for HTTP, fake DNS responses via `dnslib`, mock ICMP responses. Fast, runs in CI.
- **Integration tests** that spin up local services (HTTP server, DNS server, ICMP loopback) and run real probes against them. Verifies socket and timing code paths.
- **Pattern detector tests** — feed synthetic result streams, assert correct events fire (e.g., 3 fails in 800 ms → `micro_outage`).
- **Storage tests** — write/read SQLite, JSONL roundtrip, retention/cleanup correctness, rollup math.
- **TUI snapshot tests** — Textual renders to a string; snapshot key views to catch layout regressions.
- **Cross-platform CI** — GitHub Actions matrix on `macos-latest`, `ubuntu-latest`, `windows-latest`. Wi-Fi tests skipped when no wireless adapter present.
- **Manual test plan** doc for things hard to automate: "kill Wi-Fi for 10 s → verify event fires", "block port 53 → verify DNS-only correlation", "throttle bandwidth via `pfctl` → verify stream stalls detected".

## Open questions deferred to implementation planning

- Exact uncached-DNS probe domain. Options: a public test domain that supports wildcard queries, or instructing the user to configure a domain they control. Implementation plan to evaluate which is more reliable.
- Stream-test endpoint default. Cloudflare's `speed.cloudflare.com/__down` is a strong candidate but worth validating bandwidth/availability before locking in.
- TUI sparkline width on narrow terminals — exact breakpoints to be tuned during implementation.

## Out of scope (possible v2)

- Centralized collector for multi-machine aggregation
- Webhook/Slack/email alerting on critical events
- Automatic comparison report across two machines' data files
- Capture/replay of network conditions for repro
