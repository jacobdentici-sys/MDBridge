# Security policy

## Supported versions

MDBridge is early-stage software. Only the latest tagged release receives security fixes.

## Reporting a vulnerability

Please do not publish credentials, tokens, configuration files, or exploit details in a public issue. Contact the repository owner privately through the security contact listed on their GitHub profile.

## Deployment model

MDBridge stores account tokens and API credentials in `data/config.json`. The setup API has no built-in user authentication. The supplied Docker Compose file therefore binds the service to `127.0.0.1` by default.

Use an SSH tunnel, a private VPN, or an authenticated reverse proxy. Never expose port 7335 directly to the public internet. Back up `data/` securely and never commit it to source control.

