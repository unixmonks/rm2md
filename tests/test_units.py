import datetime as dt

import pytest
from conftest import FIXTURES

from rm2md import library, notes
from rm2md.ocr import parse_reply
from rm2md.render import render
from rm2md.sync import similar, typed_tasks
from rm2md.tasks import to_json
from rm2md.ocr import TaskItem


def meta_tree():
    return {
        "f1": {"type": "CollectionType", "visibleName": "Work", "parent": ""},
        "f2": {"type": "CollectionType", "visibleName": "Inbox", "parent": "f1"},
        "f3": {"type": "CollectionType", "visibleName": "Inbox", "parent": ""},
        "f4": {"type": "CollectionType", "visibleName": "Old", "parent": "trash"},
        "f5": {"type": "CollectionType", "visibleName": "Sub", "parent": "f3"},
        "d1": {"type": "DocumentType", "visibleName": "A", "parent": "f3", "lastModified": "1"},
        "d2": {"type": "DocumentType", "visibleName": "B", "parent": "f5", "lastModified": "2"},
        "d3": {"type": "DocumentType", "visibleName": "C", "parent": "f3", "deleted": True},
        "d4": {"type": "DocumentType", "visibleName": "D", "parent": "trash"},
    }


def test_folders_and_lookup():
    m = meta_tree()
    assert library.folders(m) == {"f1": "Work", "f2": "Work/Inbox", "f3": "Inbox", "f5": "Inbox/Sub"}
    assert library.find_folder(m, "Inbox") == "f3"  # exact path wins over name match
    assert library.find_folder(m, "work/inbox") == "f2"
    assert library.find_folder(m, "Sub") == "f5"
    with pytest.raises(LookupError, match="Folders: Inbox, Inbox/Sub"):
        library.find_folder(m, "Nope")
    with pytest.raises(LookupError):
        library.find_folder(m, "Old")


def test_notebooks_recursive():
    m = meta_tree()
    docs = library.notebooks(m, "f3", True)
    assert sorted((d.name, d.subpath) for d in docs) == [("A", ()), ("B", ("Sub",))]
    assert [d.name for d in library.notebooks(m, "f3", False)] == ["A"]


def test_page_ids_formats():
    v2 = {"cPages": {"pages": [
        {"id": "p2", "idx": {"value": "bb"}}, {"id": "p1", "idx": {"value": "ba"}},
        {"id": "px", "idx": {"value": "bc"}, "deleted": {"value": 1}}]}}
    assert library.page_ids(v2) == ["p1", "p2"]
    assert library.page_ids({"pages": ["a", "b"]}) == ["a", "b"]
    assert library.page_ids({}) == []


@pytest.mark.parametrize("name", ["Lines_v2.rm", "More_color_highlight_shader_v3.15.4.2.rm",
                                  "Normal_A_stroke_2_layers_v3.3.2.rm", "Bold_Heading_Bullet_Normal.rm"])
def test_render_fixtures(name):
    p = render((FIXTURES / name).read_bytes())
    if p.strokes:
        assert p.png.startswith(b"\x89PNG")
    else:
        assert p.png is None


def test_typed_text_markdown():
    p = render((FIXTURES / "Bold_Heading_Bullet_Normal.rm").read_bytes())
    assert p.typed == "**A**\n## new line\n- B is a letter of the alphabet\nC"


def test_typed_tasks():
    t = typed_tasks("intro\n- [ ] call Bob +phone @home\n- [x] pay rent\n- normal bullet")
    assert [(x.text, x.done, x.tags, x.project) for x in t] == [
        ("call Bob", False, ["phone"], "home"), ("pay rent", True, [], None)]


def test_parse_reply_cleans():
    r = parse_reply({"markdown": " hi ", "title": "", "confidence": "weird", "tasks": [
        {"text": "  buy   milk ", "done": False, "project": "@Home Stuff", "tags": ["#a", "b c", ""],
         "due": "2026-10-09T00:00", "priority": "X"},
        {"text": "", "done": True}, "junk",
        {"text": "x", "due": "friday"}]})
    assert r.markdown == "hi" and r.title is None and r.confidence == "medium"
    a, b = r.tasks
    assert (a.text, a.project, a.tags, a.due, a.priority) == ("buy milk", "HomeStuff", ["a", "bc"], "2026-10-09", None)
    assert b.due is None
    r = parse_reply({"markdown": "", "tasks": [{"text": "fix the SSH connection.", "scheduled": "2026-10-08"}]})
    assert r.tasks[0].text == "fix the SSH connection" and r.tasks[0].scheduled == "2026-10-08"


def test_similar():
    assert similar("Email Dana the slides", "email dana the slides.") == 1.0
    assert similar("email Dana the slides", "email Dana the slide") > 0.9
    assert similar("email Dana", "book flights") < 0.5
    assert similar("pay bill", "pay bill (scheduled tomorrow)") >= 0.8
    assert similar("pay", "pay bill scheduled tomorrow") < 0.8  # one word is too little to go on


def test_task_json():
    now = dt.datetime(2026, 10, 7, 12, 0, tzinfo=dt.timezone.utc)
    j = to_json(TaskItem("x", done=True, tags=["work"], due="2026-10-09", priority="H"), "u1", "note", ["remarkable"], "", now)
    assert j["status"] == "completed" and j["end"] == "20261007T120000Z"
    assert j["tags"] == ["remarkable", "work"] and j["priority"] == "H" and "project" not in j
    assert j["due"].startswith("2026100") and "scheduled" not in j
    j = to_json(TaskItem("y", scheduled="2026-10-08"), "u2", "note", [], "", now)
    assert j["scheduled"].startswith("2026100") and "due" not in j


def test_note_rendering():
    md = notes.render_note(name='My "Notes"', uuid="u", source="Inbox", last_modified="1760000000000", pages=[
        {"id": "a", "markdown": "# Title\ntext\n```\n# not heading\n```", "title": "Title"},
        {"id": "b", "empty": True},
        {"id": "c", "error": "boom"},
        {"id": "d", "markdown": "x", "confidence": "low"}], image_names={"a": "assets/My/a.png"})
    assert 'title: "My \\"Notes\\""' in md
    assert "## Page 1\n\n### Title\ntext\n```\n# not heading\n```\n\n![Page 1](assets/My/a.png)" in md
    assert "Page 2" not in md and "*Not transcribed yet: boom*" in md and "uncertain" in md
    assert notes.safe_name('a/b:c?') == "a-b-c"
    assert notes.demote("### TODO\n- x\n#### sub") == "### TODO\n- x\n#### sub"
    assert notes.demote("# A\n## B") == "### A\n#### B"
    assert notes.demote("# A\n### C") == "### A\n#### C"


def test_init_no_tasks_writes_tasks_false(tmp_path, monkeypatch, capsys):
    import rm2md
    from rm2md import config as config_mod
    path = tmp_path / "config.toml"
    monkeypatch.setattr(config_mod, "CONFIG_PATH", path)
    (tmp_path / "x").mkdir()
    rm2md.main(["init", "--host", f"dir:{tmp_path / 'x'}", "--folder", "Inbox", "--no-tasks"])
    assert "tasks = false" in path.read_text() and config_mod.load(path).tasks is False
    assert "tasks: off (notes only)" in capsys.readouterr().out
    rm2md.main(["init", "--force", "--host", f"dir:{tmp_path / 'x'}"])
    assert config_mod.load(path).tasks is True
