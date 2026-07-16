# Security Policy

## Supported version

Only the current `main` branch is supported while the project is pre-release.

## Reporting a vulnerability

Do not open a public issue for a suspected vulnerability or an accidentally exposed credential. Contact the repository owner privately through GitHub and include enough detail to reproduce the issue safely.

## Local execution warning

This project launches Claude Code and Codex CLI against a local workspace. Those tools may read, change, or execute files according to their configured permissions and sandbox. Use only trusted repositories and avoid permission-bypass modes.

Execution logs may include task content, CLI output, and workspace metadata. Redaction is best-effort, not a guarantee. Never provide credentials or private data in task content, and keep Git diff logging disabled unless it is necessary.
