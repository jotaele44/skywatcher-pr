import React, { useState } from 'react';
import { Outlet, useLocation } from 'react-router-dom';
import { Menu, X } from 'lucide-react';
import Sidebar from './Sidebar';
import TopStatusStrip from './TopStatusStrip';

export default function Layout() {
  const [mobileOpen, setMobileOpen] = useState(false);
  const { pathname } = useLocation();
  const consoleMode = pathname.startsWith('/console');

  return (
    <div className="flex h-screen flex-col bg-background text-foreground">
      <TopStatusStrip />
      <div className="flex min-h-0 flex-1 overflow-hidden">
        <div className="hidden md:block">
          <Sidebar />
        </div>

        {mobileOpen && (
          <div className="fixed inset-0 z-40 md:hidden">
            <div className="absolute inset-0 bg-black/60" onClick={() => setMobileOpen(false)} />
            <div className="absolute left-0 top-0 h-full">
              <Sidebar onNavigate={() => setMobileOpen(false)} />
            </div>
          </div>
        )}

        <div className="flex min-h-0 flex-1 flex-col overflow-hidden">
          <div className="flex items-center gap-2 border-b border-border px-3 py-2 md:hidden">
            <button
              type="button"
              onClick={() => setMobileOpen((value) => !value)}
              className="flex h-8 w-8 items-center justify-center rounded-lg border border-border bg-secondary text-foreground"
              aria-label={mobileOpen ? 'Close navigation' : 'Open navigation'}
            >
              {mobileOpen ? <X className="h-4 w-4" /> : <Menu className="h-4 w-4" />}
            </button>
            <span className="text-sm font-semibold">Skywatcher-PR</span>
          </div>
          <main className={consoleMode ? 'min-h-0 flex-1 overflow-hidden' : 'flex-1 overflow-y-auto scrollbar-thin'}>
            <div className={consoleMode ? 'h-full min-h-0 w-full' : 'mx-auto max-w-[1400px] space-y-5 p-4 md:p-6'}>
              <Outlet />
            </div>
          </main>
        </div>
      </div>
    </div>
  );
}
