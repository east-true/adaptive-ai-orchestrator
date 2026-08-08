from __future__ import annotations

import os
import sysconfig
from pathlib import Path
from typing import MutableMapping

#: The variable a child interpreter reads its extra import roots from.
PYTHON_PATH_VARIABLE = "PYTHONPATH"


def package_root() -> Path:
    """The directory ``adaptive_orchestrator`` itself must be imported from."""
    return Path(__file__).resolve().parent.parent.parent


def _installed_roots() -> tuple[str, ...]:
    """Import roots the interpreter already searches without any PYTHONPATH."""
    return tuple(
        os.path.abspath(path)
        for name in ("purelib", "platlib")
        if (path := sysconfig.get_path(name))
    )


def resolved_import_path(value: str | None, root: Path | None = None) -> str | None:
    """Rewrite one PYTHONPATH value so it means the same from any directory.

    Relative entries are resolved against the caller's working directory, which
    is where the operator typed the command—not the agent workspace a child is
    started in. An empty entry keeps its documented meaning of "the working
    directory" by resolving to that same place rather than being dropped.
    """

    raw = value or ""
    entries = [os.path.abspath(item) for item in raw.split(os.pathsep)] if raw else []
    root_text = os.path.abspath(str(package_root() if root is None else root))
    if root_text not in entries and root_text not in _installed_roots():
        # A source checkout reaches the CLI through an import root that only
        # exists because of PYTHONPATH. Naming it explicitly keeps a child
        # runnable even when the variable was never set—for example when the
        # package was reached through a directly manipulated sys.path.
        entries.append(root_text)
    if not entries:
        return None
    return os.pathsep.join(dict.fromkeys(entries))


def ensure_child_import_path(environ: MutableMapping[str, str] | None = None) -> str | None:
    """Make ``python -m adaptive_orchestrator...`` work from any working directory.

    Two commands start this package as a child process inside the agent
    workspace: the plan-file validation `plan generate` verifies its own output
    with, and every task the TUI launches. Both inherit ``PYTHONPATH``, so the
    documented source-checkout invocation—``PYTHONPATH=src``—resolved against
    the workspace instead of the checkout and left the child unable to import
    the package it was told to run.
    """

    target = os.environ if environ is None else environ
    value = resolved_import_path(target.get(PYTHON_PATH_VARIABLE))
    if value is None:
        return None
    target[PYTHON_PATH_VARIABLE] = value
    return value
