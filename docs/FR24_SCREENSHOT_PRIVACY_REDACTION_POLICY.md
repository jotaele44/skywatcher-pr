# FR24 Screenshot Privacy and Redaction Policy

Status: v1 foundation policy

## Purpose

FR24 screenshot fixtures can contain sensitive UI or device information. The repo must not commit raw screenshots unless they are synthetic or already redacted/safe. This policy controls fixture admission and export handling before broader FR24 visual parameters are implemented.

## Sensitive UI fields

| Field | Meaning |
|---|---|
| `user_account` | account name, profile marker, login marker |
| `email_or_handle` | email, social handle, visible username |
| `device_status_bar` | phone carrier, battery, time/status UI |
| `notification_banner` | phone/app notification content |
| `contact_or_message` | message preview or contact data |
| `precise_private_location` | exact private location shown in UI or metadata |
| `home_or_school_context` | home/school-adjacent private context |
| `face_or_person` | visible person/face in screenshot |
| `vehicle_plate` | license plate or vehicle identifier |
| `device_identifier` | device name, hardware ID, unique device text |
| `browser_tab_or_history` | browser history/tab content beyond the target page |
| `access_token_or_secret` | token, secret, auth parameter, private URL query |
| `payment_or_account_info` | payment, account, subscription, billing signal |
| `other` | any other sensitive field requiring review |

## Redaction statuses

| Status | Raw image fixture allowed? | Metadata-only allowed? |
|---|---:|---:|
| `not_reviewed` | no | no |
| `redaction_not_required` | yes | yes |
| `redaction_required` | no | yes |
| `redacted` | yes | yes |
| `metadata_only` | no | yes |
| `rejected` | no | no |

## Fixture classes

| Class | Meaning |
|---|---|
| `synthetic` | generated/non-sensitive fixture; may be committed |
| `redacted_screenshot` | screenshot with sensitive UI removed; may be committed |
| `metadata_only` | only hash/expected-output metadata may be committed |
| `external_reference_only` | no raw image; fixture points to external controlled reference |
| `do_not_commit` | not allowed in repository fixtures |

## Rules

1. Raw screenshots are prohibited until reviewed.
2. Raw screenshot fixtures are allowed only when synthetic, safely redacted, or explicitly `redaction_not_required` with no sensitive fields.
3. Screenshots containing sensitive fields default to metadata-only or external-reference-only handling.
4. Screenshots with precise private location, home/school context, minor-identifying context, account secrets, or messages must not be committed raw.
5. Expected-output JSON can be committed if it contains no sensitive UI or private-location data.
6. The parameter registry and later detector modules must consume privacy status instead of inventing their own fixture rules.

## Current implementation

The foundation helper module is `fr24_screenshot_privacy.py`. It provides controlled enums, sensitive-field normalization, fixture-class classification, `ScreenshotPrivacyAssessment`, and JSON-compatible serialization.
