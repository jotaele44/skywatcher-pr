import { describe, it, expect } from 'vitest';

import {
  PR_BOUNDS,
  REVIEW_STATUS,
  INGEST_STATUS,
  EXPORT_STATUS,
  SYNC_STATUS,
  confidenceTier,
  projectToShell,
} from '@/lib/skywatcher';

describe('confidenceTier', () => {
  it.each([
    [1, 'high'],
    [0.75, 'high'],
    [0.749, 'medium'],
    [0.5, 'medium'],
    [0.499, 'low'],
    [0, 'low'],
  ])('scores %s as %s', (score, tier) => {
    expect(confidenceTier(score)).toBe(tier);
  });

  it('distinguishes an unscored observation from a low-scoring one', () => {
    // "unknown", not "low" — a missing score is an absence of evidence, and
    // collapsing it into the low band would present it as a judgement made.
    expect(confidenceTier(null)).toBe('unknown');
    expect(confidenceTier(undefined)).toBe('unknown');
    expect(confidenceTier(0)).toBe('low');
  });
});

describe('projectToShell', () => {
  const W = 400;
  const H = 300;
  const PAD = 16;

  it('places the south-west corner of the bounds at bottom-left', () => {
    const { x, y } = projectToShell(PR_BOUNDS.minLat, PR_BOUNDS.minLon, W, H);

    expect(x).toBeCloseTo(PAD);
    expect(y).toBeCloseTo(H - PAD);
  });

  it('places the north-east corner at top-right', () => {
    const { x, y } = projectToShell(PR_BOUNDS.maxLat, PR_BOUNDS.maxLon, W, H);

    expect(x).toBeCloseTo(W - PAD);
    expect(y).toBeCloseTo(PAD);
  });

  it('inverts latitude — further north is a smaller y', () => {
    // Screen coordinates grow downward while latitude grows northward. Getting
    // this backwards flips the island vertically and nothing else complains.
    const north = projectToShell(18.4, -66.0, W, H);
    const south = projectToShell(18.0, -66.0, W, H);

    expect(north.y).toBeLessThan(south.y);
  });

  it('does not invert longitude — further east is a larger x', () => {
    const east = projectToShell(18.2, -65.5, W, H);
    const west = projectToShell(18.2, -67.0, W, H);

    expect(east.x).toBeGreaterThan(west.x);
  });

  it('keeps in-bounds points inside the padded area', () => {
    const { x, y } = projectToShell(18.2, -66.2, W, H);

    expect(x).toBeGreaterThanOrEqual(PAD);
    expect(x).toBeLessThanOrEqual(W - PAD);
    expect(y).toBeGreaterThanOrEqual(PAD);
    expect(y).toBeLessThanOrEqual(H - PAD);
  });

  it('honours a custom padding', () => {
    const { x } = projectToShell(PR_BOUNDS.minLat, PR_BOUNDS.minLon, W, H, 40);

    expect(x).toBeCloseTo(40);
  });
});

describe('status vocabularies', () => {
  const MAPS = {
    REVIEW_STATUS,
    INGEST_STATUS,
    EXPORT_STATUS,
    SYNC_STATUS,
  };

  // StatusChip maps these tones onto the shared federation status roles and
  // silently falls back to "neutral" for anything it does not recognise. So a
  // status added with an unknown tone renders as a plain grey chip with no
  // error anywhere — visible only if someone happens to look at that state.
  // This is the tone vocabulary StatusChip actually handles.
  const SUPPORTED_TONES = new Set([
    'ready',
    'warn',
    'blocked',
    'synthetic',
    'info',
    'primary',
    'muted',
  ]);

  it.each(Object.entries(MAPS))('%s entries all have a label and a tone', (_name, map) => {
    for (const [key, entry] of Object.entries(map)) {
      expect(entry.label, `${key} has no label`).toBeTruthy();
      expect(entry.tone, `${key} has no tone`).toBeTruthy();
    }
  });

  it.each(Object.entries(MAPS))('%s uses only tones StatusChip renders', (_name, map) => {
    for (const [key, entry] of Object.entries(map)) {
      expect(SUPPORTED_TONES, `${key} uses unrenderable tone "${entry.tone}"`)
        .toContain(entry.tone);
    }
  });

  it('agrees on shared status keys across maps', () => {
    // `blocked` and `rejected` appear in more than one map; they should not
    // mean different things depending on which surface renders them.
    expect(EXPORT_STATUS.blocked.tone).toBe(SYNC_STATUS.blocked.tone);
    expect(INGEST_STATUS.rejected.tone).toBe(REVIEW_STATUS.rejected.tone);
  });
});
