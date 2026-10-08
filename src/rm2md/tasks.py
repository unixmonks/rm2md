"""Taskwarrior, through the `task` command. Honours TASKRC / TASKDATA like `task` itself."""
from __future__ import annotations

import datetime as dt
import json
import shutil
import subprocess

from .ocr import TaskItem

RC = ["rc.confirmation=off", "rc.verbose=nothing", "rc.recurrence.confirmation=off"]


class TaskError(Exception):
    pass


def _task(*args: str, stdin: str | None = None) -> str:
    try:
        p = subprocess.run(["task", *RC, *args], input=stdin, capture_output=True, text=True, timeout=60)
    except FileNotFoundError:
        raise TaskError("the `task` command is not installed")
    if p.returncode != 0:
        raise TaskError(f"task {' '.join(args[:2])}: {(p.stderr or p.stdout).strip()}")
    return p.stdout


def _utc(ts: dt.datetime) -> str:
    return ts.astimezone(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def to_json(item: TaskItem, uuid: str, annotation: str, tags: list[str], project: str,
            now: dt.datetime | None = None) -> dict:
    now = now or dt.datetime.now().astimezone()
    t: dict = {
        "uuid": uuid,
        "description": item.text,
        "status": "completed" if item.done else "pending",
        "entry": _utc(now),
        "modified": _utc(now),
        "tags": sorted(set(tags) | set(item.tags)),
        "annotations": [{"entry": _utc(now), "description": annotation}],
    }
    if item.done:
        t["end"] = _utc(now)
    if item.project or project:
        t["project"] = item.project or project
    if item.priority:
        t["priority"] = item.priority
    for field in ("due", "scheduled"):
        if value := getattr(item, field):
            d = dt.date.fromisoformat(value)
            t[field] = _utc(dt.datetime(d.year, d.month, d.day).astimezone())  # local midnight, like due:fri
    if not t["tags"]:
        del t["tags"]
    return t


def add(tasks: list[dict]) -> None:
    if tasks:
        _task("import", "-", stdin=json.dumps(tasks))


def get(uuid: str) -> dict | None:
    out = _task(uuid, "export").strip()
    try:
        rows = json.loads(out or "[]")
    except json.JSONDecodeError:
        return None
    return rows[0] if rows else None


def complete(uuid: str) -> None:
    _task(uuid, "done")


def available() -> bool:
    return shutil.which("task") is not None


def sync() -> None:
    _task("sync")
