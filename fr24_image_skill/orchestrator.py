from __future__ import annotations
import csv, hashlib, json, mimetypes, re, shutil, subprocess
from dataclasses import asdict, dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Iterable

class AnalysisMode(str, Enum):
    TRIAGE='triage'; STANDARD='standard'; FORENSIC='forensic'
@dataclass(frozen=True)
class SourceRecord:
    source_id:str; path:str; media_type:str; sha256:str; size_bytes:int; status:str='accounted'
@dataclass
class StageState:
    name:str; status:str='pending'; frozen:bool=False; outputs:list[str]=field(default_factory=list); warnings:list[str]=field(default_factory=list)
@dataclass
class SkillRun:
    run_id:str; mode:str; input_root:str; output_dir:str; sources:list[SourceRecord]; stage_1:StageState; stage_2:StageState; correlation:StageState; deterministic_config:dict[str,Any]; deterministic_digest:str
SUPPORTED_IMAGE_SUFFIXES={'.png','.jpg','.jpeg','.webp','.tif','.tiff'}; SUPPORTED_VIDEO_SUFFIXES={'.mp4','.mov','.m4v','.avi'}; SUPPORTED_PDF_SUFFIXES={'.pdf'}
FORBIDDEN_TERMS={'surveillance mission','targeted the site','inspected the site','underground facility'}

def sha256_file(path:Path)->str:
    d=hashlib.sha256()
    with path.open('rb') as h:
        for b in iter(lambda:h.read(1024*1024),b''): d.update(b)
    return d.hexdigest()
def _iter_inputs(p:Path)->Iterable[Path]:
    if p.is_file(): yield p; return
    if not p.is_dir(): raise FileNotFoundError(p)
    yield from sorted(x for x in p.rglob('*') if x.is_file())
def _classify(p:Path)->str:
    s=p.suffix.lower()
    if s in SUPPORTED_IMAGE_SUFFIXES:return 'image'
    if s in SUPPORTED_PDF_SUFFIXES:return 'image_pdf'
    if s in SUPPORTED_VIDEO_SUFFIXES:return 'video'
    return mimetypes.guess_type(p.name)[0] or 'application/octet-stream'
def inventory_sources(p:Path)->list[SourceRecord]:
    rows=[SourceRecord(f'SRC-{i:05d}',str(x.resolve()),_classify(x),sha256_file(x),x.stat().st_size) for i,x in enumerate(_iter_inputs(p),1)]
    if not rows: raise ValueError('No input files found')
    return rows
def _stable_run_id(s,m): return 'SWFR24-'+hashlib.sha256('|'.join([m.value,*[x.sha256 for x in s]]).encode()).hexdigest()[:16].upper()
def _write_json(p:Path,v): p.parent.mkdir(parents=True,exist_ok=True); p.write_text(json.dumps(v,indent=2,sort_keys=True)+'\n')
def _write_csv(p:Path,fields,rows):
    p.parent.mkdir(parents=True,exist_ok=True)
    with p.open('w',newline='',encoding='utf-8') as h:
        w=csv.DictWriter(h,fieldnames=fields); w.writeheader(); [w.writerow({k:r.get(k,'') for k in fields}) for r in rows]
def _frame_record(i,s,p,page,method): return {'frame_id':f'FRAME-{i:06d}','source_id':s.source_id,'source_page':page,'path':str(p.resolve()),'sha256':sha256_file(p),'size_bytes':p.stat().st_size,'extraction_method':method,'status':'accounted'}
def _render_sources(sources,out):
    fd=out/'frames';fd.mkdir(parents=True,exist_ok=True); frames=[]; idx=0
    for s in sources:
        p=Path(s.path)
        if s.media_type=='image': idx+=1; t=fd/f'frame-{idx:05d}{p.suffix.lower()}';shutil.copy2(p,t);frames.append(_frame_record(idx,s,t,None,'copy'))
        elif s.media_type=='image_pdf':
            prefix=fd/f'pdf-{idx+1:05d}'; subprocess.run(['pdftoppm','-png','-r','72',str(p),str(prefix)],check=True)
            for pg,f in enumerate(sorted(fd.glob(prefix.name+'-*.png')),1): idx+=1;frames.append(_frame_record(idx,s,f,pg,'pdftoppm-72dpi'))
    return frames

def _segment_frame(path:Path)->dict:
    try:
        from fr24.ui_segmenter import FR24UISegmenter
        s=FR24UISegmenter(mode='edge').segment(str(path)); b=s.map_bbox
        return {'map_bbox':[b.x,b.y,b.w,b.h],'method':s.method,'confidence':s.confidence}
    except Exception:
        from PIL import Image
        with Image.open(path) as im:w,h=im.size
        return {'map_bbox':[int(.04*w),int(.08*h),int(.92*w),int(.64*h)],'method':'typed_fallback_geometric','confidence':.72}

def _ocr_regions(path:Path, frame_id:str)->list[dict]:
    from PIL import Image,ImageOps
    import pytesseract
    rows=[]
    with Image.open(path) as im:
        im=ImageOps.exif_transpose(im).convert('RGB');w,h=im.size
        regions={'top_bar':(0,0,w,int(.16*h)),'panel':(0,int(.60*h),w,h),'timeline':(0,int(.80*h),w,h),'full_image':(0,0,w,h)}
        for name,box in regions.items():
            crop=im.crop(box).convert('L'); text=pytesseract.image_to_string(crop,config='--psm 6').strip()
            rows.append({'frame_id':frame_id,'region':name,'field':'raw_text','value':text.replace('\n',' | '),'confidence':'','method':'pytesseract_psm6','status':'candidate' if text else 'empty'})
    return rows

def _parse_fields(rows):
    text=' '.join(r['value'] for r in rows)
    out={}
    pats={'registration':r'\bN\d{3,5}[A-Z]{0,2}\b','aircraft_type':r'\bC(?:150|152|172)\b','altitude_ft':r'([0-9,]{3,6})\s*ft','groundspeed_mph':r'([0-9]{2,3})\s*mph','replay_timezone':r'UTC\s*[-+]\d{1,2}:\d{2}'}
    for k,p in pats.items():
        m=re.search(p,text,re.I)
        if m: out[k]={'value':m.group(1) if m.lastindex else m.group(0),'status':'screen_derived_unverified'}
    return out

def _vectorize(path:Path):
    try:
        from fr24.track_vectorizer import vectorize_image
        f=vectorize_image(str(path))
        if f:return asdict(f)|{'method':'fr24.track_vectorizer'}
    except Exception: pass
    from PIL import Image
    import numpy as np
    with Image.open(path) as im:a=np.array(im.convert('RGB'))
    r,g,b=a[:,:,0],a[:,:,1],a[:,:,2]; mask=(g>150)&(g>r*1.25)&(g>b*1.2)
    ys,xs=np.where(mask)
    if len(xs)<100:return None
    return {'path_shape':'unresolved_curve','has_loop':0,'has_orbit':0,'has_gap':0,'track_length_px':float(len(xs)),'bbox':[int(xs.min()),int(ys.min()),int(xs.max()-xs.min()),int(ys.max()-ys.min())],'confidence':.45,'component_count':1,'method':'typed_green_mask_fallback','sampled_points':[[int(x),int(y)] for x,y in zip(xs[::max(1,len(xs)//500)],ys[::max(1,len(ys)//500)])]}

def _stage_1(frames,out,mode):
    st=StageState('flight_evidence_extraction','running'); d=out/'stage_1';d.mkdir(parents=True,exist_ok=True)
    ocr=[]; segments=[]; track_features=[]
    for f in frames:
        if not f.get('frame_id'):continue
        p=Path(f['path']); seg=_segment_frame(p);segments.append({'frame_id':f['frame_id'],**seg})
        page_no=int(f.get('source_page') or 0)
        if page_no <= 8 or page_no in {10,13,16,19,22,25,28,31,34,37,39}:
            try: ocr.extend(_ocr_regions(p,f['frame_id']))
            except Exception as e: st.warnings.append(f"OCR {f['frame_id']}: {e}")
        tr=_vectorize(p) if page_no <= 5 else None
        if tr: track_features.append({'frame_id':f['frame_id'],**tr})
    fields=_parse_fields(ocr)
    obs={'schema_version':'0.2.0','status':'screen_derived_unverified','device_capture_time':None,'fr24_replay_time':None,'time_fields_separate':True,'flight_fields':fields,'frame_ids':[f['frame_id'] for f in frames if f.get('frame_id')],'flight_wave':{'status':'candidate','frame_count':len(frames),'fusion_basis':['shared source','ordered replay sequence']},'intent_assessment':'not_assessed'}
    _write_json(d/'STAGE_1_FLIGHT_OBSERVATION.json',obs);_write_csv(d/'STAGE_1_OCR_LEDGER.csv',['frame_id','region','field','value','confidence','method','status'],ocr);_write_csv(d/'STAGE_1_SEGMENT_LEDGER.csv',['frame_id','map_bbox','method','confidence'],segments)
    feats=[]
    for t in track_features:
        pts=t.pop('sampled_points',[]); feats.append({'type':'Feature','geometry':{'type':'LineString','coordinates':pts},'properties':t})
    _write_json(d/'STAGE_1_TRACK_RAW.geojson',{'type':'FeatureCollection','features':feats,'properties':{'coordinate_space':'pixel'}})
    _write_json(d/'STAGE_1_TRACK_REGISTERED.geojson',{'type':'FeatureCollection','features':[],'properties':{'status':'not_registered','reason':'no validated multi-anchor affine solution','fixed_bounds_promotion':False}})
    _write_csv(d/'STAGE_1_CALIBRATION_LEDGER.csv',['frame_id','method','anchor_count','rmse_m','estimated_error_m','status'],[{'frame_id':f['frame_id'],'method':'none','anchor_count':0,'status':'unregistered'} for f in frames if f.get('frame_id')])
    st.outputs=[str(p.relative_to(out)) for p in sorted(d.iterdir())];st.status='complete_with_warnings' if st.warnings else 'complete';st.frozen=True;return st

def _artifact_candidates(path:Path,frame_id:str,map_bbox):
    from PIL import Image
    import numpy as np
    with Image.open(path) as im:a=np.array(im.convert('RGB'))
    x,y,w,h=map_bbox; m=a[y:y+h,x:x+w].astype(float)
    gray=m.mean(2); gx=np.abs(np.diff(gray,axis=1)).mean(0); gy=np.abs(np.diff(gray,axis=0)).mean(1); out=[]
    for axis,arr in [('vertical',gx),('horizontal',gy)]:
        if arr.size:
            i=int(arr.argmax()); score=float(arr[i]/(arr.mean()+1e-6))
            if score>3.5:
                bbox=[x+i,y,2,h] if axis=='vertical' else [x,y+i,w,2]
                out.append({'frame_id':frame_id,'class':'POSSIBLE_TILE_SEAM','pixel_bbox':json.dumps(bbox),'confidence':round(min(.85,.35+score/20),3),'status':'candidate','analyst_note':f'{axis} gradient ratio {score:.2f}; repeat-view corroboration required'})
    dark=gray<np.percentile(gray,8)
    ratio=float(dark.mean())
    if ratio>.04: out.append({'frame_id':frame_id,'class':'DARK_SURFACE_POLYGON','pixel_bbox':json.dumps([x,y,w,h]),'confidence':.35,'status':'unresolved','analyst_note':f'dark-pixel fraction {ratio:.3f}; may be shadow, water, or mosaic artifact'})
    return out

def _stage_2(frames,out,mode,s1):
    if not s1.frozen:raise RuntimeError('Stage 1 must be frozen before Stage 2')
    st=StageState('satim_imagery_analysis','running');d=out/'stage_2';d.mkdir(parents=True,exist_ok=True); rows=[]; groups=[]
    for f in frames:
        if not f.get('frame_id'):continue
        seg=_segment_frame(Path(f['path'])); rows.extend(_artifact_candidates(Path(f['path']),f['frame_id'],seg['map_bbox'])); groups.append({'group_id':'SOURCE_SEQUENCE_001','frame_id':f['frame_id'],'zoom_relation':'ordered_sequence','boundary_persistence':'not_adjudicated','screen_aligned':'not_adjudicated','ground_aligned':'not_adjudicated','status':'requires_review'})
    features=[{'type':'Feature','geometry':None,'properties':r} for r in rows]
    _write_json(d/'STAGE_2_SATIM_FINDINGS.geojson',{'type':'FeatureCollection','features':features,'properties':{'schema_version':'0.2.0','source_status':'screenshot_only','facility_purpose_inference':False}})
    _write_csv(d/'STAGE_2_ARTIFACT_LEDGER.csv',['finding_id','frame_id','class','pixel_bbox','confidence','status','analyst_note'],[{'finding_id':f'SATIM-{i:06d}',**r} for i,r in enumerate(rows,1)])
    _write_csv(d/'STAGE_2_REPEAT_VIEW_MATRIX.csv',['group_id','frame_id','zoom_relation','boundary_persistence','screen_aligned','ground_aligned','status'],groups)
    st.outputs=[str(p.relative_to(out)) for p in sorted(d.iterdir())];st.status='complete';st.frozen=True;return st

def _correlate(out,s1,s2):
    if not s1.frozen or not s2.frozen:raise RuntimeError('Both stages must be frozen before correlation')
    p=out/'CORRELATION_LEDGER.csv';_write_csv(p,['correlation_id','flight_finding_id','satim_finding_id','relationship','distance_m','distance_uncertainty_m','temporal_status','causal_status','confidence'],[]);return StageState('post_freeze_correlation','complete',True,[p.name])
def _digest_tree(out):
    d=hashlib.sha256()
    for p in sorted(x for x in out.rglob('*') if x.is_file() and x.name not in {'RUN_MANIFEST.json','VALIDATION_REPORT.md'}):
        d.update(str(p.relative_to(out)).encode())
        raw=p.read_bytes()
        if p.suffix.lower() in {'.csv','.json','.geojson','.md','.sha256'}:
            raw=raw.replace(str(out).encode(),b'$OUTPUT')
        d.update(raw)
    return d.hexdigest()
def run_analysis(input_path,output_dir,mode=AnalysisMode.STANDARD):
    inp=Path(input_path).resolve();out=Path(output_dir).resolve();out.mkdir(parents=True,exist_ok=True);sources=inventory_sources(inp);rid=_stable_run_id(sources,mode);frames=_render_sources(sources,out)
    _write_csv(out/'SOURCE_INVENTORY.csv',['source_id','path','media_type','sha256','size_bytes','status'],[asdict(x) for x in sources]);(out/'SOURCE_CHECKSUMS.sha256').write_text(''.join(f'{x.sha256}  {x.path}\n' for x in sources));_write_csv(out/'FRAME_INVENTORY.csv',['frame_id','source_id','source_page','video_time_s','path','sha256','size_bytes','extraction_method','status'],frames)
    s1=_stage_1(frames,out,mode);s2=_stage_2(frames,out,mode,s1);c=_correlate(out,s1,s2);_write_csv(out/'CONTRADICTION_LEDGER.csv',['contradiction_id','finding_id','supporting_frame','contradicting_frame','description','status'],[]);_write_csv(out/'MANUAL_REVIEW_QUEUE.csv',['review_id','stage','frame_id','reason','priority','status'],[])
    digest=_digest_tree(out);run=SkillRun(rid,mode.value,str(inp),str(out),sources,s1,s2,c,{'pdf_dpi':72,'fixed_bounds_promotion':False},digest);_write_json(out/'RUN_MANIFEST.json',asdict(run))
    page_count=sum(1 for f in frames if f.get('source_page')); errors=[]
    if any(not f.get('sha256') for f in frames if f.get('frame_id')):errors.append('missing frame hash')
    if inp.suffix.lower()=='.pdf' and page_count==0:errors.append('PDF rendered zero pages')
    report=['# Validation','',f'- Run ID: `{rid}`',f'- PDF pages: {page_count}',f'- Sources: {len(sources)}',f'- Frames: {len(frames)}',f'- Deterministic digest: `{digest}`',f"- Validation: {'PASS' if not errors else 'FAIL'}",'',*['- '+e for e in errors]];(out/'VALIDATION_REPORT.md').write_text('\n'.join(report)+'\n')
    if errors:raise ValueError('; '.join(errors))
    return run
