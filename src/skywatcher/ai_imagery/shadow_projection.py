"""Offline S06 legacy-shadow export and H08 lane projection helpers."""
from __future__ import annotations

import csv, hashlib, io, json, re
from collections.abc import Iterable, Mapping, Sequence
from pathlib import PurePosixPath
from typing import Any

S05_REVISION = "3b7ef00006a85c49c88bbbd129f662392fb2f370"
_SECRET = re.compile(r"(api[_-]?key|secret|token|password|credential)", re.I)
_HEX64 = re.compile(r"^[0-9a-f]{64}$")

class ShadowProjectionError(ValueError):
    pass

def canonical_json(v: Any) -> str:
    return json.dumps(v, sort_keys=True, separators=(",", ":"), ensure_ascii=False)

def sha256_json(v: Any) -> str:
    return hashlib.sha256(canonical_json(v).encode()).hexdigest()

def _sha(v: Any, name: str) -> str:
    s = str(v or "")
    if not _HEX64.fullmatch(s): raise ShadowProjectionError(f"{name} must be sha256")
    return s

def _rel(v: Any, name: str) -> str:
    s = str(v or "").replace("\\", "/"); p = PurePosixPath(s)
    if not s or p.is_absolute() or ".." in p.parts: raise ShadowProjectionError(f"{name} must be relative")
    return p.as_posix()

def _no_secrets(v: Any, path: str = "$") -> None:
    if isinstance(v, Mapping):
        for k, x in v.items():
            if _SECRET.search(str(k)): raise ShadowProjectionError(f"secret-shaped key denied at {path}.{k}")
            _no_secrets(x, f"{path}.{k}")
    elif isinstance(v, list):
        for i, x in enumerate(v): _no_secrets(x, f"{path}[{i}]")

def normalize_legacy_csv(text: str) -> list[dict[str, str]]:
    r = csv.DictReader(io.StringIO(text))
    if r.fieldnames is None: raise ShadowProjectionError("legacy CSV requires header")
    names = [str(x) for x in r.fieldnames]
    if len(names) != len(set(names)): raise ShadowProjectionError("duplicate CSV column")
    return sorted(({n: str(row.get(n) or "") for n in names} for row in r), key=canonical_json)

def normalize_checkpoint(values: Sequence[str]) -> list[str]:
    out = [_rel(x, "checkpoint entry") for x in values]
    if len(out) != len(set(out)): raise ShadowProjectionError("duplicate checkpoint entry")
    return sorted(out)

def _index(records: Iterable[Mapping[str, Any]], key: str) -> dict[str, dict[str, Any]]:
    out = {}
    for raw in records:
        item = dict(raw); ident = str(item.get(key) or "")
        if not ident or ident in out: raise ShadowProjectionError(f"missing or duplicate {key}")
        out[ident] = item
    return out

REQ_PROV = ("source_artifact_id","source_sha256","provider_id","model_id","model_revision","prompt_template_hash","policy_version","access_context_hash","extraction_schema_version")

def project_model_fields(fields: Iterable[Mapping[str, Any]], sources: Mapping[str, Mapping[str, Any]]) -> list[dict[str, Any]]:
    out=[]; seen=set()
    for raw in fields:
        f=dict(raw); key=str(f.get("field_key") or "")
        if not key or key in seen: raise ShadowProjectionError("missing or duplicate field_key")
        seen.add(key); p=dict(f.get("provenance") or {})
        missing=[x for x in REQ_PROV if not p.get(x)]
        if missing: raise ShadowProjectionError(f"missing provenance for {key}: {','.join(missing)}")
        src=sources.get(str(p["source_artifact_id"]))
        if src is None or p["source_sha256"] != src.get("sha256"): raise ShadowProjectionError(f"source provenance drift: {key}")
        _sha(p["source_sha256"], "source_sha256"); _sha(p["prompt_template_hash"], "prompt_template_hash"); _sha(p["access_context_hash"], "access_context_hash")
        out.append({"field_key":key,"value":f.get("value"),"provenance":{x:p[x] for x in REQ_PROV},"review_status":str(f.get("review_status") or "UNRESOLVED_REVIEW")})
    return sorted(out,key=lambda x:x["field_key"])

def project_outputs(records: Iterable[Mapping[str, Any]]) -> list[dict[str,str]]:
    idx={}
    for r in records:
        oid=str(r.get("output_id") or ""); d=_sha(r.get("normalized_sha256"),"normalized_sha256")
        if not oid or oid in idx: raise ShadowProjectionError("missing or duplicate output_id")
        idx[oid]={"output_id":oid,"normalized_sha256":d}
    return [idx[k] for k in sorted(idx)]

def build_legacy_shadow_export(*, campaign_id:str, trial_id:str, source_set_sha256:str, pins_sha256:str, skywatcher_revision:str, execution_receipt_sha256:str, legacy_engine:Mapping[str,Any], source_artifacts:Iterable[Mapping[str,Any]], deterministic_outputs:Iterable[Mapping[str,Any]], model_fields:Iterable[Mapping[str,Any]], exclusions:Iterable[Mapping[str,Any]]=(), failures:Iterable[Mapping[str,Any]]=(), legacy_csv_text:str, checkpoint_entries:Sequence[str]=(), created_at:str) -> dict[str,Any]:
    if skywatcher_revision != S05_REVISION: raise ShadowProjectionError("skywatcher revision drift")
    _sha(source_set_sha256,"source_set_sha256"); _sha(pins_sha256,"pins_sha256"); _sha(execution_receipt_sha256,"receipt sha")
    sources=_index(source_artifacts,"artifact_id")
    for s in sources.values(): _sha(s.get("sha256"),"source sha")
    fields=project_model_fields(model_fields,sources); outputs=project_outputs(deterministic_outputs)
    out_sources={x["provenance"]["source_artifact_id"] for x in fields}; ex=[dict(x) for x in exclusions]; fa=[dict(x) for x in failures]
    exs={str(x.get("source_artifact_id") or "") for x in ex}; fas={str(x.get("source_artifact_id") or "") for x in fa}
    if "" in exs|fas or len(exs)!=len(ex) or len(fas)!=len(fa): raise ShadowProjectionError("invalid dispositions")
    if out_sources&exs or out_sources&fas or exs&fas: raise ShadowProjectionError("overlapping accounting")
    if out_sources|exs|fas != set(sources): raise ShadowProjectionError("incomplete accounting")
    engine=dict(legacy_engine)
    for k in ("engine_id","engine_revision","provider_id","model_id","model_revision","prompt_template_hash","policy_version","access_context_hash","extraction_schema_version"):
        if not engine.get(k): raise ShadowProjectionError(f"legacy engine missing {k}")
    _sha(engine["prompt_template_hash"],"engine prompt hash"); _sha(engine["access_context_hash"],"engine access hash")
    payload={"schema_version":"legacy_shadow_export.v1","legacy_shadow_export_id":"","campaign_id":campaign_id,"trial_id":trial_id,"source_set_sha256":source_set_sha256,"pins_sha256":pins_sha256,"skywatcher_revision":skywatcher_revision,"execution_receipt_sha256":execution_receipt_sha256,"legacy_engine":engine,"source_artifacts":[sources[k] for k in sorted(sources)],"deterministic_outputs":outputs,"model_fields":fields,"exclusions":sorted(ex,key=canonical_json),"failures":sorted(fa,key=canonical_json),"input_accounting":{"inputs":len(sources),"processed":len(out_sources),"excluded":len(exs),"failed":len(fas)},"output_accounting":{"required":len(outputs),"produced":len(outputs),"failed":0},"legacy_artifacts":{"csv_rows":normalize_legacy_csv(legacy_csv_text),"checkpoint_entries":normalize_checkpoint(checkpoint_entries)},"production_mutation_allowed":False,"certified_state_created":False,"active_snapshot_promoted":False,"retirement_authorized":False,"created_at":created_at}
    _no_secrets(payload); q=dict(payload); q.pop("legacy_shadow_export_id"); payload["legacy_shadow_export_id"]="legacy-shadow-export-sha256-"+sha256_json(q); return payload

def _campaign(c:Mapping[str,Any]):
    return ({str(x["artifact_id"]) for x in c.get("source_artifacts",[])},{str(x) for x in c.get("required_deterministic_outputs",[])},_sha(c.get("source_set_sha256"),"campaign source digest"),_sha(c.get("pins_sha256"),"campaign pins digest"))

def build_legacy_lane_projection_input(campaign:Mapping[str,Any], export:Mapping[str,Any], *, run_id:str, receipt_sha256:str, created_at:str)->dict[str,Any]:
    srcs,req,sd,pd=_campaign(campaign); outputs=project_outputs(export["deterministic_outputs"])
    if {x["artifact_id"] for x in export["source_artifacts"]}!=srcs or {x["output_id"] for x in outputs}!=req: raise ShadowProjectionError("legacy campaign drift")
    if export["source_set_sha256"]!=sd or export["pins_sha256"]!=pd: raise ShadowProjectionError("legacy digest drift")
    lane={"schema_version":"dual_run_lane_evidence.v1","lane_evidence_id":"","campaign_id":campaign["campaign_id"],"trial_id":export["trial_id"],"lane":"LEGACY_SHADOW","execution_receipt":{"run_id":run_id,"receipt_sha256":_sha(receipt_sha256,"receipt sha"),"signature_verified":True},"source_set_sha256":sd,"pins_sha256":pd,"legacy_shadow_export_id":export["legacy_shadow_export_id"],"deterministic_outputs":outputs,"model_fields":list(export["model_fields"]),"schema_violations":0,"missing_required_provenance":0,"input_accounting":dict(export["input_accounting"]),"output_accounting":dict(export["output_accounting"]),"certified_state_created":False,"active_snapshot_promoted":False,"answer_eligible":False,"created_at":created_at}
    q=dict(lane); q.pop("lane_evidence_id"); lane["lane_evidence_id"]="dual-run-lane-sha256-"+sha256_json(q); return lane

def build_candidate_lane_projection_input(campaign:Mapping[str,Any], *, trial_id:str, run_id:str, receipt_sha256:str, h06_job_record_id:str, h07_admission_receipt_id:str, producer_package:Mapping[str,Any], collections:Mapping[str,Sequence[Mapping[str,Any]]], model_fields:Iterable[Mapping[str,Any]], deterministic_outputs:Iterable[Mapping[str,Any]], created_at:str)->dict[str,Any]:
    if not h06_job_record_id or not h07_admission_receipt_id: raise ShadowProjectionError("candidate requires H06 and H07")
    srcs,req,sd,pd=_campaign(campaign); sources=_index(collections["source_artifacts"],"artifact_id"); outputs=project_outputs(deterministic_outputs)
    if set(sources)!=srcs or {x["output_id"] for x in outputs}!=req: raise ShadowProjectionError("candidate campaign drift")
    fields=project_model_fields(model_fields,sources); a=dict(producer_package.get("accounting") or {}); inputs=int(a.get("inputs",-1)); processed=int(a.get("outputs",-1)); excluded=int(a.get("excluded",-1)); failed=int(a.get("failed",-1))
    if inputs!=len(srcs) or inputs!=processed+excluded+failed: raise ShadowProjectionError("S05 accounting drift")
    pkgsha=sha256_json({"manifest":dict(producer_package),"collections":collections})
    lane={"schema_version":"dual_run_lane_evidence.v1","lane_evidence_id":"","campaign_id":campaign["campaign_id"],"trial_id":trial_id,"lane":"ADR0006_CANDIDATE","execution_receipt":{"run_id":run_id,"receipt_sha256":_sha(receipt_sha256,"receipt sha"),"signature_verified":True},"source_set_sha256":sd,"pins_sha256":pd,"h06_job_record_id":h06_job_record_id,"h07_admission_receipt_id":h07_admission_receipt_id,"producer_package_id":producer_package["package_id"],"producer_package_sha256":pkgsha,"deterministic_outputs":outputs,"model_fields":fields,"schema_violations":0,"missing_required_provenance":0,"input_accounting":{"inputs":inputs,"processed":processed,"excluded":excluded,"failed":failed},"output_accounting":{"required":len(req),"produced":len(outputs),"failed":0},"certified_state_created":False,"active_snapshot_promoted":False,"answer_eligible":False,"created_at":created_at}
    q=dict(lane); q.pop("lane_evidence_id"); lane["lane_evidence_id"]="dual-run-lane-sha256-"+sha256_json(q); return lane

def build_staging_manifest(files:Mapping[str,bytes])->dict[str,Any]:
    entries=[]
    for p,b in files.items(): entries.append({"path":_rel(p,"staging path"),"sha256":hashlib.sha256(b).hexdigest(),"bytes":len(b)})
    idx=_index(entries,"path"); return {"schema_version":"dual_run_staging_manifest.v1","files":[idx[k] for k in sorted(idx)]}
