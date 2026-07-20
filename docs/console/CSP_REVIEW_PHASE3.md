# Phase 3 Content Security Policy Review

The desktop same-origin server emits:

```text
default-src 'self';
script-src 'self';
style-src 'self' 'unsafe-inline';
font-src 'self' data:;
img-src 'self' data: blob:;
connect-src 'self' blob:;
worker-src 'self' blob:;
object-src 'none';
base-uri 'self';
form-action 'self'
```

## Rationale

- `worker-src blob:` supports the bundled MapLibre worker without permitting a remote worker origin.
- `connect-src` excludes external providers and permits only same-origin APIs and blob resources.
- `style-src 'unsafe-inline'` is retained because the existing React diagnostic surface uses inline style attributes; removing it requires a separate repository-wide refactor.
- `object-src 'none'`, `base-uri 'self'`, and `form-action 'self'` reduce injection and navigation risk.
- `Permissions-Policy` permits geolocation only from the same local origin and disables camera and microphone.

The policy is enforced by the desktop application server and covered by a backend regression test.
