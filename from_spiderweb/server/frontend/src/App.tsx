import React from 'react';
import { MapPane } from './components/MapPane';
import { FinancePane } from './components/FinancePane';
import { useAppStore } from './state/store';

/**
 * Root component for the PRIIS V1.5 workbench. It composes the
 * overall layout: a command bar, side navigation, central workspace
 * showing the map and finance modules, and a right-hand inspector
 * panel that reflects the current selection. Real modules for
 * anomaly, graph, and query features should be added later.
 */
const App: React.FC = () => {
  const selected = useAppStore((s) => s.selected);

  return (
    <div className="app-container">
      <header className="command-bar">PRIIS V1.5 Workbench</header>
      <div className="body">
        <aside className="sidebar">
          <nav>
            <button>Finance</button>
            <button>Spatial</button>
            <button>Anomaly</button>
            <button>Graph</button>
            <button>Query</button>
          </nav>
        </aside>
        <main className="workspace">
          <MapPane />
          <FinancePane />
        </main>
        <aside className="inspector">
          {selected ? (
            <pre>{JSON.stringify(selected, null, 2)}</pre>
          ) : (
            <p>No selection</p>
          )}
        </aside>
      </div>
    </div>
  );
};

export default App;