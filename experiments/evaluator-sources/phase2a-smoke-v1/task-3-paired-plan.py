from __future__ import annotations

import contextlib
import io
import json
import sys
import tempfile
from pathlib import Path

workspace = Path.cwd()
sys.path.insert(0, str(workspace / "src"))
sys.path.insert(0, str(Path(__file__).parent))

from adaptive_orchestrator import cli
from common import manifest_dict


with tempfile.TemporaryDirectory() as directory:
    root = Path(directory)
    manifest_path = root / "manifest.json"
    manifest_path.write_text(json.dumps(manifest_dict()))
    workspace_root = root / "planned-workspaces"

    outputs = []
    for _ in range(2):
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            exit_code = cli.main([
                "paired", "plan", str(manifest_path),
                "--workspace-root", str(workspace_root),
            ])
        assert exit_code == 0
        outputs.append(json.loads(stdout.getvalue()))

    assert outputs[0] == outputs[1]
    report = outputs[0]
    assert report["agent_execution_started"] is False
    assert report["workspace_creation_started"] is False
    assert len(report["assignments"]) == 4
    assert len(report["workspaces"]) == 8
    assert len({item["path"] for item in report["workspaces"]}) == 8
    assert not workspace_root.exists()
