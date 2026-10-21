# Monitoring

## WHOOP health and training

`WHOOP · Health & Training` (`/d/whoop-health`) uses a dedicated PostgreSQL
history store and a manual CSV importer. Setup, validation, data conventions,
and backup instructions are in the [WHOOP runbook](whoop/README.md).

Flux installs `kube-prometheus-stack` from `monitoring/controllers` and applies
dashboards and custom rules from `monitoring/configs` after the controllers are
ready.

## Prometheus storage

Prometheus keeps 30 days of metrics on a 40 GiB `local-path` PVC. The TSDB is
limited to 35 GB so that the WAL and compaction have free space.

The first reconciliation after enabling the PVC replaces the existing
`emptyDir` storage. Current ephemeral history can be lost during this one-time
migration. Later Prometheus Pod restarts reuse the PVC.

Verify the rollout:

```bash
kubectl -n monitoring get prometheus kube-prometheus-stack-prometheus
kubectl -n monitoring get pvc
kubectl -n monitoring get pods -l app.kubernetes.io/name=prometheus
```

Verify the effective retention settings:

```bash
kubectl -n monitoring get prometheus kube-prometheus-stack-prometheus \
  -o jsonpath='{.spec.retention}{" / "}{.spec.retentionSize}{"\n"}'
```

## Scrape targets

List targets that are not `UP` through the Kubernetes API proxy:

```bash
kubectl get --raw \
  '/api/v1/namespaces/monitoring/services/http:kube-prometheus-stack-prometheus:9090/proxy/api/v1/targets?state=active' \
  | jq '.data.activeTargets[] | select(.health != "up") | {scrapePool, scrapeUrl, lastError}'
```

An empty result means that every discovered target is healthy. The chart's
built-in `TargetDown` alert monitors this continuously.

## Git-managed Grafana resources

The Grafana sidecar discovers ConfigMaps labeled `grafana_dashboard: "1"` in
all namespaces. `Homelab Overview` is provisioned from Git and therefore does
not depend on Grafana's local database.

Custom rules must carry `release: kube-prometheus-stack` so that the Prometheus
rule selector discovers them.

## Hardware temperatures

`Homelab Overview` includes temperature panels and alerts for the Synology NAS
and the physical mini-PC:

- Synology is scraped through its official SNMP System and Disk MIBs. In DSM,
  enable SNMPv2c under **Control Panel > Terminal & SNMP > SNMP** and use the
  community stored in the encrypted `synology-snmp-credentials` Secret. Limit
  UDP port 161 in DSM Firewall to the Kubernetes node/LAN source that runs the
  SNMP exporter.
- The mini-PC panels read `node_hwmon_temp_celsius`. Install node_exporter on
  the physical Proxmox host and add that target to Prometheus; the k3s QEMU
  guest has no access to the host's `/sys/class/hwmon` sensors.

After Flux has reconciled the encrypted Secret, read the generated SNMP
community before entering it in DSM:

```bash
kubectl -n monitoring get secret synology-snmp-credentials \
  -o jsonpath='{.data.SNMP_COMMUNITY}' | base64 --decode
echo
```

Verify Synology collection after DSM SNMP is enabled:

```bash
kubectl -n monitoring get servicemonitor
kubectl -n monitoring get pods -l app.kubernetes.io/name=prometheus-snmp-exporter
kubectl get --raw \
  '/api/v1/namespaces/monitoring/services/http:kube-prometheus-stack-prometheus:9090/proxy/api/v1/query?query=synology_system_temperature_celsius'
```

The dashboard uses conservative warning thresholds: 50°C for the Synology
system, 45°C for disks, and 70°C for the mini-PC CPU. Alerts fire at 50°C for a
Synology disk or system sensor and at 85°C for the mini-PC CPU.

## Homelab Applications (phase 1)

`Homelab Applications` is provisioned alongside `Homelab Overview` by the same
Grafana sidecar. Its stable UID is `homelab-applications`.

Phase 1 focuses on Audiobookshelf, Navidrome and Linkding. The top strip
shows k3s VM CPU/RAM and compact Synology temperature and health indicators.
CPU and RAM rankings use a fixed 0–100% scale of the single k3s VM capacity
(`kube_node_status_capacity`); they do not represent the physical Proxmox host.
The compact table includes readiness, current/1h CPU share, RAM in bytes and % of VM capacity, config storage
and restarts. Each app has its own section with readiness, CPU, RAM, config
storage, links to its UI and CPU/RAM history. External applications and user
analytics will be added when their metrics become available.

- Kubernetes readiness is available/desired Deployment replicas, not HTTP availability.
- CPU now is a 5-minute average; CPU average 1h uses a 1-hour rate.
- RAM is the working set. CPU/RAM and restarts include the main application
  container only, excluding Linkding backups and cloudflared.
- App/config storage includes Audiobookshelf config + metadata, Navidrome data,
  and Linkding data PVCs. Media PVCs are excluded. These are kubelet-reported
  values, not independently measured directory sizes. Navidrome currently reports
  shared filesystem usage exceeding its requested PVC size; the query rejects
  that value and displays `N/A`. Accurate directory sizes need a later collector.
- Synology health summarizes existing fan/thermal and disk statuses. Non-normal
  status codes are labeled `Check DSM`; missing telemetry stays `N/A`.

Validate before rollout:

```bash
kubectl kustomize monitoring/configs/proxmox > /tmp/monitoring-configs.yaml
kubectl apply --dry-run=server -f monitoring/configs/proxmox/kube-prometheus-stack/homelab-applications-dashboard.yaml
```

After committing and pushing the change for Flux reconciliation, open
`/d/homelab-applications` in Grafana. Check that the table has three application rows, readiness reads `Ready`,
missing storage displays `N/A`, and CPU percentages in cards and rankings match
the table. RAM ranking shows % of VM capacity while the table/cards show bytes. Compare RAM with `kubectl top pods`
(note that CPU uses different averaging windows). The old dashboard remains
available. No new exporter, alert, or credentials are introduced in this phase.

## Application availability (phase 2)

Flux deploys `prometheus-blackbox-exporter` as an internal ClusterIP service,
with no ingress or host port. Nine `Probe` resources use the existing Prometheus
selector (`release: kube-prometheus-stack`). Each target carries `app`, `host`,
`runtime`, `url` (the user-facing root URL), and `route` labels.

Probes run every 30 seconds with a 10-second HTTP timeout and 15-second scrape
timeout. HTTPS probes validate certificates and require HTTPS. They use the
normal Pod DNS/Tailscale route, not a DNS override to an internal service.
Prowlarr is deliberately checked over LAN HTTP at `192.168.1.59:9696/ping`.

| App | Probe path |
| --- | --- |
| Audiobookshelf, Navidrome, Radarr, Sonarr | `/ping` |
| Jellyfin, Linkding | `/health` |
| Seerr | `/api/v1/status` |
| qBittorrent | `/` |
| Prowlarr (LAN HTTP) | `/ping` |

The availability table shows all nine apps, host, route, clickable URL, probe
duration and last success. `Available` means the endpoint returned HTTP 200;
it does not verify login or playback. `Unavailable` means the exporter was
scraped successfully but the endpoint check failed. `No data` means probe
telemetry is missing or cannot be scraped. Kubernetes Deployment readiness
remains separate in the k3s resource table.

The recording rule `homelab_application_last_success_timestamp_seconds` retains
the last successful observation through failed checks and exporter outages,
starting with the first successful probe after deployment. When a target is
removed its retained value expires once its scrape series becomes stale.
The timestamp uses the configured browser timezone in Grafana.

Verify after committing/pushing and Flux reconciliation:

```bash
flux reconcile source git flux-system -n flux-system
flux reconcile kustomization monitoring-controllers -n flux-system
flux reconcile kustomization monitoring-configs -n flux-system
kubectl -n monitoring get helmrelease prometheus-blackbox-exporter
kubectl -n monitoring get probes
```

Check `probe_success{job="homelab-applications"}` and
`up{job="homelab-applications"}` in Prometheus. A temporary probe to an unused
loopback port of the exporter can verify `probe_success=0` without stopping any
application; restore a working target and check automatic recovery. Never leave
this temporary test target in Git. Verify the dashboard remains unchanged after
another Flux reconciliation. Remove the HelmRelease, probes and recording rule
from their kustomizations to roll back the exporter; restore the prior dashboard
JSON in Git to roll back its availability panels.
