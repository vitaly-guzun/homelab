# Private Seerr access through Tailscale

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

Set that URL in **Seerr -> Settings -> General -> Application URL**. Share the
Synology Tailscale machine with each remote user and, when custom tailnet access
controls are enabled, grant shared users only `tcp:8443`.

The preferred friendly URL is `https://seerr.vitalyguzun.com`. Its explicit
Vercel DNS record points to the Tailscale address of `homelab-gateway`, where
Traefik terminates HTTPS and proxies to the trusted-LAN Seerr endpoint. This
route is also private to authorized tailnet clients. The direct `:8443` URL is
kept as an independent fallback if the Kubernetes gateway is unavailable.

Do not enable Tailscale Funnel and do not forward port `8443` on the router.
Tailscale Serve keeps the endpoint private to authorized tailnet users.

The Serve configuration is stored by the Tailscale package on the NAS, not in
Docker Compose. Run the command above again after reinstalling or resetting the
Tailscale package.
