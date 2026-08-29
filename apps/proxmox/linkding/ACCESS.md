# Linkding access

Linkding has two independent HTTPS access paths. Both terminate at the same
Kubernetes `linkding` Service on port `9090`, but they use different gateways
and DNS zones.

| Client | URL | Route | Authorization |
| --- | --- | --- | --- |
| Tailnet device | `https://linkding.vitalyguzun.com` | Vercel DNS -> Tailscale `homelab-gateway` -> Traefik -> Linkding | Tailscale ACLs and Linkding login |
| Work computer without Tailscale | `https://linkding-work.vitalyguzun-homelab.com` | Cloudflare DNS -> Access -> Tunnel `linkding-proxmox` -> Linkding | Cloudflare Access and Linkding login |

The work route is the only Internet-reachable ingress path to a Kubernetes
workload in this repository. It does not require router port forwarding and
must not be used as a reason to enable Tailscale Funnel.

## Sources of truth

| Concern | Source of truth |
| --- | --- |
| Private hostname and Kubernetes backend | `traefik-ingress.yaml` |
| Work hostname and Kubernetes backend | `cloudflared-config.yaml` |
| Tunnel connector Deployment | `cloudflare.yaml` |
| Tunnel credentials | SOPS-encrypted `cloudflare-secret.yaml` |
| Private DNS record | Vercel DNS for `vitalyguzun.com` |
| Work DNS route and Access policy | Cloudflare dashboard for `vitalyguzun-homelab.com` |

`kustomization.yaml` generates the cloudflared ConfigMap with a content hash.
Changing `cloudflared-config.yaml` therefore updates the ConfigMap name in the
Pod template and makes Flux roll out the connector Pods automatically.

## Expected external configuration

### Private route

Vercel DNS must contain an explicit `A` record for `linkding.vitalyguzun.com`
pointing to the current Tailscale IPv4 address of `homelab-gateway`. The
explicit record must override any wildcard record that sends otherwise unknown
hostnames to Vercel.

Do not point this hostname at a public origin. Publishing a Tailscale address in
DNS does not make it Internet-routable; the client still needs tailnet access.

### Work route

Cloudflare must contain exactly this active Tunnel-related inventory:

- Tunnel: `linkding-proxmox`;
- DNS route: `linkding-work.vitalyguzun-homelab.com` -> `linkding-proxmox`;
- Access application: `Linkding Work`, covering the complete work hostname;
- login method: One-time PIN, or an explicitly configured identity provider;
- Allow policy: exact intended email address;
- optional Require policy: stable corporate VPN egress IP or CIDR.

Do not configure the Allow policy as `Login Methods: One-time PIN`. That rule
would accept any identity able to use that login method. Select the exact email
address instead.

The old Tunnel DNS routes for Audiobookshelf, Grafana, Raspberry Pi Linkding,
and `linkding-proxmox.vitalyguzun-homelab.com` are intentionally absent. The
Tunnel object `linkding-proxmox` itself must remain because the work hostname
still points to it.

## Changing the work hostname

Use this order to avoid briefly publishing Linkding without Access protection:

1. Add the new hostname to `cloudflared-config.yaml` and render the overlay.
2. Create an Access application or destination for the new hostname.
3. Create the Cloudflare Tunnel DNS route.
4. Commit and push the GitOps change, then wait for Flux to roll out
   `cloudflared`.
5. Test the new hostname in a private browser session and complete both the
   Access and Linkding logins.
6. Delete the old DNS route and old Access destination.

Deleting a DNS route is not the same as deleting a Tunnel. Never delete or
rotate `linkding-proxmox` credentials while the current work route depends on
them.

## Validation

Render the application overlay before committing:

```shell
kubectl kustomize apps/proxmox >/dev/null
```

When the cluster API is reachable, verify the rollout and generated
configuration:

```shell
kubectl -n linkding rollout status deployment/cloudflared
kubectl -n linkding get pods -l app=cloudflared
kubectl -n linkding get ingress linkding-custom-domain
```

Test both URLs from their intended network contexts. The work URL should first
redirect to Cloudflare Access. The private URL should work only from a tailnet
device.

## Troubleshooting

| Symptom | Likely cause |
| --- | --- |
| Vercel `DEPLOYMENT_NOT_FOUND` on the private hostname | The explicit Vercel DNS record is missing, so a wildcard sends the request to Vercel instead of the Tailscale gateway |
| Cloudflare Access login followed by `404` | The hostname is absent from the running cloudflared configuration or the connector Pods have not rolled out |
| Cloudflare `502 Bad Gateway` | The Tunnel is connected, but cloudflared cannot reach the Linkding Service |
| No Cloudflare Access prompt | The Access application does not cover the hostname, or the DNS record is not proxied through Cloudflare |
| Private hostname times out | The client is outside the tailnet, the Tailscale gateway is unavailable, or DNS points to a stale Tailscale address |

Linkding backups are independent of both access paths. See `BACKUP.md` for the
backup and restore procedure.
