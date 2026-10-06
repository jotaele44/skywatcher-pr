import { assessAcquisition, applicationPassDoesNotCertifyAcquisition } from "./skywatcherAcquisition";

describe("Skywatcher acquisition plane", () => {
  const base = {
    provider: "CNEOS" as const,
    sourceId: "cneos-cad",
    sha256: "a".repeat(64),
    retrievedAt: "2026-10-01T00:00:00Z",
    rowCount: 472,
    credentialsRequired: false,
    credentialsPresent: false,
    parserContractVersion: "1.0",
  };

  it("certifies a complete immutable source snapshot", () => {
    expect(assessAcquisition(base).state).toBe("CERTIFIED");
  });

  it("blocks a credentialed provider when credentials are deferred", () => {
    const result = assessAcquisition({ ...base, provider: "SPACE_TRACK", credentialsRequired: true });
    expect(result.state).toBe("BLOCKED");
    expect(result.reasons).toContain("CREDENTIALS_BLOCKED");
  });

  it("does not certify a source without immutable bytes", () => {
    expect(assessAcquisition({ ...base, sha256: null }).state).toBe("PROVISIONAL");
  });

  it("requires a parser contract", () => {
    expect(assessAcquisition({ ...base, parserContractVersion: null }).reasons).toContain("PARSER_CONTRACT_MISSING");
  });

  it("keeps application PASS separate from acquisition OPEN", () => {
    const open = assessAcquisition({ ...base, provider: "SPACE_TRACK", credentialsRequired: true });
    const result = applicationPassDoesNotCertifyAcquisition(true, [assessAcquisition(base), open]);
    expect(result.applicationPlane).toBe("PASS");
    expect(result.acquisitionPlane).toBe("OPEN");
  });
});
