import React, { useState } from "react";
import { ChevronsRight } from "lucide-react";
import {
  BASE_LAYERS, FEATURE_LAYERS, LAYER_GROUPS, OVERLAYS, layerTitle, validateCustomTemplate,
} from "@/live/sourceCatalog";

function Check({ checked, disabled, onChange, label, hint, type = "checkbox", name }) {
  return (
    <label className={`flex items-start gap-2 py-0.5 ${disabled ? "opacity-50" : "cursor-pointer"}`} title={hint || undefined}>
      <input
        type={type}
        name={name}
        checked={checked}
        disabled={disabled}
        onChange={onChange}
        className="mt-1 h-3.5 w-3.5 shrink-0 accent-indigo-400"
      />
      <span>
        <span className="block">{label}</span>
        {hint && disabled && <span className="block text-[10px] text-amber-300">{hint}</span>}
      </span>
    </label>
  );
}

export default function LayerMenu({ settings, onChange, onClose, openaipConfigured, sourceErrors = {}, geoError = null }) {
  const [collapsed, setCollapsed] = useState({});
  const [customDraft, setCustomDraft] = useState(settings.customTemplate || "");
  const customError = customDraft ? validateCustomTemplate(customDraft) : null;
  const overlays = new Set(settings.overlays);

  const toggleOverlay = (id, on) => {
    const next = new Set(overlays);
    if (on) next.add(id);
    else next.delete(id);
    onChange({ overlays: [...next] });
  };

  const errorHint = (id) => (sourceErrors[`sw-ov-${id}`] || (settings.baseLayer === id && sourceErrors["sw-base"])) || null;

  return (
    <div className="pointer-events-auto absolute right-14 top-12 z-30 flex max-h-[calc(100%-4rem)] items-start gap-1">
      <button type="button" onClick={onClose} aria-label="Close layer menu" title="Close layer menu" className="flex h-9 w-9 items-center justify-center rounded-md border border-white/15 bg-slate-700/80 text-white shadow-md">
        <ChevronsRight className="h-4 w-4" />
      </button>
      <div role="dialog" aria-label="Map layers" className="w-64 overflow-y-auto rounded-md border border-white/10 bg-[#283048]/95 px-3 py-2 text-[13px] text-slate-100 shadow-xl scrollbar-thin" style={{ maxHeight: "calc(100vh - 9rem)" }}>
        {FEATURE_LAYERS.map((feature) => (feature.heading ? (
          <div key={feature.id} className="mt-1">
            <Check checked={settings.features[feature.id]} onChange={(e) => onChange({ features: { ...settings.features, [feature.id]: e.target.checked } })} label={<strong>{feature.title}</strong>} />
          </div>
        ) : (
          <div key={feature.id}>
            <Check checked={settings.features[feature.id]} hint={feature.description} onChange={(e) => onChange({ features: { ...settings.features, [feature.id]: e.target.checked } })} label={feature.title} />
            {feature.id === "yourPosition" && geoError && settings.features.yourPosition && (
              <p className="-mt-0.5 ml-5 text-[10px] text-amber-300">Location unavailable: {geoError}</p>
            )}
          </div>
        )))}

        {LAYER_GROUPS.map((group) => {
          const bases = BASE_LAYERS.filter((entry) => entry.group === group.id);
          const overlayEntries = OVERLAYS.filter((entry) => entry.group === group.id);
          const isCollapsed = collapsed[group.id];
          return (
            <section key={group.id} className="mt-2">
              <button type="button" className="flex w-full items-center gap-1 font-bold" aria-expanded={!isCollapsed} onClick={() => setCollapsed((c) => ({ ...c, [group.id]: !c[group.id] }))}>
                <span className="inline-block w-3 text-slate-400">{isCollapsed ? "+" : "−"}</span>{group.title}
              </button>
              {!isCollapsed && (
                <div className="ml-4">
                  {[...bases, ...overlayEntries].map((entry) => {
                    const isBase = BASE_LAYERS.includes(entry);
                    const disabled = entry.requires === "openaip_key" && !openaipConfigured;
                    const hint = disabled ? "Needs OPENAIP_API_KEY on the backend" : errorHint(entry.id) ? `Source error: ${errorHint(entry.id)}` : entry.license;
                    return isBase ? (
                      <Check key={entry.id} type="radio" name="live-base-layer" checked={settings.baseLayer === entry.id} onChange={() => onChange({ baseLayer: entry.id })} label={layerTitle(entry)} hint={hint} />
                    ) : (
                      <Check key={entry.id} checked={overlays.has(entry.id)} disabled={disabled} onChange={(e) => toggleOverlay(entry.id, e.target.checked)} label={entry.title} hint={hint} />
                    );
                  })}
                  {group.id === "custom" && (
                    <div className="space-y-1 py-1">
                      <input
                        type="url"
                        value={customDraft}
                        onChange={(e) => setCustomDraft(e.target.value)}
                        placeholder="https://…/{z}/{x}/{y}.png"
                        aria-label="Custom tile URL template"
                        className="w-full rounded border border-white/20 bg-slate-900/70 px-1.5 py-1 text-[11px]"
                      />
                      {customError && <p className="text-[10px] text-amber-300">{customError}</p>}
                      <div className="flex gap-1">
                        <button type="button" disabled={!customDraft || Boolean(customError)} onClick={() => onChange({ customTemplate: customDraft.trim(), baseLayer: "custom_tiles" })} className="rounded border border-white/20 bg-slate-700 px-2 py-0.5 text-[11px] disabled:opacity-40">Use custom tiles</button>
                        {settings.customTemplate && (
                          <Check type="radio" name="live-base-layer" checked={settings.baseLayer === "custom_tiles"} onChange={() => onChange({ baseLayer: "custom_tiles" })} label="Custom tiles" />
                        )}
                      </div>
                    </div>
                  )}
                </div>
              )}
            </section>
          );
        })}
      </div>
    </div>
  );
}
