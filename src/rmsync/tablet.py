"""Reading the xochitl document store from the tablet.

The tablet has no rsync, so files come over as a tar stream from `ssh host tar cf -`.
A host of the form `dir:/some/path` reads a local copy of a xochitl folder instead (tests).
"""
from __future__ import annotations

import io
import json
import shlex
import shutil
import subprocess
import tarfile
from pathlib import Path

SEP = "\x1e"


class TabletError(Exception):
    pass


def _uuid_ok(u: str) -> bool:
    return bool(u) and all(c.isalnum() or c == "-" for c in u)


class Tablet:
    def __init__(self, host: str, xochitl_dir: str, ssh_options: list[str] | None = None, timeout: int = 120):
        self.host = host
        self.dir = xochitl_dir
        self.ssh_options = ssh_options or []
        self.timeout = timeout

    def _run(self, script: str) -> bytes:
        if self.host.startswith("dir:"):
            cmd = ["sh", "-c", script]
        else:
            cmd = ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=8",
                   "-o", "ServerAliveInterval=10", *self.ssh_options, self.host, script]
        try:
            p = subprocess.run(cmd, capture_output=True, timeout=self.timeout)
        except subprocess.TimeoutExpired:
            raise TabletError(f"{self.host}: timed out")
        if p.returncode != 0:
            msg = p.stderr.decode(errors="replace").strip().splitlines()
            raise TabletError(f"{self.host}: {msg[-1] if msg else f'exit {p.returncode}'}")
        return p.stdout

    @property
    def _root(self) -> str:
        return self.host[4:] if self.host.startswith("dir:") else self.dir

    def check(self) -> str:
        """Returns the device model, or raises TabletError."""
        out = self._run(f"test -d {shlex.quote(self._root)} || {{ echo 'no xochitl folder' >&2; exit 3; }};"
                        " cat /sys/devices/soc0/machine 2>/dev/null || echo unknown")
        return out.decode(errors="replace").strip() if not self.host.startswith("dir:") else "local folder"

    def list_metadata(self) -> dict[str, dict]:
        script = (f"cd {shlex.quote(self._root)} || exit 3; for f in *.metadata; do [ -e \"$f\" ] || continue; "
                  f"printf '%s\\n' \"$f\"; cat \"$f\"; printf '\\n{SEP}\\n'; done")
        docs = {}
        for rec in self._run(script).decode("utf-8", errors="replace").split(SEP):
            rec = rec.strip()
            if not rec:
                continue
            name, _, body = rec.partition("\n")
            uuid = name.removesuffix(".metadata")
            try:
                docs[uuid] = json.loads(body)
            except json.JSONDecodeError:
                continue  # half-written file; next sync picks it up
        return docs

    def fetch(self, uuids: list[str], dest: Path) -> None:
        """Copies each document's .metadata, .content and page folder into dest, replacing old copies."""
        uuids = [u for u in uuids if _uuid_ok(u)]
        if not uuids:
            return
        names = " ".join(uuids)
        script = (f"cd {shlex.quote(self._root)} || exit 3; set --; for u in {names}; do "
                  "for f in \"$u.metadata\" \"$u.content\" \"$u.pagedata\" \"$u\"; do "
                  "[ -e \"$f\" ] && set -- \"$@\" \"$f\"; done; done; tar cf - \"$@\"")
        data = self._run(script)
        dest.mkdir(parents=True, exist_ok=True)
        for u in uuids:
            shutil.rmtree(dest / u, ignore_errors=True)
            for ext in (".metadata", ".content", ".pagedata"):
                (dest / f"{u}{ext}").unlink(missing_ok=True)
        with tarfile.open(fileobj=io.BytesIO(data)) as tar:
            tar.extractall(dest, filter="data")
