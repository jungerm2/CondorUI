"""Job history endpoints backed by the local DB with schedd cross-reference."""

from __future__ import annotations

import json
import logging
from pathlib import Path

from flask import current_app, jsonify, request
from sqlalchemy import String, cast, func, or_

from app import api as _api
from app import db
from app.api import api_bp
from app.api.output_files import delete_output_files_for_submission
from app.condor import (
    DEFAULT_CONSTRAINT,
    act_on_job,
    query_jobs,
    read_job_log_completions,
)
from app.models import JobSubmission

logger = logging.getLogger(__name__)


def _build_job_entry(
    sub: JobSubmission, proc_id: int, schedd_job: dict | None = None
) -> dict:
    """Build a job dict from a DB submission record, optionally overlaying schedd data.

    When *schedd_job* is provided, real-time status and metadata from the schedd
    are used.  Otherwise the job is marked as Completed with fields synthesized
    from the DB record.

    Static attributes (Owner, Cmd, JobBatchName) are sourced from the DB record
    first (saved at submit time), falling back to schedd data if the DB values
    are null.
    """
    from app.condor import JOB_STATUS_MAP

    # Static attributes from DB (saved at submit time)
    owner = sub.owner or (schedd_job.get("Owner", "—") if schedd_job else "—")
    cmd = sub.cmd or (schedd_job.get("Cmd", "") if schedd_job else "")
    batch_name = sub.name

    if schedd_job:
        status = schedd_job.get("JobStatus", 4)
        return {
            "ClusterId": sub.cluster_id,
            "ProcId": schedd_job.get("ProcId", proc_id),
            "JobStatus": status,
            "JobStatusName": JOB_STATUS_MAP.get(status, "Unknown"),
            "Owner": owner,
            "Cmd": cmd,
            "Args": schedd_job.get("Args", ""),
            "RequestCpus": schedd_job.get("RequestCpus", "—"),
            "RequestMemory": schedd_job.get("RequestMemory", "—"),
            "RequestDisk": schedd_job.get("RequestDisk", "—"),
            "RequestGPUs": schedd_job.get("RequestGPUs", "—"),
            "QDate": schedd_job.get("QDate", 0),
            "JobStartDate": schedd_job.get("JobStartDate"),
            "CompletionDate": schedd_job.get("CompletionDate"),
            "HoldReason": schedd_job.get("HoldReason", ""),
            "RemoteHost": schedd_job.get("RemoteHost", ""),
            "ImageSize": schedd_job.get("ImageSize", 0),
            "DiskUsage": schedd_job.get("DiskUsage", 0),
            "ExitCode": schedd_job.get("ExitCode", 0),
            "ExitBySignal": schedd_job.get("ExitBySignal", False),
            "JobCurrentStartDate": schedd_job.get("JobCurrentStartDate"),
            "NumJobStarts": schedd_job.get("NumJobStarts", 1),
            "NumShadowStarts": schedd_job.get("NumShadowStarts", 1),
            "JobBatchName": schedd_job.get("JobBatchName", batch_name),
            "RemoteWallClockTime": schedd_job.get("RemoteWallClockTime", 0),
            "LastRemoteWallClockTime": schedd_job.get("LastRemoteWallClockTime", 0),
            "CumulativeSuspensionTime": schedd_job.get("CumulativeSuspensionTime", 0),
            "CumulativeRemoteSysCpu": schedd_job.get("CumulativeRemoteSysCpu", 0),
            "CumulativeRemoteUserCpu": schedd_job.get("CumulativeRemoteUserCpu", 0),
        }

    # Synthesize from DB record (job completed / no schedd data).
    # The parsed submit description is cached on the instance because this
    # helper is called once per proc and large clusters would otherwise
    # re-parse the same JSON thousands of times per request.
    desc = getattr(sub, "_parsed_submit_desc", None)
    if desc is None:
        desc = {}
        try:
            if sub.submit_description.strip().startswith("{"):
                desc = json.loads(sub.submit_description)
        except json.JSONDecodeError, AttributeError:
            desc = {}
        sub._parsed_submit_desc = desc
    request_cpus = "—"
    request_memory = "—"
    request_disk = "—"
    request_gpus = "—"
    if "request_cpus" in desc:
        request_cpus = desc["request_cpus"]
    if "request_memory" in desc:
        request_memory = desc["request_memory"]
    if "request_disk" in desc:
        request_disk = desc["request_disk"]
    if "request_gpus" in desc:
        request_gpus = desc["request_gpus"]

    args = desc.get("arguments", "")
    if isinstance(args, list):
        args = " ".join(str(a) for a in args)

    qdate = int(sub.submitted_at.timestamp()) if sub.submitted_at else 0

    entry = {
        "ClusterId": sub.cluster_id,
        "ProcId": proc_id,
        "JobStatus": 4,
        "JobStatusName": "Completed",
        "Owner": owner,
        "Cmd": cmd,
        "Args": args,
        "RequestCpus": request_cpus,
        "RequestMemory": request_memory,
        "RequestDisk": request_disk,
        "RequestGPUs": request_gpus,
        "QDate": qdate,
        "JobStartDate": None,
        "CompletionDate": None,
        "HoldReason": "",
        "RemoteHost": "",
        "ImageSize": 0,
        "DiskUsage": 0,
        "ExitCode": 0,
        "ExitBySignal": False,
        "JobCurrentStartDate": None,
        "NumJobStarts": 1,
        "NumShadowStarts": 1,
        "JobBatchName": batch_name,
        "RemoteWallClockTime": 0,
        "LastRemoteWallClockTime": 0,
        "CumulativeSuspensionTime": 0,
        "CumulativeRemoteSysCpu": 0,
        "CumulativeRemoteUserCpu": 0,
    }

    # The DB knows how a job was submitted, not how it ended.  Fill the
    # completion columns from the job's own UserLog: local file I/O, no
    # schedd history scan.  Cache the parsed map per submission so a cluster
    # with many procs reads its log once per request.
    if sub.log_path:
        completions = getattr(sub, "_completion_fields", None)
        if completions is None:
            completions = read_job_log_completions(sub.log_path)
            sub._completion_fields = completions
        fields = completions.get((sub.cluster_id, proc_id))
        if fields:
            entry.update(fields)
    return entry


@api_bp.route("/history")
def list_history():
    """List all known submissions with real-time status from the schedd.

    Reads from the local JobSubmission table (fast), then cross-references
    with the schedd to show the actual status of each cluster.  Clusters
    still in the schedd (idle / running / held) show their real status;
    clusters no longer in the schedd are marked Completed.

    Query parameters:
        source (str): One of "merged" (default), "schedd", or "db".
            - merged: return ALL procs per cluster; active ones from schedd,
              completed ones from DB.
            - schedd: return only what's currently in the schedd (one proc
              per cluster).
            - db: return all procs from the local DB only (all Completed).
    """
    source = request.args.get("source", "merged")
    limit = request.args.get(
        "limit", current_app.config["MAX_HISTORY_RESULTS"], type=int
    )
    offset = request.args.get("offset", 0, type=int)
    # When grouped=1, pagination is by cluster (each page shows N clusters with
    # all their procs). When grouped=0, pagination is by individual proc.
    grouped = request.args.get("grouped", "0") == "1"
    offset = max(offset, 0)
    limit = max(limit, 0)
    try:
        # ---- Filters (parsed up front; shared by both code paths) ----
        status_filter: int | None
        status_raw = request.args.get("status")
        if status_raw is not None and status_raw.isdigit():
            status_filter = int(status_raw)
        else:
            status_filter = None
        query_filter = (request.args.get("query") or "").strip().lower()
        # Optional single-cluster scope (dashboard's ?cluster_id=X view): without
        # it a deep-linked old cluster can fall outside the first history page
        # and render as empty even though a status bar segment offered it.
        cluster_raw = request.args.get("cluster_id")
        cluster_scope: int | None = (
            int(cluster_raw) if cluster_raw and cluster_raw.isdigit() else None
        )

        # ---- Active schedd jobs (full projection) ----
        active_jobs: list[dict] = []
        if _api.daemon_available() and source != "db":
            try:
                active_jobs = query_jobs(
                    constraint=DEFAULT_CONSTRAINT,
                    projection=[
                        "ClusterId",
                        "ProcId",
                        "JobStatus",
                        "Owner",
                        "Cmd",
                        "Args",
                        "QDate",
                        "JobStartDate",
                        "CompletionDate",
                        "HoldReason",
                        "RemoteHost",
                        "RemoteWallClockTime",
                        "ExitCode",
                        "ExitBySignal",
                        "JobBatchName",
                        "RequestCpus",
                        "RequestMemory",
                        "RequestDisk",
                        "RequestGPUs",
                    ],
                )
            except Exception:
                logger.warning(
                    "Could not query schedd for history statuses", exc_info=True
                )

        # De-duplicated active procs, preserving schedd order.
        seen: set[tuple[int, int]] = set()
        active_keys: list[tuple[int, int]] = []
        active_by_key: dict[tuple[int, int], dict] = {}
        for job in active_jobs:
            cid = job.get("ClusterId")
            pid = job.get("ProcId", 0)
            if cid is None:
                continue
            key = (cid, pid)
            if key not in seen:
                seen.add(key)
                active_keys.append(key)
                active_by_key[key] = job

        # Single-cluster scope trims the active stream here so every later
        # path (stats, matching, pagination) sees only the scoped cluster.
        if cluster_scope is not None:
            active_keys = [k for k in active_keys if k[0] == cluster_scope]
            active_by_key = {
                k: v for k, v in active_by_key.items() if k[0] == cluster_scope
            }

        # ------------------------------------------------------------------
        # Fast path: no active schedd jobs to merge with. Everything comes
        # from the local DB (all Completed), so dedup/filtering/pagination
        # are pushed down to SQL instead of materializing every proc.
        # ------------------------------------------------------------------
        if not active_keys and source != "schedd":
            # Duplicate cluster_id rows (e.g. repeated submissions recorded
            # under one cluster) are deduped: the newest record per cluster
            # wins, matching the merged path's first-record-wins semantics.
            rn_sq = db.session.query(
                JobSubmission.id.label("jid"),
                func.row_number()
                .over(
                    partition_by=JobSubmission.cluster_id,
                    order_by=JobSubmission.submitted_at.desc(),
                )
                .label("rn"),
            ).subquery()

            stats_row = (
                db.session.query(func.coalesce(func.sum(JobSubmission.num_procs), 0))
                .select_from(JobSubmission)
                .join(rn_sq, rn_sq.c.jid == JobSubmission.id)
                .filter(rn_sq.c.rn == 1)
                .filter(
                    JobSubmission.cluster_id == cluster_scope
                    if cluster_scope is not None
                    else db.true()
                )
                .one()
            )
            total_procs = int(stats_row[0] or 0)
            stats = {
                "total": total_procs,
                "idle": 0,
                "running": 0,
                "completed": total_procs,
                "held": 0,
                "removed": 0,
                "transferring": 0,
            }

            # DB-only procs are always Completed — an incompatible status
            # filter cannot match anything.
            if status_filter is not None and status_filter != 4:
                return jsonify(
                    {
                        "jobs": [],
                        "count": 0,
                        "total": 0,
                        "has_more": False,
                        "limit": limit,
                        "offset": offset,
                        "stats": stats,
                    }
                )

            base_q = JobSubmission.query.join(
                rn_sq, rn_sq.c.jid == JobSubmission.id
            ).filter(rn_sq.c.rn == 1)
            if cluster_scope is not None:
                base_q = base_q.filter(JobSubmission.cluster_id == cluster_scope)
            if query_filter:
                escaped = query_filter.replace("\\", "\\\\")
                escaped = escaped.replace("%", "\\%").replace("_", "\\_")
                pattern = f"%{escaped}%"
                base_q = base_q.filter(
                    or_(
                        JobSubmission.name.ilike(pattern, escape="\\"),
                        JobSubmission.owner.ilike(pattern, escape="\\"),
                        JobSubmission.cmd.ilike(pattern, escape="\\"),
                        cast(JobSubmission.cluster_id, String).ilike(
                            pattern, escape="\\"
                        ),
                    )
                )
            ordered = base_q.order_by(JobSubmission.submitted_at.desc())

            jobs: list[dict] = []
            if grouped:
                # Page = `limit` whole clusters; SQL LIMIT/OFFSET does the
                # slicing and only page rows are instantiated.
                total = ordered.count()
                page_subs = ordered[offset : offset + limit]
                has_more = (offset + limit) < total
                for sub in page_subs:
                    for pid in range(sub.num_procs or 0):
                        jobs.append(_build_job_entry(sub, pid))
            else:
                # Flat: paginate by individual proc. Only (id, num_procs)
                # tuples are fetched for the full filtered set; full rows
                # are loaded solely for the subs overlapping the page.
                counts = ordered.with_entities(
                    JobSubmission.id, JobSubmission.num_procs
                ).all()
                total = sum(n or 0 for _, n in counts)
                has_more = (offset + limit) < total
                window_start, window_end = offset, offset + limit
                page_ids: list[int] = []
                running = 0
                for sub_id, nprocs in counts:
                    n = nprocs or 0
                    if n and running + n > window_start:
                        page_ids.append(sub_id)
                    running += n
                    if running >= window_end:
                        break
                if page_ids:
                    subs_by_id = {
                        s.id: s
                        for s in JobSubmission.query.filter(
                            JobSubmission.id.in_(page_ids)
                        ).all()
                    }
                    running = 0
                    for sub_id, nprocs in counts:
                        n = nprocs or 0
                        sub = subs_by_id.get(sub_id)
                        if not n or sub is None:
                            # Not part of the page window — just advance.
                            running += n
                            continue
                        for pid in range(n):
                            if running >= window_end:
                                break
                            if running >= window_start:
                                jobs.append(_build_job_entry(sub, pid))
                            running += 1
                        if running >= window_end:
                            break

            return jsonify(
                {
                    "jobs": jobs,
                    "count": len(jobs),
                    "total": total,
                    "has_more": has_more,
                    "limit": limit,
                    "offset": offset,
                    "stats": stats,
                }
            )

        # ------------------------------------------------------------------
        # Merged path: active schedd procs live, completed procs from the DB.
        # Entries are only built for the current page — stats and filtering
        # use cheap per-proc / per-submission field lookups instead.
        # ------------------------------------------------------------------
        all_submissions = list(
            JobSubmission.query.order_by(JobSubmission.submitted_at.desc()).all()
        )
        # Cluster -> submission lookup (first record per cluster wins for
        # duplicates, mirroring the old (ClusterId, ProcId) dedup).
        sub_by_cluster: dict[int, JobSubmission] = {}
        for sub in all_submissions:
            sub_by_cluster.setdefault(sub.cluster_id, sub)
        deduped_subs = list(sub_by_cluster.values())
        if cluster_scope is not None:
            deduped_subs = [s for s in deduped_subs if s.cluster_id == cluster_scope]

        # Active pids per cluster (for excluding merged procs from the
        # DB-only stream).
        seen_by_cluster: dict[int, set[int]] = {}
        for cid, pid in seen:
            seen_by_cluster.setdefault(cid, set()).add(pid)

        def _page_entry(cid: int, pid: int) -> dict | None:
            sub = sub_by_cluster.get(cid)
            active = active_by_key.get((cid, pid))
            if sub is not None and pid < (sub.num_procs or 0):
                return _build_job_entry(sub, pid, active)
            if active is not None:
                return active
            return None

        def _active_status(job: dict, merged: bool) -> int:
            # Mirrors _build_job_entry / raw-dict status semantics.
            status = job.get("JobStatus", 4) if merged else job.get("JobStatus")
            return int(status or 0)

        def _active_haystack(cid: int, pid: int, job: dict) -> str:
            sub = sub_by_cluster.get(cid)
            if sub is not None and pid < (sub.num_procs or 0):
                # Merged entry: DB values take precedence, schedd fills gaps.
                owner = sub.owner or job.get("Owner", "—")
                cmd = sub.cmd or job.get("Cmd", "")
                args = job.get("Args", "")
                batch = job.get("JobBatchName", sub.name)
            else:
                owner = job.get("Owner", "")
                cmd = job.get("Cmd", "")
                args = job.get("Args", "")
                batch = job.get("JobBatchName", "")
            return " ".join(
                str(x or "") for x in (cid, owner, cmd, args, batch)
            ).lower()

        def _sub_haystack(sub: JobSubmission) -> str:
            # Haystack of a DB-only proc (identical for every proc of the
            # submission), mirroring _build_job_entry's synthesized fields.
            return " ".join(
                str(x or "")
                for x in (sub.cluster_id, sub.owner or "—", sub.cmd or "", "", sub.name)
            ).lower()

        def _status_matches(status: int) -> bool:
            return status_filter is None or status == status_filter

        def _haystack_matches(haystack: str) -> bool:
            return not query_filter or query_filter in haystack

        # ---- Global stats over the WHOLE universe (all procs) ----
        stats: dict[str, int] = {  # type: ignore[no-redef]
            "total": 0,
            "idle": 0,
            "running": 0,
            "completed": 0,
            "held": 0,
            "removed": 0,
            "transferring": 0,
        }

        def _bucket(status: int) -> None:
            stats["total"] += 1
            if status == 1:
                stats["idle"] += 1
            elif status == 2:
                stats["running"] += 1
            elif status == 4:
                stats["completed"] += 1
            elif status == 5:
                stats["held"] += 1
            elif status == 3:
                stats["removed"] += 1
            elif status == 6:
                stats["transferring"] += 1

        matched_active: list[tuple[int, int]] = []
        for cid, pid in active_keys:
            job = active_by_key[(cid, pid)]
            sub = sub_by_cluster.get(cid)
            merged = sub is not None and pid < (sub.num_procs or 0)
            status = _active_status(job, merged)
            _bucket(status)
            if _status_matches(status) and _haystack_matches(
                _active_haystack(cid, pid, job)
            ):
                matched_active.append((cid, pid))

        def _db_only_count(sub: JobSubmission) -> int:
            n = sub.num_procs or 0
            active_pids = seen_by_cluster.get(sub.cluster_id, set())
            return sum(1 for p in range(n) if p not in active_pids)

        matched_subs: list[JobSubmission] = []
        if source != "schedd":
            for sub in deduped_subs:
                db_only = _db_only_count(sub)
                if db_only <= 0:
                    continue
                for _ in range(db_only):
                    _bucket(4)
                if _status_matches(4) and _haystack_matches(_sub_haystack(sub)):
                    matched_subs.append(sub)

        jobs: list[dict] = []  # type: ignore[no-redef]
        if grouped:
            # total = number of clusters; each page shows `limit` clusters
            # with ALL their procs expanded.
            cluster_ids: list[int] = []
            known: set[int] = set()
            for cid, _ in matched_active:
                if cid not in known:
                    known.add(cid)
                    cluster_ids.append(cid)
            for sub in matched_subs:
                if sub.cluster_id not in known:
                    known.add(sub.cluster_id)
                    cluster_ids.append(sub.cluster_id)
            total = len(cluster_ids)
            page_clusters = set(cluster_ids[offset : offset + limit])
            has_more = (offset + limit) < total
            for cid, pid in matched_active:
                if cid in page_clusters:
                    entry = _page_entry(cid, pid)
                    if entry is not None:
                        jobs.append(entry)
            for sub in matched_subs:
                if sub.cluster_id in page_clusters:
                    active_pids = seen_by_cluster.get(sub.cluster_id, set())
                    for pid in range(sub.num_procs or 0):
                        if pid in active_pids:
                            continue
                        jobs.append(_build_job_entry(sub, pid))
        else:
            # Proc-level pagination (flat view): total and has_more reflect
            # individual jobs (procs). The matched stream (active procs,
            # then DB-only procs per submission) is walked without
            # materializing entries for procs outside the page window.
            total = len(matched_active) + sum(_db_only_count(s) for s in matched_subs)
            has_more = (offset + limit) < total
            window_start, window_end = offset, offset + limit
            running = 0

            for cid, pid in matched_active:
                if running >= window_end:
                    break
                if running >= window_start:
                    entry = _page_entry(cid, pid)
                    if entry is not None:
                        jobs.append(entry)
                running += 1
            if running < window_end:
                for sub in matched_subs:
                    active_pids = seen_by_cluster.get(sub.cluster_id, set())
                    for pid in range(sub.num_procs or 0):
                        if pid in active_pids:
                            continue
                        if running >= window_end:
                            break
                        if running >= window_start:
                            jobs.append(_build_job_entry(sub, pid))
                        running += 1
                    if running >= window_end:
                        break

        return jsonify(
            {
                "jobs": jobs,
                "count": len(jobs),
                "total": total,
                "has_more": has_more,
                "limit": limit,
                "offset": offset,
                "stats": stats,
            }
        )
    except Exception:
        logger.exception("Failed to list history")
        return jsonify({"error": "Failed to load history"}), 500


@api_bp.route("/history/delete", methods=["POST"])
def delete_history():
    """Delete history entries from the local DB, logs, and optionally from the schedd.

    Request JSON:
    {
        "cluster_ids": [123, 456, ...],
        "delete_outputs": false  (optional, default false)
    }
    """
    data = request.get_json()
    if not data or "cluster_ids" not in data:
        return jsonify({"error": "Missing 'cluster_ids' in request body"}), 400

    cluster_ids = data["cluster_ids"]
    if not isinstance(cluster_ids, list) or not cluster_ids:
        return jsonify({"error": "'cluster_ids' must be a non-empty list"}), 400

    delete_outputs = data.get("delete_outputs", False)

    # Ensure a clean session state to avoid "rolled back" errors
    db.session.rollback()

    results = []
    for cid in cluster_ids:
        try:
            # Use a savepoint so one failure doesn't poison the outer transaction
            with db.session.begin_nested():
                # 1. Remove from schedd if still active
                if _api.daemon_available():
                    try:
                        act_on_job("remove", str(cid))
                    except Exception:  # noqa: BLE001, S110
                        pass  # Job may already be gone from schedd

                # 2. Delete from local DB
                submission = JobSubmission.query.filter_by(cluster_id=cid).first()
                deleted_outputs = 0
                if submission:
                    # 3. Remove individual log/out/err files from disk
                    for path_attr in ("log_path", "out_path", "err_path"):
                        file_path = getattr(submission, path_attr, None)
                        if file_path and Path(file_path).exists():
                            Path(file_path).unlink()
                    # 4. Optionally remove output files from disk
                    if delete_outputs:
                        deleted_outputs = delete_output_files_for_submission(submission)
                    db.session.delete(submission)

            results.append(
                {
                    "cluster_id": cid,
                    "success": True,
                    "deleted_output_files": deleted_outputs,
                }
            )
        except Exception as e:  # noqa: BLE001
            logger.error("Failed to delete cluster %d: %s", cid, e)
            db.session.rollback()  # Rollback the failed nested transaction
            results.append(
                {
                    "cluster_id": cid,
                    "success": False,
                    "error": "Failed to delete cluster",
                }
            )

    # Commit the outer transaction — only successful savepoints will be persisted
    db.session.commit()
    return jsonify({"results": results, "count": len(results)})


@api_bp.route("/history/release", methods=["POST"])
def release_history():
    """Bulk-release held jobs.

    Request JSON:
    {
        "cluster_ids": [123, 456, ...]
    }
    """
    data = request.get_json()
    if not data or "cluster_ids" not in data:
        return jsonify({"error": "Missing 'cluster_ids' in request body"}), 400

    cluster_ids = data["cluster_ids"]
    if not isinstance(cluster_ids, list) or not cluster_ids:
        return jsonify({"error": "'cluster_ids' must be a non-empty list"}), 400

    results = []
    for cid in cluster_ids:
        try:
            result = act_on_job("release", str(cid))
            results.append({"cluster_id": cid, "success": True, "result": str(result)})
        except Exception as e:  # noqa: BLE001
            logger.error("Failed to release cluster %d: %s", cid, e)
            results.append(
                {
                    "cluster_id": cid,
                    "success": False,
                    "error": "Failed to release cluster",
                }
            )

    return jsonify({"results": results, "count": len(results)})


@api_bp.route("/submissions")
def list_submissions():
    """List submissions made through this UI (from the local database)."""
    limit = request.args.get("limit", 100, type=int)
    submissions = (
        JobSubmission.query.order_by(JobSubmission.submitted_at.desc())
        .limit(limit)
        .all()
    )
    return jsonify({"submissions": [s.to_dict() for s in submissions]})
