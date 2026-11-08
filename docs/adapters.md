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
| Client | CLI in this repo. The local operator console is `apps/console` ([ADR 0031](adrs/0031-local-operator-console.md), [ADR 0032](adrs/0032-console-existing-ollama.md)). The iPhone and Apple Watch apps are [MajestaNet/two-mobile](https://github.com/MajestaNet/two-mobile) (Apache License 2.0). How to run them is [local.md](local.md). Watch edge is `two.edge`. | CLI is on. The console is shipped and off until you open the window. The phone and watch stay `contract` because the Xcode project is the other repository. |
| Messenger | `two.channels.<name>` | None selected. |
| Device | `src/two/devices/climate/` (ADR 0022, ADR 0027, ADR 0043), `src/two/devices/tv/` (ADR 0029), and `src/two/devices/vacuum/` (ADR 0038). Shared ESPHome nodes live in `src/two/devices/esphome/` and are not a catalog slot. The kind-level `device` slot stays reserved. | `climate`, `tv`, and `vacuum` are shipped and off. A local `climate.yaml` binds zones. A local `esphome.yaml` lists nodes a climate zone may name. A local `tv.yaml` binds Samsung sets. A local `vacuum.yaml` binds Ecovacs robots. `home-action` only. |
| Export | `src/two/export/` ([ADR 0012](adrs/0012-github-export-adapter.md)) | Reserved. Not a channel. |

`two.providers` configures the model DeepSeek Harness calls. It is not
one of these slots.

## Enablement

A slot is on only when the catalog says `default_enabled: true`. Today
that is `cli` alone. The console slot is shipped and stays off until
you open the window. `selectable` is true only for `shipped` slots, so
an installation cannot turn on `contract`, `stub`, or `reserved`.
Profile `chat` is resumed by the control plane
([B20](backlog/B20-chat-profile-resume.md)). `home-action` runs the
closed climate tools when the local climate binding is enabled
([ADR 0022](adrs/0022-climate-device-protocol.md)), and the closed
television tools when the local television binding is enabled
([ADR 0029](adrs/0029-samsung-tv.md)), and the closed vacuum tools when
the local vacuum binding is enabled
([ADR 0038](adrs/0038-ecovacs-vacuum.md)). A transcript that omits the
profile is routed to `chat` or to those slots, and `all` can repeat
one closed action across the bound targets
([ADR 0030](adrs/0030-utterance-routing-and-fanout.md)). That does not enable
the watch slot, and it does not turn a device slot on by itself.
Harness profile `operator` can propose a binding for a shipped slot, or
a self-build task that extends one, after an approval digest
([ADR 0039](adrs/0039-operator-install-profile.md)). An omitted profile
does not route there. The catalog slots stay unchanged.

Channel behavior for messengers stays in [channels.md](channels.md).
The watch client contract stays in [watch-client.md](watch-client.md).
The apps that implement it are [MajestaNet/two-mobile](https://github.com/MajestaNet/two-mobile).
GitHub export stays in [source-control-export.md](source-control-export.md).
