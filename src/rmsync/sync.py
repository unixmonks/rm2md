"""Pull the folder, transcribe changed pages, write notes, add tasks."""
from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import shutil
import uuid as uuidlib
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from pathlib import Path
from typing import Callable

from . import library, mermaid, notes, tasks
from .config import Config
from .ocr import PROMPT_VERSION, OcrError, PageText, TaskItem, fix_mermaid, transcribe
from .render import render
from .tablet import Tablet

logging.getLogger("rmscene").setLevel(logging.CRITICAL)

STATE_VERSION = 1


@dataclass
class Report:
    docs_seen: int = 0
    docs_changed: list[str] = field(default_factory=list)
    pages_transcribed: int = 0
    pages_failed: list[str] = field(default_factory=list)
    tasks_added: list[str] = field(default_factory=list)
    tasks_completed: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    removed: list[str] = field(default_factory=list)
    notes_written: list[Path] = field(default_factory=list)


class State:
    def __init__(self, path: Path):
        self.path = path
        try:
            self.data = json.loads(path.read_text())
        except (OSError, json.JSONDecodeError):
            self.data = {}
        self.data.setdefault("version", STATE_VERSION)
        self.data.setdefault("docs", {})

    @property
    def docs(self) -> dict:
        return self.data["docs"]

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.data, indent=1))
        os.replace(tmp, self.path)


def _norm(s: str) -> str:
    return " ".join(re.findall(r"\w+", s.lower()))


def similar(a: str, b: str) -> float:
    a, b = _norm(a), _norm(b)
    return 1.0 if a == b else SequenceMatcher(None, a, b).ratio()


_TYPED_TASK = re.compile(r"^\s*- \[( |x)\] (.+)$")


def typed_tasks(md: str) -> list[TaskItem]:
    """Checkbox paragraphs typed with the keyboard."""
    out = []
    for line in md.splitlines():
        if m := _TYPED_TASK.match(line):
            text = m.group(2)
            tags = re.findall(r"(?:^|\s)[#+](\w[\w.-]*)", text)
            proj = re.search(r"(?:^|\s)(?:@|pro(?:ject)?:)(\w[\w.-]*)", text)
            text = re.sub(r"(?:^|\s)(?:[#+@]|pro(?:ject)?:)\w[\w.-]*", "", text).strip() or text
            out.append(TaskItem(text=text, done=m.group(1) == "x", tags=tags, project=proj.group(1) if proj else None))
    return out


Transcriber = Callable[..., PageText]


class Syncer:
    def __init__(self, cfg: Config, *, tablet: Tablet | None = None, transcriber: Transcriber = transcribe,
                 diagram_fixer: Callable[..., str] | None = fix_mermaid,
                 log: Callable[[str], None] = print, dry_run: bool = False):
        self.cfg = cfg
        self.tablet = tablet or Tablet(cfg.host, cfg.xochitl_dir, cfg.ssh_options)
        self.transcribe = transcriber
        self.fix_diagram = diagram_fixer
        self.log = log
        self.dry_run = dry_run
        self.cache = cfg.cache_dir / "xochitl"
        self.state = State(cfg.state_dir / "state.json")

    # -- main entry ---------------------------------------------------------------------------
    def run(self, full: bool = False, only: str | None = None) -> Report:
        rep = Report()
        meta = self.tablet.list_metadata()
        root = library.find_folder(meta, self.cfg.folder)
        source = library.folders(meta)[root]
        docs = library.notebooks(meta, root, self.cfg.recursive)
        if only:
            docs = [d for d in docs if d.name.lower() == only.lower() or d.uuid == only]
        rep.docs_seen = len(docs)

        def stale(d: library.Doc) -> bool:
            s = self.state.docs.get(d.uuid)
            return (full or not s or s.get("last_modified") != d.last_modified or s.get("removed")
                    or s.get("name") != d.name or s.get("subpath") != list(d.subpath)
                    or s.get("retry_tasks") or any(p.get("error") for p in s.get("pages", {}).values())
                    or not (self.cache / f"{d.uuid}.content").exists())

        changed = [d for d in docs if stale(d)]
        if changed:
            self.tablet.fetch([d.uuid for d in changed], self.cache)
        for d in changed:
            self._sync_doc(d, source, rep)
            if not self.dry_run:
                self.state.save()

        if not only:
            present = {d.uuid for d in docs}
            for u, s in self.state.docs.items():
                if u not in present and not s.get("removed"):
                    s["removed"] = True
                    rep.removed.append(s.get("name", u))
            if rep.removed and not self.dry_run:
                self.state.save()
        if self.cfg.task_sync and (rep.tasks_added or rep.tasks_completed) and not self.dry_run:
            try:
                tasks.sync()
            except tasks.TaskError as e:
                self.log(f"task sync failed: {e}")
        return rep

    # -- one notebook -------------------------------------------------------------------------
    def _sync_doc(self, d: library.Doc, source_root: str, rep: Report) -> None:
        content = library.read_content(self.cache / f"{d.uuid}.content")
        file_type = content.get("fileType", "notebook")
        if file_type != "notebook":
            rep.skipped.append(f"{d.name} ({file_type})")
            self.state.docs[d.uuid] = {"name": d.name, "subpath": list(d.subpath), "last_modified": d.last_modified,
                                       "skipped": file_type, "pages": {}, "tasks": []}
            return
        st = self.state.docs.setdefault(d.uuid, {"pages": {}, "tasks": []})
        st.pop("removed", None)
        st.pop("skipped", None)
        old_md = Path(st["md_path"]) if st.get("md_path") else None
        md_path = notes.note_path(self.cfg.notes_dir, d.subpath, d.name)
        assets = notes.assets_dir(md_path)
        label = "/".join((*d.subpath, d.name))
        rep.docs_changed.append(label)
        self.log(f"· {label}")

        page_ids = library.page_ids(content)
        if not page_ids:  # older notebooks without a page list: use the files present
            page_ids = sorted(p.stem for p in (self.cache / d.uuid).glob("*.rm"))
        pages_out, new_pages, page_tasks = [], {}, []
        images: dict[str, str] = {}
        for n, pid in enumerate(page_ids, 1):
            rm = self.cache / d.uuid / f"{pid}.rm"
            data = rm.read_bytes() if rm.exists() else b""
            h = hashlib.sha256(data).hexdigest()[:16]
            prev = st["pages"].get(pid)
            reuse = prev and prev.get("hash") == h and not prev.get("error")
            png = None
            need_png = self.cfg.page_images and data and not (assets / f"{pid}.png").exists()
            if data and (not reuse or need_png):
                try:
                    page = render(data)
                except Exception as e:  # unreadable page (newer format?)
                    page = None
                    entry = {"hash": h, "error": f"could not read page file ({e.__class__.__name__})"}
                    rep.pages_failed.append(f"{label} p{n}")
                png = page.png if page else None
            if reuse:
                entry = prev
            elif not data:
                entry = {"hash": h, "empty": True}
            elif page is not None:
                entry = self._transcribe_page(page, d.name, n, h, label, rep)
            new_pages[pid] = entry
            pages_out.append({"id": pid, **entry})
            if not entry.get("error") and not entry.get("empty"):
                page_tasks += [(pid, TaskItem(**t)) for t in entry.get("tasks", [])]
            if self.cfg.page_images and (data and (png or (assets / f"{pid}.png").exists())):
                if png and not self.dry_run:
                    assets.mkdir(parents=True, exist_ok=True)
                    (assets / f"{pid}.png").write_bytes(png)
                if not entry.get("empty"):
                    images[pid] = f"assets/{md_path.stem}/{pid}.png".replace(" ", "%20")

        st.update(name=d.name, subpath=list(d.subpath), last_modified=d.last_modified, pages=new_pages,
                  md_path=str(md_path))
        if self.cfg.tasks:
            self._reconcile_tasks(st, page_tasks, d.name, page_ids, rep)
        text = notes.render_note(name=d.name, uuid=d.uuid, source="/".join((source_root, *d.subpath)),
                                 last_modified=d.last_modified, pages=pages_out,
                                 image_names=images if self.cfg.page_images else None)
        if self.dry_run:
            self.log(f"  would write {md_path}")
            return
        md_path.parent.mkdir(parents=True, exist_ok=True)
        md_path.write_text(text)
        rep.notes_written.append(md_path)
        if old_md and old_md != md_path:  # renamed or moved on the tablet
            old_md.unlink(missing_ok=True)
            old_assets = notes.assets_dir(old_md)
            if old_assets.exists() and not assets.exists():
                shutil.move(old_assets, assets)
            shutil.rmtree(old_assets, ignore_errors=True)
        if assets.exists():  # drop images of deleted pages
            for f in assets.glob("*.png"):
                if f.stem not in new_pages:
                    f.unlink()

    def _transcribe_page(self, page, name: str, n: int, h: str, label: str, rep: Report) -> dict:
        if page.png is None:  # typed text only
            return {"hash": h, "markdown": page.typed, "title": None, "confidence": "high",
                    "tasks": [t.__dict__ for t in typed_tasks(page.typed)]}
        key = self.cfg.api_key()
        if not key:
            rep.pages_failed.append(f"{label} p{n}")
            return {"hash": h, "error": "no OpenRouter API key"}
        cached = self.cfg.cache_dir / "ocr" / f"{h}-{re.sub(r'[^\w.-]', '_', self.cfg.model)}-v{PROMPT_VERSION}.json"
        try:  # a dry run, or a run that failed later, already paid for this page
            return {**json.loads(cached.read_text()), "hash": h}
        except (OSError, json.JSONDecodeError):
            pass
        try:
            res = self.transcribe(page.png, api_key=key, model=self.cfg.model, notebook=name, page=n,
                                  typed=page.typed, reasoning=self.cfg.reasoning)
        except OcrError as e:
            self.log(f"  page {n}: {e}")
            rep.pages_failed.append(f"{label} p{n}")
            return {"hash": h, "error": str(e)[:200]}
        rep.pages_transcribed += 1
        fixer = None
        if self.fix_diagram:
            def fixer(code: str, err: str) -> str:
                return self.fix_diagram(code, err, api_key=key, model=self.cfg.model, reasoning=self.cfg.reasoning)
        res.markdown = mermaid.repair(res.markdown, fixer, self.log)
        entry = {"hash": h, "markdown": res.markdown, "title": res.title, "confidence": res.confidence,
                 "tasks": [t.__dict__ for t in res.tasks], "model": self.cfg.model}
        cached.parent.mkdir(parents=True, exist_ok=True)
        cached.write_text(json.dumps(entry))
        return entry

    # -- tasks --------------------------------------------------------------------------------
    def _reconcile_tasks(self, st: dict, found: list[tuple[str, TaskItem]], name: str, page_ids: list[str],
                         rep: Report) -> None:
        """New task lines become tasks; a box ticked later completes its task. Tasks are never
        deleted or edited from here, and one removed in Taskwarrior is not created again."""
        records = st.setdefault("tasks", [])
        used: set[int] = set()
        to_add = []
        for pid, item in found:
            best, score = None, 0.0
            for i, r in enumerate(records):
                if i in used:
                    continue
                s = similar(item.text, r["text"]) + (0.05 if r.get("page") == pid else 0)
                if s > score:
                    best, score = i, s
            if best is not None and score >= 0.8:
                used.add(best)
                r = records[best]
                if item.done and not r.get("done"):
                    r["done"] = True
                    if self.dry_run:
                        self.log(f"  would complete: {r['text']}")
                        continue
                    try:
                        cur = tasks.get(r["uuid"])
                        if cur and cur.get("status") == "pending":
                            tasks.complete(r["uuid"])
                            rep.tasks_completed.append(r["text"])
                            self.log(f"  ✓ {r['text']}")
                    except tasks.TaskError as e:
                        self.log(f"  could not complete {r['text']!r}: {e}")
                        r["done"] = False
                continue
            u = str(uuidlib.uuid4())
            page_no = page_ids.index(pid) + 1 if pid in page_ids else 0
            to_add.append(tasks.to_json(item, u, f"reMarkable: {name}, page {page_no}",
                                        self.cfg.task_tags, self.cfg.task_project))
            records.append({"uuid": u, "text": item.text, "page": pid, "done": item.done})
            used.add(len(records) - 1)
        st.pop("retry_tasks", None)
        if not to_add:
            return
        if self.dry_run:
            for t in to_add:
                self.log(f"  would add task: {t['description']}" + (" (done)" if t["status"] == "completed" else ""))
            return
        try:
            tasks.add(to_add)
        except tasks.TaskError as e:
            self.log(f"  could not add tasks: {e}")
            added = {t["uuid"] for t in to_add}
            st["tasks"] = [r for r in records if r["uuid"] not in added]  # retried next sync
            st["retry_tasks"] = True
            return
        for t in to_add:
            rep.tasks_added.append(t["description"])
            self.log(f"  + {t['description']}" + (" (done)" if t["status"] == "completed" else ""))
