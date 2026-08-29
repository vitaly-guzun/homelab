# Security and address disclosure

This repository contains the desired state of a home network. Treat it as an
infrastructure inventory even when every credential is encrypted.

## What is sensitive

Never commit these values in plaintext:

- passwords, API keys, OAuth client secrets, tunnel credentials, and tokens;
- private Age, SSH, TLS, or VPN keys;
- session cookies, recovery codes, decrypted Kubernetes Secrets, and backups;
- production `.env` files or application databases.

Kubernetes Secrets stored in Git must be encrypted with SOPS. The public Age
recipient in `.sops.yaml` is safe to publish; the matching private identity is
the secret. Local `.env`, `tls.*`, and `values.yaml` files are ignored as a
defence against accidental commits, but `.gitignore` is not a secret store.

## IP addresses and hostnames

Private RFC 1918 addresses are not globally routable and are not credentials.
Publishing one does not by itself expose the host to the Internet. However, a
collection of addresses, ports, hostnames, and storage paths describes the
network topology and can make reconnaissance or social engineering easier.

This repository therefore follows these rules:

- diagrams and runbooks use role names such as `<NAS_LAN_IP>`,
  `<K3S_NODE_IP>`, and `<JELLYFIN_LAN_IP>`;
- environment-specific manifests may contain the actual LAN endpoints required
  by NFS volumes and selector-less Kubernetes Services;
- application DNS names may be public because DNS is public by design, but
  authorization must never rely on a hostname being unknown;
- generated `*.ts.net` names are not access tokens, though avoiding unnecessary
  copies reduces disclosure of tailnet metadata;
- `127.0.0.1` means local-only, while `0.0.0.0` is a wildcard bind address and
  must be paired with an appropriate Service, firewall, or network policy;
- public resolver addresses in Traefik's DNS-01 configuration are expected and
  are unrelated to the private topology.

If the LAN topology itself must be confidential, keep the environment overlay
in a private repository or replace literal endpoints with names resolved only
by internal DNS. Encrypting ordinary private IP addresses with SOPS is possible
but usually adds operational complexity without providing meaningful access
control.

## Exposure controls

- Restrict Synology NFS exports to the exact Kubernetes nodes and Proxmox hosts
  that mount them. Never port-forward NFS from the router.
- Keep Radarr, Sonarr, Prowlarr, and qBittorrent on the trusted LAN and require
  application authentication.
- Use Tailscale ACLs/grants for private routes. Do not enable Funnel unless a
  service is deliberately intended to be public.
- Keep `linkding-work.vitalyguzun-homelab.com` behind Cloudflare Access. Use an
  exact email address as the Allow policy's `Emails` selector, not a generic
  One-time PIN login-method selector. When stable, also require the corporate
  VPN egress IP range. The Tunnel and Linkding login alone are not substitutes
  for the Access policy.
- Create or verify the Access application before publishing a Tunnel DNS route.
  Deleting a DNS route does not delete its Tunnel; retain `linkding-proxmox`
  while the Linkding work route is in use.
- Use unique credentials and least-privilege service accounts. Backups contain
  sensitive configuration and require the same protection as the source.

## Before committing

1. Render the Kustomize overlays listed in `README.md`.
2. Confirm that every tracked Kubernetes Secret contains SOPS `ENC[...]` data
   and a `sops` metadata block.
3. Inspect staged changes for credentials, private keys, generated certificates,
   production `.env` values, and backup data.
4. Check that new listening ports are limited to the intended LAN, tailnet, or
   tunnel path.
5. For Linkding Tunnel changes, verify the external DNS and Access inventory
   against `apps/proxmox/linkding/ACCESS.md`.

## If something was exposed

Removing a value in a later commit does not remove it from Git history.

- For a plaintext credential or private key, revoke or rotate it immediately,
  then remove it from the current tree. History rewriting can reduce further
  disclosure but is not a substitute for rotation.
- For a private IP address alone, credential rotation is unnecessary. Verify
  firewall rules, router port forwarding, service authentication, and VPN or
  ingress policy. Change the address only if the wider exposure model requires
  it.
- For an accidentally public service, close the route first, review access and
  application logs, rotate reachable credentials, and only then restore access
  with the intended controls.
