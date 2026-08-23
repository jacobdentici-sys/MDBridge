# Contributing

Bug reports, documentation fixes, tests, and focused pull requests are welcome.

## Before opening an issue

1. Read `docs/TROUBLESHOOTING.md`.
2. Confirm the issue still occurs on the latest release.
3. Remove credentials, tokens, manifest URLs, email addresses, usernames, and public IP addresses from logs.

Never upload `data/config.json`.

## Development

```bash
python -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
PYTHONPATH=. python -m unittest discover -s tests -v
```

On Windows PowerShell, activate with `.\.venv\Scripts\Activate.ps1` and set `$env:PYTHONPATH='.'` before running the tests.

Keep pull requests small, explain provider behavior assumptions, and add a regression test for bug fixes. Do not commit recorded API responses containing personal account data.

By contributing, you agree that your changes are distributed under GPL-3.0.

