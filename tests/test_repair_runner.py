import json
import subprocess
import sys

import pytest

from maintenance.repair_runner import run_plan


@pytest.fixture
def project(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "source.txt").write_text("original")
    (repo / ".gitignore").write_text("generated.txt\n")
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    subprocess.run(["git", "add", "."], cwd=repo, check=True)
    subprocess.run(["git", "-c", "user.name=Test", "-c", "user.email=test@example.invalid",
                    "commit", "-qm", "fixture"], cwd=repo, check=True)
    plan = {"fingerprint_files": ["source.txt", sys.executable],
            "gates": [{"id": "check", "argv": [sys.executable, "-c", "print('verified')"]}]}
    return repo, plan, tmp_path / "receipts"


def test_reuses_only_matching_pass_and_intact_log(project):
    repo, plan, output = project
    first = run_plan(repo, plan, output)
    assert first["local_status"] == "PASS" and first["certified"] is False
    second = run_plan(repo, plan, output, resume=True)
    assert second["results"][0]["reused"]
    (output / first["results"][0]["log"]).write_text("tampered")
    third = run_plan(repo, plan, output, resume=True)
    assert not third["results"][0]["reused"]
    assert third["results"][0]["log"] != first["results"][0]["log"]


def test_environment_plan_source_and_probe_drift_invalidate(project, monkeypatch):
    repo, plan, output = project
    probe = repo / "generated.txt"
    probe.write_text("dependency-v1")
    plan["fingerprint_files"].append("generated.txt")
    run_plan(repo, plan, output)
    for mutate in [lambda: monkeypatch.setenv("REPAIR_TEST_VARIATION", "changed"),
                   lambda: (repo / "source.txt").write_text("changed"),
                   lambda: probe.write_text("dependency-v2"),
                   lambda: plan["gates"][0]["argv"].append("argument")]:
        mutate()
        assert not run_plan(repo, plan, output, resume=True)["results"][0]["reused"]


def test_failure_is_not_reused_and_other_gate_runs(project):
    repo, plan, output = project
    plan["gates"].append({"id": "bad", "argv": [sys.executable, "-c", "raise SystemExit(3)"]})
    first = run_plan(repo, plan, output)
    assert first["local_status"] == "FAIL"
    second = run_plan(repo, plan, output, resume=True)
    assert second["results"][0]["reused"]
    assert not second["results"][1]["reused"]
    assert second["results"][1]["exit_code"] == 3


def test_source_mutation_fails_closed_and_stops_following_gate(project):
    repo, plan, output = project
    plan["gates"][0]["argv"] = [sys.executable, "-c", "from pathlib import Path; Path('source.txt').write_text('changed')"]
    plan["gates"].append({"id": "later", "argv": [sys.executable, "-c", "print('must not run')"]})
    result = run_plan(repo, plan, output)
    assert result["local_status"] == "FAIL"
    assert result["results"][0]["source_drift"]
    assert len(result["results"]) == 1


def test_timeout_missing_command_and_lock(project):
    repo, plan, output = project
    plan["gates"] = [{"id": "slow", "argv": [sys.executable, "-c", "import time; time.sleep(20)"], "timeout": 0.05},
                     {"id": "absent", "argv": ["/nonexistent/repair-test-command"]}]
    result = run_plan(repo, plan, output)
    assert result["results"][0]["timed_out"]
    assert result["results"][1]["exit_code"] == 127
    (output / "running.lock").write_text("another-owner")
    with pytest.raises(FileExistsError):
        run_plan(repo, plan, output)
    assert (output / "running.lock").read_text() == "another-owner"


def test_dependency_changed_during_successful_gate_fails(project):
    repo, plan, output = project
    (repo / "generated.txt").write_text("v1")
    plan["fingerprint_files"].append("generated.txt")
    plan["gates"][0]["argv"] = [sys.executable, "-c", "from pathlib import Path; Path('generated.txt').write_text('v2')"]
    result = run_plan(repo, plan, output)
    assert result["local_status"] == "FAIL"
    assert result["results"][0]["exit_code"] == 0
    assert result["results"][0]["dependency_drift"]


def test_invalid_plan_or_output_rejected_before_execution(project):
    repo, plan, output = project
    with pytest.raises(ValueError):
        run_plan(repo, plan, repo / "receipts")
    plan["gates"].append(dict(plan["gates"][0]))
    with pytest.raises(ValueError):
        run_plan(repo, plan, output)
    plan["gates"].pop()
    plan["gates"][0]["cwd"] = ".."
    with pytest.raises(ValueError):
        run_plan(repo, plan, output)
    assert not output.exists()


def test_receipt_is_machine_readable(project):
    repo, plan, output = project
    result = run_plan(repo, plan, output)
    assert json.loads((output / "result.json").read_text()) == result
