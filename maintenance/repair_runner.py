"""Receipt-backed local validation; never installs, fetches, pushes, or certifies."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import signal
import subprocess
import time
import uuid
from pathlib import Path


def digest(value):
    return hashlib.sha256(value).hexdigest()


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


def snapshot(repo):
    names = subprocess.check_output(
        ["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard"], cwd=repo,
    ).decode().split("\0")
    rows = []
    for name in sorted(set(names) - {""}):
        path = repo / name
        if path.is_symlink():
            rows.append([name, "symlink", os.readlink(path)])
        elif path.is_file():
            rows.append([name, "file", digest(path.read_bytes())])
        else:
            rows.append([name, "missing"])
    return digest(canonical(rows))


def write_json(path, data):
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(data, indent=2) + "\n")
    temporary.replace(path)


def fingerprints(repo, paths):
    return [[raw, digest((repo / raw).resolve().read_bytes())] for raw in paths]


def run_plan(repo, plan, output, resume=False):
    repo, output = Path(repo).resolve(), Path(output).resolve()
    if output == repo or repo in output.parents:
        raise ValueError("Receipt output must be outside the source checkout")
    gates = plan.get("gates", [])
    ids = [g["id"] for g in gates]
    if not gates or len(ids) != len(set(ids)):
        raise ValueError("Nonempty gates with unique IDs are required")
    for g in gates:
        if not isinstance(g["id"], str) or not g["id"].replace("-", "").replace("_", "").isalnum():
            raise ValueError("Invalid gate ID")
        if not isinstance(g.get("argv"), list) or not g["argv"] or not all(isinstance(x, str) for x in g["argv"]):
            raise ValueError("Each gate requires a nonempty argv list")
        cwd = (repo / g.get("cwd", ".")).resolve()
        if cwd != repo and repo not in cwd.parents:
            raise ValueError("Gate cwd must remain inside the checkout")
        if not isinstance(g.get("timeout", 600), (int, float)) or not 0 < g.get("timeout", 600) <= 7200:
            raise ValueError("Gate timeout must be positive and at most 7200 seconds")
    output.mkdir(parents=True, exist_ok=True)
    lock = output / "running.lock"
    fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    try:
        os.write(fd, str(os.getpid()).encode())
        source = snapshot(repo)
        # Hash environment without exposing credentials in receipts. Runtime/dependency
        # fingerprints must be declared by the plan, not inferred from a command name.
        probes = fingerprints(repo, plan.get("fingerprint_files", []))
        if not probes:
            raise ValueError("Runtime/dependency fingerprint files are required")
        binding = {"source": source, "plan": digest(canonical(plan)),
                   "environment": digest(canonical(dict(os.environ))), "probes": probes}
        binding_hash = digest(canonical(binding))
        results = []
        for gate in gates:
            prior_path = output / (gate["id"] + ".json")
            prior = json.loads(prior_path.read_text()) if resume and prior_path.exists() else None
            if snapshot(repo) != source or fingerprints(repo, plan["fingerprint_files"]) != probes:
                results.append({"id": gate["id"], "state": "BLOCKED", "reason": "SOURCE_OR_DEPENDENCY_DRIFT"})
                break
            if prior and prior.get("binding") == binding_hash and prior.get("state") == "PASS":
                log = output / prior["log"]
                if log.parent == output and log.is_file() and digest(log.read_bytes()) == prior.get("log_sha256"):
                    results.append({**prior, "reused": True})
                    continue
            attempt = gate["id"] + "-" + uuid.uuid4().hex
            log = output / (attempt + ".log")
            env = dict(os.environ)
            env["COVERAGE_FILE"] = str(output / (attempt + ".coverage"))
            started = time.time()
            timed_out = False
            with log.open("wb") as stream:
                try:
                    proc = subprocess.Popen(gate["argv"], cwd=repo / gate.get("cwd", "."),
                                            stdout=stream, stderr=subprocess.STDOUT,
                                            env=env, start_new_session=True)
                    try:
                        code = proc.wait(timeout=gate.get("timeout", 600))
                    except subprocess.TimeoutExpired:
                        timed_out = True
                        os.killpg(proc.pid, signal.SIGKILL)
                        code = proc.wait()
                    except BaseException:
                        if proc.poll() is None:
                            os.killpg(proc.pid, signal.SIGKILL)
                            proc.wait()
                        raise
                except OSError as exc:
                    stream.write(str(exc).encode())
                    code = 127
            drift = snapshot(repo) != source
            dependency_drift = fingerprints(repo, plan["fingerprint_files"]) != probes
            result = {"id": gate["id"], "binding": binding_hash,
                      "state": "PASS" if code == 0 and not drift and not dependency_drift else "FAIL",
                      "exit_code": code, "timed_out": timed_out, "source_drift": drift,
                      "dependency_drift": dependency_drift,
                      "elapsed_seconds": round(time.time() - started, 3),
                      "log": log.name, "log_sha256": digest(log.read_bytes()), "reused": False}
            write_json(output / (attempt + ".json"), result)
            write_json(prior_path, result)
            results.append(result)
            if drift or dependency_drift:
                break
        report = {"schema_version": "local-repair-receipt/1", "scope": str(repo),
                  "head": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=repo, text=True).strip(),
                  "binding": binding, "gate_count": len(gates), "results": results,
                  "local_status": "PASS" if len(results) == len(gates) and all(r["state"] == "PASS" for r in results) else "FAIL",
                  "program_status": "OPEN", "certified": False}
        write_json(output / "result.json", report)
        return report
    finally:
        os.close(fd)
        lock.unlink()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--resume", action="store_true")
    args = parser.parse_args()
    report = run_plan(args.repo, json.loads(args.plan.read_text()), args.output, args.resume)
    print(json.dumps({"local_status": report["local_status"], "program_status": report["program_status"], "gates": len(report["results"])}))
    return 0 if report["local_status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
