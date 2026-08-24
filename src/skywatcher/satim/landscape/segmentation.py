"""Validation helpers for provisional image-pixel field segmentation fixtures."""
from __future__ import annotations
import json
from pathlib import Path
from typing import Any


def _orient(a,b,c):
    return (b[0]-a[0])*(c[1]-a[1])-(b[1]-a[1])*(c[0]-a[0])


def _proper_segment_intersection(a,b,c,d):
    o1,o2,o3,o4=_orient(a,b,c),_orient(a,b,d),_orient(c,d,a),_orient(c,d,b)
    return ((o1>0)!=(o2>0)) and ((o3>0)!=(o4>0))


def _point_in_polygon_strict(p, poly):
    x,y=p; inside=False
    n=len(poly)
    for i in range(n):
        a=poly[i]; b=poly[(i+1)%n]
        if _orient(a,b,p)==0 and min(a[0],b[0])<=x<=max(a[0],b[0]) and min(a[1],b[1])<=y<=max(a[1],b[1]):
            return False
        if (a[1]>y)!=(b[1]>y):
            xint=(b[0]-a[0])*(y-a[1])/(b[1]-a[1])+a[0]
            if x < xint: inside=not inside
    return inside


def _polygon_interiors_overlap(a,b):
    for i in range(len(a)):
        for j in range(len(b)):
            if _proper_segment_intersection(a[i],a[(i+1)%len(a)],b[j],b[(j+1)%len(b)]):
                return True
    return any(_point_in_polygon_strict(p,b) for p in a) or any(_point_in_polygon_strict(p,a) for p in b)


def validate_segmentation(path: str | Path, *, expected_sha256: str, expected_width: int, expected_height: int) -> dict[str, Any]:
    raw=json.loads(Path(path).read_text(encoding="utf-8")); blockers=[]
    if raw.get("schema_version") != "satim.landscape.segmentation.v0.1": blockers.append("unsupported segmentation schema")
    if raw.get("fixture_id") != "SATIM-LANDSCAPE-C654-001": blockers.append("unexpected fixture_id")
    image=raw.get("image") or {}
    if image.get("sha256") != expected_sha256: blockers.append("segmentation raw SHA256 mismatch")
    if image.get("width_px") != expected_width or image.get("height_px") != expected_height: blockers.append("segmentation image dimensions mismatch")
    if raw.get("coordinate_system") != "IMAGE_PIXEL_XY_ORIGIN_TOP_LEFT": blockers.append("unexpected coordinate system")
    features=list(raw.get("features") or []); ids=[]; fields=[]
    for f in features:
        fid=str(f.get("id") or ""); ids.append(fid)
        p=f.get("properties") or {}; geom=f.get("geometry") or {}; coords=(geom.get("coordinates") or [[]])[0]
        if geom.get("type")!="Polygon" or len(coords)<4: blockers.append(f"invalid polygon {fid}"); continue
        if coords[0]!=coords[-1]: blockers.append(f"polygon not closed {fid}")
        for point in coords:
            if len(point)!=2: blockers.append(f"invalid coordinate arity {fid}"); continue
            x,y=point
            if not (0 <= x < expected_width and 0 <= y < expected_height): blockers.append(f"coordinate out of bounds {fid}")
        if p.get("class")=="CULTIVATED_FIELD": fields.append((fid,coords[:-1]))
    if any(not fid for fid in ids): blockers.append("segmentation feature without id")
    if len(ids)!=len(set(ids)): blockers.append("segmentation feature id uniqueness failed")
    if len(fields)!=7: blockers.append(f"expected 7 CULTIVATED_FIELD instances, found {len(fields)}")
    overlaps=[]
    for i,(aid,ap) in enumerate(fields):
        for bid,bp in fields[i+1:]:
            if _polygon_interiors_overlap(ap,bp): overlaps.append((aid,bid))
    if overlaps: blockers.append("field polygon interiors overlap: "+repr(overlaps))
    return {
        "status":"PASS" if not blockers else "FAIL",
        "field_instance_count":len(fields), "feature_count":len(features), "blockers":blockers,
        "annotation_status":raw.get("annotation_status"),
        "segmentation_completeness":raw.get("segmentation_completeness"),
        "known_omissions":list(raw.get("known_omissions") or ()),
    }
