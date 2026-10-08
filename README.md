# rmsync

Write on your reMarkable. rmsync turns the pages into Markdown notes and the to-dos into
[Taskwarrior](https://taskwarrior.org) tasks.

![A handwritten reMarkable page and the Markdown note rmsync made from it](docs/images/before-after.png)

*Left: a page from the tablet. Right: the note rmsync wrote, shown as GitHub renders it, with the
sketch turned into a diagram ([raw Markdown](docs/images/after.md)).*

rmsync syncs one folder of notebooks from the tablet over SSH (Wi-Fi or USB). A vision model reads
the handwriting through [OpenRouter](https://openrouter.ai), and each notebook becomes one Markdown
file. The same page also gave these tasks:

```
Status     Description                     Due     Scheduled  Tags
pending    fix remarkable SSH connection                      remarkable
pending    do the job                                         job remarkable
pending    get car serviced                Oct 8              remarkable
pending    pay bill                                Oct 8      remarkable
completed  get kids                        Oct 8              remarkable
completed  do laundry                      Oct 12             remarkable
```

"(due tomorrow)" became a due date, "(scheduled tomorrow)" a scheduled date and `+job` a tag. The
two crossed-out lines were added as already completed. Cross out or tick a task later and the next
sync completes it in Taskwarrior.

## Features

- **Handwriting to Markdown.** Headings, lists and paragraphs, with a picture of each page under
  its text so you can always check the original.
- **To-dos to Taskwarrior.** Due and scheduled dates, tags, projects and priorities written on the
  line. Each task is annotated with the notebook and page it came from.
- **Diagrams to Mermaid.** Flowcharts and box-and-arrow sketches become
  [Mermaid](https://mermaid.js.org) diagrams, which GitHub and Obsidian draw. Other drawings get a
  one-line description.
- **Cheap.** About $0.002 a page with the default model. Only pages that changed are sent, and
  typed (keyboard) text is read straight from the file at no cost.
- **Safe with your tasks.** rmsync only adds tasks and completes them. It never edits or deletes
  one, and a task you delete in Taskwarrior is not created again.

## Writing on the tablet

A line is a **task** when it starts with a hand-drawn box □, or with `TODO`, `todo:` or `[ ]`, or
sits in a list under a `TODO` or `Tasks` heading. Other bullet points stay notes.

On a task line you can write:

| write                                    | becomes                        |
|------------------------------------------|--------------------------------|
| a tick, cross or fill in the box, or a strike-through | completed         |
| `due fri`, `by 10/15`, `→ mon`           | due date (dates are month/day) |
| `scheduled tomorrow`, `start mon`        | scheduled date                 |
| `#word` or `+word`                       | tag                            |
| `@word` or `pro:word`                    | project                        |
| `!` or `(A)` · `(B)` · `(C)`             | priority H · M · L             |

These markers are taken out of the task text: "pay bill (due fri)" becomes the task "pay bill"
due Friday. A task counts as done only when its own line is crossed out or its own box ticked.
`*`, `•` and `-` bullets are never boxes.

For a **diagram**, draw boxes, diamonds or circles with words in them and connect them with arrows.
Words on an arrow become its label. rmsync keeps the direction you drew (top-down or left-to-right).
Words inside shapes never become tasks.

The tablet saves a page when you close its notebook. Close it, or go back to the library, before
a sync.

## Setup

You need:

- a reMarkable with SSH access. Tested on a reMarkable 2. The Paper Pro should work but hasn't
  been tried.
- Python 3.12+ and [uv](https://docs.astral.sh/uv/)
- Taskwarrior 3
- an [OpenRouter](https://openrouter.ai) API key
- optional: [mermaid-cli](https://github.com/mermaid-js/mermaid-cli) (`mmdc`), to check diagrams
  with Mermaid itself

1. **Find the tablet's address and password.** Both are under *Settings → Help → Copyrights and
   licenses*.
2. **Turn on SSH over Wi-Fi.** It is off by default and after every firmware update. Connect the
   tablet by USB and run:
   ```sh
   ssh root@10.11.99.1 rm-ssh-over-wlan on
   ```
3. **Install your SSH key.** Run `ssh-copy-id root@<tablet-ip>`. rmsync never types a password, so
   the key needs no passphrase, or must be loaded in ssh-agent.
4. **Install and configure rmsync:**
   ```sh
   uv tool install git+https://github.com/unixmonks/rmsync
   mkdir -p ~/.config/rmsync && (umask 077; cat > ~/.config/rmsync/openrouter_key)   # paste the key, then Ctrl-D
   rmsync init --host root@<tablet-ip> --folder "Notes"   # writes the config and tests the connection
   rmsync folders                                          # lists the folders, if unsure of the name
   rmsync sync -n                                          # preview: reads the pages, writes nothing
   rmsync sync
   ```
   The key can also come from `$OPENROUTER_API_KEY`.

Give the tablet a fixed address in your router (a DHCP reservation), so `host` stays right.

## Syncing automatically

Every hour with cron (`crontab -e`):

```
20 * * * * $HOME/.local/bin/rmsync sync -q >> $HOME/.local/state/rmsync/cron.log 2>&1
```

Or keep `rmsync watch` running, which syncs every five minutes. Both stay quiet while the tablet
is asleep or away, and catch up when it is back.

## Commands

```
rmsync init [--host H] [--folder F] [--notes-dir D] [--force]   write the config, test it
rmsync check                    test the connection and the folder
rmsync folders                  list the tablet's folders, with notebook counts
rmsync sync                     sync once
       -n, --dry-run            show what would change, write nothing
       --notebook NAME          only this notebook
       --retranscribe           read every page again (after changing the model)
       --no-tasks               notes only
       -q, --quiet              print only changes and errors
rmsync watch [--interval S]     sync every S seconds (default 300)
rmsync status                   notebooks, pages and tasks synced so far
```

`sync` exits 0 when all went well, 1 when a page could not be read (it is retried next time) or
the folder is wrong, and 2 when the tablet cannot be reached.

## Configuration

`~/.config/rmsync/config.toml`, written by `rmsync init`:

| setting       | default                    | what it does                                        |
|---------------|----------------------------|-----------------------------------------------------|
| `host`        | `root@10.11.99.1`          | the tablet over SSH                                 |
| `ssh_options` | `[]`                       | extra ssh options, e.g. `["-i", "~/.ssh/id_rm"]`    |
| `folder`      | `Inbox`                    | the tablet folder to sync: a name or a path         |
| `recursive`   | `true`                     | include subfolders                                  |
| `notes_dir`   | `~/notes/remarkable`       | where the Markdown goes                             |
| `page_images` | `true`                     | save a picture of each page under its text          |
| `model`       | `google/gemini-3.8-flash`  | any OpenRouter vision model                         |
| `reasoning`   | `low`                      | model effort: `low` is about $0.002 and 4 s a page  |
| `tasks`       | `true`                     | create Taskwarrior tasks                            |
| `task_tags`   | `["remarkable"]`           | tags added to every task                            |
| `task_project`| `""`                       | project for tasks that don't name one               |
| `task_sync`   | `false`                    | run `task sync` after adding or completing tasks    |

## Where things go

```
~/notes/remarkable/
├── Meeting notes.md                  one Markdown file per notebook
├── Work/Standup.md                   subfolders on the tablet become subfolders here
└── assets/Meeting notes/<page>.png   the page pictures
```

Each note is rewritten on every sync, so edit on the tablet, not in the file. Renaming or moving a
notebook on the tablet moves its note. A notebook taken out of the folder keeps its note. PDFs and
EPUBs are skipped.

rmsync keeps its records in `~/.local/state/rmsync/` and a copy of the synced notebooks in
`~/.cache/rmsync/`.

## Troubleshooting

- **"cannot reach the tablet"**: the tablet is asleep, or its address changed. Wake it and check
  the address under *Settings → Help → Copyrights and licenses*.
- **Connection refused, though the tablet answers ping**: SSH over Wi-Fi is off, usually after a
  firmware update. Run `rm-ssh-over-wlan on` over USB again (step 2 of Setup).
- **"Host key verification failed"**: firmware updates give the tablet new SSH host keys. Remove
  the old one with `ssh-keygen -R <tablet-ip>`, then connect once with `ssh root@<tablet-ip>`.
- **New tasks don't show in `task list`**: a Taskwarrior context may be hiding them. Try
  `task rc.context=none +remarkable list`.

## Development

```sh
uv run pytest                            # unit tests, plus full syncs against a fake tablet folder and the real `task`
tests/fake_tablet_ssh.sh                 # sync over real SSH from a busybox/dropbear container (needs Docker)
RMSYNC_LIVE=1 tests/fake_tablet_ssh.sh   # the same with the live model, on generated handwriting
uv run python docs/make_images.py        # rebuild the pictures above from a demo page
```
