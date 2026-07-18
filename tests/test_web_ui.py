from __future__ import annotations

import http.client
import json
import sys
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from adaptive_orchestrator.control import JobManager
from adaptive_orchestrator.web_ui import make_handler, render_index


class WebUiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.workspace = Path(self.temporary.name)
        self.manager = JobManager(self.workspace, popen=_fake_popen)
        self.token = "test-token"
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(self.manager, self.token))
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.manager.close()
        self.temporary.cleanup()

    def test_index_contains_token_but_uses_text_content_for_job_data(self) -> None:
        html = render_index(self.token)
        self.assertIn("test-token", html)
        self.assertIn("textContent", html)
        self.assertNotIn("innerHTML", html)

    def test_api_requires_token(self) -> None:
        status, payload = self._request("GET", "/api/jobs")
        self.assertEqual(status, 401)
        self.assertIn("invalid", payload["error"])

    def test_submit_list_and_cancel_api(self) -> None:
        status, submitted = self._request(
            "POST", "/api/jobs", {"request": "Run tests", "agent": "auto"}, authorized=True
        )
        self.assertEqual(status, 202)
        job_id = submitted["job"]["job_id"]
        status, listed = self._request("GET", "/api/jobs", authorized=True)
        self.assertEqual(status, 200)
        self.assertEqual(listed["jobs"][0]["job_id"], job_id)

    def _request(self, method: str, path: str, body: dict | None = None, authorized: bool = False):
        connection = http.client.HTTPConnection("127.0.0.1", self.server.server_port, timeout=2)
        headers = {"X-Orchestrator-Token": self.token} if authorized else {}
        encoded = None
        if body is not None:
            encoded = json.dumps(body)
            headers["Content-Type"] = "application/json"
        connection.request(method, path, body=encoded, headers=headers)
        response = connection.getresponse()
        payload = json.loads(response.read())
        connection.close()
        return response.status, payload


def _fake_popen(*args, **kwargs):
    del args, kwargs
    return _FakeProcess()


class _FakeProcess:
    pid = 12345
    stdout = iter(("done\n",))

    def poll(self):
        return 0

    def wait(self):
        return 0


if __name__ == "__main__":
    unittest.main()
