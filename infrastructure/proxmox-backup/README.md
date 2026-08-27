# Proxmox backups

Proxmox stores guest and host-configuration backups on the Synology NFS
storage named `synology-backup`.

## Schedule

- 04:00 Europe/Amsterdam: Proxmox `vzdump` backs up every VM and LXC using
  snapshot mode and Zstandard compression.
- 04:30 Europe/Amsterdam: `pve-config-backup.timer` archives the Proxmox host
  configuration and a small hardware and guest inventory.

Both jobs retain 7 daily, 4 weekly, and 3 monthly restore points. The guest
backup job uses the built-in Proxmox notification system. A failed host
configuration backup sends mail to `root` and writes details to the systemd
journal.

The Jellyfin LXC bind mount `/mnt/nas-media` is not part of its `vzdump`
archive. It is a read-only view of media already stored on Synology.

## Installed files

Copy the versioned files to the Proxmox host:

```shell
install -m 0755 backup-pve-config-to-synology \
  /usr/local/sbin/backup-pve-config-to-synology
install -m 0644 pve-config-backup.service pve-config-backup.timer \
  /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now pve-config-backup.timer
```

The host configuration archives are written to:

```text
/mnt/pve/synology-backup/proxmox-pve/config
```

Guest archives are managed by Proxmox under:

```text
/mnt/pve/synology-backup/proxmox-pve/vzdump
```

## Verification

Inspect schedules and recent results:

```shell
pvesh get /cluster/backup
systemctl list-timers pve-config-backup.timer
journalctl -u pve-config-backup.service
pvesm list synology-backup --content backup
```

Verify a host-configuration archive:

```shell
cd /mnt/pve/synology-backup/proxmox-pve/config
sha256sum -c pve-config-<timestamp>.tar.gz.sha256
```

Before restoring a VM or LXC, inspect the archive in the Proxmox UI and choose
a new VMID for a test restore whenever enough storage is available.
