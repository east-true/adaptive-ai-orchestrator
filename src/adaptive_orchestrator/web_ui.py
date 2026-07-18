from __future__ import annotations

import argparse
import json
import secrets
import threading
from dataclasses import asdict
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Type
from urllib.parse import urlparse

from .control import JobManager


_MAX_REQUEST_BYTES = 64 * 1024


def make_handler(manager: JobManager, token: str) -> Type[BaseHTTPRequestHandler]:
    class ControlHandler(BaseHTTPRequestHandler):
        server_version = "AdaptiveOrchestrator/0.1"

        def do_GET(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler contract.
            path = urlparse(self.path).path
            if path == "/":
                self._send(HTTPStatus.OK, render_index(token), "text/html; charset=utf-8")
                return
            if path == "/api/jobs":
                if not self._authorized():
                    return
                self._json(HTTPStatus.OK, {"jobs": [asdict(job) for job in manager.list()]})
                return
            if path.startswith("/api/jobs/"):
                if not self._authorized():
                    return
                job = manager.get(path.removeprefix("/api/jobs/"))
                if job is None:
                    self._json(HTTPStatus.NOT_FOUND, {"error": "job not found"})
                else:
                    self._json(HTTPStatus.OK, {"job": asdict(job)})
                return
            self._json(HTTPStatus.NOT_FOUND, {"error": "not found"})

        def do_POST(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler contract.
            if not self._authorized():
                return
            path = urlparse(self.path).path
            if path == "/api/jobs":
                payload = self._read_json()
                if payload is None:
                    return
                request = payload.get("request")
                agent = payload.get("agent", "auto")
                if not isinstance(request, str) or not isinstance(agent, str):
                    self._json(HTTPStatus.BAD_REQUEST, {"error": "request and agent must be strings"})
                    return
                try:
                    job = manager.submit(request, agent)
                except (RuntimeError, ValueError) as exc:
                    self._json(HTTPStatus.BAD_REQUEST, {"error": str(exc)})
                    return
                self._json(HTTPStatus.ACCEPTED, {"job": asdict(job)})
                return
            if path.startswith("/api/jobs/") and path.endswith("/cancel"):
                job_id = path.removeprefix("/api/jobs/").removesuffix("/cancel").rstrip("/")
                if manager.cancel(job_id):
                    self._json(HTTPStatus.OK, {"cancelled": True})
                else:
                    self._json(HTTPStatus.CONFLICT, {"error": "job is not cancellable"})
                return
            self._json(HTTPStatus.NOT_FOUND, {"error": "not found"})

        def log_message(self, format: str, *args: object) -> None:
            del format, args

        def _authorized(self) -> bool:
            if secrets.compare_digest(self.headers.get("X-Orchestrator-Token", ""), token):
                return True
            self._json(HTTPStatus.UNAUTHORIZED, {"error": "missing or invalid control token"})
            return False

        def _read_json(self) -> dict | None:
            try:
                length = int(self.headers.get("Content-Length", "0"))
            except ValueError:
                self._json(HTTPStatus.BAD_REQUEST, {"error": "invalid Content-Length"})
                return None
            if length <= 0 or length > _MAX_REQUEST_BYTES:
                self._json(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, {"error": "request body is empty or too large"})
                return None
            try:
                payload = json.loads(self.rfile.read(length))
            except (UnicodeDecodeError, json.JSONDecodeError):
                self._json(HTTPStatus.BAD_REQUEST, {"error": "invalid JSON"})
                return None
            if not isinstance(payload, dict):
                self._json(HTTPStatus.BAD_REQUEST, {"error": "JSON body must be an object"})
                return None
            return payload

        def _json(self, status: HTTPStatus, payload: object) -> None:
            self._send(status, json.dumps(payload, default=str), "application/json; charset=utf-8")

        def _send(self, status: HTTPStatus, body: str, content_type: str) -> None:
            encoded = body.encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(encoded)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; connect-src 'self'; frame-ancestors 'none'")
            self.end_headers()
            self.wfile.write(encoded)

    return ControlHandler


def render_index(token: str) -> str:
    encoded_token = json.dumps(token)
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Adaptive Orchestrator</title><style>
body{{font:15px system-ui,sans-serif;max-width:1100px;margin:2rem auto;padding:0 1rem;background:#101418;color:#e7edf3}}
form{{display:flex;gap:.5rem}} textarea{{flex:1;min-height:5rem}} button,textarea,select{{font:inherit;padding:.6rem}}
.job{{border:1px solid #34404a;border-radius:.5rem;padding:.8rem;margin:.7rem 0}} pre{{white-space:pre-wrap;max-height:16rem;overflow:auto}}
.meta{{color:#9fb0bf}} .failed,.cancelled,.interrupted{{color:#ff8d8d}} .completed{{color:#8de6a1}}
</style></head><body><h1>Adaptive Orchestrator</h1>
<form id="new"><textarea id="request" required placeholder="Describe one engineering task"></textarea>
<select id="agent"><option>auto</option><option>codex</option><option>claude-code</option></select><button>Queue task</button></form>
<p id="message"></p><section id="jobs"></section><script>
const token={encoded_token}; const headers={{'X-Orchestrator-Token':token}};
async function refresh(){{const r=await fetch('/api/jobs',{{headers}});const data=await r.json();
 const root=document.querySelector('#jobs');root.replaceChildren();for(const job of data.jobs){{
  const box=document.createElement('article');box.className='job '+job.status;
  const title=document.createElement('strong');title.textContent=job.status+' — '+job.agent;box.append(title);
  const meta=document.createElement('div');meta.className='meta';meta.textContent=job.job_id+' · '+job.submitted_at;box.append(meta);
  const req=document.createElement('p');req.textContent=job.request;box.append(req);
  const out=document.createElement('pre');out.textContent=(job.output_tail||[]).join('\n');box.append(out);
  if(job.status==='queued'||job.status==='running'){{const b=document.createElement('button');b.textContent='Cancel';
   b.onclick=async()=>{{await fetch('/api/jobs/'+job.job_id+'/cancel',{{method:'POST',headers}});refresh();}};box.append(b);}}
  root.append(box);}}}}
document.querySelector('#new').onsubmit=async e=>{{e.preventDefault();const request=document.querySelector('#request').value;
 const agent=document.querySelector('#agent').value;const r=await fetch('/api/jobs',{{method:'POST',headers:{{...headers,'Content-Type':'application/json'}},body:JSON.stringify({{request,agent}})}});
 const data=await r.json();document.querySelector('#message').textContent=data.error||'Task queued';if(r.ok)document.querySelector('#request').value='';refresh();}};
refresh();setInterval(refresh,1500);
</script></body></html>"""


def serve(workspace: Path, host: str = "127.0.0.1", port: int = 8765) -> None:
    if host not in {"127.0.0.1", "::1", "localhost"}:
        raise ValueError("The local control server may only bind to a loopback address.")
    token = secrets.token_urlsafe(32)
    manager = JobManager(workspace)
    server = ThreadingHTTPServer((host, port), make_handler(manager, token))
    print(f"Adaptive Orchestrator UI: http://{host}:{server.server_port}")
    print(f"Workspace: {workspace.resolve()}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        manager.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Loopback-only local Web UI and job queue.")
    parser.add_argument("--workspace", type=Path, default=Path.cwd())
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args(argv)
    workspace = args.workspace.expanduser().resolve()
    if not workspace.is_dir():
        parser.error(f"workspace is not a directory: {workspace}")
    try:
        serve(workspace, args.host, args.port)
    except ValueError as exc:
        parser.error(str(exc))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
