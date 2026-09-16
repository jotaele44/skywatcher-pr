function objectValue(value, field) {
  if (!value || typeof value !== "object" || Array.isArray(value)) throw new Error(`${field} must be an object`);
  return value;
}

function nonNegativeInteger(value, field) {
  if (!Number.isInteger(value) || value < 0) throw new Error(`${field} must be a non-negative integer`);
  return value;
}

function requireValue(value, expected, field) {
  if (value !== expected) throw new Error(`${field} must be ${expected}`);
}

export function parseObservationDensityGeojson(value) {
  const body = objectValue(value, "density response");
  if (body.type !== "FeatureCollection" || !Array.isArray(body.features)) {
    throw new Error("density response must be a FeatureCollection");
  }
  const featureCount = body.features.reduce((sum, feature, index) => {
    const featureObject = objectValue(feature, `features.${index}`);
    const properties = objectValue(featureObject.properties, `features.${index}.properties`);
    const density = properties.observation_density_norm;
    if (!Number.isFinite(density) || density < 0 || density > 1) {
      throw new Error(`features.${index}.properties.observation_density_norm must be between 0 and 1`);
    }
    return sum + nonNegativeInteger(properties.observation_count, `features.${index}.properties.observation_count`);
  }, 0);
  const matchedCount = nonNegativeInteger(body.matched_count, "matched_count");
  const unmatchedCount = nonNegativeInteger(body.unmatched_observations, "unmatched_observations");
  const totalObservations = nonNegativeInteger(body.total_observations, "total_observations");
  if (featureCount !== matchedCount) throw new Error("matched_count does not equal the feature count sum");
  if (matchedCount + unmatchedCount !== totalObservations) throw new Error("density arithmetic does not close");
  const unresolvedByName = objectValue(body.unresolved_by_name, "unresolved_by_name");
  const unresolvedCount = Object.entries(unresolvedByName).reduce(
    (sum, [name, count]) => sum + nonNegativeInteger(count, `unresolved_by_name.${name}`),
    0,
  );
  if (unresolvedCount !== unmatchedCount) {
    throw new Error("unresolved_by_name does not equal unmatched_observations");
  }
  objectValue(body.ambiguous_municipio_candidates, "ambiguous_municipio_candidates");
  const scope = objectValue(body.scope, "scope");
  requireValue(scope.state, "CANDIDATE_NOT_IDENTITY", "scope.state");
  requireValue(scope.source_field, "municipality", "scope.source_field");
  requireValue(scope.target_field, "name", "scope.target_field");
  requireValue(scope.matching, "EXACT_RAW_STRING", "scope.matching");
  requireValue(scope.normalization, "NONE", "scope.normalization");
  requireValue(scope.identity_effect, "NONE", "scope.identity_effect");
  requireValue(scope.binding_effect, "AGGREGATION_ONLY", "scope.binding_effect");
  requireValue(scope.geometry_effect, "NONE", "scope.geometry_effect");
  return {
    data: body,
    matchedCount,
    unmatchedCount,
    totalObservations,
    scopeState: scope.state,
  };
}
