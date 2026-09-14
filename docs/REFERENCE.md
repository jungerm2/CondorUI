# Reference — REST API & Data Model

Technical reference for the Condor Web UI. For user-facing setup and safety
notes, see the [README](../README.md).

> The API has **no authentication** — see the safety notes in the README before
> exposing this service.

## Conventions

- All routes are under the `/api` prefix, defined in `app/api.py`.
- Responses are JSON. Errors are `{"error": "<message>"}` with a `4xx`/`5xx` status.
- Job identifiers: `<job_id>` is `ClusterId.ProcId` (a bare cluster id also works);
  `<cluster_id>` and `<proc_id>` are integers.
- When the schedd is unreachable, list endpoints return empty results with
  `"daemon_unavailable": true` instead of failing.

## Jobs

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/api/health` | Liveness check (`{"status": "ok"}`); does not query the schedd. |
| `GET` | `/api/jobs` | Active jobs. Query: `owner`, `status` (JobStatus int), `cluster_id`, `limit` (default 200, max 5000), `offset`. Returns `{jobs, count, total, has_more, limit, offset}`. |
| `GET` | `/api/jobs/<cluster_id>` | Cluster ClassAds (all procs). |
| `GET` | `/api/jobs/<cluster_id>/details` | ClassAds plus resolved log/stdout/stderr file info. |
| `GET` | `/api/jobs/<cluster_id>/log` | User-log contents. |
| `GET` | `/api/jobs/<cluster_id>/<proc_id>/files` | Log / stdout / stderr contents for one proc. |
| `GET` | `/api/history` | Unified history table with real-time status and global `stats`. Query: `source` (`merged` default, `schedd`, `db`), `limit` (default `MAX_HISTORY_RESULTS`), `offset`, `grouped` (`0` proc-level or `1` cluster-level pagination). Returns `{jobs, count, total, has_more, limit, offset, stats}`. |
| `GET` | `/api/submissions` | Raw submissions from the local DB. |
| `POST` | `/api/submit` | Submit from a JSON submit description. |
| `POST` | `/api/submit/file` | Submit from an uploaded `.sub` file. |
| `POST` | `/api/qedit` | Edit a ClassAd attribute. Body: `{cluster_id, proc_id, attr, value}`. |
| `POST` | `/api/jobs/<job_id>/hold` | Hold a job. |
| `POST` | `/api/jobs/<job_id>/release` | Release a held job. |
| `DELETE` | `/api/jobs/<job_id>` | Remove a job. |
| `POST` | `/api/clusters/hold` | Bulk hold. Body: `{cluster_ids: [...]}`. |
| `POST` | `/api/clusters/release` | Bulk release. Body: `{cluster_ids: [...]}`. |
| `POST` | `/api/history/delete` | Delete history entries from schedd, DB, and individual log files. Body: `{cluster_ids: [...], delete_outputs: false}`. |
| `POST` | `/api/history/release` | Bulk release held jobs. Body: `{cluster_ids: [...]}`. |

## Input Files

Uploads use the raw request body with `Content-Type: application/octet-stream`
plus headers `X-Upload-Filename` (required) and `X-Overwrite: true` to replace.

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/api/files` | List files from `UPLOAD_DIR` and `OSDF_ROOT_PATH/uploads/`, marked local or staged. |
| `POST` | `/api/files` | Upload a file (see headers above). Returns `409` on name conflict without overwrite. |
| `PUT` | `/api/files/<path:filename>` | Rename a file. Body: `{filename: "new-name"}`. |
| `DELETE` | `/api/files/<path:filename>` | Delete a file from disk. |
| `POST` | `/api/files/<path:filename>/stage` | Move a file to `OSDF_ROOT_PATH/uploads/`. Requires `OSDF_ROOT_PATH`. |
| `POST` | `/api/files/<path:filename>/unstage` | Move a staged file back to `UPLOAD_DIR`. |

## Executables

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/api/executables` | List uploaded executables in `EXECUTABLES_DIR`. |
| `POST` | `/api/executables` | Upload an executable (same raw-body headers as files); stored `0755`. |
| `DELETE` | `/api/executables/<path:filename>` | Delete an executable. |

## Containers

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/api/containers` | List `.sif` images in `OSDF_ROOT_PATH/containers/`. |
| `POST` | `/api/containers/pull` | Pull a Docker image via `apptainer` (600 s timeout). Body: `{image, name?, overwrite?}`. |
| `GET` | `/api/containers/pull/stream` | Server-Sent Events stream of a pull's progress. |
| `POST` | `/api/containers/upload` | Upload an existing `.sif` file. |
| `PUT` | `/api/containers/<path:filename>` | Rename a container (display name). |
| `DELETE` | `/api/containers/<path:filename>` | Delete a container. |

## Templates

Templates are stored as `.json` files in `TEMPLATES_DIR` (slugified from the name).

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/api/templates` | List templates. |
| `POST` | `/api/templates` | Create. Body: `{name, submit_data, ...}`. Returns `409` if the name exists. |
| `PUT` | `/api/templates/<name>` | Update a template. |
| `DELETE` | `/api/templates/<name>` | Delete a template. |
| `GET` | `/api/templates/<name>/download` | Download the template file. |
| `GET` | `/api/templates/<name>/preview` | Preview the template contents. |

## Output Files & Quotas

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/api/output-files` | List output files located via `output_destination` and `transfer_output_remaps`. |
| `GET` | `/api/output-files/download/<cluster_id>/<path:filename>` | Download an output file. |
| `DELETE` | `/api/output-files/delete/<cluster_id>/<path:filename>` | Delete an output file from disk. |
| `GET` | `/api/quotas` | Parse the system `get_quotas` command. `500` if the command is unavailable. |

## Page Routes

HTML pages are served by `app/views.py` (`views_bp`).

| Route | Template | Purpose |
|---|---|---|
| `/` | `dashboard.html` | Dashboard — active jobs + history. |
| `/submit` | `submit.html` | Job submission (form / raw / upload). |
| `/templates` | `templates.html` | Submit templates. |
| `/files` | `files.html` | Input file management. |
| `/executables` | `executables.html` | Executable management. |
| `/containers` | `containers.html` | Container image management. |
| `/output-files` | `output_files.html` | Output file management. |
| `/job/<cluster_id>` | `job_details.html` | Job details (optionally `/job/<cluster_id>/<proc_id>`). |
| `/history` | — | Redirects to `/` (history is merged into the dashboard). |

## Data Model

### Database (SQLAlchemy)

The only ORM model is **`JobSubmission`** (table `job_submissions`), defined in
`app/models.py`. It records jobs submitted through the UI:

| Column | Type | Notes |
|---|---|---|
| `id` | Integer | Primary key. |
| `cluster_id` | Integer | HTCondor cluster id (indexed). |
| `name` | String(255) | Display name, defaults to `Untitled Job`. |
| `submit_description` | Text | Raw `.sub` text or a JSON string (form mode). |
| `num_procs` | Integer | Number of procs in the cluster. |
| `submitted_at` | DateTime (UTC) | Submission time. |
| `log_path` | String(1024) | Resolved `UserLog` path. |
| `out_path` | String(1024) | Resolved stdout path. |
| `err_path` | String(1024) | Resolved stderr path. |
| `output_destination` | String(1024) | Resolved output destination directory. |
| `transfer_output_remaps` | Text | Resolved `transfer_output_remaps`. |
| `owner` | String(128) | Job owner. |
| `cmd` | Text | Submitter's command (for display). |

The SQLite database lives at `DATABASE_URL` (default `instance/condor_webui.db`).

### Filesystem-backed stores

Uploaded assets are **not** database rows — the filesystem is the source of
truth, and files are grouped into UUID subdirectories (`<uuid>/<name>`).

| Store | Location | Layout / notes |
|---|---|---|
| Input files | `UPLOAD_DIR` | `<uuid>/<name>`; listing merges with the OSDF copy. |
| Staged files | `OSDF_ROOT_PATH/uploads/` | `<uuid>/<name>`; moved (not copied) to/from `UPLOAD_DIR`. |
| Executables | `EXECUTABLES_DIR` | Flat; uploaded files are made `0755`. |
| Templates | `TEMPLATES_DIR` | `<slug>.json` per template. |
| Containers | `OSDF_ROOT_PATH/containers/` | `<uuid>/<safe_name>.sif`; only when `OSDF_ROOT_PATH` is set. |
| Output files | `OUTPUT_DIR/<ClusterId>/` | Discovered via `output_destination` / `transfer_output_remaps`. |
| Job logs | `JOB_LOGS_DIR/<ClusterId>/` | HTCondor user log, stdout, stderr. |

URIs for OSDF-staged files and containers are built as
`OSDF_BASE_URI` + the stored path.