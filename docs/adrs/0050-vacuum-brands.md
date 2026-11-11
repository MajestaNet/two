# ADR 0050 — No second vacuum brand

## Status

Accepted as a rejection. ADR 0038 and ADR 0042 are unchanged. The vacuum
slot stays off until an installation binds it, and that binding stays
Ecovacs. No brand field, transport, or dependency is added by this ADR.

## Context

ADR 0038 keeps one closed tool list (`vacuum.read`, `vacuum.clean`,
`vacuum.dock`) and calls the Ecovacs Open API from this process. The
runtime dependencies are pydantic, pyyaml, fastapi, uvicorn, and
aioesphomeapi. AES is not in the standard library. A second brand has
to be a stdlib client with a real read-back, on the private LAN or on
an allowlist as small as the two Ecovacs hosts.

The brands a household actually owns do not meet that bar:

- Roborock local control is miIO on UDP 54321 with AES-128-CBC. The
  app path is a Roborock account, then a local key. The published
  client also needs MQTT and protobuf.
- iRobot Roomba firmware that a household 600, 800, 900, i, or j robot
  runs is MQTT/TLS on port 8883 with a BLID and password. The older
  HTTPS `/umi` path was removed. A from-scratch MQTT client is a new
  protocol stack, not a stdlib HTTP subset.
- Dreame is miIO, or an account client with encrypted headers. Some
  current models have local miIO disabled.
- Eufy RoboVac, including L70 and G30, is Tuya on TCP 6668. Start,
  pause, and return-home are encrypted with a local key taken from an
  account. There is no unencrypted command set that can clean and dock.
  Newer Eufy Clean is cloud and TLS.
- Shark control that has been observed is a signed account API. A
  claimed LAN REST map is not independently captured, and it does not
  cover pause and resume. Implementing it would invent a protocol.

## Decision

1. **No second brand.** The vacuum package stays the Ecovacs client.
   Existing `vacuum.yaml` files do not grow a `brand` field. An omitted
   document stays Ecovacs because the document never names a brand.
2. **The tool list does not change.** Read-back fields stay robot,
   activity, charging, station, and reachability. `require_api_host`
   stays `open.ecovacs.com` and `open.ecovacs.cn`.
3. **A later brand still has to be a stdlib client with a real
   read-back.** An AES, MQTT, protobuf, or account-scrape transport
   needs its own ADR and a dependency decision. This ADR does not
   approve those.

## Consequences

- Architecture §5.2 points here. The Ecovacs private-network exception
  stays the only device transport that leaves the LAN.
- `two vacuum robots` stays the Ecovacs nickname list and writes nothing.

## Alternatives rejected

- **Valetudo.** Local HTTP on a flashed robot is replacement firmware,
  not a brand a household buys.
- **A hand-rolled MQTT Roomba client, or a hand-rolled AES miIO or
  Tuya client.** Those are new protocol stacks. The package does not
  have a crypto library.
- **Copying an unverified Shark LAN client.**
- **An Eufy or Shark account scraper, or any host beyond the two
  Ecovacs hosts.**
