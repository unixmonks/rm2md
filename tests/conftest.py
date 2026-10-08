import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))

from fakexochitl import FakeXochitl  # noqa: E402
from rm2md.config import Config  # noqa: E402
from rm2md.ocr import OcrError, PageText, TaskItem  # noqa: E402
from rm2md.sync import typed_tasks  # noqa: E402

FIXTURES = Path(__file__).parent / "fixtures"


def spec_to_text(spec) -> PageText:
    """What a perfect transcriber would return for a fakepage spec."""
    md, items = [], []
    for ln in spec:
        if ln[0] == "h":
            md.append(f"# {ln[1]}")
        elif ln[0] == "t":
            md.append(ln[1])
        elif ln[0] == "task":
            md.append(f"- [{'x' if ln[2] else ' '}] {ln[1]}")
    for t in typed_tasks("\n".join(md)):
        items.append(t)
    return PageText(markdown="\n\n".join(md), tasks=items, title=None, confidence="high")


class MockOcr:
    """Answers from the spec registered for (notebook, page number)."""

    def __init__(self):
        self.pages: dict[tuple[str, int], object] = {}
        self.calls: list[tuple[str, int]] = []
        self.fail: set[tuple[str, int]] = set()

    def __call__(self, png, *, api_key, model, notebook, page, typed="", reasoning=""):
        assert png.startswith(b"\x89PNG")
        self.calls.append((notebook, page))
        if (notebook, page) in self.fail:
            raise OcrError("mock failure")
        return spec_to_text(self.pages[(notebook, page)])


@pytest.fixture
def env(tmp_path, monkeypatch):
    """A fake tablet folder, a private Taskwarrior database and a config pointing at both."""
    rc = tmp_path / "taskrc"
    rc.write_text(f"data.location={tmp_path / 'taskdata'}\nhooks=off\nnews.version=3.4.2\n")
    monkeypatch.setenv("TASKRC", str(rc))
    monkeypatch.delenv("TASKDATA", raising=False)
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    x = FakeXochitl(tmp_path / "xochitl")
    cfg = Config(host=f"dir:{x.root}", folder="Inbox", notes_dir=tmp_path / "notes",
                 state_dir=tmp_path / "state", cache_dir=tmp_path / "cache", task_tags=["remarkable"])
    return x, cfg, MockOcr(), tmp_path
