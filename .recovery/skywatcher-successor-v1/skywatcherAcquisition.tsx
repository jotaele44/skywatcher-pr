export type AcquisitionState = "CERTIFIED" | "PROVISIONAL" | "BLOCKED";
export type ProviderKind = "CNEOS" | "HORIZONS" | "SPACE_TRACK" | "NASA_JSC" | "NOAA" | "AIRCRAFT";

export interface SourceSnapshot {
  provider: ProviderKind;
  sourceId: string;
  sha256: string | null;
  retrievedAt: string | null;
  rowCount: number | null;
  credentialsRequired: boolean;
  credentialsPresent: boolean;
  parserContractVersion: string | null;
}

export interface AcquisitionAssessment {
  provider: ProviderKind;
  state: AcquisitionState;
  reasons: string[];
}

export function assessAcquisition(s: SourceSnapshot): AcquisitionAssessment {
  const reasons: string[] = [];
  if (!s.sourceId) reasons.push("SOURCE_ID_MISSING");
  if (!s.sha256 || !/^[a-f0-9]{64}$/i.test(s.sha256)) reasons.push("SOURCE_HASH_MISSING");
  if (!s.retrievedAt) reasons.push("RETRIEVED_AT_MISSING");
  if (s.rowCount === null || s.rowCount < 0) reasons.push("ROW_COUNT_MISSING");
  if (!s.parserContractVersion) reasons.push("PARSER_CONTRACT_MISSING");
  if (s.credentialsRequired && !s.credentialsPresent) reasons.push("CREDENTIALS_BLOCKED");

  const state: AcquisitionState =
    reasons.includes("CREDENTIALS_BLOCKED")
      ? "BLOCKED"
      : reasons.length
        ? "PROVISIONAL"
        : "CERTIFIED";
  return { provider: s.provider, state, reasons };
}

export function applicationPassDoesNotCertifyAcquisition(appTestsPass: boolean, assessments: AcquisitionAssessment[]) {
  return {
    applicationPlane: appTestsPass ? "PASS" : "FAIL",
    acquisitionPlane: assessments.every(a => a.state === "CERTIFIED") ? "PASS" : "OPEN",
  };
}
