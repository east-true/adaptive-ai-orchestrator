*Documentation › Guides › Interactive shell*

# Interactive shell

Set the workspace and agent once, then issue short commands against them.

## Interactive shell

If you want to set the workspace and agent once, then issue short commands repeatedly, use the stdlib shell on top of the existing CLI dispatch:

```bash
PYTHONPATH=src python3 -m adaptive_orchestrator.shell
    _        _        ___
   / \      / \      / _ \
  / _ \    / _ \    | | | |
 /_/ \_\  /_/ \_\    \___/

 Adaptive AI Orchestrator
 Shell v0.1.0 | Kernel v0.1
 Type help or ?; task <request> starts a quick run.
adaptive[auto:adaptive-ai-orchestrator]> workspace .
Workspace set to /path/to/adaptive-ai-orchestrator
adaptive[auto:adaptive-ai-orchestrator]> agent codex
Agent set to codex
adaptive[codex:adaptive-ai-orchestrator]> set verbose on
verbose set to on
adaptive[codex:adaptive-ai-orchestrator]> set verify python3 -m unittest
verify set to python3 -m unittest
adaptive[codex:adaptive-ai-orchestrator]> compose
Enter request. Finish with a line containing only '.'
> Run the unit tests.
> Fix any failures and explain their cause.
> .
{ ... existing cli.main JSON output ... }
adaptive[codex:adaptive-ai-orchestrator]> recent 2
#10 codex completed verify=passed duration=14.2s — Run the unit tests. Fix any failures and explain their cause.
#9 claude-code completed verify=skipped duration=8.1s — Review the implementation
adaptive[codex:adaptive-ai-orchestrator]> show #10
Execution: <execution-id>
Task: Run the unit tests. Fix any failures and explain their cause.
Status: completed
Agent: codex
...
adaptive[codex:adaptive-ai-orchestrator]> report #10 --output execution-10.md
... report written by the canonical CLI ...
adaptive[codex:adaptive-ai-orchestrator]> retry #10 --agent same
{ ... existing cli.main JSON output ... }
adaptive[codex:adaptive-ai-orchestrator]> history
claude-code: ... legacy execution/verification metrics ...
codex: ... legacy execution/verification metrics ...
adaptive[codex:adaptive-ai-orchestrator]> usage
Codex: ... current local plan usage when available ...
Claude Code: ... subscription and logged project-cost summary ...
adaptive[codex:adaptive-ai-orchestrator]> exit
```

The shell version in the banner is the distribution/shell release from package
metadata (or the source tree's `[project].version` during `PYTHONPATH=src`
development). `Kernel v0.1` is a separate milestone for the orchestration core;
the two axes are shown independently even when they happen to advance together.

The shell keeps session state only for the lifetime of the process. Agent selection starts as `inherit`: the prompt shows the effective agent from the active workspace profile, while `agent` and `status` show both the inheritance mode and effective value. `agent auto` explicitly overrides a profile-pinned agent with automatic routing, `agent inherit` returns control to the profile, and `agent <exact-id>` accepts the registry IDs implied by that profile, including configured variants such as `claude-code:opus` and `codex:gpt-5.5:high`. Switching workspaces preserves an explicit override but warns if the new profile does not register it.

The prompt and `status` also show the active workspace; `cd` aliases `workspace`, and `q` aliases `quit`. Relative `cd`/`workspace` arguments, plan-file paths, and their completions are resolved from the active workspace rather than the directory where the shell was launched. `task <request>` is the shortest execution path: it sends the rest of the line as both `--description` and `--objective`. `compose` does the same for a multiline request, ending input with a line containing only `.`; Ctrl-C or end-of-file discards any partial request. Use `run` when description and objective or other CLI flags need to differ.

`set` stores options you would otherwise retype every command. Every setting
starts at `inherit`, taking its value from the active project's config:

| Setting | Accepts |
| --- | --- |
| `verbose` | `on`, `off`, `inherit` |
| `no_escalation` | `on`, `off`, `inherit` |
| `time_limit` | positive seconds, `off`, `inherit` |
| `verify` | command text, `off`, `inherit` |

For `time_limit` and `verify`, `off` explicitly disables a value the profile
supplies, while `inherit` restores it.

A verify command is parsed as shell-style tokens and stored in a canonical
quoted form. `set verify "/tmp/check tool" --strict` keeps the spaced executable
path as one token; `set verify python3 -m unittest` keeps three ordinary ones.

`settings` shows the override mode and value for each. A row left at `inherit`
also reports what the active profile supplies — `Verbose: inherit (effective:
on)` — so the display says what a task will actually do, not only which layer
decides it. An unreadable profile reads `inherit (profile error: ...)`:

```text
set verbose on
set no_escalation off
set time_limit 600
set verify python3 -m unittest
settings
```

Session defaults are translated back into ordinary CLI argv. The shell prepends
its workspace and defaults, then forwards everything you typed — including flags
placed before a required positional — to the canonical argparse command.

- A time limit applies only to `task` and `run`; `run-plan` and `plan generate`
  do not expose that task-level flag. The other defaults apply to every routed
  command.
- Your own options then win by normal argparse rules: a later single-value
  option such as `--time-limit` overrides the session default, while repeatable
  `--verify-command` values accumulate with it.
- An explicit `off` emits `--no-verbose`, `--escalation`, `--no-time-limit`, or
  `--clear-verify-commands`. `inherit` emits nothing, restoring project-config
  behaviour.

`set verify` treats its value as command-line syntax and preserves the parsed token boundaries when it forwards that value through the CLI. Quote only tokens that require it—for example, `set verify "/opt/check tool" --fast` keeps `/opt/check tool` as one executable path while passing `--fast` as its argument.

**Reading past work back.** `recent [count]` lists the newest executions first,
each with the effective outcome's agent, execution status, verification status,
agent-process duration, attempt count after escalation, and a short task
description. It reads the workspace execution JSONL, not the protected lifecycle
source — use `replay` for lifecycle validation.

Pass the `#N` it prints straight to `show #N`, `retry #N`, or `report #N`. All
three also accept a full execution or attempt ID, or an unambiguous leading
fragment of one:

| Command | What it does |
| --- | --- |
| `show` | the canonical human-readable summary of the grouped execution |
| `report` | the canonical Markdown report |
| `retry` | reruns the original task with your current session defaults |

**How escalation shows up here.** When escalation recovers an execution,
`recent`, `show`, and reports all show the recovered outcome, while `retry`
still uses the original task definition. A failed advisory escalation does not
erase an already verified successful primary attempt — but the report still
exposes that attempt's terminal status and error, and uses the terminal
attempt's changed-file snapshot and optional diff, so later workspace effects
are never hidden. Legacy records whose escalation exists only as a nested copy
get the same attempt count and outcome treatment.

**Help topics.** `help show`, `help retry`, `help report`, `help run`, `help
run_plan`, `help plan_generate`, `help init`, `help doctor`, `help replay`, the
`paired_*` topics, and the plan/memory topics all delegate to the canonical
argparse help. Config-sensitive help uses the active session workspace.

`help` with no argument prints an overview grouped by what you are doing—session state, project checks, running work, history, memory, paired experiments, and shell control—with one usage line and summary per command, rather than `cmd.Cmd`'s single alphabetical column. A command that no group lists still appears under `Other`, so the overview cannot silently omit part of the shell's surface; a test enforces that this residual set is empty. `help <command>` is unchanged and still delegates to the canonical argparse help where a topic defines one.

`init`, `doctor`, and `replay` forward to their CLI commands with the session workspace prepended. They take no session workflow defaults, because none of them run a task: `set verbose`, `set time_limit`, and the session agent apply only to routed task, plan, and retry commands. `doctor` is the quickest way to confirm from inside a session that the current workspace's config, agent login, and runtime prerequisites are intact after `workspace` moves you somewhere new.

### Paired-experiment commands

The `paired_*` commands wrap the Phase 2a paired-smoke subcommands. They predate
the session workspace and are scoped by `--source-repository`, not
`--workspace`:

| The shell supplies the session workspace as `--source-repository` | It does not |
| --- | --- |
| `paired_validate`, `paired_dry_run`, `paired_run`, `paired_resume` | `paired_plan`, `paired_analyze` — their parsers do not define that option |

`--workspace-root` and `--control-state-dir` stay explicit. A leading bare
manifest path resolves against the session workspace; once an option comes
first, the shell rewrites nothing, because a following token is likelier an
option value than the positional.

**The shell never injects `--confirm-agent-execution`.** Authorizing the agent
and evaluator attempts a manifest describes stays an explicit act you perform
per invocation. `paired_run` and `paired_resume` entered without it behave
exactly as the CLI does.

### Tab completion

Completion covers command names, exact configured `agent` values, workspace
directories, nested plan-file paths, and the first identifier passed to `show`,
`retry`, or `report`. Identifier completion offers deduplicated execution IDs,
attempt IDs, and the `#N` references `recent` prints; an unreadable history file
simply yields no matches.

Only whitespace is treated as a readline token boundary, so IDs containing `-`
or `:` and paths containing `/` complete as a single value. The quote-aware path
completer preserves partial single/double quotes and backslash escapes,
including `./`, quoted intermediate components, and names that themselves
contain quote characters. The process-global completer and delimiter settings
are restored when the loop exits or is interrupted.

Invalid workspace paths are rejected without losing session state, command typos
suggest a close match, and a blank line is a no-op rather than `cmd.Cmd`'s
default of repeating the previous command.

When a routed command fails, the shell shows the command's own explanation. It adds `Error: <command> failed with exit code N` only when the command exited non-zero without printing anything, which would otherwise be indistinguishable from success.

Ctrl-C while composing discards the partial request. During a routed command it interrupts the current work, lets the execution layer clean up the invocation's isolated process boundary, and returns to the same shell session; at the prompt it clears the current input without repeating the banner. SIGTERM, and POSIX terminal hangup/quit signals when available, similarly unwind embedded CLI work so cleanup finalizers run, restore the shell's previous signal handlers, and exit with the conventional `128 + signal` status without a Python traceback.

Independent shell processes can target the same workspace. Recorder-managed lifecycle append, abandoned-attempt reconciliation, and materialized-state projection are serialized under one inter-process lock so one session cannot duplicate reconciliation events or overwrite a newer projection from another session. Each prospective recorder append is replay-validated before it becomes durable, so a bad transition cannot leave every later shell startup stuck on a poisoned event row.

Most commands still only build an argv list and call the canonical `adaptive_orchestrator.interfaces.cli.main` dispatch, so they stay aligned with normal CLI flags and output conventions. Shell-native convenience commands include session views (`status`, `settings`) and read-only local-data views (`history`, `recent`, `usage`). `history` currently exposes legacy operational metrics, not objective task-quality or unbiased policy estimates; do not use its percentages to rank agents. Because the command prints several agents' rates side by side, it now repeats that caveat in its own output whenever it actually shows rates, instead of relying on this document being read first.

---

[← All guides](operator-guide.md)
