# WHOOP dashboard

`WHOOP · Health & Training` has the stable Grafana UID `whoop-health` and URL
`/d/whoop-health`. It focuses on long-term history: recovery
and load, HRV/RHR trends, sleep duration/stages/quality/schedule, weekly
training volume, HR zones, activity totals and a workout journal. Additional
physiology has its own row; three exploratory scatter plots are collapsed.
The activity selector affects training panels only. Each graph and table has
its own full-width row. The latest-observation cards and data-date table are
omitted; use the WHOOP phone app for current readings.

Recovery uses WHOOP-style solid green/yellow/red bars. Recovery, Day Strain,
HRV and resting heart rate each have one dashed trailing average. Its window
adapts to the selected range: up to 14 days → 1 day; up to 45 → 3 days; up to
120 → 7 days; up to 240 → 14 days; longer → 30 days. The legend names the
active window, so 30/90/180-day views use 3/7/14-day smoothing. The
horizontal breakdown counts recorded cycles in each zone (green ≥67%,
yellow 34–66%, red ≤33%). The summary comparison and Naps panels are omitted.

## Storage and access

A dedicated PostgreSQL 17 Deployment in `monitoring` stores the historical
observations on a 1 GiB `local-path` PVC without time-based expiry. It is
separate from both Grafana's own database and Prometheus's 30-day history.
The database has no ingress or host port. A NetworkPolicy permits TCP/5432
only from Grafana and WHOOP backup pods in the same namespace. It relies on the
cluster CNI's NetworkPolicy enforcement. SQL import uses a local Unix socket
via `kubectl exec`. Flux pruning is disabled for this PVC so removing the
Deployment from Git does not automatically erase the stored observations.

Grafana uses the built-in PostgreSQL data source, UID `whoop-postgres`, with a
dedicated SELECT-only role. The existing Grafana sidecar discovers the
SOPS-encrypted `whoop-grafana-datasource` Secret (`grafana_datasource: "1"`)
and reloads provisioning without restarting Grafana. Only the reader password
is included in that provisioning Secret. The separate database credentials
Secret supplies the admin password only to PostgreSQL and the reader password
to the backup job. Database traffic stays inside the cluster; TLS is disabled
on this internal connection. Grafana's existing authentication and access
rules apply to this dashboard and data source.

CSV exports, generated SQL and database backups contain personal health data.
Keep them outside Git. `private/` is ignored for optional local backups. The
repository contains schema, queries and encrypted credentials only.

References: [Grafana PostgreSQL provisioning](https://grafana.com/docs/grafana/latest/datasources/postgres/configure/),
[official PostgreSQL image](https://hub.docker.com/_/postgres).

## Rollout and initial import

Normal deployment uses Flux after the user commits and pushes. The user also
explicitly authorized a direct live preview: the new WHOOP database, data-source
Secret and backup CronJob are already applied, without changing or suspending
the existing Flux Kustomizations or HelmRelease. Flux can adopt these resources
after the source is committed and pushed. No commit or push was performed.

The directly created editable dashboard has UID `whoop-health-preview`, lives
in the `WHOOP Preview` folder, and uses the same WHOOP database. Open
`https://grafana.vitalyguzun.com/d/whoop-health-preview`, click **Edit**, then
**Save dashboard**. It is an ordinary API-created dashboard, so file provisioning
will not overwrite these edits. The Git-managed dashboard uses the separate UID
`whoop-health` and will be installed by Flux after commit/push.

The existing Grafana stores its own database on `emptyDir`. Preview/UI changes
can be lost if the Grafana Pod is recreated. Export the preview's dashboard JSON
before such a restart and before transferring reviewed layout changes into the
Git-managed builder. A dashboard JSON export contains configuration and queries,
not the PostgreSQL observation rows. WHOOP's PostgreSQL PVC and NAS backups
are separate from Grafana's database and survive a Grafana restart.

```bash
flux reconcile source git flux-system -n flux-system
flux reconcile kustomization monitoring-controllers -n flux-system
kubectl -n monitoring rollout status deployment/whoop-postgres --timeout=180s
kubectl -n monitoring get helmrelease kube-prometheus-stack
flux reconcile kustomization monitoring-configs -n flux-system
```

Confirm PostgreSQL is Ready and the WHOOP data-source health check succeeds.
The sidecar reloads the new source without a Grafana rollout. The database and
source already exist for the direct preview, so importing again is safe.

Validate an export directory containing `physiological_cycles.csv`, `sleeps.csv`
and `workouts.csv`, then import it (Python 3.9+ and kubectl; no pip packages):

```bash
python3 monitoring/whoop/import_whoop.py '/path/to/whoop'
python3 monitoring/whoop/import_whoop.py '/path/to/whoop' --apply
```

The default Kubernetes context is `proxmox`, namespace `monitoring`; override
with `--context` and `--namespace` if required. Import access requires permission
to exec into the database pod and is equivalent to database admin access.
The first command only validates and prints counts. The second validates all
three files before starting a single transaction. It upserts by UTC cycle or
session start, updates the previously open cycle on the next export, and records
the import date. An advisory lock serializes imports. Repeating an export does
not duplicate observations. Records outside the export are preserved, so a
shorter later export does not erase older history. A session deleted in WHOOP
is not automatically deleted here; moving its start time needs manual review.

This version is a manual export/import workflow, with no WHOOP OAuth/API sync.
After import, open `/d/whoop-health` in the existing Grafana and reload the
browser page so the activity selector also refreshes.
The dashboard shows historical observations within the selected period. The
import command prints successful import counts; import timestamps remain in
`whoop.imports` for inspection without adding current-reading cards.

## Data conventions

- Physiological cycles provide daily recovery and load. `sleeps.csv` alone
  supplies sleep metrics, preventing duplicate sleep totals from the cycle CSV.
- Parse timestamps with each row's `Cycle timezone` and store UTC instants.
  Also preserve original local sleep/workout timestamps. Daily graphs use the
  main wake instant, with a cycle endpoint fallback for the initial partial
  cycle. Grafana displays absolute timestamps in Europe/Amsterdam.
- Weekly activity buckets use Monday of the original local workout date;
  categorical labels show Monday–Sunday date intervals with the year. Stacked
  bars show hours per activity or reported HR zone, including zero-activity
  weeks. An asterisk marks weeks only partly inside the selected range; totals
  include only selected workouts. Activity columns are generated dynamically
  from the selected workouts. Sleep schedule uses blue intervals on an inverted
  overnight clock. PostgreSQL stored generated columns on `whoop.sleeps` compute
  `bedtime_night_seconds` and `wake_night_seconds` on every INSERT/UPDATE,
  including the existing CSV import. They are integer seconds from local
  midnight, unwrapped at noon. Original timestamps remain unchanged. This also
  handles after-midnight bedtimes and travel without a dashboard timezone shift.
  `whoop.sleep_schedule(from, to)` selects main sleeps and computes period
  averages in SQL: 23:30 and 00:30 average to 00:00. WHOOP's `in_bed_min` includes
  awake time and remains distinct from time asleep. Business Charts formats
  axis ticks with a short HH:mm formatter and draws the intervals. There are
  no value-mapping tables, inverted floating-hour coordinates or reference dates.
  Clock coordinates retain second precision; labels use HH:mm.
- Naps are separate observations. Multiple main sleeps per cycle, duplicate
  timestamps, invalid numeric values, malformed headers, and missing cycle
  references fail validation before writing to the database.
- Preserve blanks as NULL and real zeros as zero. Open-cycle Day Strain and
  calories are not filled from a prior day. Use the supplied Sleep Need, Sleep
  Debt and Sleep Performance independently rather than recreating WHOOP scores.
- Strain is nonlinear: never sum activity Strain to calculate Day Strain or
  weekly load. Weekly volume sums activity minutes. See [WHOOP's description](https://www.whoop.com/us/en/thelocker/how-does-whoop-strain-work-101/).
- HR-zone minutes are approximate: duration × reported zone percentage / 100.
  Zones 1–5 do not cover all activity time in these exports; no normalization
  or assignment of the remainder is performed. The journal shows their total
  percentage. All-zero rows stay as reported, without inferring no effort.
- Recovery, Day Strain, HRV and resting-HR moving averages use a trailing
  time window that adapts to the selected range as listed above. They include
  a full warm-up window before the visible range, include the current
  observation and use no future observations. NULL observations are omitted
  without zero-filling. Relationship plots use complete paired observations. The
  load/recovery plot joins the next chronological cycle, not a calendar-day join
  that could be wrong during travel. Associations do not establish causation.
- No continuous HR samples, GPS routes, distance/pace or strength sets/reps are
  present in these exports. No clinical alerts or target load are synthesized.

## Validation and maintenance

```bash
python3 -m unittest discover -s monitoring/whoop -v
python3 monitoring/whoop/build_dashboard.py
kubectl kustomize monitoring/controllers/proxmox > /tmp/monitoring-controllers.yaml
kubectl kustomize monitoring/configs/proxmox > /tmp/monitoring-configs.yaml
kubectl apply --dry-run=server -f monitoring/controllers/proxmox/whoop/postgres.yaml
kubectl apply --dry-run=server -f monitoring/configs/proxmox/kube-prometheus-stack/whoop-dashboard.yaml
```

Edit `build_dashboard.py` and, for sleep rendering, `sleep_schedule.js`, then
regenerate the dashboard ConfigMap; do not manually edit the generated YAML.
The sleep panel requires signed `volkovlabs-echarts-panel` **7.2.2**, compatible
with Grafana 12.1.1. Its version is pinned in the Proxmox HelmRelease patch via
`grafana.ini.plugins.preinstall_sync`. It was also installed from the catalog
at runtime for the editable preview, without recreating the Grafana Pod. This
renderer does not fetch external libraries or send observation data elsewhere.
Flux applies the persistent startup configuration after the user's commit/push.

`schema.sql` and then `sleep-schedule.sql` run on **first database initialization**.
For later schema changes, review and explicitly apply a migration; changing the
ConfigMap alone does not migrate an existing PVC. The same applies to password
rotation: update the database roles and encrypted Secret together. Merely
changing the Secret does not reset existing PostgreSQL passwords. Pin the
PostgreSQL major version until a deliberate database upgrade is performed.

For an existing database, apply the additive sleep migration explicitly after
a backup; an updated init ConfigMap does not migrate an existing PVC. The
migration also computes the two stored columns for existing observations, so
no re-import is needed. Reapplying it is safe. The live preview database has
already been migrated.

```bash
kubectl --context proxmox -n monitoring exec -i deployment/whoop-postgres -- \
  psql -U postgres -d whoop -v ON_ERROR_STOP=1 \
  < monitoring/controllers/proxmox/whoop/sleep-schedule.sql
kubectl --context proxmox -n monitoring exec -i deployment/whoop-postgres -- \
  psql -U postgres -d whoop -v ON_ERROR_STOP=1 \
  < monitoring/controllers/proxmox/whoop/tests/sleep-schedule.sql
```

The integration check uses temporary synthetic rows and rolls back. It checks
midnight averaging, after-midnight bedtimes, travel/timezone independence,
generated-column recomputation on UPSERT, existing clocks and reader access.

Check imported counts without exposing individual measurements:

```bash
kubectl -n monitoring exec deployment/whoop-postgres -- psql -U postgres -d whoop -c \
  'SELECT (SELECT count(*) FROM whoop.cycles) AS cycles, (SELECT count(*) FROM whoop.sleeps) AS sleeps, (SELECT count(*) FROM whoop.workouts) AS workouts;'
```

Check Grafana's WHOOP data-source health and confirm the historical dates and
filtered workout totals match the export. Re-import the same export and check
that observation counts stay unchanged. A newly imported open cycle must show
NULL final Day Strain. Grafana's role must fail an INSERT/UPDATE attempt.

## Scheduled backup and restore

The PVC survives pod recreation but is local to the k3s node; it is **not a
backup**. `whoop-backup` runs every day at **03:30 Europe/Amsterdam**, using
PostgreSQL 17 `pg_dump` with the SELECT-only role. It creates a consistent
custom-format archive, reads/decompresses its entries with `pg_restore`, writes
it via a temporary filename to Synology, and verifies a SHA-256 checksum.
The exact NAS endpoint and NFS export are in `backup-cronjob.yaml`, following
the existing Linkding backup setup.

Files on the NAS:

```text
/volume1/backups/whoop/whoop-YYYY-MM-DDTHH-MM-SSZ.dump
/volume1/backups/whoop/whoop-YYYY-MM-DDTHH-MM-SSZ.dump.sha256
```

The first live backup on 2026-10-20 was restored from the NAS into a separate
temporary PostgreSQL and its table counts were checked against the source.
The restore-check Pod was then removed. The scheduled job does not delete old
archives; retention and NAS snapshots are configured separately. Dumps contain
health data and are private to the NAS backup share; they are not encrypted by
this script and never enter Git. The archive excludes role passwords, owners
and ACLs; a restore needs the reader role/grants reapplied separately.

Run an extra backup after importing new data or before a migration:

```bash
job="whoop-backup-manual-$(date +%s)"
kubectl -n monitoring create job --from=cronjob/whoop-backup "$job"
kubectl -n monitoring wait --for=condition=complete --timeout=30m "job/$job"
kubectl -n monitoring logs "job/$job"
kubectl -n monitoring get cronjob whoop-backup
```

Keep original CSV exports as well. For an additional local dump outside Git:

```bash
umask 077
mkdir -p monitoring/whoop/private
kubectl -n monitoring exec deployment/whoop-postgres -- pg_dump -U postgres -d whoop -Fc \
  > monitoring/whoop/private/whoop.dump
```

Restore into a **separate empty database** first. Verify the checksum, then run
`pg_restore --no-owner --no-acl --exit-on-error -U postgres -d <restore_db> <dump>`.
Check table counts and main-sleep/workout dates. Recreate `whoop_grafana` and
apply the grants from `schema.sql` and `sleep-schedule.sql` before switching
Grafana to the restored database. For backups predating the sleep migration,
run `sleep-schedule.sql` to add its generated columns and function. Never use a restore test to overwrite the live database.

## Rollback

To disable the dashboard, remove its ConfigMap from the configs kustomization
and its data-source Secret. Removing the `whoop` controller directory from its
parent kustomization prunes the Deployment and backup schedule after Flux adopts
them. The PVC is protected from pruning and needs explicit manual deletion.
Keep and verify a NAS backup before intentionally deleting the PVC. The separate
API-created preview must be removed through Grafana if it is no longer needed.
