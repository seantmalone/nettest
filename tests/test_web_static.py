from pathlib import Path

import nettest.web


def test_static_files_exist():
    base = Path(nettest.web.__file__).parent / "static"
    assert (base / "index.html").is_file()
    assert (base / "app.js").is_file()
    assert (base / "styles.css").is_file()


def test_index_html_has_required_elements():
    base = Path(nettest.web.__file__).parent / "static"
    html = (base / "index.html").read_text(encoding="utf-8")
    for required in (
        "plotly", "ws/live",
        'id="latency"', 'id="loss-heatmap"',
        'id="http-timing"', 'id="wifi"', 'id="stream-throughput"',
        'id="events-list"',
    ):
        assert required in html, f"index.html missing {required!r}"
