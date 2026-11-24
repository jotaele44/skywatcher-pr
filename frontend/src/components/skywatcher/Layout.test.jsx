import { describe, it, expect, vi } from 'vitest';
import { fireEvent, render, screen } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { axe } from 'vitest-axe';

// The sidebar and the status strip read application data; this test is about
// the frame around them.
vi.mock('./Sidebar', () => ({ default: () => <nav aria-label="Primary">sidebar</nav> }));
vi.mock('./TopStatusStrip', () => ({ default: () => <div>status</div> }));

import Layout from '@/components/skywatcher/Layout';

function renderLayout() {
  return render(
    <MemoryRouter initialEntries={['/']}>
      <Routes>
        <Route element={<Layout />}>
          <Route path="/" element={<h1>Dashboard</h1>} />
        </Route>
      </Routes>
    </MemoryRouter>,
  );
}

describe('Layout', () => {
  // The toggle holds only an icon. Without a name it was announced as
  // "button", on every route, at every phone width.
  it('names the mobile navigation toggle and reports whether it is open', () => {
    renderLayout();

    const toggle = screen.getByRole('button', { name: 'Open navigation' });
    expect(toggle).toHaveAttribute('aria-expanded', 'false');
    expect(toggle).toHaveAttribute('type', 'button');

    fireEvent.click(toggle);

    expect(screen.getByRole('button', { name: 'Close navigation' })).toHaveAttribute('aria-expanded', 'true');
  });

  it('gives the toggle a 44px target', () => {
    renderLayout();

    expect(screen.getByRole('button', { name: 'Open navigation' })).toHaveClass('h-11', 'w-11');
  });

  it('renders the routed page inside main, with no axe violations in the frame', async () => {
    const { container } = renderLayout();

    expect(screen.getByRole('main')).toContainElement(screen.getByRole('heading', { name: 'Dashboard' }));
    expect(await axe(container)).toHaveNoViolations();
  });
});
