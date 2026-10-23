"""The schedd query pool and serialization gate must survive wedged calls.

A timeout cannot cancel the worker (it stays blocked inside htcondor's
bindings), so the pool is retired and the serialization gate
force-released.  Ownership by token makes ``force_release`` idempotent
and turns a stale worker's eventual release into a no-op — the pair of
over/under-release hazards that a permit-counting semaphore has.
"""

import threading
from concurrent.futures import ThreadPoolExecutor

import pytest

from app import condor


def test_query_recovers_after_timeout():
    original_executor = condor._schedd_executor
    original_gate = condor._condor_serial_lock
    stuck = threading.Event()

    def block_forever():
        stuck.wait()

    try:
        # One wedged query is enough to exhaust a one-worker pool
        condor._schedd_executor = ThreadPoolExecutor(max_workers=1)
        with pytest.raises(TimeoutError):
            condor._run_with_timeout(block_forever, timeout=0.2)

        # Retiring the pool + force-releasing the gate restores capacity
        # even though the wedged worker never released either
        assert condor._run_with_timeout(lambda: "ok", timeout=2) == "ok"

        # The gate is not left locked (a stale worker still blocked inside
        # the C layer must not keep later queries waiting)
        tk = condor._condor_serial_lock.acquire()
        condor._condor_serial_lock.release(tk)

        # A stale holder's late release must not disturb the current one,
        # and force_release stays idempotent when nothing is held
        condor._condor_serial_lock.release(object())
        condor._condor_serial_lock.force_release()
        tk = condor._condor_serial_lock.acquire()
        condor._condor_serial_lock.release(tk)
    finally:
        stuck.set()
        original_executor.shutdown(wait=False, cancel_futures=True)
        condor._schedd_executor = original_executor
        condor._condor_serial_lock = original_gate
