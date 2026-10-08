"""The OpenAI-compatible client against a local fake server."""
import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from rm2md import ocr
from rm2md.config import Config
from rm2md.ocr import OcrError, Provider, fix_mermaid, transcribe

PNG = b"\x89PNG\r\n\x1a\nfake"
REPLY = {"markdown": "# Hi", "title": None, "confidence": "high",
         "tasks": [{"text": "call Bob", "done": False, "project": None, "tags": [], "due": None,
                    "scheduled": None, "priority": None}]}


class Fake:
    """Records requests; `reject` lists body keys or response_format types that get HTTP 400."""

    def __init__(self, reject=(), status=None, fenced=False):
        self.requests, self.reject, self.status, self.fenced = [], set(reject), status, fenced
        fake = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                fake.requests.append({"path": self.path, "headers": dict(self.headers), "body": body})
                rf = (body.get("response_format") or {}).get("type")
                if fake.status or set(body) & fake.reject or rf in fake.reject:
                    self.send_response(fake.status or 400)
                    self.end_headers()
                    self.wfile.write(b'{"error": {"message": "unsupported"}}')
                    return
                text = json.dumps(REPLY)
                if fake.fenced:
                    text = f"Here you go:\n```json\n{text}\n```"
                out = json.dumps({"choices": [{"message": {"content": text}}]}).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(out)

        self.server = HTTPServer(("127.0.0.1", 0), H)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.base = f"http://127.0.0.1:{self.server.server_port}/v1"

    def close(self):
        self.server.shutdown()


@pytest.fixture
def fake(request):
    ocr._WORKS.clear()
    made = []

    def make(**kw):
        f = Fake(**kw)
        made.append(f)
        return f

    yield make
    for f in made:
        f.close()


def test_request_shape_with_key(fake):
    f = fake()
    r = transcribe(PNG, provider=Provider(model="m1", base=f.base, key="sk-x", reasoning="low"), notebook="N", page=1)
    assert r.tasks[0].text == "call Bob"
    req = f.requests[0]
    assert req["path"] == "/v1/chat/completions"
    assert req["headers"]["Authorization"] == "Bearer sk-x" and "X-Title" not in req["headers"]
    b = req["body"]
    assert b["model"] == "m1" and b["reasoning_effort"] == "low" and "reasoning" not in b
    assert b["response_format"]["type"] == "json_schema"
    assert b["messages"][0]["content"][1]["image_url"]["url"].startswith("data:image/png;base64,")


def test_no_key_sends_no_auth_and_no_reasoning(fake):
    f = fake()
    transcribe(PNG, provider=Provider(model="m", base=f.base, key=None, reasoning=""), notebook="N", page=1)
    assert "Authorization" not in f.requests[0]["headers"] and "reasoning_effort" not in f.requests[0]["body"]


def test_openrouter_style():
    v = ocr._variants({"model": "m", "messages": []}, Provider(model="m", reasoning="low"))
    assert v[0]["reasoning"] == {"effort": "low"} and "reasoning_effort" not in v[0]


def test_falls_back_and_remembers(fake):
    f = fake(reject={"reasoning_effort", "json_schema"})
    p = Provider(model="local", base=f.base, reasoning="low")
    assert transcribe(PNG, provider=p, notebook="N", page=1).tasks
    shapes = [(("reasoning_effort" in r["body"]), (r["body"].get("response_format") or {}).get("type")) for r in f.requests]
    assert shapes == [(True, "json_schema"), (False, "json_schema"), (False, "json_object")]
    transcribe(PNG, provider=p, notebook="N", page=2)
    assert len(f.requests) == 4 and f.requests[3]["body"]["response_format"]["type"] == "json_object"


def test_no_response_format_and_fenced_reply(fake):
    f = fake(reject={"json_schema", "json_object"}, fenced=True)
    r = transcribe(PNG, provider=Provider(model="x", base=f.base, reasoning=""), notebook="N", page=1)
    assert r.markdown == "# Hi" and "response_format" not in f.requests[-1]["body"]


def test_auth_error_hint(fake):
    f = fake(status=401)
    with pytest.raises(OcrError, match="no API key is set"):
        transcribe(PNG, provider=Provider(model="x", base=f.base), notebook="N", page=1)
    with pytest.raises(OcrError, match="check the API key"):
        transcribe(PNG, provider=Provider(model="x", base=f.base, key="bad"), notebook="N", page=1)


def test_unreachable_server_names_it():
    with pytest.raises(OcrError, match="127.0.0.1:9"):
        transcribe(PNG, provider=Provider(model="x", base="http://127.0.0.1:9/v1", timeout=2), notebook="N",
                   page=1, retries=1)


def test_fix_mermaid_uses_provider(fake):
    f = fake(reject={"reasoning_effort"})
    out = fix_mermaid("flowchart TD\n A[x", "err", provider=Provider(model="m", base=f.base, reasoning="low"))
    assert out  # the fake answers with JSON text; what matters is the request path
    assert all(r["path"] == "/v1/chat/completions" for r in f.requests) and len(f.requests) == 2


def test_api_key_precedence(tmp_path, monkeypatch):
    kf = tmp_path / "key"
    kf.write_text("from-file\n")
    cfg = Config(api_key_env="OPENAI_API_KEY", api_key_file=kf)
    for v in ("RM2MD_API_KEY", "OPENAI_API_KEY", "OPENROUTER_API_KEY"):
        monkeypatch.delenv(v, raising=False)
    assert cfg.api_key() == "from-file"
    monkeypatch.setenv("OPENROUTER_API_KEY", "ignored")  # not the configured variable
    assert cfg.api_key() == "from-file"
    monkeypatch.setenv("OPENAI_API_KEY", "from-env")
    assert cfg.api_key() == "from-env"
    monkeypatch.setenv("RM2MD_API_KEY", "override")
    assert cfg.api_key() == "override"
    assert Config(api_key_file=tmp_path / "missing").provider().key in (None, "override")
