export type IdentityDisposition = "BOUND" | "CANDIDATE_NOT_IDENTITY" | "UNRESOLVED";

export interface ObservationIdentityEvidence {
  observationId: string;
  noradCatalogId: string | null;
  authoritativeBindingSourceSha256: string | null;
  exactIdentifierMatch: boolean;
  nameOnlyMatch: boolean;
  timeProximityOnly: boolean;
  distanceProximityOnly: boolean;
}

export function adjudicateObservationIdentity(e: ObservationIdentityEvidence) {
  const reasons: string[] = [];
  if (!e.observationId) reasons.push("OBSERVATION_ID_MISSING");
  if (!e.noradCatalogId) reasons.push("NORAD_ID_MISSING");
  if (!e.authoritativeBindingSourceSha256) reasons.push("AUTHORITATIVE_BINDING_MISSING");
  if (e.nameOnlyMatch) reasons.push("NAME_ONLY_FORBIDDEN");
  if (e.timeProximityOnly) reasons.push("TIME_PROXIMITY_ONLY_FORBIDDEN");
  if (e.distanceProximityOnly) reasons.push("DISTANCE_PROXIMITY_ONLY_FORBIDDEN");

  if (
    e.observationId &&
    e.noradCatalogId &&
    e.exactIdentifierMatch &&
    e.authoritativeBindingSourceSha256 &&
    /^[a-f0-9]{64}$/i.test(e.authoritativeBindingSourceSha256)
  ) {
    return { disposition: "BOUND" as IdentityDisposition, reasons };
  }

  const candidateEvidence = Boolean(e.noradCatalogId || e.nameOnlyMatch || e.timeProximityOnly || e.distanceProximityOnly);
  return {
    disposition: candidateEvidence ? "CANDIDATE_NOT_IDENTITY" as IdentityDisposition : "UNRESOLVED" as IdentityDisposition,
    reasons,
  };
}

export interface RlsmReadiness {
  aircraftProfilesPresent: boolean;
  spatialClassesPresent: number;
  requiredSpatialClasses: number;
  sourceHashesComplete: boolean;
}

export function assessRlsmReadiness(r: RlsmReadiness) {
  const reasons: string[] = [];
  if (!r.aircraftProfilesPresent) reasons.push("AIRCRAFT_PROFILES_MISSING");
  if (r.spatialClassesPresent < r.requiredSpatialClasses) reasons.push("SPATIAL_CLASSES_INCOMPLETE");
  if (!r.sourceHashesComplete) reasons.push("SOURCE_HASHES_INCOMPLETE");
  return { state: reasons.length ? "BLOCKED" : "PASS", reasons };
}
