from __future__ import annotations

import os
from pathlib import Path
import subprocess
import tempfile

import pytest


EXECUTOR_BRANCH = "codex/phase0-sync-executor-v2"


def test_emit_phase0_sync_manifest() -> None:
    if os.environ.get("GITHUB_HEAD_REF") != EXECUTOR_BRANCH:
        pytest.skip("one-time Phase 0 artifact transport diagnostic")

    required = ["ACTIONS_RUNTIME_TOKEN", "ACTIONS_RESULTS_URL", "GITHUB_RUN_ID"]
    missing = [name for name in required if not os.environ.get(name)]
    assert not missing, f"missing Actions artifact environment: {missing}"

    with tempfile.TemporaryDirectory() as td:
        temp_root = Path(td)
        artifact_path = temp_root / "phase0_artifact_transport.txt"
        artifact_path.write_text("phase0 artifact transport ok\n")

        client_dir = temp_root / "artifact-client"
        client_dir.mkdir()
        subprocess.run(["npm", "init", "-y"], cwd=client_dir, check=True, capture_output=True)
        subprocess.run(
            ["npm", "install", "@actions/artifact@2.3.2"],
            cwd=client_dir,
            check=True,
            capture_output=True,
        )
        upload_script = client_dir / "upload.cjs"
        upload_script.write_text(
            '''const path = require("path");
const {DefaultArtifactClient} = require("@actions/artifact");
(async () => {
  const file = process.argv[2];
  const name = `phase0-artifact-transport-${process.env.GITHUB_RUN_ID}`;
  const client = new DefaultArtifactClient();
  const result = await client.uploadArtifact(name, [file], path.dirname(file), {retentionDays: 1});
  console.log(JSON.stringify(result));
})().catch(error => {
  console.error(error && error.stack ? error.stack : error);
  process.exit(1);
});
'''
        )
        subprocess.run(["node", str(upload_script), str(artifact_path)], cwd=client_dir, check=True)
