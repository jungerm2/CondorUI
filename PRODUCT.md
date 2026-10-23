# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Users

Researchers on a shared HPC/HTCondor compute cluster (e.g. a university lab). They submit job batches between analysis runs, monitor progress (idle/running/held), fetch and upload input/output files, and manage container images and executables. Sessions are frequent and short: glance at the dashboard, act, leave.

## Product Purpose

A web UI over HTCondor's schedd: one place to submit, monitor, edit (qedit), hold/release/remove jobs, and manage the files and images those jobs need, without memorizing `condor_submit` syntax for routine cases (a raw submit-file editor covers the rest).

## Positioning

Zero-install, self-hosted cluster companion driven by the machine-local schedd — not a generic job dashboard: HTCondor ClassAd semantics (universes, transfer rules, staging checks, hold reasons) are first-class in the forms and details view.

## Operating Context

Runs on a node whose filesystem already holds the user's cluster artifacts (LogsDir-styled output paths, staging directories, OSDF-cached containers). Machine-local SQLite tracks submission history and saved templates. HTCondor tooling (`condor_q`, `condor_rm`, `condor_hold`, `condor_qedit`) is the authority; the UI's language is derived from it. No auth (deliberately out of scope this session).

## Capabilities and Constraints

- Dashboard: merged live-queue + history view, grouped by cluster, bulk hold/release/remove/edit, status filters, search, 30s auto-refresh, quotas.
- Submit: form builder (form ↔ raw submit-file two-way sync), raw editor, upload `.sub`, job templates.
- Files: upload/stage/unstage/delete/rename staging-directory files.
- Containers: list, pull, rename, delete images.
- Executables: upload/delete cluster-executables.
- Job details: live refresh, stdout/stderr/log panes, submit-file view, ClassAd attribute table + edit, download outputs.
- Output files: per-job output browsing/download.
- Constraint: dark-first single theme; functional name "Condor Web UI" stays; no auth flows; graceful degradation when schedd is down is already established behavior.

## Brand Commitments

Title "Condor Web UI" — keep, used verbatim in header/docs/tests.

Visual world (2026-10-21, user decision "play it straight" on the direction round): the **category standard, executed impeccably** — dark admin-panel canon (sidebar shell, stat overview, dense job table) embraced outright; the differentiator is craft, not an invented persona world. **Craft bar: GitHub (Actions/PRs) + Kubernetes Dashboard** — software-legible status/duration/panel polish plus calm, plain, disciplined layout. No theatrics, no persona styling.

Recorded exception to "dark-first single theme": the pre-existing light-theme DOM (`light-theme` class + header toggle, bound by the working theme script and left test-green) ships alongside; dark is the default and the design target, light is a carried-over convenience surface, not a second design system.

## Evidence on Hand

Working Flask app + vanilla JS/CSS frontend (`app/templates`, `app/static`); Playwright tests in `tests/`; hand-ALTERed runtime SQLite in `instance/`. No logos, no marketing assets, no real-screenshot corpus.

## Product Principles

1. **Queue truth at a glance** — dashboard must answer "what's running/broken/finished" faster than terminal `condor_q`.
2. **HTCondor semantics, not abstractions** — status codes, hold reasons, transfer rules stay named as HTCondor names them.
3. **Fast to leave** — researchers visit often, stay briefly; density and muscle memory beat novelty.
4. **Degrade gracefully** — schedd down ≠ app broken; the UI says so plainly.

## Accessibility & Inclusion

WCAG AA contrast on dark surfaces; full keyboard reachability (sortable headers, modals, focus management already in place); honors reduced-motion; no time-limited interactions beyond the explicit countdown refresh.
