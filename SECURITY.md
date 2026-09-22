# Security policy

## Reporting a vulnerability

Use GitHub's **Report a vulnerability** option in the repository Security tab. Do not open a
public issue for an unpatched vulnerability and do not include live credentials in a report.
Include affected versions, reproduction steps, impact, and a suggested mitigation when possible.

## Supported versions

Security fixes target the current `main` branch. This project has not published a stable 1.0
release yet.

## Deployment boundary

The default application is a single-user local research environment. It has no user accounts or
multi-tenant authorization. Keep it bound to `127.0.0.1` unless you add authentication, TLS, rate
limiting, network isolation, a separate vault service identity, and production monitoring.

Agent text, evidence, case records, and messages are untrusted input. Agent capabilities are
limited by server-side schemas and policies. Never add generic shell, filesystem, database,
browser, URL-fetching, or secret-reading tools to an agent profile.

## Credential handling

- Put provider credentials in `.env` or a secret manager.
- Use a dedicated key with a provider-side spending limit.
- Rotate a key immediately if it appears in a commit, issue, log, screenshot, or chat.
- Run a history-aware secret scan before making a fork or repository public.

The detailed threat model and trust limits are in [docs/SECURITY.md](docs/SECURITY.md).
