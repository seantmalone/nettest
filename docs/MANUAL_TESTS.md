# Manual Test Plan

These tests cover behaviors that aren't reliable in CI (real network conditions, OS-specific permissions, multi-machine setups). Run before each release.

## 1. Wi-Fi loss event fires

1. `nettest --probes ping,wifi`
2. Disable Wi-Fi for ~10s, re-enable.
3. Expected: TUI surfaces a `wifi_drop` info event and at least one `micro_outage` warn event when reconnect lags.

## 2. DNS-only failure correlation

1. Block UDP/TCP port 53 outbound (`pfctl` rule on Mac, Windows Firewall on Win).
2. `nettest`
3. Expected: TUI surfaces `dns_only_fail` events; ping and HTTP probes continue succeeding (HTTP fails on DNS step but TCP/ICMP to public IPs are fine).
4. Remove block; verify recovery.

## 3. Stream stall detection

1. With `pfctl` or `tc`, throttle a single TCP flow to 10 KB/s for 30s during a stream probe cycle.
2. Expected: Stream probe records non-zero `stall_count`; pattern detector emits `stream_stall` after threshold.

## 4. Cross-machine comparison

1. Start `nettest` on Mac and Windows boxes simultaneously.
2. Open `http://<mac>:8080` and `http://<win>:8080` in side-by-side browser tabs.
3. Trigger a brief router restart.
4. Expected: both dashboards show coordinated failure window; loss heatmap on each is similar; events are emitted on both.

## 5. PyInstaller binary works on a clean machine

1. Take the built `nettest` binary to a machine without Python installed.
2. `./nettest --duration 30s --no-tui --no-web --probes ping`
3. Expected: it runs, writes `./data/<host>/` files, exits cleanly.

## 6. RFC1918 binding warning

1. `nettest --bind 0.0.0.0` on a machine that has a public IP on its primary interface.
2. Expected: stderr shows the public-IP warning at startup. `--bind 127.0.0.1` suppresses the warning.

## 7. `--replay` against real data

1. After a multi-hour real run, stop `nettest`. `nettest --replay data/<host>/results.db`
2. Expected: TUI opens, shows historical aggregates without running new probes.

## 8. Pause/resume marks the timeline

1. With TUI running, press `p` to pause, wait 10s, press `p` again.
2. Open `http://localhost:8080`, query `/api/events`. Expected: a `_paused` and `_resumed` marker in the events feed at the corresponding timestamps.

## 9. Long-soak retention (periodic, not per-release)

1. Run for 8+ days continuously.
2. Verify `data/<host>/results.db` size stabilizes (raw rows older than 7 days are pruned, rollups preserved).

> Run this every quarter or before any retention-related code change — not before every release.

## 10. ICMP fallback on Linux without sysctl

1. On a Linux box where unprivileged ICMP is not enabled, `nettest --probes ping`.
2. Expected: ping probe falls back gracefully (logs the issue, returns failures with informative `error` strings) — does not crash the scheduler.
