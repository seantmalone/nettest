from pathlib import Path

import pytest

from nettest.config import Config, load_config


def test_config_defaults_load_with_no_file(tmp_path: Path):
    cfg = load_config(config_path=None, search_dirs=[tmp_path])
    assert cfg.probes.ping.interval_ms == 250
    assert cfg.probes.http.interval_ms == 2000
    assert cfg.ui.web.port == 8080
    assert cfg.storage.retention.raw_results_days == 7


def test_config_loads_from_yaml(tmp_path: Path):
    cfg_file = tmp_path / "nettest.yaml"
    cfg_file.write_text(
        "probes:\n  ping:\n    interval_ms: 100\nui:\n  web:\n    port: 9000\n"
    )
    cfg = load_config(config_path=cfg_file)
    assert cfg.probes.ping.interval_ms == 100
    assert cfg.ui.web.port == 9000
    assert cfg.probes.http.interval_ms == 2000


def test_config_rejects_negative_intervals(tmp_path: Path):
    cfg_file = tmp_path / "nettest.yaml"
    cfg_file.write_text("probes:\n  ping:\n    interval_ms: -1\n")
    with pytest.raises(ValueError):
        load_config(config_path=cfg_file)


def test_config_default_targets_include_smart_tokens():
    cfg = Config()
    assert "auto:gateway" in cfg.targets.ping
    assert "auto:system" in cfg.targets.dns.resolvers


def test_config_search_picks_first_existing_dir(tmp_path: Path):
    a = tmp_path / "a"
    b = tmp_path / "b"
    a.mkdir()
    b.mkdir()
    (b / "nettest.yaml").write_text("ui:\n  web:\n    port: 7777\n")
    cfg = load_config(config_path=None, search_dirs=[a, b])
    assert cfg.ui.web.port == 7777


def test_config_rejects_unknown_top_level_key(tmp_path: Path):
    cfg_file = tmp_path / "nettest.yaml"
    cfg_file.write_text("totally_made_up: 1\n")
    with pytest.raises(ValueError):
        load_config(config_path=cfg_file)
