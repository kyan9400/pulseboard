# Changelog

All notable changes to Pulseboard are documented here.

## 1.2.0 — 2026-08-26

- Added per-monitor SLO error-budget reports with selectable windows and targets.
- Added observed uptime, estimated downtime, remaining budget, and exhaustion states.
- Added Prometheus export for 24-hour error-budget consumption.
- Added an error-budget control surface to the operations dashboard.

## 1.1.0 — 2026-08-26

- Added a public, auto-refreshing service status page with current availability and incident history.
- Kept the public presentation privacy-safe by omitting monitored endpoint URLs.

## 1.0.0 — 2026-08-26

- Added scheduled HTTP and HEAD availability checks with bounded concurrency.
- Added automatic incident opening and recovery tracking.
- Added the operations dashboard, JSON API, health probes, and Prometheus metrics.
- Added SQLite persistence, optional API-key write protection, and outbound target safeguards.
- Added a non-root container image, Compose deployment, and automated tests.
