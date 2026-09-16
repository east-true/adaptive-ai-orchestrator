#!/usr/bin/python3
"""Give Codex model commands a proc-free namespace before native policy enforcement."""

from __future__ import annotations

import os
import sys
import tempfile


_BWRAP = "/usr/bin/bwrap"
_NATIVE_HELPER = "/phase2b-native-helper/codex-linux-sandbox"


def main() -> None:
    # This directory lives below the outer, supervisor-pinned /tmp. It hides
    # the trusted CLI core's mutable credential home from every model command.
    model_home = tempfile.mkdtemp(prefix="phase2b-codex-model-home-", dir="/tmp")
    os.chmod(model_home, 0o700)
    arguments = [
        _BWRAP,
        "--die-with-parent",
        "--new-session",
        "--unshare-all",
        "--hostname",
        "phase2b",
        "--dev",
        "/dev",
        "--dir",
        "/proc",
        "--bind",
        "/tmp",
        "/tmp",
        "--dir",
        "/run",
        "--ro-bind",
        "/etc",
        "/etc",
    ]
    for path in ("/usr", "/bin", "/sbin", "/lib", "/lib64"):
        if os.path.exists(path):
            arguments.extend(("--ro-bind", path, path))
    arguments.extend((
        "--bind",
        "/workspace",
        "/workspace",
        "--ro-bind",
        "/workspace/.git",
        "/workspace/.git",
        "--bind",
        model_home,
        "/agent-home",
        "--ro-bind",
        "/phase2b-bin",
        "/phase2b-bin",
        "--ro-bind",
        "/phase2b-runtime",
        "/phase2b-runtime",
        "--ro-bind",
        "/phase2b-native-helper",
        "/phase2b-native-helper",
        "--remount-ro",
        "/agent-home",
        "--remount-ro",
        "/",
        "--remount-ro",
        "/dev",
        "--chdir",
        "/workspace",
        "--",
        _NATIVE_HELPER,
        *sys.argv[1:],
    ))
    os.execv(_BWRAP, arguments)


if __name__ == "__main__":
    main()
