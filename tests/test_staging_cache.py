"""Persistent staging-directory cache."""

import time

from app.api.staging import BackgroundScanCache


def test_persisted_listing_survives_a_restart(tmp_path):
    cache_file = tmp_path / "containers.json"

    first = BackgroundScanCache(grace=1.0)
    first.attach(cache_file)
    data, scanning = first.get("containers-path", lambda: [{"name": "old"}])

    assert data == [{"name": "old"}]
    assert scanning is False
    assert cache_file.exists()

    restarted = BackgroundScanCache(grace=1.0)
    restarted.attach(cache_file)
    cached, scanning = restarted.get("containers-path", lambda: [{"name": "refreshed"}])

    assert cached == [{"name": "old"}]
    assert scanning is True

    time.sleep(0.1)
    refreshed, scanning = restarted.get(
        "containers-path", lambda: [{"name": "refreshed"}]
    )
    assert refreshed == [{"name": "refreshed"}]
    assert scanning is False


def test_cache_is_ignored_for_a_different_directory(tmp_path):
    cache_file = tmp_path / "containers.json"
    first = BackgroundScanCache(grace=1.0)
    first.attach(cache_file)
    assert first.get("path-a", lambda: [{"name": "a"}])[0] == [{"name": "a"}]

    second = BackgroundScanCache(grace=1.0)
    second.attach(cache_file)
    data, _scanning = second.get("path-b", lambda: [{"name": "b"}])
    assert data == [{"name": "b"}]
