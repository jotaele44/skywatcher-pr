#!/usr/bin/env python3
from __future__ import annotations
import argparse, hashlib, json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
CONTRACT=ROOT/"config"/"flight_corpus_v4.json"

def sha256(p:Path)->str:
    h=hashlib.sha256()
    with p.open("rb") as f:
        for c in iter(lambda:f.read(1024*1024),b""): h.update(c)
    return h.hexdigest()

def main()->int:
    ap=argparse.ArgumentParser()
    ap.add_argument("manifest",type=Path)
    ns=ap.parse_args()
    m=json.loads(ns.manifest.read_text())
    c=json.loads(CONTRACT.read_text())
    assert m["schema_version"]=="skywatcher.flight_corpus.import.v1"
    assert m["corpus_version"]=="V4"
    d=m["denominators"]; cd=c["denominators"]
    for k in ("nonempty_logical_records","single_point_exclusions","trajectory_eligible","unordered_pair_denominator"):
        assert d[k]==cd[k],f"denominator mismatch: {k}"
    assert d["trajectory_eligible"]==d["nonempty_logical_records"]-d["single_point_exclusions"]
    assert d["unordered_pair_denominator"]==d["trajectory_eligible"]*(d["trajectory_eligible"]-1)//2
    ids=set(); paths=set()
    for row in m["datasets"]:
        assert row["dataset_id"] not in ids,"duplicate dataset_id"
        assert row["path"] not in paths,"duplicate dataset path"
        ids.add(row["dataset_id"]); paths.add(row["path"])
        p=(ns.manifest.parent/row["path"]).resolve()
        assert p.is_file(),f"missing dataset: {row['path']}"
        assert sha256(p)==row["sha256"],f"hash mismatch: {row['path']}"
    required=set(c["blocked"])
    assert required.issubset(set(m["blocked"])),"V4 blocker silently removed"
    print("FLIGHT_CORPUS_V4_IMPORT=PASS")
    print(f"DATASETS={len(m['datasets'])}")
    return 0

if __name__=="__main__": raise SystemExit(main())
