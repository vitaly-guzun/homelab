#!/bin/sh
set -eu
umask 077

timestamp="$(date -u +%Y-%m-%dT%H-%M-%SZ)"
filename="whoop-${timestamp}.dump"
temporary_file="/tmp/${filename}"
partial_file="/backups/whoop/${filename}.partial"
checksum_partial="/backups/whoop/${filename}.sha256.partial"

trap 'rm -f "${temporary_file}" "${partial_file}" "${checksum_partial}"' EXIT
mkdir -p /backups/whoop

# The SELECT-only account can take a consistent logical backup. No DB secrets
# or role passwords are included; owners/ACLs are reapplied separately on restore.
pg_dump --format=custom --no-owner --no-acl --file="${temporary_file}"
# Read and decompress every archived entry, not just its table of contents.
pg_restore --file=/dev/null "${temporary_file}"
test -s "${temporary_file}"
cp "${temporary_file}" "${partial_file}"
mv "${partial_file}" "/backups/whoop/${filename}"
cd /backups/whoop
sha256sum "${filename}" > "${checksum_partial}"
mv "${checksum_partial}" "${filename}.sha256"
sha256sum --check "${filename}.sha256"
echo "WHOOP backup completed: ${filename}"
