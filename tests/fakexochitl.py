"""Build a fake xochitl document folder like the one on the tablet."""
from __future__ import annotations

import json
import shutil
import time
import uuid as uuidlib
from pathlib import Path

from fakepage import write_page


class FakeXochitl:
    def __init__(self, root: Path):
        self.root = root
        root.mkdir(parents=True, exist_ok=True)

    def _meta(self, u: str, **kw) -> None:
        m = {"deleted": False, "lastModified": str(int(time.time() * 1000)), "metadatamodified": False,
             "modified": False, "parent": "", "pinned": False, "synced": False, "version": 1}
        p = self.root / f"{u}.metadata"
        if p.exists():
            m.update(json.loads(p.read_text()))
        m.update(kw)
        p.write_text(json.dumps(m))

    def folder(self, name: str, parent: str = "", u: str | None = None) -> str:
        u = u or str(uuidlib.uuid4())
        self._meta(u, type="CollectionType", visibleName=name, parent=parent)
        (self.root / f"{u}.content").write_text("{}")
        return u

    def notebook(self, name: str, parent: str, pages: list, file_type: str = "notebook", seed: int = 1) -> tuple[str, list[str]]:
        """pages: list of fakepage line specs (or bytes for a raw .rm, or None for a blank page)."""
        u = str(uuidlib.uuid4())
        ids = [str(uuidlib.uuid4()) for _ in pages]
        self._meta(u, type="DocumentType", visibleName=name, parent=parent)
        (self.root / u).mkdir()
        self._write_content(u, ids, file_type)
        for pid, spec in zip(ids, pages):
            self.set_page(u, pid, spec, seed=seed, touch=False)
        return u, ids

    def _write_content(self, u: str, ids: list[str], file_type: str = "notebook", deleted: set = frozenset()) -> None:
        letters = "abcdefghijklmnopqrstuvwxyz"
        cpages = [{"id": pid, "idx": {"timestamp": "1:2", "value": "b" + letters[i]}, "template": {"value": "Blank"},
                   **({"deleted": {"timestamp": "1:9", "value": 1}} if pid in deleted else {})}
                  for i, pid in enumerate(ids)]
        (self.root / f"{u}.content").write_text(json.dumps(
            {"cPages": {"pages": cpages, "original": {"timestamp": "0:0", "value": -1}}, "fileType": file_type,
             "formatVersion": 2, "orientation": "portrait", "pageCount": len(ids) - len(deleted)}))

    def set_page(self, u: str, pid: str, spec, seed: int = 1, touch: bool = True) -> None:
        f = self.root / u / f"{pid}.rm"
        if spec is None:
            f.unlink(missing_ok=True)
        elif isinstance(spec, bytes):
            f.write_bytes(spec)
        else:
            write_page(f, spec, seed=seed)
        if touch:
            self.touch(u)

    def touch(self, u: str, **kw) -> None:
        time.sleep(0.002)
        self._meta(u, lastModified=str(int(time.time() * 1000)), **kw)

    def delete_page(self, u: str, ids: list[str], pid: str) -> None:
        self._write_content(u, ids, deleted={pid})
        self.touch(u)

    def trash(self, u: str) -> None:
        self.touch(u, parent="trash")

    def remove(self, u: str) -> None:
        shutil.rmtree(self.root / u, ignore_errors=True)
        for ext in (".metadata", ".content"):
            (self.root / f"{u}{ext}").unlink(missing_ok=True)
