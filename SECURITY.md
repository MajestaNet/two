# Security Policy

## Reporting a vulnerability

Do **not** file secrets, tokens, private hostnames, or exploit details in a public GitHub issue.

Email **steve.th.zinke@gmail.com** with:

- a description of the issue
- affected versions or commits if known
- reproduction steps that do not include live credentials

We will acknowledge the report and work on a fix before any public disclosure.

## Deployment boundaries

DevFlow and the Mac inference endpoint are private-network services.

- Do not bind Ollama or the DevFlow API to a publicly routed interface.
- Do not open inbound Slack HTTP callbacks; use Socket Mode only if Slack is enabled.
- Do not commit `.env`, Slack tokens, cloud keys, or model weight files.

See [docs/public-repo.md](docs/public-repo.md) and [docs/architecture.md](docs/architecture.md) section 15.
