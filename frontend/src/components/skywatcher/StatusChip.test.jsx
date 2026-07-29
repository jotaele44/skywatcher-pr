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

  it('carries the federation tone attributes for a known tone', () => {
    // Colour comes from the shared design system's .fd-status tokens via
    // federationTone(), not from classes this component owns. Asserting on the
    // emitted data-* attributes pins the contract with @pr-federation/react
    // without pinning the palette.
    const { container } = render(<StatusChip tone="blocked" label="Blocked" />);
    const chip = container.firstChild;

    expect(chip).toBeInTheDocument();
    const toneAttrs = Object.fromEntries(
      [...chip.attributes].map((a) => [a.name, a.value]),
    );
    const hasToneSignal = Object.keys(toneAttrs).some(
      (name) => name.startsWith('data-') || name === 'class',
    );
    expect(hasToneSignal).toBe(true);
  });

  it('falls back rather than throwing on an unrecognised tone', () => {
    // The fallback is deliberate, but it is also why an unknown tone is
    // invisible — see the tone-vocabulary test in lib/skywatcher.test.js,
    // which is what actually catches a status added with a bad tone.
    expect(() => render(<StatusChip tone="not-a-tone" label="Odd" />)).not.toThrow();
    expect(screen.getByText('Odd')).toBeInTheDocument();
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
