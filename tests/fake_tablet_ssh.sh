#!/bin/sh
# End-to-end over real SSH: an Alpine container (busybox sh + tar, dropbear sshd, like the tablet)
# holding a fake xochitl folder. rm2md syncs it with the mock OCR, then once with the live API
# if RM2MD_LIVE=1. Needs docker.
set -eu
ROOT=$(cd "$(dirname "$0")/.." && pwd)
W=$(mktemp -d)
NAME=rm2md-fake-tablet-$$
trap 'docker rm -f "$NAME" >/dev/null 2>&1; rm -rf "$W"' EXIT
ssh-keygen -q -t ed25519 -N "" -f "$W/key"
docker run -d --name "$NAME" -p 127.0.0.1::22 alpine:3.20 sh -c \
  'apk add -q dropbear >/dev/null && mkdir -p /etc/dropbear /root/.ssh && sed -i "s#^root:[^:]*:[^:]*:[^:]*:[^:]*:[^:]*:#root:x:0:0:root:/home/root:#" /etc/passwd && mkdir -p /home/root/.ssh && touch /ready && exec dropbear -F -E -R -p 22' >/dev/null
for i in $(seq 60); do docker exec "$NAME" test -f /ready 2>/dev/null && break; sleep 1; done
docker cp "$W/key.pub" "$NAME:/home/root/.ssh/authorized_keys"
docker exec "$NAME" sh -c 'chown -R root:root /home/root; chmod 700 /home/root /home/root/.ssh; chmod 600 /home/root/.ssh/authorized_keys; mkdir -p /home/root/.local/share/remarkable; printf "reMarkable 2.0" > /tmp/machine'
PORT=$(docker port "$NAME" 22 | head -1 | cut -d: -f2)
cd "$ROOT"
uv run python tests/fake_tablet_ssh.py "$NAME" "$PORT" "$W"
