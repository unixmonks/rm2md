import shutil

import pytest

from rm2md import mermaid

GOOD = 'flowchart TD\n  A["write code"] --> B{"pass?"}\n  B -->|"yes"| C(("deploy"))'
HAS_MMDC = shutil.which("mmdc") is not None


@pytest.mark.parametrize("code,err", [
    (GOOD, None),
    ('A["x"] --> B["y"]', "first line"),
    ('flowchart TD\n  A["x] --> B', "quote"),
    ('flowchart TD\n  A["x"] --> B{"y"', "missing }"),
    ('flowchart TD\n  A["x"]] --> B', "unbalanced ]"),
    ('flowchart TD\n  A["has (brackets] in label"] --> B', None),  # brackets inside quotes are text
])
def test_structural(code, err):
    got = mermaid.check(code, mmdc="")
    assert (got is None) if err is None else (err in got)


@pytest.mark.skipif(not HAS_MMDC, reason="mmdc not installed")
def test_mmdc_parses():
    assert mermaid.check(GOOD) is None
    assert mermaid.check('flowchart TD\n  A["x"] --> --> B') is not None  # passes the structural check only


def test_repair_keeps_good_blocks_and_fixes_bad():
    md = f"intro\n\n```mermaid\n{GOOD}\n```\n\ntext\n\n```mermaid\nflowchart TD\n  A[\"x] --> B\n```"
    calls = []

    def fixer(code, err):
        calls.append(err)
        return 'flowchart TD\n  A["x"] --> B'

    out = mermaid.repair(md, fixer, mmdc="")
    assert len(calls) == 1 and "quote" in calls[0]
    assert out.count("```mermaid") == 2 and 'A["x"] --> B' in out and GOOD in out


def test_repair_falls_back_to_text():
    md = "```mermaid\nflowchart TD\n  A[\"x] --> B\n```"
    out = mermaid.repair(md, lambda c, e: "still [broken", mmdc="")
    assert "```mermaid" not in out and "*[diagram; see the page image]*" in out and '```text\nflowchart TD' in out
    boom = mermaid.repair(md, lambda c, e: (_ for _ in ()).throw(RuntimeError("down")), mmdc="")
    assert "```text" in boom
    assert "```text" in mermaid.repair(md, None, mmdc="")


def test_checker_failure_is_not_a_diagram_error(tmp_path):
    fake = tmp_path / "mmdc"
    fake.write_text("#!/bin/sh\necho 'TimeoutError: Timed out after 30000 ms while waiting for the WS endpoint' >&2\nexit 1\n")
    fake.chmod(0o755)
    assert mermaid.check(GOOD, mmdc=str(fake)) is None
    fake.write_text("#!/bin/sh\necho 'Error: Parse error on line 2:' >&2\nexit 1\n")
    assert "Parse error on line 2" in mermaid.check(GOOD, mmdc=str(fake))
