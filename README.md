# nettest

High-frequency network diagnostic utility for Mac, Windows, and Linux. Catches the kind of intermittent failures that one-shot tools miss: brief sub-second blips, DNS-only outages, mid-stream stalls, and Wi-Fi flaps.

## What it does

Runs a suite of probes — ping, DNS (cached + uncached), HTTP with full timing breakdown, TCP connect, traceroute, sustained streaming download, MTU probe, bandwidth, Wi-Fi signal — at independent cadences (250 ms for cheap probes, slower for expensive ones). Persists every result to SQLite and JSONL, detects failure patterns in real time, and presents results live in either a rich terminal UI (Textual) or a web dashboard (FastAPI + Plotly).

## Install

```bash
pip install nettest
```

Requires Python 3.11+. Pre-built binaries for macOS and Windows are available on the [releases page](https://github.com/seantmalone/nettest/releases).

## Quick start

```bash
nettest                          # run with smart defaults; opens TUI + dashboard at :8080
nettest --snapshot               # 30-second sample, prints summary, exits
nettest --duration 1h            # run for an hour then stop
nettest --no-tui                 # headless (web dashboard only)
nettest --replay results.db      # explore yesterday's data
nettest --bind 127.0.0.1         # restrict web UI to localhost
```

Open `http://localhost:8080` from any machine on your LAN.

## Comparing across machines

Run `nettest` on each box. Each writes its own data under `./data/<hostname>/` and exposes its own dashboard. Open multiple browser tabs to compare. The independent design means each machine keeps measuring even if the network is broken — important when the network *is* what you're investigating.

## Configuration

`nettest` runs with no config. To customize, copy `examples/nettest.yaml` to `./nettest.yaml` (project-local) or `~/.config/nettest/config.yaml` (user-global) and edit. CLI flags override the config.

## Data

```
./data/<hostname>/
  results.db           # SQLite with raw results, events, rollups
  YYYY-MM-DD.jsonl     # one line per probe result, daily file
  nettest.log          # nettest's own diagnostic log
```

Default retention: raw results 7 days, per-minute rollups 90 days, per-hour rollups 1 year.

## License

MIT
