"""The document tree from xochitl's .metadata files, and page order from .content files."""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path


@dataclass
class Doc:
    uuid: str
    name: str
    subpath: tuple[str, ...]  # folders between the synced folder and the notebook
    last_modified: str
    file_type: str = "notebook"


def _alive(meta: dict) -> bool:
    return not meta.get("deleted") and meta.get("parent") != "trash"


def folders(meta: dict[str, dict]) -> dict[str, str]:
    """uuid -> full path ("Work/Inbox") of every live folder."""
    out: dict[str, str] = {}

    def path(u: str, seen: tuple = ()) -> str | None:
        m = meta.get(u)
        if not m or m.get("type") != "CollectionType" or not _alive(m) or u in seen:
            return None
        parent = m.get("parent") or ""
        if not parent:
            return m.get("visibleName", u)
        p = path(parent, seen + (u,))
        return None if p is None else f"{p}/{m.get('visibleName', u)}"

    for u, m in meta.items():
        if m.get("type") == "CollectionType" and (p := path(u)):
            out[u] = p
    return out


def find_folder(meta: dict[str, dict], wanted: str) -> str:
    """Folder uuid for a name or path. Raises LookupError with the candidates."""
    wanted = wanted.strip("/")
    paths = folders(meta)
    exact = [u for u, p in paths.items() if p.lower() == wanted.lower()]
    if not exact and "/" not in wanted:
        exact = [u for u, p in paths.items() if p.rsplit("/", 1)[-1].lower() == wanted.lower()]
    if len(exact) == 1:
        return exact[0]
    if exact:
        raise LookupError(f"{wanted!r} matches several folders: " + ", ".join(sorted(paths[u] for u in exact))
                          + ". Use the full path.")
    raise LookupError(f"no folder {wanted!r} on the tablet. Folders: " + (", ".join(sorted(paths.values())) or "none"))


def notebooks(meta: dict[str, dict], root: str, recursive: bool) -> list[Doc]:
    """Documents under folder `root` (file type is filled in later from .content)."""
    children: dict[str, list[str]] = {}
    for u, m in meta.items():
        if _alive(m):
            children.setdefault(m.get("parent") or "", []).append(u)
    docs: list[Doc] = []

    def walk(folder: str, sub: tuple[str, ...]) -> None:
        for u in children.get(folder, []):
            m = meta[u]
            if m.get("type") == "CollectionType":
                if recursive:
                    walk(u, sub + (m.get("visibleName", u),))
            elif m.get("type") == "DocumentType":
                docs.append(Doc(u, m.get("visibleName", u), sub, str(m.get("lastModified", ""))))

    walk(root, ())
    return docs


def read_content(path: Path) -> dict:
    try:
        return json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return {}


def page_ids(content: dict) -> list[str]:
    """Page uuids in display order, skipping deleted pages. Handles both .content formats."""
    cpages = content.get("cPages")
    if isinstance(cpages, dict) and isinstance(cpages.get("pages"), list):
        live = [p for p in cpages["pages"] if isinstance(p, dict) and p.get("id") and not p.get("deleted")]
        live.sort(key=lambda p: str((p.get("idx") or {}).get("value", "")))
        return [p["id"] for p in live]
    return [p for p in content.get("pages") or [] if isinstance(p, str)]
