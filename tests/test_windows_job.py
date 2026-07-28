import ctypes
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from adaptive_orchestrator.execution import _windows_job as windows_job_module
from adaptive_orchestrator.execution._windows_job import WindowsJob


class FakeWindowsJobApi:
    def __init__(self, fail_at: str | None = None) -> None:
        self.fail_at = fail_at
        self.calls: list[tuple[object, ...]] = []
        self.job_handle = object()
        self.process_handle = 24680

    def _record(self, operation: str, *arguments: object) -> None:
        self.calls.append((operation, *arguments))
        if self.fail_at == operation:
            raise OSError(f"{operation} failed")

    def create_unnamed_job(self) -> object:
        self._record("create_unnamed_job")
        return self.job_handle

    def set_kill_on_close(self, job_handle: object, enabled: bool) -> None:
        self._record("set_kill_on_close", job_handle, enabled)

    def assign_process(self, job_handle: object, process_handle: object) -> None:
        self._record("assign_process", job_handle, process_handle)

    def terminate_job(self, job_handle: object, exit_code: int) -> None:
        self._record("terminate_job", job_handle, exit_code)

    def close_handle(self, handle: object) -> None:
        self._record("close_handle", handle)


class WindowsJobTests(unittest.TestCase):
    def test_extended_limit_structure_matches_windows_abi(self) -> None:
        expected_size = 144 if ctypes.sizeof(ctypes.c_void_p) == 8 else 112
        self.assertEqual(
            ctypes.sizeof(windows_job_module._JobObjectExtendedLimitInformation),
            expected_size,
        )

    def test_create_arms_a_fresh_unnamed_job(self) -> None:
        api = FakeWindowsJobApi()

        job = WindowsJob.create(api)

        self.assertTrue(job.armed)
        self.assertFalse(job.closed)
        self.assertEqual(
            api.calls,
            [
                ("create_unnamed_job",),
                ("set_kill_on_close", api.job_handle, True),
            ],
        )

    def test_assign_uses_popen_owned_handle_without_closing_it(self) -> None:
        api = FakeWindowsJobApi()
        job = WindowsJob.create(api)
        api.calls.clear()

        job.assign_process_handle(api.process_handle)

        self.assertEqual(
            api.calls,
            [
                ("assign_process", api.job_handle, api.process_handle),
            ],
        )

    def test_assign_failure_preserves_error_without_closing_popen_handle(self) -> None:
        api = FakeWindowsJobApi(fail_at="assign_process")
        job = WindowsJob.create(api)
        api.calls.clear()

        with self.assertRaisesRegex(OSError, "assign_process failed"):
            job.assign_process_handle(api.process_handle)

        self.assertEqual(api.calls, [("assign_process", api.job_handle, api.process_handle)])
        self.assertFalse(job.closed)

    def test_create_configuration_failure_closes_job_handle(self) -> None:
        api = FakeWindowsJobApi(fail_at="set_kill_on_close")

        with self.assertRaisesRegex(OSError, "set_kill_on_close failed"):
            WindowsJob.create(api)

        self.assertEqual(api.calls[-1], ("close_handle", api.job_handle))

    def test_terminate_uses_requested_exit_code(self) -> None:
        api = FakeWindowsJobApi()
        job = WindowsJob.create(api)
        api.calls.clear()

        job.terminate(23)

        self.assertEqual(api.calls, [("terminate_job", api.job_handle, 23)])

    def test_disarm_removes_kill_on_close_once(self) -> None:
        api = FakeWindowsJobApi()
        job = WindowsJob.create(api)
        api.calls.clear()

        job.disarm()
        job.disarm()

        self.assertFalse(job.armed)
        self.assertEqual(api.calls, [("set_kill_on_close", api.job_handle, False)])

    def test_failed_disarm_leaves_job_armed(self) -> None:
        api = FakeWindowsJobApi()
        job = WindowsJob.create(api)
        api.calls.clear()
        api.fail_at = "set_kill_on_close"

        with self.assertRaisesRegex(OSError, "set_kill_on_close failed"):
            job.disarm()

        self.assertTrue(job.armed)

    def test_close_is_idempotent(self) -> None:
        api = FakeWindowsJobApi()
        job = WindowsJob.create(api)
        api.calls.clear()

        job.close()
        job.close()

        self.assertTrue(job.closed)
        self.assertEqual(api.calls, [("close_handle", api.job_handle)])

    def test_failed_close_can_be_retried(self) -> None:
        api = FakeWindowsJobApi()
        job = WindowsJob.create(api)
        api.calls.clear()
        api.fail_at = "close_handle"

        with self.assertRaisesRegex(OSError, "close_handle failed"):
            job.close()
        self.assertFalse(job.closed)

        api.fail_at = None
        job.close()
        self.assertTrue(job.closed)

    def test_context_manager_closes_job_without_suppressing_body_error(self) -> None:
        api = FakeWindowsJobApi()

        with self.assertRaisesRegex(LookupError, "body failed"):
            with WindowsJob.create(api) as job:
                self.assertFalse(job.closed)
                raise LookupError("body failed")

        self.assertTrue(job.closed)
        self.assertEqual(api.calls[-1], ("close_handle", api.job_handle))

    def test_context_manager_preserves_body_error_when_close_also_fails(self) -> None:
        api = FakeWindowsJobApi()

        with self.assertRaisesRegex(LookupError, "body failed"):
            with WindowsJob.create(api) as job:
                api.fail_at = "close_handle"
                raise LookupError("body failed")

        self.assertFalse(job.closed)
        self.assertIn(("terminate_job", api.job_handle, 1), api.calls)
        self.assertEqual(
            [call for call in api.calls if call == ("close_handle", api.job_handle)],
            [("close_handle", api.job_handle), ("close_handle", api.job_handle)],
        )

    def test_operations_after_close_are_rejected(self) -> None:
        api = FakeWindowsJobApi()
        job = WindowsJob.create(api)
        job.close()

        with self.assertRaisesRegex(RuntimeError, "closed"):
            job.assign_process_handle(1)
        with self.assertRaisesRegex(RuntimeError, "closed"):
            job.terminate()
        with self.assertRaisesRegex(RuntimeError, "closed"):
            job.disarm()

    def test_invalid_process_handle_and_exit_code_do_not_call_api(self) -> None:
        api = FakeWindowsJobApi()
        job = WindowsJob.create(api)
        api.calls.clear()

        for process_handle in (None, True, 0, -1, object()):
            with self.subTest(process_handle=process_handle), self.assertRaises(ValueError):
                job.assign_process_handle(process_handle)
        for exit_code in (True, -1, 0x1_0000_0000):
            with self.subTest(exit_code=exit_code), self.assertRaises(ValueError):
                job.terminate(exit_code)

        self.assertEqual(api.calls, [])


if __name__ == "__main__":
    unittest.main()
