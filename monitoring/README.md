# Monitoring

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
