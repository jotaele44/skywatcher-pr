# V-6 + V-7 — NOAA Cluster Profile & Roster Expansion

**Vectors:** V-6 (federal overflight profiling) + V-7 (tail confirmation/merge) · depth L3 · controlled-analytical · validity = cross-source coherence · **Updated:** 2026-06-21

---

## V-6 — NOAA federal cluster: PROFILED & CROSS-VALIDATED

82 RF-series sightings resolve into **two distinct federal missions**, not one:

### (a) Hurricane reconnaissance — 2025-08-16, coordinated 3-aircraft day
| Tail | Aircraft | Altitude band | Speed | Role |
|---|---|---|---|---|
| **N42RF** | Lockheed WP-3D Orion | 8,000–20,000 ft | 270–410 mph | storm **penetration** |
| **N49RF** | Gulfstream G-IV | 26,700–44,975 ft | 466–527 mph | **high-altitude synoptic** survey |
| **N43RF** | NOAA RF-series | ~7,950 ft | 300 mph | low-level |

All three airborne the **same day**, the WP-3D + G-IV pairing being NOAA's signature storm package (low penetrator + high-altitude environmental).

**Cross-source validation (T1+T2+T3):** On **2025-08-16, Hurricane Erin** was a Cat-4/5 storm **~150 mi NE of San Juan**, rapidly intensifying through an eyewall-replacement cycle — and **NOAA hurricane hunters were actively flying it** (NHC tropical cyclone report). The FR24 screenshots captured NOAA's Erin reconnaissance staged over/through PR airspace. Registry (what), OCR timing (when), and NHC reporting (why) all cohere. **This is the highest-confidence structural finding of the whole effort.**

### (b) Coastal survey — Feb–Mar 2026 (off-season)
**N56RF (DHC-6 Twin Otter)** — 70 low-and-slow passes, **550–5,800 ft, 90–180 mph**, in Feb/Mar 2026. No storm; this is routine **coastal/marine survey**, a separate NOAA mission from the hurricane work. Long continuous tracks on 2026-03-01 (descending coastal runs) confirm a survey profile, not transit.

→ `outputs/ocr_events/noaa_profile.json`. **V-6 EXHAUSTED.**

---

## V-7 — tail confirmation & roster merge

**19 new platforms registry-confirmed** (of 277 new tails); merged with the original 17 into a **36-platform master** (`platform_master_expanded.csv`). Remaining 195 "unconfirmed-plausible" are valid N-numbers handed to a batch script.

### Confirmed-platform categories (new + original)
| Category | New confirmed | Notable |
|---|---|---|
| **Federal** | 4 | NOAA cluster (above) |
| **Government (PR)** | 3 | N255PD (police Bell 429), N5855Z (PREPA #2), N516PR (DRNA Caravan) |
| Survey | 1 | N811NA (Digital Aerial Solutions) |
| Resident civil | 10 | N540DB (442 shots), N936DM, N620GG, N750CK (SJ bizjet), N888EV, HL Caravan fleet |
| Transient (context) | 37 NetJets + 12 Flexjet + 11 airline/cargo | not resident — overflights |

### New affiliate / fleet links (T1)
- **Windsock Management** operates **≥2 Bell 407s** — N407PR **+ N411PR** (same owner).
- **PREPA** confirmed **2-ship** AS350 unit — N5854Z + N5855Z (Air Operations Dept).
- **Police-pattern Bell 429 ×2** — N767PD (ASG) + N255PD.
- **"HL" Caravan fleet** — N961HL + N963HL share owner (Caravan International Leasing, NV); a cargo-feeder fleet (N962HL/N965HL same series).
- Prior SPV link still stands: N999ZY + N600UH at 1666 Ave Ponce de León.

### Validation gate performance (full corpus)
Rejected 20 OCR-garbage tails (FAA I/O rule) + **N253TH (reserved-only, 274 misreads)** + **N6854Z (deregistered)**, and corrected two of my own inferences (N811NA≠NASA, N26DP≠police). The gate is doing exactly its job at 10k scale.

### Finishing the remaining 195 (your machine)
```bash
cd /Users/jotaele/Developer/skywatcher-pr
python3 scripts/v7_batch_confirm.py     # ~1 req/sec, resumable -> confirmed_owners.csv
```
Then the confirmed rows can be folded into `platform_master_expanded.csv`.

---

## Vector state
- **V-1** fleet pattern-of-life — CLOSED. **V-5** OCR expansion — CLOSED. **V-6** NOAA profile — CLOSED. **V-7** roster merge — substantially complete (19 confirmed; 195 queued to batch script).
- **V-8 (queued)** — re-run fleet **correlation/rendezvous** (main brief §7) on the 36-platform expanded master: co-presence among the NOAA jets, PREPA pair, police Bell 429s, and the resident rotor fleet is the next structural-signal layer.

### Deliverables
- `FR24_V6_V7_REPORT.md` (this) · `platform_master_expanded.csv` (36 platforms) · `expanded_fleet_roster.csv` (277 new tails, categorized)
- `scripts/v6_noaa_profile.py` · `scripts/v7_batch_confirm.py` · `outputs/ocr_events/noaa_profile.json`
