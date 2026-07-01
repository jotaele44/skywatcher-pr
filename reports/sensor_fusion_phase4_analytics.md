# Skywatcher Sensor Fusion Phase 4 Analytics

## Vector

`SKYWATCHER_SENSOR_FUSION_PHASE4_ANALYTICS`

## Added

- `src/skywatcher/fusion/historical_baselines.py`
  - Builds aggregate historical baselines by corridor and domain.
  - Produces review-context-only baseline metadata.

- `src/skywatcher/fusion/anomaly_scoring.py`
  - Scores current aggregate records against historical baselines.
  - Emits review-band classifications only.

- `scripts/build_sensor_fusion_historical_baselines.py`
  - Builds `outputs/sensor_fusion/historical_baselines.json`.

- `scripts/build_sensor_fusion_anomalies.py`
  - Builds `outputs/sensor_fusion/anomaly_review.json`.

- `scripts/export_sensor_fusion_thehub.py`
  - Builds TheHub-compatible `sensor_fusion_analytics_v1` export.

- `scripts/build_sensor_fusion_visualization.py`
  - Builds dashboard visualization summary JSON.

- `tests/test_sensor_fusion_phase4_analytics.py`
  - Tests baseline grouping, anomaly scoring, TheHub export contract, and visualization payloads.

## Guardrails

- No live tracking.
- No tactical routing.
- No operational cueing.
- All outputs use `review_context_only`.
- TheHub export contract is analytics/context only.

## Validation Required

```bash
git fetch origin
git checkout gpt/airspace-maritime-sensor-fusion
git rebase origin/main
pytest
git push --force-with-lease origin gpt/airspace-maritime-sensor-fusion
```

## Merge Prep

PR #33 can be prepared for merge only after the Phase 4 pytest pass is confirmed on the rebased branch.
