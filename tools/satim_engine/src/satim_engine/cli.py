from __future__ import annotations
import argparse
from pathlib import Path
import pandas as pd
from .inventory import extract_zips, build_manifest
from .tracks import parse_csv_track, parse_kml_coordinates, NonTrackCSV
from .scoring import score_tracks
from .graph import build_graph_from_ledgers
from .plugins.visual_ocr import extract_visual_metadata
from .plugins.gis_join import bbox_context_join

def run(input_dir: str, output_dir: str) -> None:
    out = Path(output_dir); out.mkdir(parents=True, exist_ok=True)
    extracted = extract_zips(input_dir, output_dir)
    manifest = build_manifest(extracted)
    manifest.to_csv(out / "SATIM_MASTER_FILE_MANIFEST.csv", index=False)
    track_dfs, errors, skipped = [], [], []
    for _, r in manifest[manifest.role == "track_candidate"].iterrows():
        p = Path(r.path)
        try:
            df = parse_csv_track(str(p)) if p.suffix.lower()==".csv" else parse_kml_coordinates(str(p))
            track_dfs.append(df)
        except NonTrackCSV as e:
            skipped.append({"path": str(p), "reason": str(e)})
        except Exception as e:
            errors.append({"path": str(p), "error": str(e)})
    
    # v21: avoid pandas concat FutureWarning by filtering empty/all-NA frames before concat.
    clean_track_dfs = []
    for frame in track_dfs:
        if frame is not None and not frame.empty:
            clean_track_dfs.append(frame.dropna(axis=1, how="all"))
    tracks = pd.concat(clean_track_dfs, ignore_index=True) if clean_track_dfs else pd.DataFrame()
    if not tracks.empty:
        tracks = score_tracks(tracks)
        tracks.to_csv(out / "SATIM_TRACK_LEDGER.csv", index=False)
        nodes, edges = build_graph_from_ledgers(tracks)
        nodes.to_csv(out / "SATIM_GRAPH_NODES.csv", index=False)
        edges.to_csv(out / "SATIM_GRAPH_EDGES.csv", index=False)
        bbox_context_join(tracks).to_csv(out / "SATIM_GIS_JOIN_LEDGER.csv", index=False)
    visual_rows=[]
    for _, r in manifest[manifest.role == "visual_candidate"].iterrows():
        visual_rows.append(extract_visual_metadata(r.path))
    pd.DataFrame(visual_rows).to_csv(out / "SATIM_VISUAL_OCR_LEDGER.csv", index=False)
    pd.DataFrame(errors).to_csv(out / "SATIM_ERROR_LEDGER.csv", index=False)
    pd.DataFrame(skipped).to_csv(out / "SATIM_SKIPPED_NONTRACK_CSV_LEDGER.csv", index=False)
    (out / "SATIM_RUN_REPORT.md").write_text(
        f"# SATIM production run report\n\n"
        f"Files: {len(manifest)}\n"
        f"Track files parsed: {len(clean_track_dfs)}\n"
        f"Non-track CSV skipped: {len(skipped)}\n"
        f"Parser errors: {len(errors)}\n"
        f"Visual OCR rows: {len(visual_rows)}\n"
    )

def main(argv=None):
    ap = argparse.ArgumentParser(description="Run SATIM production batch engine.")
    ap.add_argument("--input", required=True, help="Folder containing source zip files")
    ap.add_argument("--output", required=True, help="Output folder")
    args = ap.parse_args(argv)
    run(args.input, args.output)

if __name__ == "__main__":
    main()
