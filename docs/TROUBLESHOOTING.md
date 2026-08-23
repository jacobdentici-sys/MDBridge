# Troubleshooting

## Status shows HTTP 429

The MDBList daily API allowance has been exhausted. On a free account, keep the default 15-minute interval. Wait for MDBList's UTC reset; MDBridge will retry automatically.

Check usage under MDBList **Preferences → API Access**. Other clients using the same key, including Kodi add-ons, also consume the allowance.

## MDBList updates but Stremio is behind

Confirm `stremio_connected` is `true` and inspect `last_error`. Some specials or nonstandard episode IDs may not exist in Cinemeta's episode ordering and cannot be represented correctly in Stremio's watched bitfield.

Reconnect Stremio from the setup page if the authorization key was revoked.

## Nuvio stopped synchronizing

Confirm Nuvio Cloud is enabled and the configured profile number is correct. Nuvio refresh tokens rotate; do not restore only an old token from a stale `config.json` while the service is running.

## Reeel does not show MDBList status

First confirm the watched item appears on the MDBList website and that Reeel is signed into the same MDBList account. An exhausted MDBList API allowance can also prevent the app from refreshing. The **Reeel Sync** panel on the MDBList website refers to the Netflix browser extension, not the Reeel mobile application's normal account synchronization.

## The setup page is unreachable on a VPS

The safe default listens only on the server's loopback interface. Create an SSH tunnel:

```bash
ssh -L 7335:127.0.0.1:7335 USER@SERVER_IP
```

Then open `http://127.0.0.1:7335` locally. Do not expose TCP 7335 publicly.

## Collecting diagnostics

Before opening an issue, include sanitized output from:

```bash
docker compose ps
curl -fsS http://127.0.0.1:7335/health
curl -fsS http://127.0.0.1:7335/api/status
docker compose logs --tail=100
```

Remove API keys, tokens, email addresses, private manifest URLs, public IP addresses, and usernames. Never attach `data/config.json`.

