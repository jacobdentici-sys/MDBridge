# Installation

MDBridge runs as one Docker container and stores its configuration in the local `data/` directory. It does not require a separate database.

## Before you begin

You need:

- Docker Engine with the Compose plugin
- an always-on Linux host, NAS, mini PC, or VPS
- an MDBList API key
- a TMDB Read Access Token
- optionally, a Nuvio Cloud account and a Stremio account

Back up your existing watch history before enabling bidirectional synchronization. MDBridge is early-alpha software and watched synchronization is additive: manual unwatch does not propagate in version 0.1.2.

## Quick install

```bash
git clone https://github.com/jacobdentici-sys/MDBridge.git
cd MDBridge
docker compose up -d --build
docker compose ps
```

The built-in default is 900 seconds. To choose a different interval before the first start, copy `.env.example` to `.env` and edit `MDBRIDGE_SYNC_INTERVAL`. Existing installations should change the interval from the setup page because their saved `config.json` takes precedence.

The supplied Compose configuration listens only on `127.0.0.1:7335` because the setup page can change account connections and contains credential-bearing operations.

On the Docker host, open `http://127.0.0.1:7335`.

From another computer, create an SSH tunnel:

```bash
ssh -L 7335:127.0.0.1:7335 USER@SERVER_IP
```

Keep that terminal open and visit `http://127.0.0.1:7335` on your computer.

## Oracle Cloud Always Free VPS

The following example assumes Ubuntu and an SSH key already configured in Oracle Cloud.

```bash
ssh ubuntu@SERVER_IP
sudo apt-get update
sudo apt-get install -y ca-certificates curl git
curl -fsSL https://get.docker.com | sudo sh
sudo usermod -aG docker "$USER"
exit
```

Reconnect so the Docker group change takes effect, then install MDBridge:

```bash
ssh ubuntu@SERVER_IP
mkdir -p ~/apps
cd ~/apps
git clone https://github.com/jacobdentici-sys/MDBridge.git
cd MDBridge
docker compose up -d --build
```

Do not add an Oracle ingress rule for TCP 7335. Use the SSH tunnel above. An SSH ingress rule for TCP 22 restricted to your own IP is preferred.

## Account setup

Open the MDBridge setup page and complete these sections in order:

1. Paste your MDBList API key.
2. Paste your TMDB Read Access Token.
3. Optional: sign into Nuvio once and select the correct profile number. The password is exchanged for a refresh token and is not stored.
4. Optional: create and approve the Stremio account link.
5. Select **Sync now**, then confirm that `last_error` is `null`.

For Kodi/POV, connect POV directly to MDBList for both watched status and resume progress. Do not connect POV to MDBridge and do not run a second Kodi scrobbler for the same account.

## Request usage

The default 15-minute interval produces 96 runs daily. With the current two baseline MDBList reads per run, that is about 192 requests per day. Imports, writes, manual syncs, pagination, and other applications add requests.

MDBList free accounts currently receive 1,000 requests per day. Avoid a 60-second interval on a free account; two baseline reads per minute would use about 2,880 requests daily.

Change the interval in `.env` before the first start or from the setup page afterward. The value is in seconds and cannot be lower than 30.

## Updating

```bash
cd ~/apps/MDBridge
git pull --ff-only
docker compose up -d --build
```

The `data/` directory persists across rebuilds. Back it up securely because it contains service tokens and API credentials.

Version 0.1.2 is data-compatible with 0.1.1 and requires no migration.

## Health checks

```bash
curl -fsS http://127.0.0.1:7335/health
curl -fsS http://127.0.0.1:7335/api/status
docker compose logs --tail=100
```

Healthy output includes `{"ok":true}`, a recent `last_run`, and `last_error: null`.
