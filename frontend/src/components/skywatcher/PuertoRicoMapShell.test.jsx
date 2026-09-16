import { describe, expect, it } from "vitest";

import { parseObservationDensityGeojson } from "@/lib/observation-density";

const validDensity = {
  type: "FeatureCollection",
  features: [
    {
      type: "Feature",
      properties: { name: "San Juan", observation_count: 2, observation_density_norm: 1 },
      geometry: null,
    },
  ],
  matched_count: 2,
  unmatched_observations: 1,
  unresolved_by_name: { Outside: 1 },
  total_observations: 3,
  ambiguous_municipio_candidates: {},
  scope: {
    state: "CANDIDATE_NOT_IDENTITY",
    source_field: "municipality",
    target_field: "name",
    matching: "EXACT_RAW_STRING",
    normalization: "NONE",
    identity_effect: "NONE",
    binding_effect: "AGGREGATION_ONLY",
    geometry_effect: "NONE",
  },
};

describe("municipio observation density contract", () => {
  it("closes feature and total arithmetic without granting identity", () => {
    expect(parseObservationDensityGeojson(validDensity)).toMatchObject({
      matchedCount: 2,
      unmatchedCount: 1,
      totalObservations: 3,
      scopeState: "CANDIDATE_NOT_IDENTITY",
    });
  });

  it("rejects mismatched arithmetic and any binding promotion", () => {
    expect(() => parseObservationDensityGeojson({ ...validDensity, matched_count: 1 })).toThrow("feature count sum");
    expect(() => parseObservationDensityGeojson({
      ...validDensity,
      scope: { ...validDensity.scope, binding_effect: "CANONICAL_BINDING" },
    })).toThrow("scope.binding_effect must be AGGREGATION_ONLY");
    expect(() => parseObservationDensityGeojson({
      ...validDensity,
      unresolved_by_name: { Outside: 0 },
    })).toThrow("unresolved_by_name does not equal unmatched_observations");
  });
});
