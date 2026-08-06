*Documentation › Guides › Terminal UI*

# Terminal UI

A full-screen monitor over the executions this workspace has recorded, with a
rendered report per execution and live output for runs started from the UI.

> The screens below are captured from a 96×26 terminal against a demo workspace
> whose `.orchestrator/executions.jsonl` is synthetic. Blank filler rows are
> trimmed; nothing else is edited.

## Starting it

```bash
PYTHONPATH=src python3 -m adaptive_orchestrator.tui --workspace .
```

Installed, the same screen is `adaptive-ai-orchestrator-tui --workspace .`.

| Option | Meaning |
| --- | --- |
| `--workspace` | workspace whose `.orchestrator/executions.jsonl` is read (default: current directory) |
| `--control-state-dir` | protected lifecycle event directory — pass the same one routed CLI commands use when it is not the default |
| `--max-tasks` | concurrent CLI children the UI will admit (default `3`) |

It combines terminal records with the protected lifecycle event projection, so
an execution appears with `selected`, `started`, `terminal`, `evaluated`, or
`finalized` progress before its terminal JSONL row exists.

## The dashboard

The UI opens here, newest execution first.

```text
Adaptive Orchestrator — …/scratchpad/tui-demo                                    5/5 executions

  ID        ATTEMPTS  AGENT        VERIFICATION  TASK
✓ 9a51b6c7         1  claude-code  passed        Explain the escalation ladder in the operato…
✓ d2e4f8a9         1  codex        passed        Add a changelog entry for the TUI task list
✗ b70a8c33         1  claude-code  not-run       Port the retry backoff to the Windows proces…
✓ 6c1de5f0         2  claude-code  failed        Cache the resolved workspace profile between…
✓ 3f9c21ab         1  codex        passed        Document the --json flag on the status comma…

?:help  n:new task  /:filter  Enter:report  Tab:tasks  q:quit                       running:0/3
```

- **`ID`** is the first eight characters of the execution id — the same short
  prefix `show`, `retry`, and `report` accept, so a row can be carried straight
  to the CLI;
- the leading glyph is the status: `✓` finished well, `✗` failed, `●` still in
  flight, `·` anything else. There is no `STATUS` column because the glyph
  already says it and the exact status string is one `Enter` away;
- **`ATTEMPTS`** counts the attempts grouped under one execution, so an
  escalation shows as `2` on a single row rather than as two rows;
- a **`TASK ID`** column appears only when some task id is shared by more than
  one row — the case where it says something the execution id cannot. Where the
  workflow mints one task id per run it is suppressed and its width goes to
  `TASK`;
- the footer's `running:N/M` is background runs started in *this session* out of
  `--max-tasks`; the header's `X/Y executions` is the recorded row count.

Columns shrink toward what is actually on screen, so a narrow terminal keeps
`TASK` readable instead of padding empty width.

## One execution's report

`Enter` renders the same Markdown report the CLI's `report` command produces,
scrollable with `j`/`k`, `PgUp`/`PgDn`, `g`/`G`:

```text
Adaptive Orchestrator — …/scratchpad/tui-demo                                    5/5 executions

Execution d2e4f8a9-1c05-4b7e-93af-6ad81c250b73

Outcome

- Status: `completed`
- Agent: `codex`
- Model: `gpt-5-codex`
- Verification: `passed`
- Duration: 22.4s
- Attempts: 1
- Recorded at: `2026-08-06T14:26:33.915Z`

Task

Add a changelog entry for the TUI task list

Objective: Record the execution-id column under [Unreleased].

Routing

Selected agent: `codex`
- Difficulty: `1`
- Risk: `1`
?:help  j k:scroll  Esc:back  q:quit                                                running:0/3
```

An execution still in flight, with no terminal record yet, shows the short
summary and `(in flight; no terminal record yet)` instead.

## Filtering

`/` opens a one-line prompt; terms are whitespace-separated, matched
case-insensitively, and all must match (AND) across id, status, agent,
verification, task id, and description:

```text
Adaptive Orchestrator — …/scratchpad/tui-demo             2/5 executions  filter:'codex passed'

  ID        ATTEMPTS  AGENT       VERIFICATION  TASK
✓ d2e4f8a9         1  codex       passed        Add a changelog entry for the TUI task list
✓ 3f9c21ab         1  codex       passed        Document the --json flag on the status command

Filter 'codex passed': 2/5 executions.                                              running:0/3
```

The active filter stays in the header. `Esc` clears it — and while a filter is
set, `Esc` clears the filter before it steps back a screen.

## Starting a task

`n` asks for one line and starts it; there is no composer screen, because both
agents are invoked non-interactively (`claude --print`, `codex exec`) and what
a submitted request produces is a recorded execution, not a conversation.

```text
New task: Document the TUI key bindings
```

The request becomes both `--description` and `--objective` of a normal
`cli run --verbose --summary` child. No `--agent` is passed: the workspace
profile decides, and the CLI and the [interactive shell](shell.md) remain the
places to override it. Submitting hands off to the task list:

```text
Adaptive Orchestrator — …/scratchpad/tui-demo                                    6/6 executions

   #    ID        STATUS      ELAPSED  REQUEST
>\ #1   —         running          7s  Document the TUI key bindings
— output of #1 (Enter for full log) —
[run:claude-code] Reading docs/guides/tui.md
[run:claude-code] Reading src/adaptive_orchestrator/interfaces/tui.py

?:help  n:new task  Enter:log  c:cancel  x:clear finished  Tab:dashboard  q:quit    running:1/3
```

The character after the `>` marker is a spinner while the child runs. `ID` is
`—` until the run's output names it. `run --summary` opens with
`Execution: <id>`, so the id is read off the stream the task is already
showing; from then on the row carries the same eight-character prefix as the
dashboard, and the line above the preview carries the full value — that is the
one to copy when following the run into `show`, `retry`, or `report`:

```text
   #    ID        STATUS      ELAPSED  REQUEST
>  #1   5699e508  exit 0          24s  Document the TUI key bindings
— output of #1 · 5699e508-2a0e-4cdc-89f0-20af62fe30dd (Enter for full log) —
[run:claude-code] Reading docs/guides/tui.md
[run:claude-code] Reading src/adaptive_orchestrator/interfaces/tui.py
[run:claude-code] Drafting the key table
[run:claude-code] Applying edit to docs/guides/tui.md
[run:claude-code] {"result": "Updated docs/guides/tui.md.", "usage": {"input_tokens": 12, "outp…
Execution: 5699e508-2a0e-4cdc-89f0-20af62fe30dd
Task: Document the TUI key bindings
Status: completed
Agent: claude-code
Verification: skipped
Attempts: 1
Duration: 24.1s

Task #1 finished (exit 0).                                                          running:0/3
```

Up to `--max-tasks` children run at once, each with its own output buffer
(bounded at 5000 lines). `c` sends SIGTERM to the selected child's dedicated
process group and escalates to SIGKILL when pressed again, so a cancelled UI
child cannot leave its coding-agent subprocess behind; `C` cancels every
running child, and `x` drops finished tasks from the list. Quitting is refused
while children are running, and an unhandled crash or Ctrl-C force-cancels them
on the way out.

## The live log

`Enter` on a task opens its full output. Follow mode pins the view to the tail;
any scroll key turns it off, and `f` toggles it back:

```text
Adaptive Orchestrator — …/scratchpad/tui-demo                                    6/6 executions

#1 running 13s  3 lines  follow:on  Document the TUI key bindings
Esc: back to tasks   f: toggle follow
[run:claude-code] Reading docs/guides/tui.md
[run:claude-code] Reading src/adaptive_orchestrator/interfaces/tui.py
[run:claude-code] Drafting the key table
```

## Keys

`?` opens the same list in an overlay; any key closes it.

| Key | Action |
| --- | --- |
| `Tab` | switch between the dashboard and the task list |
| `Enter` | open the selected execution's report, or the selected task's log |
| `j` `k` `↑` `↓` `PgUp` `PgDn` `g` `G` | move and scroll |
| `/` | filter executions |
| `n` | start a task |
| `c` `C` `x` | cancel selected, cancel all, drop finished tasks |
| `r` `a` | refresh now, toggle auto-refresh |
| `f` | toggle log follow (log view) |
| `?` | help overlay |
| `Esc` | step back one screen, or clear the filter first if one is set |
| `q` | quit from any view; refused while a task is running |

`Esc` is the only "step back" key and `q` always means quit — neither doubles
as the other.

## Refreshing

Auto-refresh (on by default, `a` toggles) checks the sources every two seconds
and replays them only when the event log or the execution JSONL actually
changed on disk; `r` forces a re-read. A task finishing also triggers one, so
its execution appears on the dashboard without waiting for the timer.

## Watching a long run

`run`, `run-plan`, and `plan generate` accept `--verbose`, which streams the running agent's stdout to stderr as it arrives instead of staying silent until the process exits:

```bash
PYTHONPATH=src python3 -m adaptive_orchestrator.cli run --agent codex --verbose \
  --description "..." --objective "..."
```

`run`/`run-plan` stdout still only carries the final JSON result, while successful `plan generate` keeps its existing plan summary. In every case `--verbose` output goes to stderr, so the command's normal stdout contract is unaffected. This is the flag the TUI passes to its own children, which is why their logs read the way they do above.

## Scope

The TUI is intentionally a client of existing CLI and telemetry contracts. It
does not duplicate routing, verification, escalation, configuration, or report
logic, and it does not configure a run — agent selection lives in the CLI and
the interactive shell.

---

[← All guides](operator-guide.md)
