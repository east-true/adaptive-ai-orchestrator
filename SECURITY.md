# Security Policy

## Supported versions

The project is pre-release. Only the latest commit on `main` receives security
fixes; older commits and experimental artifacts are not supported releases.

## Reporting a vulnerability

Do not open a public issue for a suspected vulnerability, an accidentally
exposed credential, or a bypass of an execution boundary. Submit the report
through [GitHub private vulnerability reporting](https://github.com/east-true/adaptive-ai-orchestrator/security/advisories/new).

Include, when available:

- the affected commit and platform;
- the entry point, configuration, and minimum reproduction;
- the security impact and whether exploitation was observed;
- sanitized logs or a proposed fix.

Never include a live credential. If the private form is temporarily unavailable,
open a public issue containing no vulnerability details and ask the maintainer
to restore the private reporting channel.

The maintainer will acknowledge reports on a best-effort basis, validate the
scope, and coordinate disclosure before publishing details. This project cannot
promise a response SLA, embargo length, bounty, or compatibility fix for an
unreleased commit.

## Local execution warning

This project launches Claude Code and Codex CLI against a local workspace. Those tools may read, change, or execute files according to their configured permissions and sandbox. Use only trusted repositories and avoid permission-bypass modes.

Execution logs may include task content, CLI output, and workspace metadata. Redaction is best-effort, not a guarantee. Never provide credentials or private data in task content, and keep Git diff logging disabled unless it is necessary.

Protected evaluator files and local control-state directories are trust
boundaries, not cryptographically isolated services. A security report should
state whether the agent process could write outside its configured workspace or
alter an evaluator artifact despite the documented checks.
