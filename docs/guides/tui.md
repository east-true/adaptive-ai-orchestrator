*Documentation › Guides › Terminal UI*

# Terminal UI

A full-screen view for watching several tasks at once, with live output and
rendered reports.

## Full-screen terminal UI

For a dashboard-oriented local workflow, start the stdlib `curses` TUI:

```bash
PYTHONPATH=src python3 -m adaptive_orchestrator.tui --workspace .
```

It combines terminal records with the protected lifecycle event projection,
keeps escalated attempts together, and can show `selected`, `started`,
`terminal`, `evaluated`, or `finalized` progress before the terminal JSONL row
exists. Pass the same `--control-state-dir` used by routed CLI commands when a
non-default protected state directory is configured.

Press `n` to compose a short task; the TUI launches the normal `cli run` path as
a shell-free child process and shows its combined live output. Up to
`--max-tasks` children run concurrently (default `3`), each with its own output
buffer. `c` sends SIGTERM to the selected child's dedicated process group and
escalates to SIGKILL when pressed again, preventing a cancelled UI child from
leaving its coding-agent subprocess behind; `C` cancels every running child.

The dashboard, the task list, and the log view are separate screens:

| Key | Action |
| --- | --- |
| `Tab` | switch between the dashboard and the task list |
| `Enter` | open the selected execution's detail, or the selected task's log |
| `j` `k` `↑` `↓` `PgUp` `PgDn` `g` `G` | move and scroll |
| `/` | filter rows by whitespace-separated terms (AND, case-insensitive) |
| `n` | compose and start a task |
| `c` `C` `x` | cancel selected, cancel all, drop finished tasks |
| `r` `a` | refresh now, toggle auto-refresh |
| `f` | toggle log follow |
| `?` | help overlay |
| `q` `Esc` | step back one screen; `q` on the dashboard quits |

Auto-refresh re-reads the sources every couple of seconds, but only replays them
when the event log or execution JSONL actually changes on disk. Quitting from the
dashboard while children are running is refused until they are cancelled.

The TUI is intentionally a client of existing CLI and telemetry contracts. It
does not duplicate routing, verification, escalation, configuration, or report
logic.

## Watching a long run

`run`, `run-plan`, and `plan generate` accept `--verbose`, which streams the running agent's stdout to stderr as it arrives instead of staying silent until the process exits:

```bash
PYTHONPATH=src python3 -m adaptive_orchestrator.cli run --agent codex --verbose \
  --description "..." --objective "..."
```

`run`/`run-plan` stdout still only carries the final JSON result, while successful `plan generate` keeps its existing plan summary. In every case `--verbose` output goes to stderr, so the command's normal stdout contract is unaffected.

---

[← All guides](operator-guide.md)
