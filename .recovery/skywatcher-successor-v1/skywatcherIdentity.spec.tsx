import { adjudicateObservationIdentity, assessRlsmReadiness } from "./skywatcherIdentity";

describe("Skywatcher observation identity and RLSM gates", () => {
  it("binds observation to NORAD only with exact authoritative evidence", () => {
    const r = adjudicateObservationIdentity({
      observationId: "obs-1",
      noradCatalogId: "49277",
      authoritativeBindingSourceSha256: "b".repeat(64),
      exactIdentifierMatch: true,
      nameOnlyMatch: false,
      timeProximityOnly: false,
      distanceProximityOnly: false,
    });
    expect(r.disposition).toBe("BOUND");
  });

  it("does not bind from name only", () => {
    const r = adjudicateObservationIdentity({
      observationId: "obs-1",
      noradCatalogId: "49277",
      authoritativeBindingSourceSha256: null,
      exactIdentifierMatch: false,
      nameOnlyMatch: true,
      timeProximityOnly: false,
      distanceProximityOnly: false,
    });
    expect(r.disposition).toBe("CANDIDATE_NOT_IDENTITY");
    expect(r.reasons).toContain("NAME_ONLY_FORBIDDEN");
  });

  it("does not bind from time proximity only", () => {
    const r = adjudicateObservationIdentity({
      observationId: "obs-1",
      noradCatalogId: "49277",
      authoritativeBindingSourceSha256: null,
      exactIdentifierMatch: false,
      nameOnlyMatch: false,
      timeProximityOnly: true,
      distanceProximityOnly: false,
    });
    expect(r.disposition).toBe("CANDIDATE_NOT_IDENTITY");
  });

  it("does not bind from distance proximity only", () => {
    const r = adjudicateObservationIdentity({
      observationId: "obs-1",
      noradCatalogId: "49277",
      authoritativeBindingSourceSha256: null,
      exactIdentifierMatch: false,
      nameOnlyMatch: false,
      timeProximityOnly: false,
      distanceProximityOnly: true,
    });
    expect(r.disposition).toBe("CANDIDATE_NOT_IDENTITY");
  });

  it("blocks RLSM when AircraftProfiles is absent", () => {
    const r = assessRlsmReadiness({
      aircraftProfilesPresent: false,
      spatialClassesPresent: 3,
      requiredSpatialClasses: 3,
      sourceHashesComplete: true,
    });
    expect(r.state).toBe("BLOCKED");
    expect(r.reasons).toContain("AIRCRAFT_PROFILES_MISSING");
  });

  it("blocks RLSM when spatial classes are incomplete", () => {
    const r = assessRlsmReadiness({
      aircraftProfilesPresent: true,
      spatialClassesPresent: 2,
      requiredSpatialClasses: 3,
      sourceHashesComplete: true,
    });
    expect(r.state).toBe("BLOCKED");
  });

  it("passes RLSM only when profiles, classes and hashes close", () => {
    const r = assessRlsmReadiness({
      aircraftProfilesPresent: true,
      spatialClassesPresent: 3,
      requiredSpatialClasses: 3,
      sourceHashesComplete: true,
    });
    expect(r.state).toBe("PASS");
  });
});
