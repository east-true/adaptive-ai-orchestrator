# Contributing

Thank you for considering a contribution. This project is an early-stage,
CLI-first orchestration kernel, so small changes with explicit tests and clear
evidence are easier to review than broad rewrites.

## Before you start

- Use GitHub Issues for reproducible bugs and scoped feature proposals.
- Use the private channel in [SECURITY.md](SECURITY.md) for vulnerabilities,
  leaked credentials, or other sensitive reports. Do not put sensitive details
  in a public issue.
- Follow the [Code of Conduct](CODE_OF_CONDUCT.md).
- For a large architectural or experimental-protocol change, open an issue
  before implementation so its scope and evidence requirements can be agreed.

## Development setup

Python 3.10 or newer on a POSIX host is required. Upgrade `pip` before
installing because older PEP 517 frontends may not read the project's PEP 621
metadata correctly.

```bash
python3 -m venv .venv
. .venv/bin/activate
python -m pip install --upgrade "pip>=24"
python -m pip install -e .
python -m unittest discover -s tests -v
```

The core has no runtime Python dependency outside the standard library. Claude
Code and Codex are optional execution targets; tests must remain runnable
without either CLI, provider credentials, or network access.

## Making a change

1. Fork the repository and create a focused branch.
2. Add or update tests for behavior changes.
3. Keep provider-specific process details in execution adapters and keep core
   task, routing, and evaluation contracts vendor-neutral.
4. Update public documentation when commands, persisted schemas, or safety
   boundaries change.
5. Run the checks below, then open a pull request using the repository template.

```bash
python -m unittest discover -s tests -v
python -m adaptive_orchestrator.cli --help
git diff --check
```

Tests should use temporary directories and deterministic fixtures. They must not
depend on a contributor's home directory, local agent history, subscription
state, or ignored `.orchestrator/` data.

## Experimental evidence

Files under `experiments/` distinguish protocol construction evidence from
agent-performance evidence. A screening artifact, smoke test, or dry run must
not be described as an agent ranking. Changes to a preregistered contract must
be made as an explicit version or amendment; do not silently rewrite frozen
inputs. Candidate-agent runs require the authorization stated by the relevant
protocol.

Tracked artifacts must not include protected evaluator bodies, credentials,
private knowledge bases, machine-specific paths, or local execution logs. If a
result relies on local-only protected material, document the public
reproducibility boundary without publishing that material.

## Pull-request expectations

A pull request should explain:

- the problem and the chosen scope;
- user-visible and persisted-data changes;
- tests or other verification performed;
- any safety, privacy, compatibility, or experimental-validity tradeoff;
- related issues and documentation.

Maintainers may ask to split changes that mix unrelated behavior, protocol, and
documentation work. By contributing, you agree that your contribution is
licensed under the repository's [Apache License 2.0](LICENSE).
