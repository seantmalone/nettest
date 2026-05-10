from nettest.host import current_hostname


def test_current_hostname_is_nonempty_string():
    h = current_hostname()
    assert isinstance(h, str)
    assert len(h) > 0
    assert "\n" not in h
