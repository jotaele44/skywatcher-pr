import React, { useState } from "react";
import { Layers3 } from "lucide-react";
import PageHeader from "@/components/skywatcher/PageHeader";
import DiagnosticNoticeBanner from "@/components/skywatcher/DiagnosticNoticeBanner";
import Panel from "@/components/skywatcher/Panel";
import IlapAnnotationPalette from "@/components/skywatcher/IlapAnnotationPalette";
import MultiAnalystComparison from "@/components/skywatcher/MultiAnalystComparison";
import TemporalImageStackViewer from "@/components/skywatcher/TemporalImageStackViewer";
import CandidateExplainabilityPane from "@/components/skywatcher/CandidateExplainabilityPane";

export default function ILAPReviewLab() {
  const [annotationClass, setAnnotationClass] = useState("vegetation_palm");

  return (
    <div className="space-y-5">
      <PageHeader
        title="ILAP Visual Review Lab"
        subtitle="Human + machine scene annotation, temporal comparison, and explainability. Candidate review only."
        icon={Layers3}
      />
      <DiagnosticNoticeBanner />

      <div className="grid gap-5 xl:grid-cols-[minmax(0,1.25fr)_minmax(320px,0.75fr)]">
        <div className="space-y-5">
          <Panel bodyClassName="space-y-4">
            <div>
              <h2 className="text-sm font-bold text-foreground">Color-coded annotation</h2>
              <p className="mt-1 text-xs text-muted-foreground">
                Select an object class. Color is a UI encoding only; evidence state and confidence are separate fields.
              </p>
            </div>
            <IlapAnnotationPalette value={annotationClass} onChange={setAnnotationClass} />
            <div className="rounded-lg border border-dashed border-border p-4 text-xs text-muted-foreground">
              Active class: <span className="font-semibold text-foreground">{annotationClass}</span>. Image-canvas binding remains OPEN; original unmarked imagery must stay immutable when added.
            </div>
          </Panel>

          <Panel bodyClassName="space-y-4">
            <TemporalImageStackViewer frames={[]} />
          </Panel>

          <Panel bodyClassName="space-y-4">
            <MultiAnalystComparison analysts={[]} comparisons={[]} />
          </Panel>
        </div>

        <div className="space-y-5">
          <Panel bodyClassName="space-y-4">
            <CandidateExplainabilityPane candidate={null} />
          </Panel>

          <Panel bodyClassName="space-y-3">
            <h2 className="text-sm font-bold text-foreground">Calibration posture</h2>
            <ul className="space-y-1.5 text-xs text-muted-foreground">
              <li>• Palm/tree corpus: OPEN</li>
              <li>• Roof/tarp/pool/glare controls: OPEN</li>
              <li>• Vehicle baselines: OPEN</li>
              <li>• Path-network controls: OPEN</li>
              <li>• Access-friction references: OPEN</li>
              <li>• Composite ILAP thresholds: CALIBRATION_REQUIRED</li>
            </ul>
          </Panel>
        </div>
      </div>
    </div>
  );
}
