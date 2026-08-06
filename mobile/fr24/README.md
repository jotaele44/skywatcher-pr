# Skywatcher FR24 mobile intake

This directory defines a bounded iOS intake path:

```text
Photos / Share Sheet
  -> Apple Shortcuts
  -> Scriptable prepare phase
  -> a-Shell Put File + Execute Command + Get File
  -> Scriptable finalize phase
  -> Files / Quick Look
```

## Scope

Mobile v1 establishes source custody and validates PNG/JPEG headers, dimensions,
size, run identity, and the result contract. It intentionally performs no OCR,
aircraft identification, map geolocation, marker extraction, or RLSM database
promotion. All such fields remain explicitly unresolved.

The desktop RLSM pipeline remains authoritative for analytical observations.

## Why Shortcuts coordinates the transaction

Scriptable cannot reliably launch a-Shell, wait for it to finish, and recover a
result in one synchronous call. Shortcuts has native a-Shell actions and is the
only reliable coordinator across both application sandboxes. Scriptable still
owns the input/result contracts, run identity, validation, and presentation.

## Install

1. In Scriptable, create a script named `SkywatcherFR24Controller` and paste
   `SkywatcherFR24Controller.js` into it.
2. In a-Shell, create:

   ```text
   ~/shortcuts/skywatcher-fr24/app/
   ~/shortcuts/skywatcher-fr24/input/
   ~/shortcuts/skywatcher-fr24/output/
   ```

3. Copy `analyze_fr24_mobile.py` to:

   ```text
   ~/shortcuts/skywatcher-fr24/app/analyze_fr24_mobile.py
   ```

4. Copy `run_fr24_mobile.sh` to:

   ```text
   ~/shortcuts/skywatcher-fr24/app/run_fr24_mobile.sh
   ```

5. In a-Shell, run:

   ```sh
   chmod +x ~/shortcuts/skywatcher-fr24/app/run_fr24_mobile.sh
   ```

## Shortcut contract

Create a Shortcut named **Skywatcher FR24 Intake**. Enable **Show in Share
Sheet** and accept Images and Files.

### Input selection

1. Receive Shortcut Input.
2. If there is no input, use **Select Photos**, limit one.
3. Get the file name, file size, and content type.
4. Reject multiple inputs.

### Scriptable prepare phase

Run `SkywatcherFR24Controller` with a Dictionary:

```json
{
  "phase": "prepare",
  "original_filename": "IMG_1234.PNG",
  "byte_size": 1234567,
  "content_type": "public.png"
}
```

Stop immediately unless `status` equals `prepared`. Preserve `run_id` and the
complete returned Dictionary.

Convert that returned Dictionary to JSON text. This is the input manifest.

### Fixed a-Shell staging

Use a-Shell **Put File** actions to write exactly:

```text
~/shortcuts/skywatcher-fr24/input/source_image
~/shortcuts/skywatcher-fr24/input/input_manifest.json
```

The original filename is metadata only. It is never used in a command line.

Run the following using a-Shell **Execute Command**, configured **In App**:

```sh
sh ~/shortcuts/skywatcher-fr24/app/run_fr24_mobile.sh
```

The command is intentionally constant. Do not append Shortcut input or user
text.

Use a-Shell **Get File** to retrieve:

```text
~/shortcuts/skywatcher-fr24/output/result.json
```

Read it as text, then parse it as JSON.

### Scriptable finalize phase

Run the same Scriptable script with:

```json
{
  "phase": "finalize",
  "expected_run_id": "THE_PREPARE_RUN_ID",
  "result": "THE_RESULT_JSON_TEXT",
  "present": true
}
```

Accept only `accepted_provisional`. Any other status is a failed intake and must
not be promoted into a desktop database.

### Save package

Save the following under a run-specific Files directory:

```text
Skywatcher/FR24-Mobile/<run_id>/
  input_manifest.json
  result.json
  source_image
```

Do not rename `source_image` before hashing. The original name remains in the
manifest.

## Cancellation and errors

| Condition | Required behavior |
|---|---|
| User cancels photo selection | Exit without creating a run |
| More than one input | Reject before Scriptable prepare |
| Input over 40 MiB | Scriptable returns `input_exceeds_40_mib` |
| Non-PNG/JPEG | Analyzer writes `unsupported_image_format` |
| Invalid dimensions | Analyzer writes a deterministic dimension error |
| Missing a-Shell files | Runner exits 66 |
| Analyzer error | Result contains zero observations |
| Run ID mismatch | Scriptable rejects the result |
| Invalid SHA-256 | Scriptable rejects the result |
| Mobile result claims non-provisional status | Scriptable rejects the result |

## Userscripts boundary

A Userscripts adapter may later collect page-visible metadata from FR24 in
Safari. Browser-derived fields must use a separate provenance label and must
never be merged silently with screenshot-derived observations. Userscripts is
not part of the native app screenshot transaction.

## Local tests

```sh
pytest -q tests/test_fr24_mobile.py
ruff check mobile/fr24/analyze_fr24_mobile.py tests/test_fr24_mobile.py
```
