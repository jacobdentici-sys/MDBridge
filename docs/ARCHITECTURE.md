# Architecture

MDBList is the canonical watched-history and resume store. MDBridge polls cloud state from MDBList, Nuvio, and Stremio, normalizes identifiers to IMDb movie/show IDs plus season and episode numbers, and merges newer state.

```text
POV/Kodi ───────────────> MDBList <──────────────> MDBridge
                              ^                     /      \
                              |                    v        v
                         POV/Nimbus             Nuvio    Stremio
```

## Components

- `app/main.py` provides the FastAPI setup/status API and optional Stremio catalog.
- `app/sync_engine.py` performs reconciliation under a single asynchronous lock.
- `app/mdblist.py`, `app/nuvio.py`, and `app/stremio.py` adapt provider data to the shared models.
- `app/tmdb.py` resolves IMDb/TMDB mappings and runtimes needed to convert percentages into positions.
- `app/config.py` stores configuration and tokens in `/data/config.json`.

## Merge rules

1. Watched state is additive in version 0.1.2.
2. MDBList remains authoritative after remote additions are imported.
3. Newer resume timestamps win; near-tied timestamps use meaningful forward progress.
4. Watched items do not retain active resume sessions.
5. Unknown provider fields are preserved when Stremio library records are merged.
6. Equivalent resume positions are not rewritten on every polling cycle.

## Stremio behavior

The optional Stremio manifest exposes Continue Watching catalogs, but synchronization does not depend on installing that manifest. MDBridge reads and writes the Stremio account datastore because ordinary Stremio add-ons do not receive player progress events.

## Trust boundary

The setup API has no built-in login. Docker therefore binds it to loopback by default. Treat `/data` and the private manifest token as secrets, and use an SSH tunnel, private VPN, or authenticated HTTPS reverse proxy.
