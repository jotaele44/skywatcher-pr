// Computed dashboard selectors for Skywatcher-PR diagnostic surface
export function computeMetrics(d) {
  const observations = d.observations || [];
  const exports = d.exports || [];
  const reviews = d.reviews || [];

  const totalObservations = observations.length;
  const syntheticObservations = observations.filter((o) => o.synthetic_flag).length;
  const verifiedObservations = observations.filter((o) => o.review_status === "verified").length;
  const needsReviewCount = observations.filter((o) => o.review_status === "needs_review").length;
  const highConfidence = observations.filter((o) => (o.confidence_score ?? 0) >= 0.75).length;
  const lowConfidence = observations.filter((o) => (o.confidence_score ?? 0) < 0.5).length;

  const blockedExportCount = exports.filter((e) => e.export_status === "blocked").length;
  const productionEligibleExports = exports.filter(
    (e) => e.production_eligible && !(e.export_mode === "production" && e.contains_synthetic_rows)
  ).length;
  const validTestExports = exports.filter((e) => e.export_mode === "test" && e.export_status === "valid").length;

  const manualReviewBacklog = reviews.filter((r) => r.review_status === "open" || r.review_status === "in_review").length;

  // Truth state — fixed diagnostic posture
  const hubDiscoveryReady = true;
  const hubLiveExecutionReady = false;

  return {
    totalObservations, syntheticObservations, verifiedObservations, needsReviewCount,
    highConfidence, lowConfidence, blockedExportCount, productionEligibleExports,
    validTestExports, manualReviewBacklog, hubDiscoveryReady, hubLiveExecutionReady,
    aircraftCount: (d.aircraft || []).length,
    captureCount: (d.captures || []).length,
    assetCount: (d.assets || []).length,
    routeCount: (d.routes || []).length,
  };
}