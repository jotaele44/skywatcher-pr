#!/usr/bin/env python3
"""V-7: batch-confirm OCR'd tails against the FAA registry.
Reads the unconfirmed-plausible tails, pulls owner/make/model/type, writes confirmed_owners.csv.
Run from repo root (needs internet):  python3 scripts/v7_batch_confirm.py
Polite: ~1 req/sec. Resumable (skips tails already in confirmed_owners.csv)."""
import csv, os, re, time, urllib.request
ROOT=os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ROSTER=os.path.join(ROOT,'expanded_fleet_roster.csv')
OUT=os.path.join(ROOT,'confirmed_owners.csv')
URL="https://registry.faa.gov/aircraftinquiry/Search/NNumberResult?nNumberTxt=%s"
def field(html, label):
    m=re.search(re.escape(label)+r'\s*</td>\s*<td[^>]*>\s*([^<]+)', html, re.I)
    return (m.group(1).strip() if m else '')
def owner(html):
    m=re.search(r'Registered Owner.*?Name\s*</td>\s*<td[^>]*>\s*([^<]+)', html, re.I|re.S)
    return (m.group(1).strip() if m else '')
def status(html):
    if 'is Deregistered' in html: return 'deregistered'
    if 'Reserved N-Number' in html or 'has Reserved' in html: return 'reserved_only'
    if 'is Assigned' in html or 'Assigned/Multiple' in html: return 'assigned'
    return 'unknown'
done=set()
if os.path.exists(OUT):
    for r in csv.DictReader(open(OUT)): done.add(r['tail'])
tails=[]
for r in csv.DictReader(open(ROSTER)):
    if r['category']=='unconfirmed-plausible' and r['tail'] not in done:
        tails.append(r['tail'])
print(f"to confirm: {len(tails)} (skipping {len(done)} done)")
mode='a' if done else 'w'
with open(OUT, mode, newline='') as f:
    w=csv.writer(f)
    if not done: w.writerow(['tail','reg_status','make','model','type','owner'])
    for i,t in enumerate(tails,1):
        try:
            req=urllib.request.Request(URL%t[1:], headers={'User-Agent':'Mozilla/5.0'})
            html=urllib.request.urlopen(req,timeout=20).read().decode('utf-8','ignore')
            st=status(html)
            w.writerow([t,st,field(html,'Manufacturer Name'),field(html,'Model'),
                        field(html,'Type Aircraft'),owner(html)]); f.flush()
        except Exception as e:
            w.writerow([t,'ERROR','','','',str(e)[:40]]); f.flush()
        if i%10==0: print(f"  {i}/{len(tails)}")
        time.sleep(1.0)
print("wrote confirmed_owners.csv")
