import json
import subprocess

from conftest import FIXTURES

from rmsync.sync import Syncer

P1 = [("h", "Project Falcon"), ("t", "met with Dana"), ("task", "email Dana the slides", False),
      ("task", "book flights #work", False), ("task", "renew passport", True)]
P2 = [("t", "random thoughts"), ("t", "no tasks here")]


def tw(*args):
    out = subprocess.run(["task", "rc.verbose=nothing", *args, "export"], capture_output=True, text=True, check=True).stdout
    return json.loads(out or "[]")


def run(cfg, ocr, **kw):
    logs = []
    rep = Syncer(cfg, transcriber=ocr, log=logs.append).run(**kw)
    return rep, logs


def setup_inbox(x, ocr):
    inbox = x.folder("Inbox")
    x.folder("Other")
    u, ids = x.notebook("Meeting notes", inbox, [P1, P2, None])
    ocr.pages[("Meeting notes", 1)] = P1
    ocr.pages[("Meeting notes", 2)] = P2
    return inbox, u, ids


def test_first_sync_writes_notes_and_tasks(env):
    x, cfg, ocr, tmp = env
    inbox, u, ids = setup_inbox(x, ocr)
    other = x.folder("Elsewhere")
    x.notebook("Not synced", other, [P2])
    rep, _ = run(cfg, ocr)
    assert rep.docs_changed == ["Meeting notes"]
    assert sorted(ocr.calls) == [("Meeting notes", 1), ("Meeting notes", 2)]  # blank page not sent
    md = (cfg.notes_dir / "Meeting notes.md").read_text()
    assert "## Page 1\n\n### Project Falcon" in md and "random thoughts" in md and "Page 3" not in md
    assert f"![Page 1](assets/Meeting%20notes/{ids[0]}.png)" in md
    assert (cfg.notes_dir / "assets" / "Meeting notes" / f"{ids[0]}.png").exists()
    pending = {t["description"]: t for t in tw("status:pending")}
    assert set(pending) == {"email Dana the slides", "book flights"}
    assert pending["book flights"]["tags"] == ["remarkable", "work"]
    assert pending["book flights"]["annotations"][0]["description"] == "reMarkable: Meeting notes, page 1"
    assert [t["description"] for t in tw("status:completed")] == ["renew passport"]


def test_second_sync_is_a_noop(env):
    x, cfg, ocr, tmp = env
    setup_inbox(x, ocr)
    run(cfg, ocr)
    ocr.calls.clear()
    rep, _ = run(cfg, ocr)
    assert rep.docs_changed == [] and ocr.calls == []
    assert len(tw()) == 3


def test_edit_one_page_only_retranscribes_it_and_ticks_complete(env):
    x, cfg, ocr, tmp = env
    _, u, ids = setup_inbox(x, ocr)
    run(cfg, ocr)
    ocr.calls.clear()
    p1b = [("h", "Project Falcon"), ("t", "met with Dana"), ("task", "email Dana the slides", True),
           ("task", "book flight #work", False), ("task", "renew passport", True), ("task", "call the bank", False)]
    ocr.pages[("Meeting notes", 1)] = p1b
    x.set_page(u, ids[0], p1b, seed=2)
    rep, _ = run(cfg, ocr)
    assert ocr.calls == [("Meeting notes", 1)]
    assert rep.tasks_completed == ["email Dana the slides"]
    assert rep.tasks_added == ["call the bank"]  # "book flight" matched "book flights": no duplicate
    assert {t["description"] for t in tw("status:pending")} == {"book flights", "call the bank"}


def test_task_deleted_in_taskwarrior_is_not_recreated(env):
    x, cfg, ocr, tmp = env
    _, u, ids = setup_inbox(x, ocr)
    run(cfg, ocr)
    t = next(t for t in tw("status:pending") if t["description"] == "book flights")
    subprocess.run(["task", "rc.confirmation=off", t["uuid"], "delete"], capture_output=True, check=True)
    x.set_page(u, ids[1], P2 + [("t", "more")], seed=3)
    ocr.pages[("Meeting notes", 2)] = P2 + [("t", "more")]
    run(cfg, ocr, full=True)
    assert {t["description"] for t in tw("status:pending")} == {"email Dana the slides"}


def test_rename_move_and_delete_page(env):
    x, cfg, ocr, tmp = env
    inbox, u, ids = setup_inbox(x, ocr)
    run(cfg, ocr)
    sub = x.folder("Projects", inbox)
    x.touch(u, visibleName="Falcon", parent=sub)
    ocr.pages[("Falcon", 1)] = P1
    x.delete_page(u, ids, ids[1])
    ocr.calls.clear()
    run(cfg, ocr)
    assert ocr.calls == []  # same page content: reused
    assert not (cfg.notes_dir / "Meeting notes.md").exists()
    new = cfg.notes_dir / "Projects" / "Falcon.md"
    assert "Project Falcon" in new.read_text() and "random thoughts" not in new.read_text()
    imgs = sorted(p.name for p in (cfg.notes_dir / "Projects" / "assets" / "Falcon").iterdir())
    assert imgs == [f"{ids[0]}.png"]
    assert len(tw()) == 3


def test_ocr_failure_is_retried(env):
    x, cfg, ocr, tmp = env
    setup_inbox(x, ocr)
    ocr.fail.add(("Meeting notes", 1))
    rep, _ = run(cfg, ocr)
    assert rep.pages_failed == ["Meeting notes p1"]
    assert "Not transcribed yet" in (cfg.notes_dir / "Meeting notes.md").read_text()
    assert tw() == []
    ocr.fail.clear()
    ocr.calls.clear()
    rep, _ = run(cfg, ocr)
    assert ocr.calls == [("Meeting notes", 1)] and len(rep.tasks_added) == 3


def test_typed_text_page_needs_no_ocr(env):
    x, cfg, ocr, tmp = env
    inbox = x.folder("Inbox")
    x.notebook("Typed", inbox, [(FIXTURES / "Bold_Heading_Bullet_Normal.rm").read_bytes()])
    run(cfg, ocr)
    assert ocr.calls == []
    assert "### new line" in (cfg.notes_dir / "Typed.md").read_text()


def test_pdf_skipped_and_removed_notebook_reported(env):
    x, cfg, ocr, tmp = env
    inbox, u, ids = setup_inbox(x, ocr)
    x.notebook("A paper", inbox, [], file_type="pdf")
    rep, _ = run(cfg, ocr)
    assert rep.skipped == ["A paper (pdf)"]
    x.trash(u)
    rep, _ = run(cfg, ocr)
    assert rep.removed == ["Meeting notes"]
    assert (cfg.notes_dir / "Meeting notes.md").exists()


def test_dry_run_writes_nothing(env):
    x, cfg, ocr, tmp = env
    setup_inbox(x, ocr)
    logs = []
    Syncer(cfg, transcriber=ocr, log=logs.append, dry_run=True).run()
    assert not cfg.notes_dir.exists() and tw() == []
    assert any("would add task: email Dana the slides" in l for l in logs)
    ocr.calls.clear()
    rep, _ = run(cfg, ocr)
    assert ocr.calls == [] and len(rep.tasks_added) == 3  # transcriptions from the dry run reused


def test_task_failure_keeps_transcription_and_retries(env, monkeypatch):
    x, cfg, ocr, tmp = env
    setup_inbox(x, ocr)
    monkeypatch.setenv("TASKRC", str(tmp / "missing" / "rc"))
    import rmsync.tasks as t
    real = t._task
    monkeypatch.setattr(t, "_task", lambda *a, **k: (_ for _ in ()).throw(t.TaskError("boom")))
    run(cfg, ocr)
    monkeypatch.setattr(t, "_task", real)
    monkeypatch.setenv("TASKRC", str(tmp / "taskrc"))
    ocr.calls.clear()
    rep, _ = run(cfg, ocr)
    assert ocr.calls == [] and len(rep.tasks_added) == 3


def test_broken_diagram_is_repaired_once_and_cached(env):
    from rmsync.ocr import PageText
    x, cfg, ocr, tmp = env
    inbox = x.folder("Inbox")
    x.notebook("Flow", inbox, [[("t", "a diagram")]])
    broken = 'flowchart TD\n  A["start] --> B["end"]'
    ocr.pages[("Flow", 1)] = [("t", "x")]
    fixes = []

    def mock_ocr(png, **kw):
        ocr.calls.append((kw["notebook"], kw["page"]))
        return PageText(markdown=f"# Flow\n\n```mermaid\n{broken}\n```", tasks=[])

    def fixer(code, err, **kw):
        fixes.append(err)
        return 'flowchart TD\n  A["start"] --> B["end"]'

    Syncer(cfg, transcriber=mock_ocr, diagram_fixer=fixer, log=lambda s: None).run()
    md = (cfg.notes_dir / "Flow.md").read_text()
    assert len(fixes) == 1 and '```mermaid\nflowchart TD\n  A["start"] --> B["end"]\n```' in md
    Syncer(cfg, transcriber=mock_ocr, diagram_fixer=fixer, log=lambda s: None).run(full=True)
    assert len(fixes) == 1 and len(ocr.calls) == 1  # repaired text was stored with the page
