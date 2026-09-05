# Changelog

## 0.1.2 - 2026-09-05

- Fix the example environment file so it keeps the documented 15-minute default.
- Preserve the intended no-op behavior when MDBList has no paused session to clear.
- Validate new MDBList and TMDB credentials before replacing working credentials.
- Write configuration and state files atomically with private file permissions.
- Avoid rewriting equivalent Nuvio and Stremio resume positions every polling cycle.
- Add sync-interval and disconnect controls to the setup page.
- Harden provider error messages and Cinemeta redirect handling.
- Add a container health check, drop Linux capabilities, and enable Dependabot.
- Update supported dependencies and CI actions, and add lint and dependency-audit checks.
- Expand regression coverage for credential safety, configuration writes, and provider behavior.

## 0.1.1 - 2026-08-22

- Bind the setup service to loopback by default.
- Add container hardening and bounded Docker logs.
- Follow Cinemeta redirects when resolving Stremio episode metadata.
- Use a quota-friendly 15-minute default sync interval.
- Redact credential-bearing MDBList request URLs from HTTP errors and logs.
- Add repository ignore rules, a security policy, and CI.
- Add installation, architecture, troubleshooting, support, and contribution documentation.

## 0.1.0 - 2026-08-16

- Initial private build.
