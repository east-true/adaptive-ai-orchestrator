from __future__ import annotations

import ctypes
import os
from types import TracebackType
from typing import Protocol


# These aliases deliberately use fixed-width ctypes instead of ctypes.wintypes.
# On a non-Windows host wintypes.DWORD follows the host C ABI, which makes the
# structures below the wrong size even though importing the module succeeds.
_BOOL = ctypes.c_int32
_DWORD = ctypes.c_uint32
_HANDLE = ctypes.c_void_p
_SIZE_T = ctypes.c_size_t
_ULONG_PTR = ctypes.c_size_t

_JOB_OBJECT_EXTENDED_LIMIT_INFORMATION = 9
_JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x00002000


class _JobObjectBasicLimitInformation(ctypes.Structure):
    _fields_ = [
        ("PerProcessUserTimeLimit", ctypes.c_int64),
        ("PerJobUserTimeLimit", ctypes.c_int64),
        ("LimitFlags", _DWORD),
        ("MinimumWorkingSetSize", _SIZE_T),
        ("MaximumWorkingSetSize", _SIZE_T),
        ("ActiveProcessLimit", _DWORD),
        ("Affinity", _ULONG_PTR),
        ("PriorityClass", _DWORD),
        ("SchedulingClass", _DWORD),
    ]


class _IoCounters(ctypes.Structure):
    _fields_ = [
        ("ReadOperationCount", ctypes.c_uint64),
        ("WriteOperationCount", ctypes.c_uint64),
        ("OtherOperationCount", ctypes.c_uint64),
        ("ReadTransferCount", ctypes.c_uint64),
        ("WriteTransferCount", ctypes.c_uint64),
        ("OtherTransferCount", ctypes.c_uint64),
    ]


class _JobObjectExtendedLimitInformation(ctypes.Structure):
    _fields_ = [
        ("BasicLimitInformation", _JobObjectBasicLimitInformation),
        ("IoInfo", _IoCounters),
        ("ProcessMemoryLimit", _SIZE_T),
        ("JobMemoryLimit", _SIZE_T),
        ("PeakProcessMemoryUsed", _SIZE_T),
        ("PeakJobMemoryUsed", _SIZE_T),
    ]


class _WindowsJobApi(Protocol):
    """Small seam around WinAPI calls, allowing POSIX-hosted unit tests."""

    def create_unnamed_job(self) -> object: ...

    def set_kill_on_close(self, job_handle: object, enabled: bool) -> None: ...

    def assign_process(self, job_handle: object, process_handle: object) -> None: ...

    def terminate_job(self, job_handle: object, exit_code: int) -> None: ...

    def close_handle(self, handle: object) -> None: ...


def _last_error(operation: str) -> OSError:
    get_last_error = getattr(ctypes, "get_last_error", None)
    error_code = int(get_last_error()) if get_last_error is not None else 0
    format_error = getattr(ctypes, "FormatError", None)
    if format_error is not None:
        try:
            detail = str(format_error(error_code)).strip()
        except OSError:
            detail = f"Windows error {error_code}"
    else:
        detail = f"Windows error {error_code}"
    return OSError(error_code, f"{operation} failed: {detail}")


class _CtypesWindowsJobApi:
    """ctypes-backed implementation loaded only when a real job is created."""

    def __init__(self) -> None:
        if os.name != "nt":
            raise OSError("Windows Job Objects are only available on Windows")

        win_dll = getattr(ctypes, "WinDLL", None)
        if win_dll is None:
            raise OSError("ctypes.WinDLL is unavailable on this Python runtime")
        kernel32 = win_dll("kernel32", use_last_error=True)

        self._create_job_object = kernel32.CreateJobObjectW
        self._create_job_object.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p]
        self._create_job_object.restype = _HANDLE

        self._set_information_job_object = kernel32.SetInformationJobObject
        self._set_information_job_object.argtypes = [_HANDLE, ctypes.c_int, ctypes.c_void_p, _DWORD]
        self._set_information_job_object.restype = _BOOL

        self._assign_process_to_job_object = kernel32.AssignProcessToJobObject
        self._assign_process_to_job_object.argtypes = [_HANDLE, _HANDLE]
        self._assign_process_to_job_object.restype = _BOOL

        self._terminate_job_object = kernel32.TerminateJobObject
        self._terminate_job_object.argtypes = [_HANDLE, _DWORD]
        self._terminate_job_object.restype = _BOOL

        self._close_handle = kernel32.CloseHandle
        self._close_handle.argtypes = [_HANDLE]
        self._close_handle.restype = _BOOL

    def create_unnamed_job(self) -> object:
        handle = self._create_job_object(None, None)
        if not handle:
            raise _last_error("CreateJobObjectW")
        return handle

    def set_kill_on_close(self, job_handle: object, enabled: bool) -> None:
        information = _JobObjectExtendedLimitInformation()
        if enabled:
            information.BasicLimitInformation.LimitFlags = _JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        if not self._set_information_job_object(
            job_handle,
            _JOB_OBJECT_EXTENDED_LIMIT_INFORMATION,
            ctypes.byref(information),
            ctypes.sizeof(information),
        ):
            raise _last_error("SetInformationJobObject")

    def assign_process(self, job_handle: object, process_handle: object) -> None:
        if not self._assign_process_to_job_object(job_handle, process_handle):
            raise _last_error("AssignProcessToJobObject")

    def terminate_job(self, job_handle: object, exit_code: int) -> None:
        if not self._terminate_job_object(job_handle, exit_code):
            raise _last_error("TerminateJobObject")

    def close_handle(self, handle: object) -> None:
        if not self._close_handle(handle):
            raise _last_error("CloseHandle")


class WindowsJob:
    """Own one unnamed Windows Job Object and its process-tree lifetime."""

    __slots__ = ("_api", "_armed", "_handle")

    def __init__(self, api: _WindowsJobApi, handle: object) -> None:
        self._api = api
        self._handle: object | None = handle
        self._armed = True

    @classmethod
    def create(cls, api: _WindowsJobApi | None = None) -> WindowsJob:
        resolved_api = api if api is not None else _CtypesWindowsJobApi()
        handle = resolved_api.create_unnamed_job()
        try:
            resolved_api.set_kill_on_close(handle, True)
        except BaseException:
            try:
                resolved_api.close_handle(handle)
            except OSError:
                # Preserve the configuration failure; it explains why the job
                # could not safely own a process tree in the first place.
                pass
            raise
        return cls(resolved_api, handle)

    @property
    def closed(self) -> bool:
        return self._handle is None

    @property
    def armed(self) -> bool:
        return self._armed

    def _open_handle(self) -> object:
        if self._handle is None:
            raise RuntimeError("Windows job is closed")
        return self._handle

    def assign_process_handle(self, process_handle: object) -> None:
        """Assign a live Popen-owned process handle without reopening by PID."""
        try:
            raw_handle = int(process_handle)
        except (TypeError, ValueError, OverflowError) as exc:
            raise ValueError("process_handle must be a positive native handle") from exc
        if isinstance(process_handle, bool) or raw_handle <= 0:
            raise ValueError("process_handle must be a positive native handle")
        job_handle = self._open_handle()
        # Popen retains ownership of this handle and closes it while reaping;
        # the Job adapter must not close or duplicate it.
        self._api.assign_process(job_handle, raw_handle)

    def terminate(self, exit_code: int = 1) -> None:
        if isinstance(exit_code, bool) or not isinstance(exit_code, int) or not 0 <= exit_code <= 0xFFFFFFFF:
            raise ValueError("exit_code must be an unsigned 32-bit integer")
        self._api.terminate_job(self._open_handle(), exit_code)

    def disarm(self) -> None:
        handle = self._open_handle()
        if not self._armed:
            return
        self._api.set_kill_on_close(handle, False)
        self._armed = False

    def close(self) -> None:
        handle = self._handle
        if handle is None:
            return
        self._api.close_handle(handle)
        self._handle = None

    def __enter__(self) -> WindowsJob:
        self._open_handle()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> bool:
        try:
            self.close()
        except OSError:
            if exc_value is None:
                raise
            # Cleanup must not replace the exception that caused the context
            # to unwind. If CloseHandle itself failed, explicitly terminate an
            # armed job before one retry so its tree cannot keep running merely
            # because handle cleanup was unsuccessful.
            if self._armed:
                try:
                    self.terminate()
                except OSError:
                    pass
            try:
                self.close()
            except OSError:
                pass
        return False
