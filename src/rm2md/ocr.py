"""Handwriting → Markdown + tasks, with a vision model behind any OpenAI-compatible API
(OpenRouter by default; OpenAI, Ollama, LM Studio, vLLM and others work the same way)."""
from __future__ import annotations

import base64
import datetime as dt
import json
import re
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field

DEFAULT_API_BASE = "https://openrouter.ai/api/v1"
# Part of the transcription cache key: bump when the prompt changes what comes back.
PROMPT_VERSION = 4

PROMPT = """You transcribe a handwritten page from a reMarkable tablet notebook.
Today is {today} ({weekday}). Notebook: "{notebook}", page {page}.

Return JSON only, with these fields:

"markdown": the page as clean Markdown. Keep the writer's words; fix only obvious letter-level
misreads. Use headings for underlined or large titles, lists for bullet points, "- [ ]" / "- [x]"
for task lines (below). Write each word once. A crossed-out task is written once, wholly inside
~~ ~~, even if the line only crosses part of it. Do not add commentary or anything not on the
page. Write a word you cannot read as [?].
Flowcharts, box-and-arrow diagrams, process diagrams, trees and mind maps: write them as a Mermaid
block, placed where the diagram is on the page:
```mermaid
flowchart TD
  A["Start"] --> B{{"Is it ready?"}}
  B -->|"yes"| C["Ship it"]
  B -->|"no"| A
```
Rules: use flowchart TD (top to bottom) or flowchart LR (left to right), whichever matches the
drawing. Short ids (A, B, C...). Every label in double quotes, with the writer's words: A["text"]
box, B{{"text"}} diamond, C("text") rounded box, D(("text")) circle. Arrows -->, lines ---, dashed
arrows -.->, arrow text -->|"text"|. Never put a double quote inside a label (use '). No styles,
classes, comments or subgraphs. Text written inside diagram shapes is never a task.
Other drawings (pictures, doodles, charts): describe briefly in italics, e.g. "*[sketch: a house
with a tree]*".

"tasks": one entry per task on the page, in page order. A line is a task when it starts with a
hand-drawn checkbox (a small square or circle), or with "TODO", "todo:" or "[ ]"; also every item
listed under a heading such as "TODO", "To do" or "Tasks". Other bullet points are NOT tasks.
Judge "done" for each line on its own: a task is done ONLY if that line itself is struck through,
or its own checkbox has a tick, cross or fill. Bullets such as *, •, -, ○ are not checkboxes and
never mean done. Other struck-through lines elsewhere on the page do not make a line done.
For each task:
  "text": the task without the checkbox, bullet, trailing full stop and the markers below; keep
          any other words, including words in brackets that are not a marker
  "done": as above; false when unsure
  "project": from "@word" or "pro:word" or "project:word" on the line, else null
  "tags": from "#word" or "+word" on the line (no # or +), else []
  "due": from "due fri", "by 12/3", "due:tomorrow", "→ mon" etc. as YYYY-MM-DD computed from today, else null.
         Dates like 12/3 are month/day.
  "scheduled": from "scheduled tomorrow", "sched mon", "start 12/3" etc., as YYYY-MM-DD the same way, else null
  "priority": "H" for "!" or "!!" or "!!!" or "(A)" on the line, "M" for "(B)", "L" for "(C)", else null
  The text of a marker is removed from "text", along with brackets around it: "pay bill (due fri)"
  is text "pay bill" with a due date.

"title": a short title for the page if it has an obvious heading, else null
"confidence": "high", "medium" or "low" for the transcription as a whole
{typed}"""

SCHEMA = {
    "name": "page",
    "strict": True,
    "schema": {
        "type": "object",
        "additionalProperties": False,
        "required": ["markdown", "tasks", "title", "confidence"],
        "properties": {
            "markdown": {"type": "string"},
            "title": {"type": ["string", "null"]},
            "confidence": {"type": "string", "enum": ["high", "medium", "low"]},
            "tasks": {"type": "array", "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["text", "done", "project", "tags", "due", "scheduled", "priority"],
                "properties": {
                    "text": {"type": "string"},
                    "done": {"type": "boolean"},
                    "project": {"type": ["string", "null"]},
                    "tags": {"type": "array", "items": {"type": "string"}},
                    "due": {"type": ["string", "null"]},
                    "scheduled": {"type": ["string", "null"]},
                    "priority": {"anyOf": [{"type": "string", "enum": ["H", "M", "L"]}, {"type": "null"}]},
                },
            }},
        },
    },
}


class OcrError(Exception):
    pass


@dataclass
class TaskItem:
    text: str
    done: bool = False
    project: str | None = None
    tags: list[str] = field(default_factory=list)
    due: str | None = None
    priority: str | None = None
    scheduled: str | None = None


@dataclass
class PageText:
    markdown: str
    tasks: list[TaskItem]
    title: str | None = None
    confidence: str = "high"


_WORD = re.compile(r"[^\w.\-]+")


def _clean_word(s: str | None) -> str | None:
    if not s:
        return None
    s = _WORD.sub("", s.strip().lstrip("#+@"))
    return s or None


def _clean_date(s: str | None) -> str | None:
    if not s:
        return None
    try:
        return dt.date.fromisoformat(s.strip()[:10]).isoformat()
    except ValueError:
        return None


def parse_reply(obj: dict) -> PageText:
    tasks = []
    for t in obj.get("tasks") or []:
        if not isinstance(t, dict) or not str(t.get("text", "")).strip():
            continue
        tasks.append(TaskItem(
            text=" ".join(str(t["text"]).split()).rstrip(".").strip() or str(t["text"]).strip(),
            done=bool(t.get("done")),
            project=_clean_word(t.get("project")),
            tags=[w for w in (_clean_word(x) for x in t.get("tags") or [] if isinstance(x, str)) if w],
            due=_clean_date(t.get("due")),
            scheduled=_clean_date(t.get("scheduled")),
            priority=t.get("priority") if t.get("priority") in ("H", "M", "L") else None,
        ))
    conf = obj.get("confidence")
    return PageText(
        markdown=str(obj.get("markdown") or "").strip(),
        tasks=tasks,
        title=(str(obj["title"]).strip() or None) if obj.get("title") else None,
        confidence=conf if conf in ("high", "medium", "low") else "medium",
    )


def _extract_json(text: str) -> dict:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```\w*\s*|\s*```$", "", text)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", text, re.S)
        if m:
            return json.loads(m.group(0))
        raise


@dataclass
class Provider:
    """An OpenAI-compatible chat completions endpoint and the model to use on it."""
    model: str
    base: str = DEFAULT_API_BASE
    key: str | None = None  # None: no Authorization header (local servers)
    reasoning: str = "low"  # "" sends no reasoning setting
    timeout: int = 120

    @property
    def url(self) -> str:
        return self.base.rstrip("/") + "/chat/completions"

    @property
    def openrouter(self) -> bool:
        return "openrouter.ai" in self.base


def transcribe(png: bytes, *, provider: Provider, notebook: str, page: int, typed: str = "",
               today: dt.date | None = None, retries: int = 3) -> PageText:
    today = today or dt.date.today()
    typed_note = (f"\nThe page also has typed text (already known, include it in the markdown where it fits):\n"
                  f"<<<\n{typed}\n>>>\n") if typed else ""
    prompt = PROMPT.format(today=today.isoformat(), weekday=today.strftime("%A"), notebook=notebook,
                           page=page, typed=typed_note)
    body = {
        "model": provider.model,
        "messages": [{"role": "user", "content": [
            {"type": "text", "text": prompt},
            {"type": "image_url", "image_url": {"url": "data:image/png;base64," + base64.b64encode(png).decode()}},
        ]}],
        "response_format": {"type": "json_schema", "json_schema": SCHEMA},
        "temperature": 0,
    }
    text = _chat(body, provider, retries)
    try:
        return parse_reply(_extract_json(text))
    except (json.JSONDecodeError, ValueError, AttributeError) as e:
        raise OcrError(f"{provider.model}: reply was not the expected JSON ({e})")


class _Rejected(OcrError):
    """The provider refused the request as malformed (HTTP 400/422): try a plainer one."""


# (endpoint, model) -> index of the request variant that worked, so later pages start there.
_WORKS: dict[tuple[str, str], int] = {}


def _variants(body: dict, p: Provider) -> list[dict]:
    """The request, then plainer versions for servers that reject an option: without the
    reasoning setting, with plain JSON mode instead of a schema, and with neither."""
    full = dict(body)
    if p.reasoning:
        if p.openrouter:
            full["reasoning"] = {"effort": p.reasoning}
        else:
            full["reasoning_effort"] = p.reasoning
    plain = dict(body)
    out = [full, plain]
    if "response_format" in body:
        out.append({**plain, "response_format": {"type": "json_object"}})
        out.append({k: v for k, v in plain.items() if k != "response_format"})
    seen, unique = set(), []
    for v in out:
        k = json.dumps({x: y for x, y in v.items() if x != "messages"}, sort_keys=True)
        if k not in seen:
            seen.add(k)
            unique.append(v)
    return unique


def _chat(body: dict, p: Provider, retries: int = 3) -> str:
    """Sends a chat request and returns the reply text, falling back to plainer requests when the
    provider rejects an option."""
    variants = _variants(body, p)
    key = (p.url, p.model)
    start = min(_WORKS.get(key, 0), len(variants) - 1)
    last: OcrError | None = None
    for i in range(start, len(variants)):
        try:
            text = _post(variants[i], p, retries)
            _WORKS[key] = i
            return text
        except _Rejected as e:
            last = e
    raise last or OcrError("failed")


def _post(body: dict, p: Provider, retries: int) -> str:
    """POSTs once, retrying network and server errors."""
    headers = {"Content-Type": "application/json"}
    if p.key:
        headers["Authorization"] = f"Bearer {p.key}"
    if p.openrouter:
        headers.update({"X-Title": "rm2md", "HTTP-Referer": "https://github.com/unixmonks/rm2md"})
    data = json.dumps(body).encode()
    last = None
    for attempt in range(retries):
        req = urllib.request.Request(p.url, data=data, method="POST", headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=p.timeout) as r:
                reply = json.load(r)
            if "error" in reply:
                raise OcrError(f"{p.model}: {reply['error'].get('message', reply['error'])}")
            content = reply["choices"][0]["message"]["content"]
            if isinstance(content, list):
                content = "".join(c.get("text", "") for c in content if isinstance(c, dict))
            return content or ""
        except urllib.error.HTTPError as e:
            detail = e.read().decode(errors="replace")[:300]
            msg = f"{p.model}: HTTP {e.code} {detail}"
            if e.code in (400, 422):
                raise _Rejected(msg)
            if e.code in (401, 403):
                raise OcrError(msg + (" (no API key is set: see api_key_env / api_key_file)" if not p.key
                                      else " (check the API key)"))
            if e.code in (402, 404):
                raise OcrError(msg + (" (check model and api_base)" if e.code == 404 else ""))
            last = OcrError(msg)
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            last = OcrError(f"{p.model} at {p.base}: {e}")
        except (KeyError, IndexError, TypeError, json.JSONDecodeError) as e:
            last = OcrError(f"{p.model}: unexpected reply ({e})")
        if attempt < retries - 1:
            time.sleep(2 * (attempt + 1))
    raise last or OcrError("failed")


FIX_PROMPT = """This Mermaid diagram does not parse. Fix the syntax only; keep every node, label and
arrow. Labels in double quotes, no double quotes inside labels, no styles or comments.
Reply with the corrected diagram only, no code fence.

Error:
{error}

Diagram:
{code}"""


def fix_mermaid(code: str, error: str, *, provider: Provider) -> str:
    body = {"model": provider.model, "temperature": 0,
            "messages": [{"role": "user", "content": FIX_PROMPT.format(error=error[:800], code=code)}]}
    text = _chat(body, provider).strip()
    return re.sub(r"^```(?:mermaid)?\s*|\s*```$", "", text).strip()
