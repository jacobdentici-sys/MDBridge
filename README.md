# MDBridge 0.1.1

[![Tests](https://github.com/jacobdentici-sys/MDBridge/actions/workflows/tests.yml/badge.svg)](https://github.com/jacobdentici-sys/MDBridge/actions/workflows/tests.yml)
[![Python 3.12](https://img.shields.io/badge/python-3.12-blue.svg)](https://www.python.org/)
[![Docker](https://img.shields.io/badge/deployment-Docker-2496ED.svg)](https://www.docker.com/)
[![License: GPL v3](https://img.shields.io/badge/license-GPLv3-blue.svg)](LICENSE)

> Early alpha. Back up your watch history before enabling bidirectional synchronization.

> **Tracking only:** MDBridge does not find, host, download, or provide video streams. It only synchronizes account watch state and resume positions.

MDBridge is a self-hosted synchronization companion for this specific setup:

- **MDBList** is the canonical watched-history and resume database.
- **Kodi + POV** reads and writes watched/resume state directly through POV's MDBList integration.
- **Nuvio** reads and writes its Nuvio Cloud watched state and Continue Watching state.
- **Stremio** reads and writes the Stremio account datastore used by Stremio clients on your TVs.
- An optional Stremio catalog endpoint exposes MDBList Continue Watching rows as a normal Stremio add-on catalog.

MDBridge is deliberately small: one Python container, no database server, and no account system. It is most useful when you already use MDBList as your source of truth and want a lightweight bridge for Stremio and Nuvio. If you want a broader multi-user media tracker with Plex, Jellyfin, Emby, ratings, and lists, consider [Scrob](https://github.com/ellite/scrob).

MDBridge is an independent community project and is not affiliated with MDBList, Stremio, Nuvio, TMDB, Kodi, or POV.

## Documentation

- [Installation](docs/INSTALLATION.md)
- [Architecture](docs/ARCHITECTURE.md)
- [Troubleshooting](docs/TROUBLESHOOTING.md)
- [Security policy](SECURITY.md)
- [Contributing](CONTRIBUTING.md)

## Why this is a companion service, not only a Stremio add-on

A normal Stremio add-on is request/response. It can provide catalogs, metadata, streams, and subtitles, but it does not receive the player's play/pause/seek/stop events. MDBridge therefore synchronizes the **Stremio account cloud datastore** instead. That has an advantage for multi-TV use: every Stremio TV signed into the same account contributes to the same cloud watch state, so no tracker plug-in is required on each TV.

The optional `manifest.json` endpoint is only for an extra MDBList Continue Watching catalog. Tracking does not depend on installing that catalog.

## What this build synchronizes

| Direction | Watched movies/episodes | Partial resume progress |
|---|---:|---:|
| Nuvio -> MDBList | Yes | Yes |
| Stremio -> MDBList | Yes | Yes |
| MDBList -> Nuvio | Yes | Yes |
| MDBList -> Stremio | Yes | Yes |
| POV/Kodi -> MDBList | Handled directly by POV | Handled directly by POV |

MDBridge polls every 15 minutes by default. The minimum allowed interval is 30 seconds.

Each run currently uses at least two MDBList API requests, and watched-history pagination can use more. MDBList's free plan allows 1,000 requests per day, so the 15-minute default leaves room for Kodi add-ons and other clients. A 60-second interval is intended only for an account with a sufficient API allowance.

## Important behavior

1. MDBList is authoritative.
2. A watched item found in Nuvio or Stremio that is not in MDBList is added to MDBList.
3. A newer partial position found in Nuvio or Stremio is written to an MDBList paused scrobble session.
4. MDBList paused sessions are then pushed into Nuvio and Stremio.
5. MDBList watched items missing on Nuvio or Stremio are pushed there.
6. For an MDBList resume point that contains only a percentage, MDBridge uses TMDB runtime data to reconstruct the absolute playback position required by Nuvio and Stremio.

This makes a typical path look like:

```text
Nuvio TV -> Nuvio Cloud -> MDBridge -> MDBList -> POV -> Nimbus widget

POV/Kodi -> MDBList -> MDBridge -> Nuvio Cloud -> Nuvio Continue Watching
                            \\-> Stremio account -> Stremio Continue Watching

Stremio TV -> Stremio account -> MDBridge -> MDBList -> POV/Nimbus + Nuvio
```

## Requirements

- An MDBList account and API key.
- A free TMDB Read Access Token.
- A Nuvio account with Nuvio Cloud enabled if you want Nuvio synchronization.
- A Stremio account if you want Stremio synchronization.
- Docker on an always-on computer, NAS, mini PC, or server.

## Install with Docker

```bash
git clone https://github.com/jacobdentici-sys/MDBridge.git
cd MDBridge
docker compose up -d --build
```

See the [full installation guide](docs/INSTALLATION.md) for Linux, NAS/home-server, and Oracle Cloud VPS instructions.

The supplied Compose file binds MDBridge to the server's loopback interface. On the server itself, open:

```text
http://127.0.0.1:7335
```

For a remote VPS, create an SSH tunnel from your computer and then open the same address locally:

```bash
ssh -L 7335:127.0.0.1:7335 USER@YOUR-SERVER-IP
```

For a trusted home LAN, you may deliberately change the Compose port mapping to `7335:7335`, but anyone who can reach that port can operate the setup API. Do not expose it directly to the public internet.

The web page lets you:

1. Enter the MDBList API key.
2. Enter the TMDB Read Access Token.
3. Connect Nuvio using email/password and select the Nuvio profile number.
4. Link Stremio using Stremio's account authorization flow.
5. Run a manual sync and inspect sync statistics.

Nuvio's password is submitted only for the initial sign-in and is not stored in `config.json`. Nuvio refresh tokens rotate, so MDBridge persists each replacement token immediately.

## Kodi / POV configuration

Keep POV connected directly to MDBList. Do not put MDBridge between POV and MDBList.

Recommended architecture:

```text
POV watched provider = MDBList
POV resume provider = MDBList
Nimbus Continue Watching/In Progress widget = POV directory
```

You do not need the Scrob Kodi service for this architecture. Running two independent Kodi scrobblers is unnecessary and could create duplicate writes.

## Nuvio configuration

Sign into Nuvio Cloud and leave Nuvio's own cloud synchronization enabled. MDBridge reads and writes the profile's cloud watched/progress records, so all Nuvio devices using that profile share the result.

MDBridge exchanges your Nuvio password for a refresh token. Only the refresh token is persisted.

## Stremio configuration

Use **Create Stremio link** on the MDBridge page, authorize it in Stremio, then select **I authorized it, check now**.

No tracker add-on needs to be installed separately on each Stremio TV. MDBridge reads the account's `libraryItem` state, including:

- movie watched count
- series watched bitfield
- current `video_id`
- `timeOffset`
- `duration`
- `lastWatched`

### Optional MDBridge Stremio catalog

The home page displays a private, tokenized URL such as:

```text
http://YOUR-SERVER-IP:7335/<private-token>/manifest.json
```

Install that URL in Stremio only if you want separate **MDBList Continue Watching** movie and series catalogs. It is not required for synchronization.

If Stremio clients outside your home need this catalog, MDBridge must be reachable from those clients through HTTPS. Do not expose port 7335 directly to the public internet. Put it behind an authenticated/restricted reverse proxy or VPN.

## Completion and resume handling

- MDBridge does not infer completion merely because a remote progress value crosses 80 percent.
- Completion is imported from the actual watched state exposed by Nuvio or Stremio.
- Partial progress is stored in MDBList using its scrobble start/pause API.
- When a remotely watched item is imported, any matching MDBList paused session is cleared.
- Progress below 1 percent is ignored to avoid creating noisy Continue Watching entries from accidental starts.

## Current limitations in 0.1.1

- **Manual unwatch is not yet propagated.** Watched synchronization is additive in this build. Marking something unwatched on one service will not remove it from the others.
- Stremio stores one current playback position per movie/series library item. MDBridge cannot create more resume slots than Stremio itself stores.
- Nuvio's cloud RPC interface is not the Stremio add-on protocol and can change independently of this project.
- Exact MDBList -> Nuvio/Stremio resume depends on TMDB returning a runtime. If runtime cannot be resolved, watched status still syncs but that resume point is skipped for those clients.
- The current build has been live-tested with one MDBList, Nuvio, Stremio, TMDB, and POV/Kodi setup on an Oracle Linux VPS. That is useful validation, not a guarantee for every account or library shape.
- Nuvio Cloud RPC methods and Stremio account datastore behavior are not stable public integration contracts and may change without notice.
- Stremio series state provides a single `lastWatched` timestamp for the series, so MDBridge cannot reconstruct the original watch time of every historical episode.

## Security

`data/config.json` contains service tokens and API keys. Docker mounts `./data` into the container. Treat that directory as secret and do not commit it to Git. The included `.gitignore` excludes it, but verify staged files before every push.

The included setup web page does not implement its own login. Docker binds it to `127.0.0.1` by default. Access it through an SSH tunnel or private VPN; if you use a public hostname, add HTTPS and authentication at the reverse proxy. See `SECURITY.md`.

## Tests

```bash
PYTHONPATH=. python -m unittest discover -s tests -v
```

## Project notes and attribution

MDBridge was designed against current public API behavior and current open-source implementations as of August 22, 2026. In particular, the Stremio datastore/bitfield and Nuvio Cloud integration behavior was cross-checked against the GPLv3 project **ellite/scrob**. MDBridge is therefore distributed under GPLv3 as well.

Relevant upstream projects and API documentation:

- MDBList API: `https://api.mdblist.com/docs`
- MDBList OpenAPI source: `https://github.com/linaspurinis/api.mdblist.com`
- Stremio feature request for playback-event add-on support: `https://github.com/Stremio/stremio-features/issues/824`
- Scrob: `https://github.com/ellite/scrob`
- POV: `https://github.com/kodifitzwell/repo`

## License

GNU General Public License v3.0. See `LICENSE`.
