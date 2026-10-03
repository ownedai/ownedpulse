# Security

## Security model

OwnedPulse is a demonstrator. Its default configuration assumes a single user on a workstation or an isolated, trusted network.

- The OwnedPulse API and UI have **no authentication**.
- PostgreSQL, Qdrant, Ollama, Docling and Langfuse ports are published on the host. Qdrant and Ollama have no authentication of their own.
- The API and UI run in development mode (auto-reload, Vite development server, bind-mounted source).

Do not expose an OwnedPulse installation to the internet or to untrusted networks. If you need remote access, put it behind a VPN or an authenticating reverse proxy, and restrict the published ports with a host firewall.

## Credentials

- Replace every `change_me` value in `.env` before the first start. `install.sh` refuses to run while `POSTGRES_PASSWORD` or the Langfuse secrets are unset or still `change_me`.
- `.env` is git-ignored. Never commit it.
- `install.sh` writes generated Langfuse API keys into `.env`.

## Supported versions

| Version | Supported |
|---|---|
| 1.1.x | Yes |
| < 1.1 | No. Delete clones made before 2026-10-02 and clone again (see CHANGELOG). |

## Reporting a vulnerability

Report vulnerabilities privately through GitHub: **Security** tab → **Report a vulnerability** on https://github.com/ownedai/ownedpulse. Please do not open a public issue for security problems.

Expect an acknowledgement within a few working days. This is a single-maintainer project; fixes are best effort.
