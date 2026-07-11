#!/usr/bin/env python3
"""V-6: profile the NOAA RF-series federal cluster from the full OCR ledger.
Run from repo root:  python3 scripts/v6_noaa_profile.py
Reads outputs/ocr_events/full_sightings.jsonl (+ sightings_raw.jsonl)."""
import json, os
from collections import Counter, defaultdict
from datetime import datetime
ROOT=os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT=os.path.join(ROOT,'outputs/ocr_events')
NOAA={"N42RF":"WP-3D Orion (Hurricane Hunter)","N43RF":"NOAA RF-series",
      "N49RF":"Gulfstream G-IV (high-alt recon)","N56RF":"DHC-6 Twin Otter"}
rows=[]
for fn in ('full_sightings.jsonl','sightings_raw.jsonl'):
    p=os.path.join(OUT,fn)
    if os.path.exists(p):
        for l in open(p):
            try: rows.append(json.loads(l))
            except: pass
rf=[r for r in rows if (r.get('tail') or '') in NOAA]
print(f"NOAA RF-series sightings: {len(rf)} across {len(set(r['tail'] for r in rf))} aircraft\n")
bydate=defaultdict(Counter); bytail=Counter(); months=Counter(); alts=defaultdict(list)
for r in rf:
    t=r['tail']; bytail[t]+=1
    ts=r.get('ts_utc')
    if ts:
        d=ts[:10]; bydate[d][t]+=1; months[ts[:7]]+=1
    a=r.get('alt_ft')
    if a:
        try: alts[t].append(int(str(a).replace(',','')))
        except: pass
print("Per-aircraft:")
for t,c in bytail.most_common():
    al=alts[t]; ab=f"alt {min(al)}-{max(al)}ft" if al else "alt n/a"
    print(f"  {t:7} {c:>4} sightings  {NOAA[t]:38} {ab}")
print("\nBy month (overflight tempo):")
for m,c in sorted(months.items()): print(f"  {m}: {c}")
# Atlantic hurricane season = Jun 1 - Nov 30
season=sum(c for m,c in months.items() if 6<=int(m[5:7])<=11)
off=sum(months.values())-season
print(f"\nHurricane season (Jun-Nov): {season}  |  off-season (Dec-May): {off}")
print("Multi-NOAA-aircraft days (>=2 RF tails same day):")
for d,cc in sorted(bydate.items()):
    if len(cc)>=2: print(f"  {d}: {dict(cc)}")
json.dump({"sightings":len(rf),"per_tail":dict(bytail),"by_month":dict(months),
           "season_vs_off":[season,off]}, open(os.path.join(OUT,'noaa_profile.json'),'w'),indent=1)
print("\nwrote outputs/ocr_events/noaa_profile.json")
