"""Compatibility entry point for :mod:`adaptive_orchestrator.interfaces.cli`."""

from adaptive_orchestrator.interfaces.cli import *  # noqa: F403


if __name__ == "__main__":
    # Propagate the status: the shim is the documented
    # `python3 -m adaptive_orchestrator.<name>` entry point, and dropping
    # main()'s return value made every failure exit 0 there while the
    # installed console script reported it correctly.
    raise SystemExit(main())
