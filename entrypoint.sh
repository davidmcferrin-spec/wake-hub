#!/bin/sh
# Drop to PUID/PGID after fixing volume ownership. Unraid uses 99:100.
set -eu
mkdir -p /config /data
PUID="${PUID:-0}"
PGID="${PGID:-0}"
if [ "$(id -u)" = "0" ] && [ "$PUID" != "0" ]; then
  if id wakehub >/dev/null 2>&1; then
    usermod -o -u "$PUID" wakehub
  else
    useradd -o -u "$PUID" -M -s /usr/sbin/nologin wakehub
  fi
  groupmod -o -g "$PGID" wakehub 2>/dev/null || groupadd -o -g "$PGID" wakehub
  usermod -g "$PGID" wakehub
  chown -R "$PUID:$PGID" /config /data
  exec setpriv --reuid "$PUID" --regid "$PGID" --init-groups -- "$@"
fi
exec "$@"
