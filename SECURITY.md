# Security policy

## Supported version

Security fixes are provided for the latest release.

## Deployment notes

- Set `PULSEBOARD_API_KEY` or place Pulseboard behind an authenticated reverse proxy before exposing it to an untrusted network.
- Private, loopback, reserved, and link-local monitoring targets are blocked by default. Enable `PULSEBOARD_ALLOW_PRIVATE_TARGETS` only on a trusted network.
- Redirects are never followed by the checker, which limits redirect-based server-side request forgery.
- Run a single application worker. The built-in scheduler is intentionally coordinated in-process for a compact deployment.

Please report a suspected vulnerability through GitHub's private security advisory feature instead of a public issue.
