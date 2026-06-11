/**
 * FR24 temporal wave dashboard visibility overlay.
 *
 * This module is optional and read-only. It renders a browser-side panel from
 * window.fr24TemporalWaveData when fr24_temporal_wave_dashboard.json exists.
 * It injects a tab-style control into the existing dashboard tab bar without
 * mutating the main dashboard's React state model.
 */

const temporalWaveDataReady = (data) =>
  data && Array.isArray(data.rows);

const TemporalWavePanel = ({ data }) => {
  const [open, setOpen] = React.useState(false);
  const [statusFilter, setStatusFilter] = React.useState("ALL");

  React.useEffect(() => {
    window.__openFr24TemporalWaves = () => setOpen(true);
    return () => {
      if (window.__openFr24TemporalWaves) delete window.__openFr24TemporalWaves;
    };
  }, []);

  const rows = temporalWaveDataReady(data) ? data.rows : [];
  const counts = temporalWaveDataReady(data) ? (data.counts || {}) : {};
  const filtered = React.useMemo(() => {
    return rows.filter(r => {
      if (statusFilter !== "ALL" && (r.physics_status || "") !== statusFilter) return false;
      return true;
    });
  }, [rows, statusFilter]);

  if (!temporalWaveDataReady(data)) {
    return null;
  }

  const generatedAt = data.generated_at ? new Date(data.generated_at).toLocaleString() : "—";
  const statusCounts = data.physics_status_counts || {};

  return (
    <div className="fixed right-4 bottom-4 z-50 font-sans">
      {!open && (
        <button
          onClick={() => setOpen(true)}
          className="rounded-full bg-gray-900 text-white shadow-lg px-4 py-2 text-sm font-semibold hover:bg-gray-800 md:hidden"
        >
          Temporal Waves · {counts.wave_count ?? rows.length}
        </button>
      )}

      {open && (
        <div className="w-[min(960px,calc(100vw-2rem))] max-h-[85vh] overflow-hidden rounded-xl bg-white shadow-2xl border border-gray-200">
          <div className="bg-gray-900 text-white px-4 py-3 flex items-center justify-between">
            <div>
              <h2 className="text-sm font-bold">FR24 Temporal Waves</h2>
              <p className="text-xs text-gray-400">Read-only candidate visibility · generated {generatedAt}</p>
            </div>
            <button onClick={() => setOpen(false)} className="text-xs text-gray-300 hover:text-white">Close</button>
          </div>

          <div className="bg-amber-50 border-b border-amber-200 px-4 py-3">
            <p className="text-sm font-semibold text-amber-900">Candidates only — no events are promoted or verified here.</p>
            <p className="text-xs text-amber-800 mt-1">
              This panel reads exported temporal-wave JSON only. Filters live in browser memory and do not write files.
            </p>
          </div>

          <div className="p-4 space-y-4 overflow-y-auto max-h-[70vh]">
            <div className="grid grid-cols-2 md:grid-cols-5 gap-3">
              <TemporalStat label="Waves" value={counts.wave_count ?? rows.length} />
              <TemporalStat label="Multi-observation" value={counts.multi_obs_wave_count ?? 0} />
              <TemporalStat label="Physics review" value={counts.physics_violation_wave_count ?? 0} />
              <TemporalStat label="Review rows" value={counts.physics_review_rows ?? 0} />
              <TemporalStat label="Coherent" value={counts.temporal_coherent_count ?? 0} />
            </div>

            <div className="flex flex-wrap gap-2">
              {["ALL", "passed", "needs_review"].map(s => (
                <button
                  key={s}
                  onClick={() => setStatusFilter(s)}
                  className={`px-3 py-1 rounded-full text-xs font-medium ${
                    statusFilter === s ? "bg-blue-600 text-white" : "bg-gray-100 text-gray-600 hover:bg-gray-200"
                  }`}
                >
                  {s === "ALL" ? "ALL" : `${s} (${statusCounts[s] || 0})`}
                </button>
              ))}
            </div>

            {filtered.length === 0 ? (
              <div className="rounded-lg bg-gray-50 p-6 text-sm text-gray-500 text-center">
                No temporal waves match the current filter.
              </div>
            ) : (
              <div className="space-y-2">
                {filtered.slice(0, 100).map((r, i) => (
                  <TemporalWaveCard key={r.wave_id || i} row={r} />
                ))}
                {filtered.length > 100 && (
                  <p className="text-xs text-gray-400 text-center">Showing first 100 of {filtered.length} waves</p>
                )}
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
};

const TemporalStat = ({ label, value }) => (
  <div className="rounded-lg border border-gray-200 bg-gray-50 p-3">
    <p className="text-xl font-bold text-gray-800">{Number(value || 0).toLocaleString()}</p>
    <p className="text-xs text-gray-500">{label}</p>
  </div>
);

const TemporalWaveCard = ({ row }) => {
  const needsReview = (row.physics_status || "") === "needs_review";
  const statusClass = needsReview
    ? "bg-red-100 text-red-800 border-red-200"
    : "bg-green-100 text-green-800 border-green-200";

  return (
    <div className="rounded-lg border border-gray-200 bg-white p-3 shadow-sm">
      <div className="flex flex-wrap items-center gap-2 mb-2">
        <span className="font-mono text-sm font-semibold text-blue-700">{row.wave_aircraft_identity || row.wave_id}</span>
        <span className={`px-2 py-0.5 rounded border text-xs font-medium ${statusClass}`}>
          {row.physics_status || "unknown"}
        </span>
        <span className="ml-auto text-xs text-gray-400">{row.wave_id || "—"}</span>
      </div>
      <div className="grid grid-cols-2 md:grid-cols-5 gap-2 text-xs text-gray-600">
        <div><span className="text-gray-400">obs:</span> {row.wave_obs_count ?? "—"}</div>
        <div><span className="text-gray-400">duration:</span> {row.wave_duration_minutes ?? "—"} min</div>
        <div><span className="text-gray-400">coverage:</span> {row.wave_avg_field_coverage ?? "—"}</div>
        <div><span className="text-gray-400">confidence:</span> {row.wave_avg_confidence ?? "—"}</div>
        <div><span className="text-gray-400">violations:</span> {row.physics_violation_count ?? 0}</div>
      </div>
      {(row.physics_violation_details || "").trim() && (
        <p className="mt-2 text-xs text-red-700 bg-red-50 rounded p-2">{row.physics_violation_details}</p>
      )}
      <p className="mt-2 text-xs text-gray-400">
        {row.wave_earliest_iso || "—"} → {row.wave_latest_iso || "—"}
      </p>
    </div>
  );
};

const injectTemporalWaveTab = () => {
  if (typeof document === "undefined") return;
  if (!temporalWaveDataReady(window.fr24TemporalWaveData)) return;
  if (document.getElementById("fr24-temporal-waves-tab-button")) return;

  const tabBars = [...document.querySelectorAll("div")].filter(el =>
    el.className &&
    String(el.className).includes("border-b") &&
    String(el.className).includes("flex")
  );
  const tabBar = tabBars.find(el => el.textContent && el.textContent.includes("FR24 Review Queue"));
  if (!tabBar) return;

  const btn = document.createElement("button");
  btn.id = "fr24-temporal-waves-tab-button";
  btn.type = "button";
  btn.textContent = "Temporal Waves";
  btn.className = "px-4 py-2 text-sm font-medium rounded-t border-b-2 border-transparent text-gray-500 hover:text-gray-700";
  btn.addEventListener("click", () => {
    if (window.__openFr24TemporalWaves) window.__openFr24TemporalWaves();
  });
  tabBar.appendChild(btn);
};

const TemporalWaveRoot = () => {
  const [data, setData] = React.useState(window.fr24TemporalWaveData || null);

  React.useEffect(() => {
    const syncFromWindow = () => {
      const next = window.fr24TemporalWaveData || null;
      if (temporalWaveDataReady(next)) {
        setData(next);
        setTimeout(injectTemporalWaveTab, 0);
      }
    };

    syncFromWindow();
    window.addEventListener("fr24TemporalWaveDataLoaded", syncFromWindow);
    const interval = window.setInterval(syncFromWindow, 250);
    const timeout = window.setTimeout(() => window.clearInterval(interval), 30000);

    return () => {
      window.removeEventListener("fr24TemporalWaveDataLoaded", syncFromWindow);
      window.clearInterval(interval);
      window.clearTimeout(timeout);
    };
  }, []);

  React.useEffect(() => {
    if (temporalWaveDataReady(data)) {
      injectTemporalWaveTab();
      setTimeout(injectTemporalWaveTab, 250);
      setTimeout(injectTemporalWaveTab, 1000);
    }
  }, [data]);

  return <TemporalWavePanel data={data} />;
};

const mountTemporalWavePanel = () => {
  if (typeof document === "undefined") return;
  if (document.getElementById("fr24-temporal-wave-panel-root")) return;
  const container = document.createElement("div");
  container.id = "fr24-temporal-wave-panel-root";
  document.body.appendChild(container);
  ReactDOM.render(<TemporalWaveRoot />, container);
};

if (typeof window !== "undefined") {
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", mountTemporalWavePanel);
  } else {
    mountTemporalWavePanel();
  }
}
