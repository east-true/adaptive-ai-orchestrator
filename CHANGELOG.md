# Changelog

Notable changes to this project will be documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and release versions
follow [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- Public contribution, conduct, support, and issue-reporting guidance.
- Installable console entry points and continuous-integration checks.
- An interactive-shell startup wordmark with independently sourced shell and
  kernel versions.
- Interactive-shell `init`, `doctor`, and `replay` commands, which forward to
  their existing CLI counterparts with the session workspace applied.
- Interactive-shell `paired_*` commands for the Phase 2a paired smoke. The
  session workspace is supplied as `--source-repository` only to the
  subcommands whose parsers define it, and the shell never injects
  `--confirm-agent-execution`.

- A `--version` flag reporting the distribution and kernel versions.
- `show`, `report`, and `retry` accept an unambiguous leading fragment of an
  execution or attempt id, the way `git` accepts a short commit hash. Exact ids
  still win, fragments shorter than four characters are ignored, and an
  ambiguous fragment lists its candidates instead of resolving to one.
- A `run --task <request>` shorthand that uses one sentence as both the
  description and the objective, matching the interactive shell's `task`. It is
  rejected alongside the explicit description/objective options.
- A `--summary` flag on `run`, `run-plan`, and `retry` that prints the readable
  view `show` renders instead of the JSON record. Reading the result of a run
  otherwise meant finding the execution id inside the dump and calling `show`
  with it. JSON stays the default so scripted callers are unaffected, and an
  execution whose record cannot be read back falls back to JSON.
- First-run guidance where the interfaces previously dead-ended: `show`,
  `report`, and `retry` in a workspace with no recorded execution now name the
  command that creates one, the shell's `recent` points at `task <request>`, the
  terminal UI's execution list explains an empty dashboard, and `memory search`
  says on stderr whether `[]` means an empty store or filters that matched
  nothing.

### Fixed

- `python3 -m adaptive_orchestrator.cli` now exits with the status the command
  returned. The compatibility shim called `main()` and discarded its result, so
  every failure exited 0 under the documented development invocation—`doctor`
  on a broken setup, `plan validate` on an invalid file, a failed run—while the
  installed console script reported them correctly. `python3 -m
  adaptive_orchestrator.tui` had the same defect.
- `doctor` no longer prints the account email, organization ID, and organization
  name. Claude Code answers `auth status` with JSON that was echoed raw and cut
  off mid-object; only the fields describing whether the CLI is usable are
  shown now. Non-JSON status output is unchanged.
- Usage text names a command that can actually be run. Reached through
  `python3 -m adaptive_orchestrator.cli`, argparse reported `cli.py`; the
  interactive shell claimed `adaptive-orchestrator`, which is not the name
  `[project.scripts]` installs. Both now follow the real invocation.
- A task time limit is now honored when a descendant detaches itself into its
  own session. Such a process keeps the inherited output pipes open and is
  outside the process group being killed, so the runner's final output drain
  waited for it and a timed-out command stayed open for as long as that
  descendant lived. The drain is now bounded, already-received output is kept,
  and the captured stderr reports that collection stopped early.
- The terminal UI no longer hangs when wrapping double-width text in a very
  narrow pane. Both wrap sites clamp their budget to a minimum of one column,
  where a CJK glyph never fits; the hard-break loop then made no progress and
  spun forever. Such a glyph is now emitted on its own line and clipped by the
  renderer.
- An empty `XDG_STATE_HOME` is now treated as unset, per the XDG Base Directory
  specification. It was honored literally, which resolved the protected control
  state directory relative to the current working directory instead of
  `~/.local/state`, so a workspace's lifecycle log and routing projection could
  silently be created somewhere new depending on where the command was run.
- `run`, `run-plan`, and `plan generate` say on stderr why they are exiting
  non-zero—execution status, verification status, the agent's first error line,
  and the `show` command for the full record. A failed run previously
  communicated nothing but a non-zero status and a JSON dump to search. stdout
  is unchanged, so piping the record still works.
- `run` reports an unreadable `--description-file` or `--objective-file` as a
  one-line argument error instead of a Python traceback.
- `run-plan` now reports an unreadable plan file as a one-line error instead of
  a Python traceback, matching `plan validate` and `plan generate`. It also
  reads the plan before opening the lifecycle recorder, so a mistyped path no
  longer reconciles attempts and rewrites the routing projection for a run that
  cannot start.
- The execution telemetry and engineering-memory JSONL files are now written
  owner-only (`0600`). They hold full prompts, agent output, and the workspace
  diff when it is enabled, but were left at the process umask's usual
  world-readable default while the lifecycle event log and routing state were
  already owner-only. An existing world-readable file is tightened on the next
  write; the containing directory's mode is left alone.
- A Codex run is no longer recorded as failed because of one unreadable output
  line. A line that parsed as JSON but was not an object raised while being read
  as an event, which the kernel converted into a `failed` record with no result
  and zero duration—for a run that had already completed, and after the
  lifecycle log had recorded its real terminal status. Such lines are now
  skipped like truncated ones, matching the Claude adapter.
- `show`, `retry`, and `report` now report an unresolvable `#N` reference as a
  normal lookup failure. Digit detection accepted characters such as the
  superscript `²` that integer parsing then rejected, surfacing a `ValueError`
  instead.
- The package no longer fails to import on Windows. The event log and routing
  state store used POSIX-only `fcntl` file locking unconditionally; they now
  go through a small cross-platform lock helper that uses `msvcrt` on
  Windows.
- The terminal UI's prompt no longer hides everything to the right of the
  cursor. It drew only the text before the caret, so moving back into a value
  with an arrow key, `Home`, or `Ctrl-A` blanked out the rest of it—at the
  caret's leftmost position the line looked empty, and forward-delete gave no
  sight of what it was removing. The window now scrolls only its left edge,
  keeping the caret and the following text visible together.

### Changed

- The terminal UI's task list now shows each run's execution id, so a task
  started there can be followed into `show`, `retry`, or `report`. A task was
  identified only by a session-local `#N` that survived nothing and matched no
  record; the id is read from the `Execution:` line `run --summary` already
  prints, and rows show the same eight-character prefix the dashboard and the
  CLI use, with the full value above the output preview.
- The dashboard's `TASK ID` column appears only where task ids group rows.
  `workflow.run` mints one per run unless a caller supplies it, so outside
  paired experiments it was a second random identifier standing 1:1 with the
  execution id—a column of noise beside the one value follow-up commands take.
  Its width goes to `TASK` when it is not earning it.
- The terminal UI is scoped to a monitor over recorded executions. It opens on
  the dashboard rather than a task-composition screen, and starting a run is a
  one-line prompt that hands off to the task list instead of a full view with
  its own transcript and boxed input. The composition screen was drifting into
  a chat client for a pipeline that has no conversation to show: both agents
  are invoked non-interactively (`claude --print`, `codex exec`), so a
  submitted request produces a recorded execution, not a reply. Configuring an
  agent stays with the CLI and the interactive shell, which already have it.
- Every CLI option now documents itself in `--help`. Eighteen had no help text,
  including `--workspace` on all eleven commands that accept it.
- `run --help` groups its thirty-plus options under what they configure—agent
  selection, task definition, verification, routing, escalation, output—instead
  of one flat list.
- `--help` lists subcommands in the order they are used—set up, run, inspect,
  then maintain—instead of putting `show`/`report`/`retry` ahead of the commands
  that produce anything to inspect.
- The interactive shell's `usage` reports a Codex quota reset in hours or
  minutes when it is less than a day away. Whole-day truncation showed every
  such reset as `0d`, which reads as "already reset".
- The interactive shell's `settings` now shows the value behind each inherited
  row, not just the word `inherit`, so it says what a task will actually do.
  `set` also names the valid settings when given an unknown one.
- The interactive shell no longer restates a failure as `failed with exit code
  N` when the command already printed its own reason. The generic line still
  appears when a command exits non-zero silently.
- The interactive shell's `help` with no argument now prints a grouped command
  overview with per-command usage and summaries instead of `cmd.Cmd`'s single
  alphabetical column. Summaries are read from each command's docstring, so the
  overview cannot drift from `help <command>`. Any command a group omits still
  lists under `Other`. `help <command>` is unchanged.
- The interactive shell's `history` now prints its "do not rank agents" caveat
  alongside the rates themselves. The numbers come from whichever agent was
  selected rather than from a controlled assignment, and printing several
  agents' percentages together otherwise reads as a ranking.
- The Phase 2b comparative-evaluation research record—candidate ledger, stage
  evidence artifacts, JSON schemas, preregistration, evaluation protocol, and
  work log—moved to a separate private repository. It recorded screening
  verdicts naming third-party public repositories. No published claim depended
  on it: learned routing is disabled and no comparative agent run has been
  authorized.
- Package metadata now matches the public repository name.
- Process cleanup now isolates each POSIX invocation and uses a guarded Windows
  Job Object launch path so timeout or interruption stays within the owned tree.
- Repository licensing changes from MIT to Apache License 2.0 from this change
  forward; previously published MIT-licensed revisions remain available under
  their original terms.

The source currently identifies itself as version `0.1.0`, but no GitHub or
package-index release has been published. A versioned section and comparison
link will be added when the first release is tagged.
