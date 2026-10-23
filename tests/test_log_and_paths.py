"""Tests for UserLog event filtering and per-proc stdout/stderr path resolution."""

from datetime import datetime

from app.condor import (
    _path_with_proc,
    _pick_per_proc_path,
    filter_job_log_events,
    read_job_log_completions,
)

# Full terminated-event body: the event reader requires the usage/resource
# detail lines, not just the header and exit line.
TERMINATED_EVENT = """005 ({cluster}.{proc:03d}.000) {date} Job terminated.
    (1) Normal termination (return value {return_value})
        Usr 0 00:00:00, Sys 0 00:00:00  -  Run Remote Usage
        Usr 0 00:00:00, Sys 0 00:00:00  -  Run Local Usage
        Usr 0 00:00:00, Sys 0 00:00:00  -  Total Remote Usage
        Usr 0 00:00:00, Sys 0 00:00:00  -  Total Local Usage
    0  -  Run Bytes Sent By Job
    27848  -  Run Bytes Received By Job
    0  -  Total Bytes Sent By Job
    27848  -  Total Bytes Received By Job
    Partitionable Resources :    Usage  Request Allocated
       Cpus                 :                 1         1
       Disk (KB)            :       40       30   4203309
       Memory (MB)          :        1        1         1
...
"""


MIXED_LOG = """000 (100.000.000) 02/10 14:22:01 Job submitted.
    Detail line for proc 0
000 (101.000.000) 02/10 14:22:02 Job submitted from another cluster.
000 (100.001.000) 02/10 14:22:03 Job executing on host A (pid 111)
    CPU_STATS detail for proc1
001 (100.001.000) 02/10 14:22:04 Job terminated, exit 0
    More proc1 detail
001 (100.000.000) 02/10 14:22:05 Job terminated, exit 0
    Proc0 detail line
"""


class TestFilterJobLogEvents:
    def test_proc_view_excludes_other_procs_and_clusters(self):
        f = filter_job_log_events(MIXED_LOG, 100, 1)
        assert "100.000" not in f
        assert "101" not in f
        assert "100.001" in f
        assert "CPU_STATS detail for proc1" in f

    def test_proc_zero_view_keeps_only_proc_zero(self):
        f = filter_job_log_events(MIXED_LOG, 100, 0)
        assert "100.001" not in f
        assert "100.000" in f
        assert "101" not in f

    def test_single_event_log_passes_through(self):
        single = "000 (200.000.000) 02/10 14:22:01 Job submitted.\n"
        assert filter_job_log_events(single, 200, 0) == single

    def test_unparseable_content_is_returned_unchanged(self):
        raw = "no event headers here\n"
        assert filter_job_log_events(raw, 5, 0) == raw

    def test_empty_content(self):
        assert filter_job_log_events("", 100, 0) == ""


class TestPathWithProc:
    def test_zero_padded_proc(self):
        assert (
            _path_with_proc("condor_job_logs/00000042/00000.out", 5)
            == "condor_job_logs/00000042/00005.out"
        )

    def test_bare_proc_suffix(self):
        assert (
            _path_with_proc("condor_job_logs/42.0.out", 12)
            == "condor_job_logs/42.12.out"
        )

    def test_cluster_zero_padding_untouched(self):
        # The 8-digit cluster id must not be repurposed as the proc id
        assert _path_with_proc("logs/00000042/42.0.out", 3) == "logs/00000042/42.3.out"


class TestPickPerProcPath:
    def _touch(self, tmp_path, name):
        p = tmp_path / name
        p.write_text("x")
        return str(p)

    def test_derived_existing_wins(self, tmp_path):
        proc0 = str(tmp_path / "job.0.out")  # intentionally absent
        derived = self._touch(tmp_path, "job.7.out")
        assert _pick_per_proc_path(proc0, proc0, 7) == derived

    def test_shared_file_kept(self, tmp_path):
        shared = self._touch(tmp_path, "job.0.out")
        assert _pick_per_proc_path(shared, shared, 7) == shared

    def test_missing_classad_path_beaten_by_existing_shared(self, tmp_path):
        shared = self._touch(tmp_path, "job.0.out")
        missing = str(tmp_path / "other.resolved")
        assert _pick_per_proc_path(shared, missing, 7) == shared

    def test_both_missing_falls_back_to_resolved_classad(self, tmp_path):
        proc0 = str(tmp_path / "job.0.out")
        ca = str(tmp_path / "other.resolved")
        assert _pick_per_proc_path(proc0, ca, 7) == ca


class TestJobLogCompletions:
    def _write_log(self, tmp_path, body: str) -> str:
        path = tmp_path / "job.log"
        path.write_text(body)
        return str(path)

    def test_completion_date_wall_time_and_exit_code(self, tmp_path):
        body = (
            "000 (100.000.000) 2020-07-10 10:44:00 Job submitted from host: <x>\n"
            "...\n"
            "001 (100.000.000) 2020-07-10 10:45:00 Job executing on host: <x>\n"
            "...\n"
            + TERMINATED_EVENT.format(
                cluster=100,
                proc=0,
                date="2020-07-10 10:46:00",
                return_value=0,
            )
            + "001 (100.001.000) 2020-07-10 10:45:00 Job executing on host: <x>\n"
            "...\n"
            + TERMINATED_EVENT.format(
                cluster=100,
                proc=1,
                date="2020-07-10 10:45:30",
                return_value=1,
            )
        )
        completions = read_job_log_completions(self._write_log(tmp_path, body))

        assert completions[(100, 0)] == {
            "CompletionDate": int(datetime(2020, 7, 10, 10, 46).timestamp()),
            "RemoteWallClockTime": 60,
            "LastRemoteWallClockTime": 60,
            "ExitCode": 0,
            "ExitBySignal": False,
        }
        assert completions[(100, 1)]["LastRemoteWallClockTime"] == 30
        assert completions[(100, 1)]["ExitCode"] == 1

    def test_unfinished_tail_is_ignored(self, tmp_path):
        body = (
            "001 (100.000.000) 2020-07-10 10:45:00 Job executing on host: <x>\n"
            "...\n"
            + TERMINATED_EVENT.format(
                cluster=100,
                proc=0,
                date="2020-07-10 10:46:00",
                return_value=0,
            )
            + "001 (100.001.000) 2020-07-10 10:46:00 Job executing on host: <x>\n"
        )
        completions = read_job_log_completions(self._write_log(tmp_path, body))

        assert (100, 0) in completions
        assert (100, 1) not in completions

    def test_missing_and_empty_logs(self, tmp_path):
        assert read_job_log_completions(str(tmp_path / "missing.log")) == {}
        empty = tmp_path / "empty.log"
        empty.write_text("")
        assert read_job_log_completions(str(empty)) == {}
