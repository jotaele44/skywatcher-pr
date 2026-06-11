/**
 * Puerto Rico Airspace Intelligence Dashboard
 *
 * Reads from window.flightData (JSON export from run_all.py --export-json).
 * Embedded via dashboard.html using Babel standalone + React CDN — no build step.
 */

const { useState, useMemo } = React;

const PAGE_SIZE = 200;

// ── Icons ────────────────────────────────────────────────────────────────────
const ICON_PATHS = {
  activity:    "M22 12h-4l-3 9L9 3l-3 9H2",
  alert:       "M10.29 3.86L1.82 18a2 2 0 001.71 3h16.94a2 2 0 001.71-3L13.71 3.86a2 2 0 00-3.42 0zM12 9v4M12 17h.01",
  plane:       "M21 16v-2l-8-5V3.5a1.5 1.5 0 00-3 0V9l-8 5v2l8-2.5V19l-2 1.5V22l3.5-1 3.5 1v-1.5L13 19v-5.5l8 2.5z",
  shield:      "M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z",
  clock:       "M12 2a10 10 0 100 20A10 10 0 0012 2zM12 6v6l4 2",
  chevronUp:   "M18 15l-6-6-6 6",
  chevronDown: "M6 9l6 6 6-6",
  search:      "M21 21l-4.35-4.35M17 11A6 6 0 105 11a6 6 0 0012 0z",
  x:           "M18 6L6 18M6 6l12 12",
};

const Icon = ({ name, size = 16, className = "" }) => (
  <svg xmlns="http://www.w3.org/2000/svg" width={size} height={size}
    viewBox="0 0 24 24" fill="none" stroke="currentColor"
    strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"
    className={className}>
    <path d={ICON_PATHS[name] || ""} />
  </svg>
);

// ── Severity helpers ─────────────────────────────────────────────────────────
const SEVERITY_STYLE = {
  CRITICAL: { badge: "bg-red-700 text-white",   border: "border-red-700" },
  HIGH:     { badge: "bg-red-500 text-white",   border: "border-red-400" },
  MEDIUM:   { badge: "bg-yellow-400 text-gray-900", border: "border-yellow-400" },
  LOW:      { badge: "bg-blue-400 text-white",  border: "border-blue-400" },
  INFO:     { badge: "bg-gray-400 text-white",  border: "border-gray-300" },
};
const severityStyle = (s, key) => (SEVERITY_STYLE[s] || SEVERITY_STYLE.INFO)[key];

const SeverityBadge = ({ severity }) => (
  <span className={`px-2 py-0.5 rounded text-xs font-semibold ${severityStyle(severity, "badge")}`}>
    {severity}
  </span>
);

// ── Shared primitives ────────────────────────────────────────────────────────
const ConfidenceBar = ({ value }) => {
  const pct = Math.round((value || 0) * 100);
  const color = pct >= 80 ? "bg-green-500" : pct >= 60 ? "bg-yellow-400" : "bg-red-400";
  return (
    <div className="flex items-center gap-2">
      <div className="flex-1 h-2 bg-gray-200 rounded">
        <div className={`h-2 rounded ${color}`} style={{ width: `${pct}%` }} />
      </div>
      <span className="text-xs text-gray-500 w-8 text-right">{pct}%</span>
    </div>
  );
};

const StatCard = ({ label, value, sub, icon }) => (
  <div className="bg-white rounded-lg shadow p-4 flex items-start gap-3">
    <div className="p-2 bg-blue-50 rounded-lg text-blue-600">
      <Icon name={icon} size={20} />
    </div>
    <div>
      <p className="text-2xl font-bold text-gray-800">{value}</p>
      <p className="text-sm font-medium text-gray-600">{label}</p>
      {sub && <p className="text-xs text-gray-400 mt-0.5">{sub}</p>}
    </div>
  </div>
);

const TabButton = ({ label, active, onClick }) => (
  <button onClick={onClick}
    className={`px-4 py-2 text-sm font-medium rounded-t border-b-2 transition-colors ${
      active
        ? "border-blue-600 text-blue-600 bg-white"
        : "border-transparent text-gray-500 hover:text-gray-700"
    }`}>
    {label}
  </button>
);

const SortTh = ({ label, field, sort, onSort }) => (
  <th className="px-3 py-2 text-left text-xs font-semibold text-gray-500 uppercase cursor-pointer select-none hover:text-gray-700"
    onClick={() => onSort(field)}>
    <span className="flex items-center gap-1">
      {label}
      {sort.field === field && (
        <Icon name={sort.dir === "asc" ? "chevronUp" : "chevronDown"} size={12} />
      )}
    </span>
  </th>
);

const SearchInput = ({ value, onChange, placeholder }) => (
  <div className="relative">
    <Icon name="search" size={14} className="absolute left-3 top-2.5 text-gray-400" />
    <input
      type="text"
      placeholder={placeholder}
      value={value}
      onChange={e => onChange(e.target.value)}
      className="w-full pl-8 pr-4 py-2 text-sm border border-gray-200 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-300"
    />
    {value && (
      <button onClick={() => onChange("")} className="absolute right-3 top-2.5 text-gray-400 hover:text-gray-600">
        <Icon name="x" size={14} />
      </button>
    )}
  </div>
);

// ════════════════════════════════════════════════════════════════════════════
// TAB 1 — OVERVIEW
// ════════════════════════════════════════════════════════════════════════════
const OverviewTab = ({ data }) => {
  const { flights = [], alerts = [], aircraft_profiles = [] } = data;

  const totalHours = useMemo(() => {
    const mins = flights.reduce((s, f) => s + (f.flight_duration_minutes || 0), 0);
    return (mins / 60).toFixed(1);
  }, [flights]);

  const uniqueAircraftCount = useMemo(
    () => aircraft_profiles.length || new Set(flights.map(f => f.callsign)).size,
    [aircraft_profiles, flights]
  );

  const operatorCounts = useMemo(() => {
    const counts = {};
    flights.forEach(f => {
      const op = f.operator || f.callsign || "Unknown";
      counts[op] = (counts[op] || 0) + 1;
    });
    return Object.entries(counts).sort((a, b) => b[1] - a[1]).slice(0, 5);
  }, [flights]);

  const maxOpCount = operatorCounts[0]?.[1] || 1;

  const recentAlerts = useMemo(
    () => [...alerts].sort((a, b) => (b.triggered_at || "").localeCompare(a.triggered_at || "")).slice(0, 8),
    [alerts]
  );

  return (
    <div className="space-y-6">
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <StatCard label="Aircraft tracked" value={uniqueAircraftCount}               icon="plane"     />
        <StatCard label="Total flights"    value={flights.length.toLocaleString()}   icon="activity"  />
        <StatCard label="Flight hours"     value={totalHours}                         icon="clock"     sub="combined" />
        <StatCard label="Alerts generated" value={alerts.length.toLocaleString()}    icon="alert"     />
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
        <div className="bg-white rounded-lg shadow p-4">
          <h3 className="text-sm font-semibold text-gray-700 mb-3">Top operators by flight count</h3>
          <div className="space-y-2">
            {operatorCounts.map(([op, cnt]) => (
              <div key={op}>
                <div className="flex justify-between text-xs text-gray-600 mb-0.5">
                  <span className="truncate max-w-xs">{op}</span>
                  <span className="font-medium ml-2">{cnt}</span>
                </div>
                <div className="h-2 bg-gray-100 rounded">
                  <div className="h-2 bg-blue-500 rounded" style={{ width: `${(cnt / maxOpCount) * 100}%` }} />
                </div>
              </div>
            ))}
          </div>
        </div>

        <div className="bg-white rounded-lg shadow p-4">
          <h3 className="text-sm font-semibold text-gray-700 mb-3">Recent alerts</h3>
          {recentAlerts.length === 0 ? (
            <p className="text-xs text-gray-400">No alerts in database.</p>
          ) : (
            <div className="space-y-2">
              {recentAlerts.map((a, i) => (
                <div key={a.alert_id || i} className="flex items-start gap-2 text-xs">
                  <SeverityBadge severity={a.severity} />
                  <span className="text-gray-600 flex-1 leading-tight">{a.alert_type} — {a.callsign}</span>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  );
};

// ════════════════════════════════════════════════════════════════════════════
// TAB 2 — AIRCRAFT CATALOG
// ════════════════════════════════════════════════════════════════════════════
const AircraftCatalogTab = ({ data }) => {
  const { aircraft_profiles = [], flights = [] } = data;
  const [query, setQuery] = useState("");

  const flightsByCallsign = useMemo(() => {
    const m = {};
    flights.forEach(f => { m[f.callsign] = (m[f.callsign] || 0) + 1; });
    return m;
  }, [flights]);

  const profiles = useMemo(() => {
    const q = query.toLowerCase();
    return aircraft_profiles.filter(p =>
      !q ||
      (p.callsign || "").toLowerCase().includes(q) ||
      (p.operator || "").toLowerCase().includes(q) ||
      (p.primary_mission || "").toLowerCase().includes(q)
    );
  }, [aircraft_profiles, query]);

  return (
    <div className="space-y-4">
      <SearchInput value={query} onChange={setQuery} placeholder="Search callsign, operator, mission…" />
      {profiles.length === 0 ? (
        <p className="text-sm text-gray-400 text-center py-8">No aircraft match your search.</p>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
          {profiles.map(p => (
            <div key={p.callsign || p.id} className="bg-white rounded-lg shadow p-4 border-l-4 border-blue-500">
              <div className="flex justify-between items-start mb-2">
                <span className="text-lg font-bold text-gray-800">{p.callsign}</span>
                <span className="text-xs bg-gray-100 text-gray-600 px-2 py-0.5 rounded">{p.aircraft_type || "—"}</span>
              </div>
              <p className="text-xs text-gray-500 mb-1">{p.operator || "Unknown operator"}</p>
              <p className="text-sm font-medium text-blue-700 mb-3">{p.primary_mission || "Mission unknown"}</p>
              <div className="space-y-1 text-xs text-gray-500">
                <div className="flex justify-between">
                  <span>Flights recorded</span>
                  <span className="font-medium">{flightsByCallsign[p.callsign] || 0}</span>
                </div>
                <div>
                  <span className="mb-0.5 block">Confidence</span>
                  <ConfidenceBar value={p.confidence_level} />
                </div>
                {p.last_seen && (
                  <div className="flex justify-between">
                    <span>Last seen</span>
                    <span className="font-medium">{p.last_seen.slice(0, 10)}</span>
                  </div>
                )}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
};

// ════════════════════════════════════════════════════════════════════════════
// TAB 3 — FLIGHT LOG
// ════════════════════════════════════════════════════════════════════════════
const FLIGHT_COLS = [
  { label: "Callsign",     field: "callsign" },
  { label: "Date",         field: "takeoff_time" },
  { label: "Origin",       field: "origin_airport" },
  { label: "Destination",  field: "destination_airport" },
  { label: "Duration",     field: "flight_duration_minutes" },
  { label: "Max alt (ft)", field: "max_altitude_ft" },
  { label: "Mission",      field: "mission_type" },
];

const FlightLogTab = ({ data }) => {
  const { flights = [] } = data;
  const [query, setQuery] = useState("");
  const [sort, setSort] = useState({ field: "takeoff_time", dir: "desc" });

  const filtered = useMemo(() => {
    const q = query.toLowerCase();
    return flights.filter(f =>
      !q ||
      (f.callsign || "").toLowerCase().includes(q) ||
      (f.mission_type || "").toLowerCase().includes(q) ||
      (f.origin_airport || "").toLowerCase().includes(q) ||
      (f.destination_airport || "").toLowerCase().includes(q)
    );
  }, [flights, query]);

  const sorted = useMemo(() => {
    return [...filtered].sort((a, b) => {
      const av = a[sort.field] ?? "";
      const bv = b[sort.field] ?? "";
      const cmp = String(av).localeCompare(String(bv), undefined, { numeric: true });
      return sort.dir === "asc" ? cmp : -cmp;
    });
  }, [filtered, sort]);

  const toggleSort = field => {
    setSort(s => ({ field, dir: s.field === field && s.dir === "asc" ? "desc" : "asc" }));
  };

  const page = sorted.slice(0, PAGE_SIZE);

  return (
    <div className="space-y-3">
      <SearchInput value={query} onChange={setQuery} placeholder="Filter by callsign, mission, airport…" />
      <p className="text-xs text-gray-400">{sorted.length.toLocaleString()} of {flights.length.toLocaleString()} flights</p>
      <div className="overflow-x-auto bg-white rounded-lg shadow">
        <table className="min-w-full text-sm">
          <thead className="bg-gray-50 border-b border-gray-200">
            <tr>
              {FLIGHT_COLS.map(c => (
                <SortTh key={c.field} label={c.label} field={c.field} sort={sort} onSort={toggleSort} />
              ))}
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-100">
            {page.map((f, i) => (
              <tr key={f.flight_id || i} className="hover:bg-gray-50">
                <td className="px-3 py-2 font-mono font-medium text-blue-700">{f.callsign}</td>
                <td className="px-3 py-2 text-gray-600">{(f.takeoff_time || "").slice(0, 10)}</td>
                <td className="px-3 py-2 text-gray-600">{f.origin_airport || "—"}</td>
                <td className="px-3 py-2 text-gray-600">{f.destination_airport || "—"}</td>
                <td className="px-3 py-2 text-gray-600">{f.flight_duration_minutes ? `${f.flight_duration_minutes} min` : "—"}</td>
                <td className="px-3 py-2 text-gray-600">{f.max_altitude_ft ? f.max_altitude_ft.toLocaleString() : "—"}</td>
                <td className="px-3 py-2 text-gray-500 text-xs">{f.mission_type || "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
        {sorted.length > PAGE_SIZE && (
          <p className="text-xs text-gray-400 text-center py-2">
            Showing first {PAGE_SIZE} of {sorted.length} results
          </p>
        )}
      </div>
    </div>
  );
};

// ════════════════════════════════════════════════════════════════════════════
// TAB 4 — INTELLIGENCE ANALYSIS
// ════════════════════════════════════════════════════════════════════════════
const SEVERITY_ORDER = ["ALL", "CRITICAL", "HIGH", "MEDIUM", "LOW", "INFO"];

const IntelligenceTab = ({ data }) => {
  const { alerts = [], anomalies = [] } = data;
  const [severityFilter, setSeverityFilter] = useState("ALL");

  const alertCounts = useMemo(() => {
    const c = {};
    alerts.forEach(a => { c[a.severity] = (c[a.severity] || 0) + 1; });
    return c;
  }, [alerts]);

  const filtered = useMemo(() => {
    const subset = severityFilter === "ALL" ? alerts : alerts.filter(a => a.severity === severityFilter);
    return [...subset].sort((a, b) => (b.triggered_at || "").localeCompare(a.triggered_at || ""));
  }, [alerts, severityFilter]);

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap gap-2">
        {SEVERITY_ORDER.map(s => (
          <button key={s} onClick={() => setSeverityFilter(s)}
            className={`px-3 py-1 rounded-full text-xs font-medium transition-colors ${
              severityFilter === s ? "bg-blue-600 text-white" : "bg-gray-100 text-gray-600 hover:bg-gray-200"
            }`}>
            {s}{s !== "ALL" && alertCounts[s] ? ` (${alertCounts[s]})` : ""}
          </button>
        ))}
      </div>

      {filtered.length === 0 ? (
        <p className="text-sm text-gray-400 text-center py-8">No alerts at this severity level.</p>
      ) : (
        <div className="space-y-2">
          {filtered.map((a, i) => (
            <div key={a.alert_id || i}
              className={`bg-white rounded-lg shadow p-3 border-l-4 ${severityStyle(a.severity, "border")}`}>
              <div className="flex items-center gap-2 mb-1">
                <SeverityBadge severity={a.severity} />
                <span className="text-xs font-semibold text-gray-700">{a.alert_type}</span>
                <span className="ml-auto text-xs font-mono text-blue-600">{a.callsign}</span>
              </div>
              <p className="text-xs text-gray-600">{a.description}</p>
              {a.triggered_at && (
                <p className="text-xs text-gray-400 mt-1">{a.triggered_at.slice(0, 19).replace("T", " ")} UTC</p>
              )}
            </div>
          ))}
        </div>
      )}

      {anomalies.length > 0 && (
        <div className="mt-4">
          <h3 className="text-sm font-semibold text-gray-700 mb-2">GIS anomalies</h3>
          <div className="bg-white rounded-lg shadow overflow-hidden">
            <table className="min-w-full text-xs">
              <thead className="bg-gray-50">
                <tr>
                  <th className="px-3 py-2 text-left text-gray-500">Flight</th>
                  <th className="px-3 py-2 text-left text-gray-500">Type</th>
                  <th className="px-3 py-2 text-left text-gray-500">Detail</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-100">
                {anomalies.slice(0, 50).map((a, i) => (
                  <tr key={a.anomaly_id || i}>
                    <td className="px-3 py-1.5 font-mono text-blue-700">{a.flight_id}</td>
                    <td className="px-3 py-1.5 text-gray-600">{a.anomaly_type}</td>
                    <td className="px-3 py-1.5 text-gray-500">{a.description}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
};

// ════════════════════════════════════════════════════════════════════════════
// TAB 5 — FR24 REVIEW QUEUE
// ════════════════════════════════════════════════════════════════════════════
const FR24_QUEUE_LOCALSTORAGE_KEY = "fr24_dashboard_queue_state_v1";

const FR24_ALLOWED_QUEUE_STATUSES = [
  "dashboard_review_open",
  "dashboard_review_deferred",
  "dashboard_review_rejected",
  "dashboard_review_accepted_after_manual_review",
];

const FR24_TIER_LABEL = {
  1: "Field disagreement",
  2: "Fusion conflict",
  3: "Manual review",
  4: "Duplicate review",
  5: "Metadata gap",
  6: "OCR failure",
};

const FR24_TIER_STYLE = {
  1: "bg-red-600 text-white",
  2: "bg-red-400 text-white",
  3: "bg-yellow-400 text-gray-900",
  4: "bg-blue-400 text-white",
  5: "bg-purple-400 text-white",
  6: "bg-gray-400 text-white",
};

const FR24_QUEUE_STATUS_LABEL = {
  dashboard_review_open: "Open",
  dashboard_review_deferred: "Deferred",
  dashboard_review_rejected: "Rejected",
  dashboard_review_accepted_after_manual_review: "Accepted after manual review",
};

const FR24_QUEUE_STATUS_STYLE = {
  dashboard_review_open: "bg-blue-100 text-blue-800 border-blue-200",
  dashboard_review_deferred: "bg-yellow-100 text-yellow-800 border-yellow-200",
  dashboard_review_rejected: "bg-red-100 text-red-800 border-red-200",
  dashboard_review_accepted_after_manual_review: "bg-green-100 text-green-800 border-green-200",
};

const fr24RowIdentity = (row) =>
  row.candidate_id || row.image_path || row.image_name || "";

const fr24LoadLocalState = () => {
  try {
    const raw = window.localStorage.getItem(FR24_QUEUE_LOCALSTORAGE_KEY);
    return raw ? JSON.parse(raw) : {};
  } catch (e) {
    return {};
  }
};

const fr24SaveLocalState = (state) => {
  try {
    window.localStorage.setItem(FR24_QUEUE_LOCALSTORAGE_KEY, JSON.stringify(state));
  } catch (e) {
    // localStorage may be unavailable (private mode, quota) — fall back to in-memory only.
  }
};

const FR24EmptyState = ({ children }) => (
  <div className="bg-white rounded-lg shadow p-6 text-center text-sm text-gray-500">
    {children}
  </div>
);

const ReviewQueueTab = ({ fr24 }) => {
  if (!fr24 || !Array.isArray(fr24.rows)) {
    return (
      <FR24EmptyState>
        <p className="font-semibold text-gray-700 mb-2">FR24 review queue not loaded</p>
        <p>Generate it with:</p>
        <code className="block mt-2 bg-gray-100 px-3 py-2 rounded text-xs">
          python fr24_dashboard_data.py
        </code>
        <p className="mt-2 text-xs">Then refresh this page.</p>
      </FR24EmptyState>
    );
  }

  const rows = fr24.rows;
  const [tierFilter, setTierFilter] = useState("ALL");
  const [sourceFilter, setSourceFilter] = useState("ALL");
  const [localState, setLocalState] = useState(fr24LoadLocalState);

  const setRowStatus = (identity, status) => {
    if (!identity) return;
    setLocalState(prev => {
      const next = { ...prev };
      if (!status || status === "dashboard_review_open") {
        delete next[identity];
      } else {
        next[identity] = status;
      }
      fr24SaveLocalState(next);
      return next;
    });
  };

  const resetAll = () => {
    if (Object.keys(localState).length === 0) return;
    setLocalState({});
    fr24SaveLocalState({});
  };

  const tierValues = useMemo(() => {
    const seen = new Set();
    rows.forEach(r => seen.add(String(r.priority_tier ?? "")));
    return ["ALL", ...[...seen].filter(Boolean).sort()];
  }, [rows]);

  const sourceValues = useMemo(() => {
    const seen = new Set();
    rows.forEach(r => seen.add(r.queue_source || ""));
    return ["ALL", ...[...seen].filter(Boolean).sort()];
  }, [rows]);

  const filtered = useMemo(() => {
    return rows.filter(r => {
      if (tierFilter !== "ALL" && String(r.priority_tier ?? "") !== tierFilter) return false;
      if (sourceFilter !== "ALL" && (r.queue_source || "") !== sourceFilter) return false;
      return true;
    });
  }, [rows, tierFilter, sourceFilter]);

  const generatedAt = fr24.generated_at
    ? new Date(fr24.generated_at).toLocaleString()
    : "—";

  return (
    <div className="space-y-4">
      <div className="bg-amber-50 border-l-4 border-amber-400 px-4 py-3 rounded">
        <p className="text-sm font-semibold text-amber-900">Candidates only — no events are confirmed.</p>
        <p className="text-xs text-amber-800 mt-1">
          State transitions live in this browser only and never write a <code>confirmed*</code>,
          <code> verified_event</code>, or <code> validated_aircraft_event</code> label.
        </p>
      </div>

      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <StatCard label="Queue rows"           value={rows.length}                       icon="alert" />
        <StatCard label="Visible"              value={filtered.length}                   icon="search" sub={`tier ${tierFilter} · source ${sourceFilter}`} />
        <StatCard label="Local state entries"  value={Object.keys(localState).length}    icon="shield" sub="(browser-only)" />
        <StatCard label="Generated"            value={fr24.row_count ?? rows.length}     icon="clock" sub={generatedAt} />
      </div>

      <div className="bg-white rounded-lg shadow p-4 space-y-3">
        <div>
          <p className="text-xs font-semibold text-gray-600 mb-2">Tier</p>
          <div className="flex flex-wrap gap-2">
            {tierValues.map(t => (
              <button key={`tier-${t}`} onClick={() => setTierFilter(t)}
                className={`px-3 py-1 rounded-full text-xs font-medium transition-colors ${
                  tierFilter === t ? "bg-blue-600 text-white" : "bg-gray-100 text-gray-600 hover:bg-gray-200"
                }`}>
                {t === "ALL" ? "ALL" : `T${t} · ${FR24_TIER_LABEL[Number(t)] || t}`}
              </button>
            ))}
          </div>
        </div>
        <div>
          <p className="text-xs font-semibold text-gray-600 mb-2">Source</p>
          <div className="flex flex-wrap gap-2">
            {sourceValues.map(s => (
              <button key={`src-${s}`} onClick={() => setSourceFilter(s)}
                className={`px-3 py-1 rounded-full text-xs font-medium transition-colors ${
                  sourceFilter === s ? "bg-blue-600 text-white" : "bg-gray-100 text-gray-600 hover:bg-gray-200"
                }`}>
                {s}
              </button>
            ))}
          </div>
        </div>
        {Object.keys(localState).length > 0 && (
          <div className="flex justify-end">
            <button onClick={resetAll} className="text-xs text-blue-600 hover:underline">
              Reset all local transitions
            </button>
          </div>
        )}
      </div>

      {filtered.length === 0 ? (
        <FR24EmptyState>No rows match the current filters.</FR24EmptyState>
      ) : (
        <div className="space-y-2">
          {filtered.slice(0, PAGE_SIZE).map((r, i) => {
            const identity = fr24RowIdentity(r);
            const baseStatus = r.queue_status || "dashboard_review_open";
            const status = localState[identity] || baseStatus;
            const tier = Number(r.priority_tier);
            const tierBadge = FR24_TIER_STYLE[tier] || "bg-gray-300 text-gray-800";
            const statusBadge = FR24_QUEUE_STATUS_STYLE[status] || "bg-gray-100 text-gray-700 border-gray-200";
            return (
              <div key={identity || i} className="bg-white rounded-lg shadow p-3 border-l-4 border-gray-200">
                <div className="flex flex-wrap items-center gap-2 mb-1">
                  <span className={`px-2 py-0.5 rounded text-xs font-semibold ${tierBadge}`}>
                    T{r.priority_tier} · {FR24_TIER_LABEL[tier] || "—"}
                  </span>
                  <span className="px-2 py-0.5 rounded text-xs font-semibold bg-gray-100 text-gray-700">
                    score {r.priority_score ?? "—"}
                  </span>
                  <span className="text-xs font-mono text-blue-700 truncate max-w-md">
                    {r.image_name || r.image_path || identity}
                  </span>
                  <span className="ml-auto text-xs text-gray-400">{r.queue_source || "—"}</span>
                </div>
                <div className="grid grid-cols-1 md:grid-cols-3 gap-1 text-xs text-gray-600 mb-2">
                  <div><span className="text-gray-400">review:</span> {r.review_status || "—"}</div>
                  <div><span className="text-gray-400">selection:</span> {r.selection_status || "—"}</div>
                  <div><span className="text-gray-400">dedup:</span> {r.dedup_status || "—"}</div>
                </div>
                <div className="flex flex-wrap items-center gap-2">
                  <span className={`px-2 py-0.5 rounded text-xs font-medium border ${statusBadge}`}>
                    {FR24_QUEUE_STATUS_LABEL[status] || status}
                  </span>
                  {FR24_ALLOWED_QUEUE_STATUSES.filter(s => s !== status).map(s => (
                    <button key={`btn-${identity}-${s}`} onClick={() => setRowStatus(identity, s)}
                      className="px-2 py-0.5 text-xs rounded border border-gray-200 text-gray-600 hover:bg-gray-50">
                      → {FR24_QUEUE_STATUS_LABEL[s] || s}
                    </button>
                  ))}
                </div>
              </div>
            );
          })}
          {filtered.length > PAGE_SIZE && (
            <p className="text-xs text-gray-400 text-center py-2">
              Showing first {PAGE_SIZE} of {filtered.length} rows
            </p>
          )}
        </div>
      )}
    </div>
  );
};

// ════════════════════════════════════════════════════════════════════════════
// ROOT APP
// ════════════════════════════════════════════════════════════════════════════
const TABS = [
  { id: "overview",  label: "Overview",              Component: OverviewTab },
  { id: "catalog",   label: "Aircraft Catalog",       Component: AircraftCatalogTab },
  { id: "flightlog", label: "Flight Log",             Component: FlightLogTab },
  { id: "intel",     label: "Intelligence Analysis",  Component: IntelligenceTab },
  { id: "fr24queue", label: "FR24 Review Queue",      Component: ReviewQueueTab },
];

const App = ({ data = window.flightData || {}, fr24 = window.fr24DashboardData || null }) => {
  const [tab, setTab] = useState("overview");

  const exportedAt = data.exported_at
    ? new Date(data.exported_at).toLocaleString()
    : "—";

  const ActiveTab = TABS.find(t => t.id === tab)?.Component || OverviewTab;

  return (
    <div className="min-h-screen bg-gray-100 font-sans">
      <header className="bg-gray-900 text-white px-6 py-3 flex items-center justify-between shadow">
        <div className="flex items-center gap-3">
          <Icon name="shield" size={22} className="text-blue-400" />
          <div>
            <h1 className="text-base font-bold leading-tight">Puerto Rico Airspace Intelligence</h1>
            <p className="text-xs text-gray-400">FlightRadar24 analysis pipeline</p>
          </div>
        </div>
        <span className="text-xs text-gray-500">Exported: {exportedAt}</span>
      </header>

      <div className="bg-gray-50 border-b border-gray-200 px-6 flex gap-1">
        {TABS.map(t => (
          <TabButton key={t.id} label={t.label} active={tab === t.id} onClick={() => setTab(t.id)} />
        ))}
      </div>

      <main className="max-w-7xl mx-auto px-6 py-6">
        <ActiveTab data={data} fr24={fr24} />
      </main>
    </div>
  );
};

if (typeof document !== "undefined" && document.getElementById("root")) {
  ReactDOM.render(<App />, document.getElementById("root"));
}
