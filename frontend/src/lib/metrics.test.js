import { describe, it, expect } from 'vitest';

import { computeMetrics } from '@/lib/metrics';

// computeMetrics is the dashboard's only aggregation layer and had no tests.
// Most of it is counting, but one rule is a real safety guarantee — see the
// production-eligibility block below — and several defaults decide whether a
// partial payload renders zeroes or throws.

const observation = (over = {}) => ({
  review_status: 'new',
  synthetic_flag: false,
  confidence_score: 0.9,
  ...over,
});

describe('computeMetrics — observation counts', () => {
  it('counts by review status and synthetic flag independently', () => {
    const m = computeMetrics({
      observations: [
        observation({ review_status: 'verified' }),
        observation({ review_status: 'verified', synthetic_flag: true }),
        observation({ review_status: 'needs_review' }),
      ],
    });

    expect(m.totalObservations).toBe(3);
    expect(m.verifiedObservations).toBe(2);
    expect(m.needsReviewCount).toBe(1);
    expect(m.syntheticObservations).toBe(1);
  });

  it('splits confidence at 0.75 and 0.5, leaving the middle band in neither', () => {
    const m = computeMetrics({
      observations: [
        observation({ confidence_score: 0.75 }), // high — boundary is inclusive
        observation({ confidence_score: 0.74 }), // middle
        observation({ confidence_score: 0.5 }), // middle — boundary is inclusive
        observation({ confidence_score: 0.49 }), // low
      ],
    });

    expect(m.highConfidence).toBe(1);
    expect(m.lowConfidence).toBe(1);
    // The two middle observations are deliberately in neither bucket; the
    // dashboard shows high and low, not a partition.
    expect(m.highConfidence + m.lowConfidence).toBeLessThan(m.totalObservations);
  });

  it('treats a missing confidence score as low rather than skipping it', () => {
    // `confidence_score ?? 0` — an observation that never got scored is a
    // low-confidence one, not an absent one. Counting it as neither would
    // quietly shrink the denominator operators are reading.
    const m = computeMetrics({ observations: [observation({ confidence_score: undefined })] });

    expect(m.lowConfidence).toBe(1);
    expect(m.highConfidence).toBe(0);
  });
});

describe('computeMetrics — production eligibility', () => {
  // This is the rule worth protecting: skywatcher is a synthetic-first
  // producer, and a production export carrying synthetic rows must not be
  // counted as production-eligible however it is flagged.

  it('excludes a production export that contains synthetic rows', () => {
    const m = computeMetrics({
      exports: [
        { production_eligible: true, export_mode: 'production', contains_synthetic_rows: true },
      ],
    });

    expect(m.productionEligibleExports).toBe(0);
  });

  it('counts a production export with no synthetic rows', () => {
    const m = computeMetrics({
      exports: [
        { production_eligible: true, export_mode: 'production', contains_synthetic_rows: false },
      ],
    });

    expect(m.productionEligibleExports).toBe(1);
  });

  it('allows synthetic rows in a test export', () => {
    // The exclusion is scoped to production mode — synthetic rows are the
    // normal case for a test export and must not be penalised.
    const m = computeMetrics({
      exports: [
        { production_eligible: true, export_mode: 'test', contains_synthetic_rows: true },
      ],
    });

    expect(m.productionEligibleExports).toBe(1);
  });

  it('never counts an export that is not flagged eligible', () => {
    const m = computeMetrics({
      exports: [
        { production_eligible: false, export_mode: 'production', contains_synthetic_rows: false },
      ],
    });

    expect(m.productionEligibleExports).toBe(0);
  });

  it('counts blocked exports and valid test exports separately', () => {
    const m = computeMetrics({
      exports: [
        { export_status: 'blocked' },
        { export_mode: 'test', export_status: 'valid' },
        { export_mode: 'production', export_status: 'valid' },
      ],
    });

    expect(m.blockedExportCount).toBe(1);
    expect(m.validTestExports).toBe(1); // production/valid is not a test export
  });
});

describe('computeMetrics — review backlog', () => {
  it('counts open and in_review as backlog, and nothing else', () => {
    const m = computeMetrics({
      reviews: [
        { review_status: 'open' },
        { review_status: 'in_review' },
        { review_status: 'resolved' },
        { review_status: 'rejected' },
      ],
    });

    expect(m.manualReviewBacklog).toBe(2);
  });
});

describe('computeMetrics — partial and empty payloads', () => {
  it('returns zeroes for an empty payload instead of throwing', () => {
    // Every collection defaults, so a dashboard rendering before data arrives
    // shows zeroes rather than crashing.
    const m = computeMetrics({});

    expect(m.totalObservations).toBe(0);
    expect(m.productionEligibleExports).toBe(0);
    expect(m.manualReviewBacklog).toBe(0);
    expect(m.aircraftCount).toBe(0);
    expect(m.captureCount).toBe(0);
    expect(m.assetCount).toBe(0);
    expect(m.routeCount).toBe(0);
  });

  it('passes through the simple collection sizes', () => {
    const m = computeMetrics({
      aircraft: [{}, {}],
      captures: [{}],
      assets: [{}, {}, {}],
      routes: [],
    });

    expect(m.aircraftCount).toBe(2);
    expect(m.captureCount).toBe(1);
    expect(m.assetCount).toBe(3);
    expect(m.routeCount).toBe(0);
  });

  it('reports the fixed diagnostic readiness posture', () => {
    // Hard-coded rather than derived: this producer is discovery-ready but not
    // live-execution ready, and the dashboard must not imply otherwise.
    const m = computeMetrics({});

    expect(m.hubDiscoveryReady).toBe(true);
    expect(m.hubLiveExecutionReady).toBe(false);
  });
});
