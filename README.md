# Condor Web UI

A web interface for submitting, monitoring, and managing [HTCondor](https://htcondor.org/)
jobs. It wraps the HTCondor Python bindings in a Flask app with a dashboard, a
job-submission wizard, reusable templates, and pages for managing input files,
executables, containers, and output files — no command line required.

## Quick Start

**Requirements**

- This app needs to run on a condor access point to have access to the condor scheduler, the OSDF, etc. You'll also need to connect to the port, so consider port forwarding via an ssh connection.
- The [uv](https://docs.astral.sh/uv/) package manager which will install the dependencies (Python ≥ 3.14 and HTCondor Python bindings (`htcondor` / `htcondor2`))
- Optional: `apptainer` (for pulling container images) and `get_quotas` (for the quota view) these will typically already be available from the AP.  

```bash
# 1. Install dependencies
uv sync

# 2. (Optional) configure via environment variables — see Configuration below
source .env

# 3. Run the webUI
uv run python run.py
```

Open **http://localhost:5000**. The app starts even if the schedd is down and
will show a "daemon unavailable" notice rather than failing.

## Features

- **Dashboard** — live view of active jobs with status counts, filters, sorting,
  hold / release / remove, and QEdit. History is merged into the same table with
  cluster/proc pagination and a "group by ClusterID" toggle. Auto-refreshes every 30 s.
- **Job Submission** — three modes: Form Builder, Raw `.sub` editor, or upload a
  `.sub` file. Supports shell commands, itemdata (`queue from`), and output remaps.
- **Templates** — save, load, edit, download, and delete reusable submit descriptions.
- **Job Details** — per-process ClassAd attributes plus log / stdout / stderr
  tailing and download.
- **Data Management** — upload and stage/unstage input files to OSDF, manage
  uploaded executables, browse and download job output files, and pull Docker
  images (converted to Apptainer `.sif`) or upload `.sif` files.
- **System** — disk quota view, dark/light theme, toast notifications, and a
  connection status indicator.

## Configuration

Every setting has a sensible default; override via environment variables.

| Variable | Default | Description |
|---|---|---|
| `SECRET_KEY` | `condor-webui-dev-key` | Flask secret key. **Change before exposing the app.** |
| `DATABASE_URL` | `sqlite:///<root>/instance/condor_webui.db` | SQLAlchemy database URI. Relative SQLite paths resolve against `instance/`, not the working directory. |
| `UPLOAD_DIR` | `<root>/uploads` | Uploaded input files. |
| `EXECUTABLES_DIR` | `<root>/executables` | Uploaded executables. |
| `OUTPUT_DIR` | `<root>/outputs` | Transferred job output (`OUTPUT_DIR/<ClusterId>/`). |
| `JOB_LOGS_DIR` | `<root>/condor_job_logs` | Job stdout, stderr, and user logs. |
| `TEMPLATES_DIR` | `<root>/templates` | Saved submit templates (`.json` files). |
| `OSDF_ROOT_PATH` | `/staging/${USER:0:1}/$USER/webui` | OSDF staging root; files/containers land in `uploads/` and `containers/` subdirs. |
| `OSDF_BASE_URI` | `osdf:///chtc` | URI prefix used to build `transfer_input_files` paths. |
| `MAX_HISTORY_RESULTS` | `200` | Default history page size. |
| `MAX_CONTENT_LENGTH` | `10737418240` (10 GB) | Maximum upload size in bytes. |
| `HOST` | `0.0.0.0` | Dev-server bind address. |
| `PORT` | `5000` | Dev-server port. |
| `FLASK_DEBUG` | `0` | Set to `1` for auto-reload (development only). |

## Safety & Operational Notes

> ⚠️ This is a **development server with no authentication or authorization**.
> Anyone who can reach the port has full control. Read this section before exposing it.

- **No login / access control.** Every visitor can submit, hold, release, and
  remove jobs and upload/delete files. The default bind is `0.0.0.0`, so run it
  behind a firewall, VPN, or an authenticating reverse proxy — never on an open network.
- **Actions run as the server's OS user.** HTCondor commands, `apptainer pull`,
  and `get_quotas` execute with the identity of whoever launched `run.py`; job
  submission and file access are limited to that user's HTCondor permissions.
- **Deletion is permanent.** Removing a job also deletes its `OUTPUT_DIR/<ClusterId>/`
  directory from disk, and deleting files, executables, or output files unlinks
  them immediately. There is no undo or trash.
- **Staging moves files, it does not copy them.** Staging a file to OSDF (or
  unstaging it back) relocates the only copy, so a file is never in two places at once.
- **Change `SECRET_KEY`** away from the default before any shared or long-lived deployment.
- **Resource use.** Uploads default to a 10 GB cap and container pulls are slow;
  keep an eye on disk usage in the app's data directories and on `OSDF_ROOT_PATH`.

## Development

```bash
uv run pytest                                    # run the test suite
uv run ruff format .                             # format
uv run ruff check --extend-select I --fix .      # lint + sort imports
```

Tests use the `create_app()` factory with an in-memory database:

```python
from app import create_app
app = create_app({"TESTING": True, "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:"})
```

See [`docs/REFERENCE.md`](docs/REFERENCE.md) for the full REST API and data model.
