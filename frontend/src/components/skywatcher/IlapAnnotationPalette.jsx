import React from "react";

const DEFAULT_CLASSES = [
  { id: "vegetation_palm", label: "Vegetation / Palm", color: "#009E73" },
  { id: "roof_building", label: "Roof / Building", color: "#0072B2" },
  { id: "managed_land_earthwork", label: "Managed Land / Earthwork", color: "#D55E00" },
  { id: "water_hydrography", label: "Water / Hydrography", color: "#56B4E9" },
  { id: "vehicles_parking", label: "Vehicles / Parking", color: "#E69F00" },
  { id: "roads_access", label: "Roads / Access", color: "#F0E442" },
  { id: "utilities_infrastructure", label: "Utilities / Infrastructure", color: "#CC79A7" },
  { id: "quarry_excavation", label: "Quarry / Excavation", color: "#8B6F47" },
  { id: "artifact_ui_unresolved", label: "Artifact / UI / Unresolved", color: "#777777" },
  { id: "control_reference", label: "Control / Reference", color: "#FFFFFF" },
];

export default function IlapAnnotationPalette({
  value,
  onChange,
  classes = DEFAULT_CLASSES,
  disabled = false,
}) {
  return (
    <div className="space-y-2" aria-label="ILAP annotation class palette">
      <div className="flex items-center justify-between gap-3">
        <p className="text-xs font-semibold text-foreground">Annotation class</p>
        <span className="text-[10px] text-muted-foreground">Color = UI encoding only</span>
      </div>
      <div className="grid grid-cols-2 gap-2 md:grid-cols-3">
        {classes.map((item) => {
          const selected = value === item.id;
          return (
            <button
              key={item.id}
              type="button"
              disabled={disabled}
              onClick={() => onChange?.(item.id)}
              aria-pressed={selected}
              className={`flex items-center gap-2 rounded-lg border px-2.5 py-2 text-left text-xs transition ${
                selected ? "border-foreground/60 bg-secondary" : "border-border bg-card hover:bg-secondary/50"
              } disabled:cursor-not-allowed disabled:opacity-50`}
            >
              <span
                className="h-4 w-4 shrink-0 rounded border border-black/30"
                style={{ backgroundColor: item.color }}
                aria-hidden="true"
              />
              <span className="min-w-0 truncate">{item.label}</span>
            </button>
          );
        })}
      </div>
      <p className="text-[10px] leading-relaxed text-muted-foreground">
        Evidence state must be encoded independently by outline/fill style. Analyst markup remains a derived annotation and is not ground truth.
      </p>
    </div>
  );
}

export { DEFAULT_CLASSES as ILAP_COLORBLIND_CLASSES };
