"""Driven by fake_tablet_ssh.sh: builds the library, copies it into the container, syncs over ssh."""
import json
import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from conftest import MockOcr  # noqa: E402
from fakexochitl import FakeXochitl  # noqa: E402

from rmsync.config import Config  # noqa: E402
from rmsync.ocr import transcribe  # noqa: E402
from rmsync.sync import Syncer  # noqa: E402
from rmsync.tablet import Tablet  # noqa: E402

name, port, work = sys.argv[1], sys.argv[2], Path(sys.argv[3])
X = "/home/root/.local/share/remarkable/xochitl"

P1 = [("h", "Groceries and errands"), ("task", "buy oat milk #shopping", False), ("task", "pick up the dry cleaning", False),
      ("task", "pay electric bill due fri", True), ("t", "remember: farmers market sat")]
P2 = [("h", "Ideas"), ("t", "rmsync could watch the folder"), ("t", "- use a cron job instead"),
      ("task", "write README @rmsync", False)]

x = FakeXochitl(work / "xochitl")
inbox = x.folder("Inbox")
x.folder("Archive")
sub = x.folder("Weekly", inbox)
x.notebook("Errands", inbox, [P1, None, P2], seed=4)
x.notebook("Week 41", sub, [P2], seed=5)
subprocess.run(["docker", "cp", str(x.root), f"{name}:{X}"], check=True)
subprocess.run(["docker", "exec", name, "chown", "-R", "root:root", X], check=True)

rc = work / "taskrc"
rc.write_text(f"data.location={work / 'taskdata'}\nhooks=off\nnews.version=3.4.2\n")
os.environ["TASKRC"] = str(rc)
opts = ["-p", port, "-i", str(work / "key"), "-o", "StrictHostKeyChecking=no", "-o", f"UserKnownHostsFile={work}/kh"]
cfg = Config(host="root@127.0.0.1", ssh_options=opts, folder="Inbox", notes_dir=work / "notes",
             state_dir=work / "state", cache_dir=work / "cache")

print("check:", Tablet(cfg.host, cfg.xochitl_dir, opts).check())
live = os.environ.get("RMSYNC_LIVE") == "1"
ocr = MockOcr()
for k, v in {("Errands", 1): P1, ("Errands", 3): P2, ("Week 41", 1): P2}.items():
    ocr.pages[k] = v
rep = Syncer(cfg, transcriber=transcribe if live else ocr).run()
print(rep.docs_changed, rep.pages_transcribed, rep.tasks_added, rep.pages_failed)
assert sorted(rep.docs_changed) == ["Errands", "Weekly/Week 41"], rep.docs_changed
assert not rep.pages_failed
tasks = json.loads(subprocess.run(["task", "export"], capture_output=True, text=True, check=True).stdout)
for t in tasks:
    print(f"  {t['status']:9} {t['description']!r} project={t.get('project')} tags={t.get('tags')} due={t.get('due')}")
assert len(tasks) == 5, len(tasks)
rep2 = Syncer(cfg, transcriber=ocr).run()
assert rep2.docs_changed == [], rep2.docs_changed
print("--- Errands.md ---")
print((work / "notes" / "Errands.md").read_text())
print("fake tablet over ssh: OK")
