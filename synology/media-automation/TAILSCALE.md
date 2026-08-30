# Private media automation access through Tailscale

## Preferred custom-domain routes

Authorized tailnet clients use the shared `homelab-gateway` Tailscale endpoint.
Traefik terminates HTTPS and forwards each hostname to exactly one trusted-LAN
backend on Synology:

| Application | Private URL | Kubernetes config | Synology backend |
| --- | --- | --- | --- |
| Seerr | `https://seerr.vitalyguzun.com` | `apps/proxmox/seerr` | `192.168.1.59:5055` |
| Radarr | `https://radarr.vitalyguzun.com` | `apps/proxmox/radarr` | `192.168.1.59:7878` |
| Sonarr | `https://sonarr.vitalyguzun.com` | `apps/proxmox/sonarr` | `192.168.1.59:8989` |
| qBittorrent | `https://torrent.vitalyguzun.com` | `apps/proxmox/torrent` | `192.168.1.59:8080` |

Prowlarr remains available only on the trusted LAN at
`http://192.168.1.59:9696`.

Every private hostname requires all of the following:

1. An explicit Vercel DNS `A` record pointing to the current Tailscale IPv4
   address of `homelab-gateway`.
2. A selector-less Kubernetes Service and EndpointSlice pointing to the one
   intended Synology port.
3. A Traefik Ingress using the `websecure` entrypoint and the `letsencrypt`
   certificate resolver.
4. An authorized Tailscale client. The `100.64.0.0/10` destination is not
   reachable from the public Internet.

The shared gateway is declared in
`infrastructure/controllers/proxmox/traefik/tailscale-service.yaml`. The
application manifests are included from `apps/proxmox/kustomization.yaml` and
reconciled by Flux. No router port forwarding, Cloudflare Tunnel, or Tailscale
Funnel is used for these routes.

Require application authentication for Radarr, Sonarr, and qBittorrent even
though their routes are tailnet-only. Keep Prowlarr LAN-only because it contains
indexer credentials and does not need routine remote access.

## DNS and route verification

Check the route in this order:

```bash
dig +short @ns1.vercel-dns.com torrent.vitalyguzun.com A
dig +short @1.1.1.1 torrent.vitalyguzun.com A
dig +short torrent.vitalyguzun.com A
kubectl -n torrent get ingress,service,endpointslice
```

Replace `torrent` with the relevant application name. For qBittorrent the
hostname is `torrent.vitalyguzun.com`, while its Kubernetes namespace is
`torrent`.

A Vercel `404: NOT_FOUND` / `DEPLOYMENT_NOT_FOUND` response means the client is
still resolving the wildcard Vercel address instead of the explicit Tailscale
record. Compare the authoritative, public, router, and local resolver results.
On macOS, clear a stale system DNS entry with:

```bash
sudo killall -HUP mDNSResponder
```

Then fully quit and reopen the browser. DNS cache expiry is also safe; pushing
the same manifests again does not correct a stale client-side DNS answer.

## Optional direct Seerr fallback

The Compose service exposes Seerr on two host addresses:

- `${WEB_BIND_ADDRESS}:5055` for trusted LAN clients;
- `127.0.0.1:5055` as the local-only backend for Tailscale Serve.

Install and authenticate the official Tailscale package on Synology, then
publish Seerr privately inside the tailnet:

```bash
sudo tailscale serve --bg --https=8443 http://127.0.0.1:5055
sudo tailscale serve status
```

Port `8443` is intentional. Synology system services can occupy or intercept
port `443`, which prevents the Tailscale TLS handshake from completing on this
NAS. The resulting URL has this form:

```text
https://<NAS_MAGICDNS_NAME>:8443
```

The canonical Application URL in Seerr should be
`https://seerr.vitalyguzun.com`. The direct `:8443` route is optional and should
only be kept when an independent fallback during Kubernetes gateway outages is
desired. If it is enabled, share the Synology Tailscale machine only with the
intended users and restrict custom tailnet grants to `tcp:8443`.

Do not enable Tailscale Funnel and do not forward port `8443` on the router.
Tailscale Serve keeps the endpoint private to authorized tailnet users.

The Serve configuration is stored by the Tailscale package on the NAS, not in
Docker Compose. Run the command above again after reinstalling or resetting the
Tailscale package.
