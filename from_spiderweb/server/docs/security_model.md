# Security Model

The PRIIS prototype handles sensitive data about government contracts,
infrastructure sites, and potential anomalies. Proper security
controls are essential to prevent unauthorized access, tampering,
and disclosure. This document outlines the key aspects of a secure
deployment.

## Data Protection

- **Encryption in transit** – Use HTTPS for all client–server and
  server–server communication. TLS certificates should be issued
  by a trusted authority and rotated regularly.
- **Encryption at rest** – Configure your database to use disk
  encryption. For cloud providers, enable managed encryption keys or
  supply your own customer-managed keys.
- **Access controls** – Restrict database credentials to the least
  privileges required. Use separate accounts for application access
  and administrative tasks. Protect secrets in a secret manager.

## Authentication and Authorization

- Implement an authentication layer (e.g., JWT-based bearer tokens) to
  verify the identity of users and services. Use a library such as
  OAuth2 middleware in FastAPI.
- Define roles (analyst, administrator, guest) and enforce
  authorization checks on API endpoints. For example, only
  authorized analysts should be able to ingest new data.

## Input Validation

- Validate all incoming data using the JSON schemas defined in
  `contracts/`. This prevents injection attacks and ensures
  consistent data structure.
- Sanitize user-generated content (e.g., free-text descriptions) to
  mitigate cross-site scripting (XSS) if rendered in the frontend.

## Logging and Auditing

- Log significant actions, including user logins, data ingestion
  events, and query executions. Store logs in a tamper-evident
  system.
- Implement an audit trail for the evidence ledger to track who
  created or modified findings.

## Deployment Hardening

- Keep dependencies up to date and monitor for CVEs.
- Run containers with non‑root users and minimal capabilities.
- Restrict network access to the database so that only the backend
  service can connect to it.

## Privacy Considerations

- Do not store personally identifiable information (PII) unless
  absolutely necessary. Redact sensitive fields in datasets.
- Follow relevant laws and regulations (e.g., GDPR, Puerto Rico
  privacy laws) for handling public data and inter-agency records.

## Next Steps

- Integrate an authentication provider (e.g., Auth0, Clerk,
  Supabase Auth) into the backend.
- Implement rate limiting and other anti-abuse mechanisms on
  endpoints, especially the query layer.
- Perform regular penetration testing and threat modeling exercises.