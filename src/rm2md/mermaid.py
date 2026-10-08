"""Checking the Mermaid blocks in a transcription, so a broken diagram never reaches a note.

With `mmdc` (mermaid-cli) on PATH each block is parsed by Mermaid itself; otherwise a structural
check catches the usual mistakes (unknown diagram type, unbalanced brackets or quotes).
"""
from __future__ import annotations

import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Callable

BLOCK = re.compile(r"```mermaid[ \t]*\n(.*?)\n?```", re.S)
KINDS = ("flowchart", "graph", "sequenceDiagram", "classDiagram", "stateDiagram", "erDiagram",
         "mindmap", "gantt", "pie", "timeline", "journey")
PAIRS = {"[": "]", "(": ")", "{": "}"}


def _structural(code: str) -> str | None:
    lines = [ln for ln in code.splitlines() if ln.strip() and not ln.strip().startswith("%%")]
    if not lines or not lines[0].strip().startswith(KINDS):
        return "the first line must name the diagram type, e.g. flowchart TD"
    for n, ln in enumerate(lines[1:], 2):
        if ln.count('"') % 2:
            return f"line {n}: unbalanced double quote"
        stack, quoted = [], False
        for ch in ln:
            if ch == '"':
                quoted = not quoted
            elif quoted:
                continue
            elif ch in PAIRS:
                stack.append(PAIRS[ch])
            elif ch in PAIRS.values():
                if not stack or stack.pop() != ch:
                    return f"line {n}: unbalanced {ch}"
        if stack:
            return f"line {n}: missing {stack[-1]}"
    return None


def check(code: str, mmdc: str | None = None) -> str | None:
    """None if the diagram parses, else the error."""
    if err := _structural(code):
        return err
    mmdc = mmdc if mmdc is not None else shutil.which("mmdc")
    if not mmdc:
        return None
    with tempfile.TemporaryDirectory() as d:
        src, out = Path(d) / "d.mmd", Path(d) / "d.svg"
        src.write_text(code)
        for _ in range(2):
            try:
                p = subprocess.run([mmdc, "-q", "-i", str(src), "-o", str(out)], capture_output=True,
                                   text=True, timeout=90)
            except (subprocess.TimeoutExpired, OSError):
                continue
            if p.returncode == 0:
                return None
            msg = (p.stderr or p.stdout).strip()
            # Only Mermaid's own errors count. mmdc also fails when its headless browser does not
            # start; that says nothing about the diagram.
            m = re.search(r"((?:Parse|Lexical|Syntax) error.*?)(?:\n\s*at |\Z)", msg, re.S)
            if m or "No diagram type detected" in msg or "UnknownDiagramError" in msg:
                return (m.group(1) if m else msg)[:800]
        return None  # the checker could not run: trust the structural check


def repair(markdown: str, fixer: Callable[[str, str], str] | None, log: Callable[[str], None] = lambda s: None,
           mmdc: str | None = None) -> str:
    """Checks every ```mermaid block; asks `fixer(code, error)` once for a broken one, and turns a block
    that still fails into plain text with a pointer to the page image."""

    def one(m: re.Match) -> str:
        code = m.group(1).strip()
        err = check(code, mmdc)
        if err and fixer:
            try:
                fixed = fixer(code, err)
                if fixed and not check(fixed, mmdc):
                    log("  fixed a Mermaid diagram")
                    return f"```mermaid\n{fixed}\n```"
            except Exception as e:  # the repair is best effort
                log(f"  could not fix a Mermaid diagram: {e}")
        if err:
            log(f"  Mermaid diagram kept as text: {err.splitlines()[0]}")
            return f"*[diagram; see the page image]*\n\n```text\n{code}\n```"
        return f"```mermaid\n{code}\n```"

    return BLOCK.sub(one, markdown)
