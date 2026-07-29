import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';

import StatusChip from '@/components/skywatcher/StatusChip';
import { REVIEW_STATUS } from '@/lib/skywatcher';

// The first component test in this frontend. Beyond covering StatusChip, it is
// what proves the jsdom half of the harness actually works — the pure-logic
// tests alongside it would pass with testing-library entirely absent.

describe('StatusChip', () => {
  it('renders its label', () => {
    render(<StatusChip tone="ready" label="Verified" />);

    expect(screen.getByText('Verified')).toBeInTheDocument();
  });

  // Colour comes from the shared design system's .fd-status tokens via
  // federationTone(), not from classes this component owns. federationTone
  // returns { className: 'fd-status', 'data-status': <canonical role> }, so
  // data-status is the whole observable contract — assert its value, not its
  // presence. StatusChip always sets a className regardless of tone, so any
  // check that merely looks for attributes passes even when every tone has
  // collapsed to the neutral fallback.
  const EXPECTED_ROLE = {
    ready: 'success',
    warn: 'warning',
    blocked: 'danger',
    synthetic: 'process',
    info: 'info',
    primary: 'tier',
    muted: 'neutral',
  };

  const roleOf = (tone, label = 'X') => {
    const { container, unmount } = render(<StatusChip tone={tone} label={label} />);
    const role = container.firstChild.getAttribute('data-status');
    const className = container.firstChild.className;
    unmount();
    return { role, className };
  };

  it.each(Object.entries(EXPECTED_ROLE))(
    'renders tone %s as the federation role %s',
    (tone, expected) => {
      const { role, className } = roleOf(tone);

      expect(role).toBe(expected);
      expect(className).toContain('fd-status');
    },
  );

  it('keeps distinct tones distinct', () => {
    // The fallback is `neutral`, so the most likely way this contract breaks is
    // everything collapsing to it at once. Each per-tone expectation above
    // catches that too, but only this one says why the suite went red.
    const roles = Object.keys(EXPECTED_ROLE).map((tone) => roleOf(tone).role);

    expect(new Set(roles).size).toBeGreaterThan(1);
    expect(new Set(roles).size).toBe(new Set(Object.values(EXPECTED_ROLE)).size);
  });

  it('falls back to neutral for an unrecognised tone, distinguishably', () => {
    // Both halves matter: without the second, a total collapse to neutral would
    // satisfy this test rather than fail it.
    expect(roleOf('not-a-tone').role).toBe('neutral');
    expect(roleOf('not-a-tone').role).not.toBe(roleOf('blocked').role);
  });


  it('renders without a tone at all', () => {
    render(<StatusChip label="Default" />);

    expect(screen.getByText('Default')).toBeInTheDocument();
  });

  it('renders an icon when given one', () => {
    const Icon = (props) => <svg data-testid="chip-icon" {...props} />;
    render(<StatusChip tone="info" label="Triaged" icon={Icon} />);

    expect(screen.getByTestId('chip-icon')).toBeInTheDocument();
    expect(screen.getByText('Triaged')).toBeInTheDocument();
  });

  it('applies an extra className alongside its own', () => {
    const { container } = render(
      <StatusChip tone="ready" label="Verified" className="mt-2" />,
    );

    expect(container.firstChild.className).toContain('mt-2');
  });

  it('renders every review status the app defines', () => {
    // Cheap guard that no entry in the vocabulary breaks the chip — the maps
    // are edited far more often than this component is.
    for (const [key, { label, tone }] of Object.entries(REVIEW_STATUS)) {
      const { unmount } = render(<StatusChip tone={tone} label={label} />);
      expect(screen.getByText(label), `${key} did not render`).toBeInTheDocument();
      unmount();
    }
  });
});
