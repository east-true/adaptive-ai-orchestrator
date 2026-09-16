#!/usr/bin/python3
"""Replace Claude sandbox-runtime's mount plan with a fixed trusted boundary.

Claude's core may use procfs and its mutable credential home while preparing a
Bash tool call. At the final SRT wrapper boundary we validate only the command
shape, discard the caller-supplied mount plan, close inherited descriptors, and
construct a fixed model namespace whose writable storage is limited to the
outer supervisor-pinned workspace and /tmp.
"""

from __future__ import annotations

import ctypes
import ctypes.util
import errno
import os
import re
import resource
import socket
import sys
import tempfile


_BWRAP = "/usr/bin/bwrap"
_MODEL_PATH = (
    "/phase2b-runtime/node/bin:"
    "/phase2b-runtime/go/bin:"
    "/phase2b-runtime/rust-toolchain/bin:"
    "/phase2b-runtime/cargo/bin:"
    "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
)
_SCMP_ACT_ALLOW = 0x7FFF0000
_SCMP_ACT_ERRNO = 0x00050000
_SCMP_CMP_EQ = 4
_SCMP_CMP_MASKED_EQ = 7
_NAMESPACE_CLONE_FLAGS = (
    0x00000080,  # CLONE_NEWTIME
    0x00020000,  # CLONE_NEWNS
    0x02000000,  # CLONE_NEWCGROUP
    0x04000000,  # CLONE_NEWUTS
    0x08000000,  # CLONE_NEWIPC
    0x10000000,  # CLONE_NEWUSER
    0x20000000,  # CLONE_NEWPID
    0x40000000,  # CLONE_NEWNET
)
_DENIED_SYSCALLS = (
    "add_key",
    "chroot",
    "fsconfig",
    "fsmount",
    "fsopen",
    "fspick",
    "io_uring_enter",
    "io_uring_register",
    "io_uring_setup",
    "kcmp",
    "mount",
    "mount_setattr",
    "move_mount",
    "open_tree",
    "pidfd_getfd",
    "pivot_root",
    "process_vm_readv",
    "process_vm_writev",
    "process_madvise",
    "ptrace",
    "keyctl",
    "request_key",
    "setns",
    "umount",
    "umount2",
    "unshare",
)
_FORBIDDEN_SRT_SCAFFOLD = re.compile(
    r"argv0\s*=\s*apply-seccomp"
    r"|(?:^|[;&|()\n]\s*)(?:exec\s+)?(?:[^\s;&|()]*/)?apply-seccomp(?:\s|$)"
    r"|(?:^|[;&|()\n]\s*)(?:exec\s+)?(?:[^\s;&|()]*/)?socat(?:\s|$)"
    r"|(?:^|[;&|()\n]\s*)(?:exec\s+)?(?:[^\s;&|()]*/)?(?:proxy|proxy\.py)(?:\s|$)",
    flags=re.IGNORECASE,
)
_OWNED_CLOSE_ATTEMPTS = 8


class _ScmpArgCompare(ctypes.Structure):
    _fields_ = (
        ("arg", ctypes.c_uint),
        ("op", ctypes.c_int),
        ("datum_a", ctypes.c_uint64),
        ("datum_b", ctypes.c_uint64),
    )


def _fd_identity(fd: int) -> tuple[int, int, int, int] | None:
    for _attempt in range(_OWNED_CLOSE_ATTEMPTS):
        try:
            observed = os.fstat(fd)
            return (
                observed.st_dev,
                observed.st_ino,
                observed.st_mode,
                observed.st_rdev,
            )
        except OSError as exc:
            if exc.errno == errno.EBADF:
                return None
        except BaseException:
            pass
    raise RuntimeError("seccomp descriptor identity could not be verified")


def _close_owned_fd(fd: int) -> None:
    identity = _fd_identity(fd)
    if identity is None:
        return
    for _attempt in range(_OWNED_CLOSE_ATTEMPTS):
        current = _fd_identity(fd)
        if current is None or current != identity:
            return
        try:
            os.close(fd)
            return
        except OSError as exc:
            if exc.errno == errno.EBADF:
                return
        except BaseException:
            pass
        current = _fd_identity(fd)
        if current is None or current != identity:
            return
    raise RuntimeError("seccomp descriptor cleanup could not be verified")


def _errno_action(value: int) -> int:
    return _SCMP_ACT_ERRNO | (value & 0xFFFF)


def _load_libseccomp() -> ctypes.CDLL:
    library_name = ctypes.util.find_library("seccomp")
    if not library_name:
        raise RuntimeError("libseccomp is unavailable")
    library = ctypes.CDLL(library_name, use_errno=True)
    library.seccomp_init.argtypes = (ctypes.c_uint32,)
    library.seccomp_init.restype = ctypes.c_void_p
    library.seccomp_release.argtypes = (ctypes.c_void_p,)
    library.seccomp_release.restype = None
    library.seccomp_syscall_resolve_name.argtypes = (ctypes.c_char_p,)
    library.seccomp_syscall_resolve_name.restype = ctypes.c_int
    library.seccomp_rule_add_array.argtypes = (
        ctypes.c_void_p,
        ctypes.c_uint32,
        ctypes.c_int,
        ctypes.c_uint,
        ctypes.POINTER(_ScmpArgCompare),
    )
    library.seccomp_rule_add_array.restype = ctypes.c_int
    library.seccomp_export_bpf.argtypes = (ctypes.c_void_p, ctypes.c_int)
    library.seccomp_export_bpf.restype = ctypes.c_int
    return library


def _add_rule(
    library: ctypes.CDLL,
    context: int,
    syscall_name: str,
    action: int,
    comparisons: tuple[_ScmpArgCompare, ...] = (),
) -> None:
    syscall_number = library.seccomp_syscall_resolve_name(
        syscall_name.encode("ascii")
    )
    # A syscall absent on this architecture cannot be invoked here.
    if syscall_number < 0:
        return
    comparison_array = None
    if comparisons:
        array_type = _ScmpArgCompare * len(comparisons)
        comparison_array = array_type(*comparisons)
    result = library.seccomp_rule_add_array(
        context,
        action,
        syscall_number,
        len(comparisons),
        comparison_array,
    )
    if result != 0:
        raise RuntimeError(
            f"unable to add seccomp rule for {syscall_name}: errno={-result}"
        )


def _seccomp_filter_fd() -> int:
    library = _load_libseccomp()
    context = library.seccomp_init(_SCMP_ACT_ALLOW)
    if not context:
        raise RuntimeError("unable to initialize seccomp filter")
    try:
        deny = _errno_action(errno.EPERM)
        for syscall_name in _DENIED_SYSCALLS:
            _add_rule(library, context, syscall_name, deny)
        # Returning ENOSYS makes libc fall back to clone/vfork for ordinary
        # child processes while denying clone3 namespace creation wholesale.
        _add_rule(library, context, "clone3", _errno_action(errno.ENOSYS))
        _add_rule(
            library,
            context,
            "socket",
            deny,
            (_ScmpArgCompare(0, _SCMP_CMP_EQ, socket.AF_UNIX, 0),),
        )
        _add_rule(
            library,
            context,
            "socketpair",
            deny,
            (_ScmpArgCompare(0, _SCMP_CMP_EQ, socket.AF_UNIX, 0),),
        )
        for flag in _NAMESPACE_CLONE_FLAGS:
            _add_rule(
                library,
                context,
                "clone",
                deny,
                (_ScmpArgCompare(0, _SCMP_CMP_MASKED_EQ, flag, flag),),
            )
        fd = os.memfd_create("phase2b-claude-seccomp", flags=0)
        os.set_inheritable(fd, True)
        result = library.seccomp_export_bpf(context, fd)
        if result != 0:
            try:
                _close_owned_fd(fd)
            except BaseException:
                # This process terminates on the export failure, so the kernel
                # closes any still-owned quarantined descriptor at exit.  The
                # export diagnostic remains authoritative.
                pass
            raise RuntimeError(f"unable to export seccomp filter: errno={-result}")
        os.lseek(fd, 0, os.SEEK_SET)
        return fd
    finally:
        library.seccomp_release(context)


def _validated_boundary(arguments: list[str]) -> int:
    try:
        boundary = arguments.index("--")
    except ValueError as exc:
        raise RuntimeError("Claude bubblewrap invocation has no command boundary") from exc
    if boundary == len(arguments) - 1:
        raise RuntimeError("Claude bubblewrap invocation has no command")
    outer = arguments[:boundary]
    if any(
        token in {"--seccomp", "--add-seccomp"}
        or token.startswith("--seccomp=")
        or token.startswith("--add-seccomp=")
        for token in outer
    ):
        raise RuntimeError("Claude bubblewrap invocation supplied an unmanaged filter")
    if "--share-net" in outer:
        raise RuntimeError("Claude bubblewrap invocation shared the network")
    for required in ("--die-with-parent", "--new-session", "--unshare-net"):
        if required not in outer:
            raise RuntimeError(
                f"Claude bubblewrap invocation omitted required option {required}"
            )
    if "--unshare-all" not in outer and not all(
        option in outer for option in ("--unshare-user", "--unshare-pid")
    ):
        raise RuntimeError("Claude bubblewrap invocation omitted user/pid isolation")
    if any(token == "--cap-add" or token.startswith("--cap-add=") for token in outer) or not any(
        outer[index:index + 2] == ["--cap-drop", "ALL"]
        for index in range(max(0, len(outer) - 1))
    ):
        raise RuntimeError("Claude bubblewrap invocation did not drop all capabilities")
    if not any(
        outer[index:index + 2] == ["--proc", "/proc"]
        for index in range(max(0, len(outer) - 1))
    ):
        raise RuntimeError("Claude bubblewrap invocation did not mount procfs")
    tmpfs_positions = [
        index
        for index in range(max(0, len(outer) - 1))
        if outer[index : index + 2] == ["--tmpfs", "/tmp"]
    ]
    if len(tmpfs_positions) != 1:
        raise RuntimeError(
            "Claude bubblewrap invocation did not supply one isolated /tmp"
        )
    command = arguments[boundary + 1:]
    if (
        len(command) != 3
        or command[0] not in {"bash", "/bin/bash", "/usr/bin/bash"}
        or command[1] != "-c"
    ):
        raise RuntimeError("Claude bubblewrap command boundary shape drifted")
    script = command[2]
    if "\n" in script or "\r" in script:
        raise RuntimeError("Claude bubblewrap command boundary contains a newline")
    if _FORBIDDEN_SRT_SCAFFOLD.search(script):
        raise RuntimeError("Claude built-in seccomp/proxy helper was not disabled")
    return boundary


def _close_unmanaged_descriptors(keep: int) -> None:
    try:
        maximum = resource.getrlimit(resource.RLIMIT_NOFILE)[0]
    except (OSError, ValueError):
        maximum = 1024
    if maximum == resource.RLIM_INFINITY:
        maximum = 65536
    maximum = min(int(maximum), 1_048_576)
    if keep > 3:
        os.closerange(3, keep)
    os.closerange(keep + 1, maximum)


def _fixed_model_boundary(command: list[str], filter_fd: int) -> list[str]:
    model_home = tempfile.mkdtemp(prefix="phase2b-claude-model-home-", dir="/tmp")
    os.chmod(model_home, 0o700)
    arguments = [
        _BWRAP,
        "--die-with-parent",
        "--new-session",
        "--unshare-all",
        "--hostname",
        "phase2b",
        "--cap-drop",
        "ALL",
        "--clearenv",
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
        "--dir",
        "/workspace",
        "--bind",
        "/workspace",
        "/workspace",
        "--ro-bind",
        "/workspace/.git",
        "/workspace/.git",
        "--dir",
        "/agent-home",
        "--bind",
        model_home,
        "/agent-home",
        "--dir",
        "/phase2b-runtime",
        "--dir",
        "/phase2b-runtime/node",
        "--dir",
        "/phase2b-runtime/node/bin",
        "--dir",
        "/phase2b-runtime/node/lib",
        "--dir",
        "/phase2b-runtime/node/lib/node_modules",
    ))
    fixed_read_only_mounts = (
        (
            "/phase2b-runtime/node/bin/node",
            "/phase2b-runtime/node/bin/node",
        ),
        (
            "/phase2b-runtime/node/lib/node_modules/npm",
            "/phase2b-runtime/node/lib/node_modules/npm",
        ),
        ("/phase2b-runtime/go", "/phase2b-runtime/go"),
        ("/phase2b-runtime/cargo", "/phase2b-runtime/cargo"),
        ("/phase2b-runtime/rustup", "/phase2b-runtime/rustup"),
        (
            "/phase2b-runtime/rust-toolchain",
            "/phase2b-runtime/rust-toolchain",
        ),
    )
    mounted_targets: set[str] = set()
    for source, target in fixed_read_only_mounts:
        if os.path.exists(source):
            arguments.extend(("--ro-bind", source, target))
            mounted_targets.add(target)
    if "/phase2b-runtime/node/lib/node_modules/npm" in mounted_targets:
        arguments.extend((
            "--symlink",
            "../lib/node_modules/npm/bin/npm-cli.js",
            "/phase2b-runtime/node/bin/npm",
            "--symlink",
            "../lib/node_modules/npm/bin/npx-cli.js",
            "/phase2b-runtime/node/bin/npx",
        ))
    for key, value in (
        ("CARGO_HOME", "/phase2b-runtime/cargo"),
        ("CI", "1"),
        ("GOENV", "off"),
        ("GOCACHE", "/tmp/go-cache"),
        ("GOROOT", "/phase2b-runtime/go"),
        ("HOME", "/agent-home"),
        ("LANG", "C.UTF-8"),
        ("LC_ALL", "C.UTF-8"),
        ("LD_LIBRARY_PATH", "/phase2b-runtime/rust-toolchain/lib"),
        ("LOGNAME", "phase2b"),
        ("NO_COLOR", "1"),
        ("PATH", _MODEL_PATH),
        ("NPM_CONFIG_CACHE", "/tmp/npm-cache"),
        ("PYTHONDONTWRITEBYTECODE", "1"),
        ("PYTHONNOUSERSITE", "1"),
        ("RUSTUP_HOME", "/phase2b-runtime/rustup"),
        ("SHELL", "/bin/sh"),
        ("TMPDIR", "/tmp"),
        ("USER", "phase2b"),
        ("XDG_CACHE_HOME", "/tmp/xdg-cache"),
        ("XDG_CONFIG_HOME", "/tmp/xdg-config"),
        ("XDG_DATA_HOME", "/tmp/xdg-data"),
    ):
        arguments.extend(("--setenv", key, value))
    arguments.extend((
        "--remount-ro",
        "/agent-home",
        "--remount-ro",
        "/",
        "--remount-ro",
        "/dev",
        "--seccomp",
        str(filter_fd),
        "--chdir",
        "/workspace",
        "--",
        *command,
    ))
    return arguments


def main() -> None:
    try:
        arguments = sys.argv[1:]
        command_boundary = _validated_boundary(arguments)
        filter_fd = _seccomp_filter_fd()
    except (OSError, RuntimeError) as exc:
        raise SystemExit(f"phase2b Claude sandbox hardening failed: {exc}") from exc
    hardened = _fixed_model_boundary(
        arguments[command_boundary + 1 :],
        filter_fd,
    )
    _close_unmanaged_descriptors(filter_fd)
    os.execv(_BWRAP, hardened)


if __name__ == "__main__":
    main()
