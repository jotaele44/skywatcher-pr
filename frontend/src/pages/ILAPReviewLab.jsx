import React, { useEffect, useState } from "react";
import { Layers3 } from "lucide-react";
import PageHeader from "@/components/skywatcher/PageHeader";
import DiagnosticNoticeBanner from "@/components/skywatcher/DiagnosticNoticeBanner";
import Panel from "@/components/skywatcher/Panel";
import IlapAnnotationPalette from "@/components/skywatcher/IlapAnnotationPalette";
import MultiAnalystComparison from "@/components/skywatcher/MultiAnalystComparison";
import TemporalImageStackViewer from "@/components/skywatcher/TemporalImageStackViewer";
import CandidateExplainabilityPane from "@/components/skywatcher/CandidateExplainabilityPane";
import { federation } from "@/api/federationClient";

export default function ILAPReviewLab() {
  const [annotationClass, setAnnotationClass] = useState("vegetation_palm");
  const [review, setReview] = useState({
    candidate: null, frames: [], analysts: [], annotations: [], comparisons: [],
    availability: { candidate: "OPEN", frames: "OPEN", annotations: "OPEN", comparisons: "OPEN" },
  });
  const [loadError, setLoadError] = useState(null);

  useEffect(() => {
    let active = true;
    federation.ilap.review()
      .then((payload) => { if (active) setReview(payload); })
      .catch((error) => { if (active) setLoadError(error); });
    return () => { active = false; };
  }, []);

  const saveAnnotation = async (className) => {
    setAnnotationClass(className);
    if (!review.candidate?.candidate_id || !review.frames?.[0]?.frame_id) return;
    const created = await federation.entities.ILAPReviewAnnotations.create({
      candidate_id: review.candidate.candidate_id,
      source_frame_id: review.frames[0].frame_id,
      class_name: className,
      actor_type: "HUMAN",
      evidence_state: "REVIEW_UNRESOLVED",
      coordinate_space: "FRAME_UNBOUND",
      geometry: null,
      derived_annotation: true,
      created_at: new Date().toISOString(),
    });
    setReview((current) => ({
      ...current,
      annotations: [created, ...(current.annotations || [])],
      availability: { ...current.availability, annotations: "AVAILABLE" },
    }));
  };

  return (
    <div className="space-y-5">
      <PageHeader title="ILAP Visual Review Lab" subtitle="Human + machine scene annotation, temporal comparison, and explainability. Candidate review only." icon={Layers3} />
      <DiagnosticNoticeBanner />
      {loadError && <div className="rounded-lg border border-destructive/40 p-3 text-xs text-destructive">ILAP review payload unavailable: {loadError.message}</div>}

      <div className="grid gap-5 xl:grid-cols-[minmax(0,1.25fr)_minmax(320px,0.75fr)]">
        <div className="space-y-5">
          <Panel bodyClassName="space-y-4">
            <div>
              <h2 className="text-sm font-bold text-foreground">Color-coded annotation</h2>
              <p className="mt-1 text-xs text-muted-foreground">Select an object class. Color is a UI encoding only; evidence state and confidence are separate fields.</p>
            </div>
            <IlapAnnotationPalette value={annotationClass} onChange={saveAnnotation} disabled={!review.candidate || !review.frames?.length} />
            <div className="rounded-lg border border-dashed border-border p-4 text-xs text-muted-foreground">
              Active class: <span className="font-semibold text-foreground">{annotationClass}</span>. Annotation remains disabled until a real candidate and source frame are available; source imagery stays immutable.
            </div>
          </Panel>

          <Panel bodyClassName="space-y-4"><TemporalImageStackViewer frames={review.frames || []} /></Panel>
          <Panel bodyClassName="space-y-4"><MultiAnalystComparison analysts={review.analysts || []} comparisons={review.comparisons || []} /></Panel>
        </div>

        <div className="space-y-5">
          <Panel bodyClassName="space-y-4"><CandidateExplainabilityPane candidate={review.candidate} /></Panel>
          <Panel bodyClassName="space-y-3">
            <h2 className="text-sm font-bold text-foreground">Evidence availability</h2>
            <ul className="space-y-1.5 text-xs text-muted-foreground">
              {Object.entries(review.availability || {}).map(([key, state]) => <li key={key}>• {key}: {state}</li>)}
            </ul>
          </Panel>
        </div>
      </div>
    </div>
  );
}
