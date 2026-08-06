// Skywatcher FR24 mobile controller for Scriptable.
//
// Shortcuts remains the cross-app transaction coordinator:
//   prepare -> a-Shell Put File/Execute/Get File -> finalize.
// Scriptable validates contracts and presents results; it does not pretend that
// iOS supports a synchronous Scriptable -> a-Shell -> Scriptable callback.

const SCHEMA_VERSION = "skywatcher.fr24.mobile.v1";
const MAX_BYTES = 40 * 1024 * 1024;

function fail(code, message) {
  return {
    schema_version: SCHEMA_VERSION,
    status: "error",
    error: { code, message },
  };
}

function uuid() {
  return UUID.string();
}

function isoNow() {
  return new Date().toISOString();
}

function cleanOriginalName(value) {
  if (typeof value !== "string" || value.length === 0) return null;
  return value.replace(/[\u0000-\u001f\u007f]/g, "").slice(0, 255);
}

function prepare(parameter) {
  const item = parameter && typeof parameter === "object" ? parameter : {};
  const byteSize = Number(item.byte_size || 0);
  if (!Number.isFinite(byteSize) || byteSize <= 0) {
    return fail("missing_byte_size", "Shortcut must provide a positive input byte size.");
  }
  if (byteSize > MAX_BYTES) {
    return fail("input_exceeds_40_mib", "The selected screenshot exceeds the mobile limit.");
  }

  const runId = uuid();
  return {
    schema_version: SCHEMA_VERSION,
    status: "prepared",
    phase: "prepare",
    run_id: runId,
    received_at: isoNow(),
    source: {
      original_filename: cleanOriginalName(item.original_filename),
      declared_byte_size: byteSize,
      shortcut_content_type: item.content_type || null,
    },
    staging: {
      source_filename: "source_image",
      manifest_filename: "input_manifest.json",
      result_filename: "result.json",
      relative_root: "skywatcher-fr24",
    },
    policy: {
      bounded_mode: true,
      network_allowed: false,
      provisional_only: true,
    },
  };
}

function validateHexSha256(value) {
  return typeof value === "string" && /^[a-f0-9]{64}$/.test(value);
}

function validateResult(result, expectedRunId) {
  if (!result || typeof result !== "object") return "result_not_object";
  if (result.schema_version !== SCHEMA_VERSION) return "schema_version_mismatch";
  if (result.run_id !== expectedRunId) return "run_id_mismatch";
  if (result.status === "error") return null;
  if (!result.source || !validateHexSha256(result.source.sha256)) return "invalid_source_sha256";
  if (!result.image || !Number.isInteger(result.image.width) || !Number.isInteger(result.image.height)) {
    return "invalid_image_dimensions";
  }
  if (!result.classification || result.classification.status !== "provisional") {
    return "non_provisional_mobile_result";
  }
  if (!Array.isArray(result.unresolved_fields)) return "invalid_unresolved_fields";
  return null;
}

async function presentResult(result) {
  const alert = new Alert();
  if (result.status === "error") {
    alert.title = "Skywatcher mobile intake failed";
    alert.message = `${result.error.code}\n\nNo analytical observations were promoted.`;
  } else {
    const unresolved = result.unresolved_fields.length;
    alert.title = "Skywatcher FR24 intake complete";
    alert.message = [
      `SHA-256: ${result.source.sha256}`,
      `Image: ${result.image.width} × ${result.image.height}`,
      `Orientation: ${result.image.orientation}`,
      `Classification: provisional`,
      `Unresolved fields: ${unresolved}`,
    ].join("\n");
  }
  alert.addAction("OK");
  await alert.present();
}

async function finalize(parameter) {
  const item = parameter && typeof parameter === "object" ? parameter : {};
  const expectedRunId = item.expected_run_id;
  let result = item.result;
  if (typeof result === "string") {
    try {
      result = JSON.parse(result);
    } catch (_) {
      return fail("result_json_invalid", "a-Shell returned invalid JSON.");
    }
  }
  const error = validateResult(result, expectedRunId);
  if (error) return fail(error, "The a-Shell result failed the mobile contract.");
  if (item.present !== false) await presentResult(result);
  return {
    schema_version: SCHEMA_VERSION,
    status: result.status === "error" ? "rejected" : "accepted_provisional",
    phase: "finalize",
    result,
  };
}

async function main() {
  const parameter = args.shortcutParameter || {};
  const phase = parameter.phase || "prepare";
  let output;
  if (phase === "prepare") output = prepare(parameter);
  else if (phase === "finalize") output = await finalize(parameter);
  else output = fail("unsupported_phase", `Unsupported phase: ${phase}`);
  Script.setShortcutOutput(output);
  Script.complete();
}

await main();
