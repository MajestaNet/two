# Adapters and clients

How an installation sees optional surfaces. The canonical rules are
[architecture.md](architecture.md) §5.2, §6.3.H, and §12.6, and
[ADR 0021](adrs/0021-adapter-install-catalog.md). This page is the menu,
not a second design.

Print it:

```bash
uv run two adapters
```

The file is [config/adapters/catalog.yaml](../config/adapters/catalog.yaml).
`two adapters` reads that file and writes nothing. It does not start a
process. Copying a package into the tree does not enable it.

## Kinds

| Kind | Where it lives | What an install may do |
| --- | --- | --- |
| Client | CLI in this repo. Mobile and watch apps are specified here and built elsewhere. Watch edge is `two.edge`. | CLI is on. Mobile and watch stay `contract` until their executors exist. |
| Messenger | `two.channels.<name>` | None selected. |
| Device | `src/two/devices/<name>/` after a protocol ADR | Reserved. No package yet. `chat` and `home-action` only. |
| Export | `src/two/export/` ([ADR 0012](adrs/0012-github-export-adapter.md)) | Reserved. Not a channel. |

`two.providers` configures the model DeepSeek Harness calls. It is not
one of these slots.

## Enablement

A slot is on only when the catalog says `default_enabled: true`. Today
that is `cli` alone. `selectable` is true only for `shipped` slots, so
an installation cannot turn on `contract`, `stub`, or `reserved`.
Profile `chat` is resumed by the control plane
([B20](backlog/B20-chat-profile-resume.md)). `home-action` stays refused.
That does not enable the watch slot.

Channel behavior for messengers stays in [channels.md](channels.md).
The watch client spec stays in [watch-client.md](watch-client.md).
GitHub export stays in [source-control-export.md](source-control-export.md).
