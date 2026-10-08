"""rm2md: one reMarkable folder → Markdown notes + Taskwarrior tasks, over SSH."""
from __future__ import annotations

import argparse
import datetime as dt
import fcntl
import sys
import time
from pathlib import Path

from . import config as config_mod
from . import library, tasks
from .tablet import Tablet, TabletError


def _lock(cfg: config_mod.Config):
    cfg.state_dir.mkdir(parents=True, exist_ok=True)
    f = open(cfg.state_dir / "lock", "w")
    try:
        fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        raise SystemExit("another rm2md is running")
    return f


def _summary(rep, quiet: bool) -> None:
    parts = []
    if rep.docs_changed:
        parts.append(f"{len(rep.docs_changed)} notebook(s) updated")
    if rep.pages_transcribed:
        parts.append(f"{rep.pages_transcribed} page(s) transcribed")
    if rep.tasks_added:
        parts.append(f"{len(rep.tasks_added)} task(s) added")
    if rep.tasks_completed:
        parts.append(f"{len(rep.tasks_completed)} completed")
    if rep.pages_failed:
        parts.append(f"{len(rep.pages_failed)} page(s) failed, retried next sync")
    for s in rep.skipped:
        print(f"skipped {s}: only notebooks are synced")
    for r in rep.removed:
        print(f"{r}: no longer in the folder on the tablet; its note was kept")
    if parts:
        print(", ".join(parts) + ".")
    elif not quiet:
        print(f"Up to date ({rep.docs_seen} notebook(s)).")


def cmd_init(a, cfg) -> int:
    path = config_mod.CONFIG_PATH
    if path.exists() and not a.force:
        print(f"{path} exists (use --force to overwrite)")
    else:
        config_mod.write_template(path, a.host or cfg.host, a.folder or cfg.folder,
                                  a.notes_dir or str(cfg.notes_dir).replace(str(Path.home()), "~"), cfg.api_key_file,
                                  tasks=not a.no_tasks)
        print(f"wrote {path}")
        cfg = config_mod.load(path)
    print(f"key: {'found' if cfg.api_key() else 'MISSING — set OPENROUTER_API_KEY or ' + str(cfg.api_key_file)}")
    if not cfg.tasks:
        print("tasks: off (notes only)")
    else:
        print(f"tasks: {'on, Taskwarrior found' if tasks.available() else 'on, but Taskwarrior (task) is MISSING — install it, or set tasks = false'}")
    return cmd_check(a, cfg)


def cmd_check(a, cfg) -> int:
    t = Tablet(cfg.host, cfg.xochitl_dir, cfg.ssh_options)
    try:
        print(f"tablet: {cfg.host} ({t.check()})")
        meta = t.list_metadata()
    except TabletError as e:
        print(f"tablet: cannot connect: {e}")
        print("  Check Wi-Fi is on, the IP is right, and your key is installed: ssh-copy-id " + cfg.host)
        return 1
    try:
        root = library.find_folder(meta, cfg.folder)
        docs = library.notebooks(meta, root, cfg.recursive)
        print(f"folder: {library.folders(meta)[root]} ({len(docs)} document(s))")
    except LookupError as e:
        print(f"folder: {e}")
        return 1
    return 0


def cmd_folders(a, cfg) -> int:
    t = Tablet(cfg.host, cfg.xochitl_dir, cfg.ssh_options)
    meta = t.list_metadata()
    for u, p in sorted(library.folders(meta).items(), key=lambda kv: kv[1].lower()):
        n = len(library.notebooks(meta, u, False))
        print(f"{p}  ({n})")
    return 0


def cmd_sync(a, cfg) -> int:
    from .sync import Syncer
    if a.no_tasks:
        cfg.tasks = False
    _l = _lock(cfg)
    try:
        rep = Syncer(cfg, dry_run=a.dry_run, log=(lambda s: None) if a.quiet else print).run(full=a.full, only=a.notebook, retranscribe=a.retranscribe)
    except TabletError as e:
        print(f"cannot reach the tablet: {e}", file=sys.stderr)
        return 2
    except LookupError as e:
        print(e, file=sys.stderr)
        return 1
    _summary(rep, a.quiet)
    return 1 if rep.pages_failed else 0


def cmd_watch(a, cfg) -> int:
    from .sync import Syncer
    _l = _lock(cfg)
    away = False
    print(f"watching {cfg.host}:{cfg.folder} every {a.interval}s (Ctrl-C to stop)")
    while True:
        stamp = dt.datetime.now().strftime("%H:%M")
        try:
            rep = Syncer(cfg, log=lambda s: print(s)).run()
            if away:
                print(f"{stamp} tablet is back")
            away = False
            if rep.docs_changed or rep.removed:
                print(stamp, end=" ")
                _summary(rep, True)
        except TabletError as e:
            if not away:
                print(f"{stamp} tablet not reachable ({e}); will keep trying")
            away = True
        except LookupError as e:
            print(f"{stamp} {e}")
        except KeyboardInterrupt:
            return 0
        try:
            time.sleep(a.interval)
        except KeyboardInterrupt:
            return 0


def cmd_status(a, cfg) -> int:
    from .sync import State
    st = State(cfg.state_dir / "state.json")
    print(f"config: {config_mod.CONFIG_PATH}{'' if config_mod.CONFIG_PATH.exists() else ' (missing; run rm2md init)'}")
    print(f"tablet: {cfg.host}   folder: {cfg.folder}   notes: {cfg.notes_dir}   model: {cfg.model}")
    for u, d in sorted(st.docs.items(), key=lambda kv: kv[1].get("name", "")):
        pages = d.get("pages", {})
        failed = sum(1 for p in pages.values() if p.get("error"))
        flags = " (removed from tablet)" if d.get("removed") else f" (skipped: {d['skipped']})" if d.get("skipped") else ""
        print(f"  {'/'.join([*d.get('subpath', []), d.get('name', u)])}: {len(pages)} page(s), "
              f"{len(d.get('tasks', []))} task(s){f', {failed} failed' if failed else ''}{flags}")
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="rm2md", description=__doc__)
    sub = p.add_subparsers(dest="cmd", required=True)
    i = sub.add_parser("init", help="write a config file and test the connection")
    i.add_argument("--host"); i.add_argument("--folder"); i.add_argument("--notes-dir"); i.add_argument("--force", action="store_true")
    i.add_argument("--no-tasks", action="store_true", help="notes only: write tasks = false")
    sub.add_parser("check", help="test the connection and the folder")
    sub.add_parser("folders", help="list the folders on the tablet")
    s = sub.add_parser("sync", help="sync once")
    s.add_argument("-n", "--dry-run", action="store_true", help="show what would change; write nothing")
    s.add_argument("--full", action="store_true", help="re-read every notebook (pages already transcribed are reused)")
    s.add_argument("--notebook", help="only this notebook (name or id)")
    s.add_argument("--retranscribe", action="store_true",
                   help="send every page to the model again (after changing model or prompt)")
    s.add_argument("--no-tasks", action="store_true", help="notes only, this time (see tasks in the config)")
    s.add_argument("-q", "--quiet", action="store_true", help="print only changes and errors")
    w = sub.add_parser("watch", help="sync every few minutes while the tablet is reachable")
    w.add_argument("--interval", type=int, default=300, help="seconds between syncs (default 300)")
    sub.add_parser("status", help="what has been synced")
    a = p.parse_args(argv)
    cfg = config_mod.load()
    return {"init": cmd_init, "check": cmd_check, "folders": cmd_folders, "sync": cmd_sync,
            "watch": cmd_watch, "status": cmd_status}[a.cmd](a, cfg)
