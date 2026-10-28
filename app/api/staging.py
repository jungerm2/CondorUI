"""Background scans for network-backed staging directories.

OSDF staging can live on an autofs/NFS mount where a single missing
directory lookup takes seconds.  Blocking a page request on that lookup
makes a local list appear empty or stuck.  This cache starts the scan in
the background, gives it a short grace period for fast filesystems, then
serves whatever is currently known.
"""

from __future__ import annotations

import json
import logging
import threading
import time
from pathlib import Path

logger = logging.getLogger(__name__)


class BackgroundScanCache:
    """TTL cache for one slow directory scan.

    Results can optionally be persisted so a restart serves the previous
    listing immediately while the background refresh runs.
    """

    def __init__(self, ttl: float = 60.0, grace: float = 0.2) -> None:
        self._ttl = ttl
        self._grace = grace
        self._lock = threading.Lock()
        self._done = threading.Event()
        self._key: str | None = None
        self._data: list[dict] | None = None
        self._updated = 0.0
        self._scanning = False
        self._storage: Path | None = None
        self._loaded = False

    def attach(self, storage: Path) -> None:
        """Load a persisted listing from *storage* on the next ``get``."""
        with self._lock:
            if self._storage == storage:
                return
            self._storage = storage
            self._loaded = False

    def get(self, key: str, scanner) -> tuple[list[dict] | None, bool]:
        """Return ``(entries, scanning)`` and refresh stale data in the background.

        The first call waits up to ``grace`` seconds; on a slow mount it
        returns ``(None, True)`` while the scan continues.  Existing stale
        data is served immediately while a refresh runs.
        """
        with self._lock:
            if not self._loaded:
                self._load_locked(key)
                self._loaded = True
            if key != self._key:
                self._key = key
                self._data = None
                self._updated = 0.0
            stale = self._data is None or (time.monotonic() - self._updated) > self._ttl
            if stale and not self._scanning:
                self._scanning = True
                self._done.clear()
                threading.Thread(target=self._run, args=(scanner,), daemon=True).start()
            data = self._data
            scanning = self._scanning

        if data is None and scanning:
            self._done.wait(self._grace)
            with self._lock:
                data = self._data
                scanning = self._scanning
        return data, scanning

    def invalidate(self) -> None:
        with self._lock:
            self._updated = 0.0

    def _load_locked(self, key: str) -> None:
        if self._storage is None:
            return
        try:
            payload = json.loads(self._storage.read_text(encoding="utf-8"))
        except OSError, ValueError:
            return
        if payload.get("key") != key or not isinstance(payload.get("data"), list):
            return
        self._key = key
        self._data = payload["data"]
        # Treat the persisted listing as stale so it is refreshed immediately.
        self._updated = 0.0

    def _save_locked(self, data: list[dict]) -> None:
        if self._storage is None:
            return
        try:
            self._storage.parent.mkdir(parents=True, exist_ok=True)
            temporary = self._storage.with_name(f"{self._storage.name}.tmp")
            temporary.write_text(
                json.dumps({"key": self._key, "data": data}), encoding="utf-8"
            )
            temporary.replace(self._storage)
        except OSError:
            logger.warning("Could not save staging cache %s", self._storage)

    def _run(self, scanner) -> None:
        try:
            data = scanner()
        except Exception:
            logger.exception("Background staging scan failed")
            data = []
        with self._lock:
            self._data = data
            self._updated = time.monotonic()
            self._scanning = False
            self._save_locked(data)
        self._done.set()
