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
