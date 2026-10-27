# Watch and iPhone voice client

Design spec for a later agent on a Mac with Xcode. This repository
does not contain the app. ADR 0015 places first-party client source
outside this tree. Implement the app in its own directory or
repository. Do not add an Xcode project here.

The server side this spec calls is implemented
([ADR 0020](adrs/0020-watch-edge-mtls.md)). Read that ADR,
[client-api-design.md](client-api-design.md) §6, and
[client-threat-model.md](client-threat-model.md) before writing Swift.
Where this file and those documents disagree, the ADR wins.

## What the app is

A push-to-talk client. The watch captures speech, keeps recognition on
the watch, and sends text to the control API. The iPhone app enrolls
the device certificate and is the place the operator types the PKCS#12
password once. HomePods are not part of this build. They stay speakers
for a later media binding.

The app does not open Ollama, DeepSeek Harness, a shell, or git. It
does not embed `TWO_API_TOKEN`. It does not hold `TWO_EDGE_TOKEN`.
Caddy on the Mac injects that token after mutual TLS succeeds.

## Targets

| Target | Role | Minimum |
| --- | --- | --- |
| iOS app | Enrollment, show the same health and approval screens | iOS 17 |
| watchOS app | Push to talk, health, approval | watchOS 10 |

SwiftUI. Swift concurrency. No third-party networking or crypto
packages. Use `URLSession` and Security.framework. One shared Swift
package or app group for the API client so the watch and the phone do
not fork the request code.

Bundle identifiers and the keychain access group are the operator's.
The entitlements are: keychain access group shared by both targets,
network client, microphone on the watch, speech recognition on the
watch. Do not set `NSAllowsArbitraryLoads`.

## Enrollment

On the Mac mini, with the API still on `127.0.0.1:8741`:

```bash
uv run two edge plan --listen PRIVATE-LAN-IP
uv run two edge issue --listen PRIVATE-LAN-IP
```

`two edge issue` writes `$TWO_DATA_DIR/edge/` mode 0700:

| File | Who needs it | Commit? |
| --- | --- | --- |
| `ca.crt` | App pins this CA | No |
| `watch.p12` | Imported once into the watch keychain | No |
| `watch-p12.password` | Typed once into the iPhone app, then forgotten | No |
| `server.crt` / `server.key` / `ca.key` | Caddy and the CA only. Never leave the mini | No |
| `edge.env` | `TWO_EDGE_TOKEN` for the Caddy process and `two api` | No |
| `Caddyfile` | `caddy run --config` that file | No |

Copy `ca.crt` and `watch.p12` to the iPhone by AirDrop or a cable.
Do not email them and do not put them in git. The operator exports
`TWO_EDGE_TOKEN` from `edge.env` into the environment of both Caddy
and `two api`, then starts Caddy. The API process is not given a LAN
bind.

The iPhone screen asks for the PKCS#12 password, calls
`SecPKCS12Import`, and stores the identity in the keychain with
`kSecAttrAccessibleWhenUnlockedThisDeviceOnly` and the shared access
group. The item is not synchronizable. iCloud Keychain must not copy
it. After import, the app deletes any copy of the p12 from the
container. The password is not stored.

Confirm against current Apple documentation whether that keychain
access group is visible to the paired watch. If it is not, send the
p12 once over Watch Connectivity, import it on the watch, and delete
the file. The private key is generated on the mini today (the CA signs
it). A later slice can switch to a key generated on the watch. Do not
block the first app on that change.

Revocation is operational: `two edge issue --force` replaces the CA
and the token. The app then fails server trust until the operator
enrolls again.

## Connection

Base URL: `https://PRIVATE-LAN-IP:8443`. The host is the address
passed to `two edge issue`. The app stores that host in the keychain
or in preferences on device. It does not ship a default IP.

`URLSession` delegate:

1. Server trust: evaluate the chain against the pinned `ca.crt` bytes
   that were enrolled. Public CAs are not enough for this host. Reject
   any chain that does not end at that CA.
2. Client certificate challenge: answer with the enrolled identity
   (`URLCredential(identity:certificates:persistence:)`). Persistence is
   `.forSession`. The key stays in the keychain.

The app sets no `X-Two-Edge-Token` and no `X-Two-Client-Id`. Caddy
overwrites both. Sending `TWO_API_TOKEN` is a defect.

Away from the house Wi-Fi, the watch reaches the mini only through the
paired iPhone's private overlay (Tailscale or WireGuard). watchOS has
no Tailscale client. Do not add a public DNS name, a port forward, or
an ngrok-style tunnel. If the overlay is down, the UI says the mini is
unreachable.

`auth.oidc_available` is false. Leave a single place in the API client
where an `Authorization: Bearer` header will be added later, and leave
it empty. Do not invent a token. ADR 0016 has to be accepted before
that header is real.

## API

JSON, `Content-Type: application/json`. Extra fields are rejected.
Read `X-Correlation-Id` from responses and show it on error screens.

### Capabilities

`GET /v1/system/capabilities`

A successful watch response looks like:

```json
{
  "principal": "client:watch",
  "scopes": ["approvals:decide", "system:read", "tasks:read"],
  "allowed_harness_profiles": ["chat", "home-action"],
  "auth": {
    "method": "edge_client",
    "oidc_available": false,
    "mobile_ready": false,
    "edge_available": true
  }
}
```

Scope order is sorted. Feature-detect from this body. Hide any control
whose scope is absent. `allowed_harness_profiles` is the only set of
profiles the voice screen may send.

### Voice turn

`POST /v1/voice/turns`

```json
{"text": "set the living room to 20", "profile": "home-action"}
```

`profile` is `chat` or `home-action`, or it is omitted. `text` is 1 to
4000 characters, the transcript only. An omitted profile asks the mini
to route the words (ADR 0030): a device phrase becomes `home-action`
on the matching slot, and anything else becomes `chat`. "turn all tvs
off" is one turn that repeats the closed power action on every bound
set. Sending `profile` is still valid and keeps the previous meaning.

| Status | `error.code` | What the UI does |
| --- | --- | --- |
| 202 | — | `profile: chat` is stored. `profile: home-action` is stored when the mini's climate, television, or vacuum binding is enabled. An omitted profile is stored as whichever of those the route selects. The `VoiceTurnReceipt` is authoritative. `reply` is plain text only when `status` is `complete`. `climate`, `tv`, or `vacuum` is the device read-back for one target. `fanout` lists every target when the instruction was repeated. `route_slots` names the device slots that were selected. `awaiting_approval` carries `action_digest` and `pending_action` or `pending_tv`. Do not speak `reply` in this build. A voice turn does not add a coding-task row. |
| 403 | `forbidden` | The profile is not allowed. If the detail is `client cannot submit self-build`, the app tried the coding path. That is a bug in the app. Do not retry. |
| 409 | `profile_not_executable` | `home-action` was not stored because no local climate, television, or vacuum binding is enabled. Tell the operator the pipe works and the binding is off. |
| 401 | `unauthorized` | Enrollment or the edge token on the mini is wrong. Send the operator back to enrollment. |
| 422 | `validation_error` | The transcript was empty or the JSON gained a field. |

Do not call `POST /v1/tasks`. That is the coding submit path. The watch
receives 403 `client cannot submit self-build`. Do not call pause,
resume, cancel, config, or artifact content. Those scopes are absent
on purpose.

`tasks:message` is also absent. Do not post messages onto an existing
coding task.

### Reading state

`GET /v1/system/health` and `GET /v1/system/queue` need `system:read`.

`GET /v1/tasks` and `GET /v1/tasks/{id}` need `tasks:read`. The task
projection includes open approvals. Show action class, digest, and
consequences from that projection. Do not show a diff patch. `GET
/v1/tasks/{id}/diff` returns `source_included: false` for this client.
Render the summary counts only.

### Approval

`POST /v1/tasks/{id}/approvals/{approval_id}/decide`

```json
{"decision": "approve", "action_digest": "sha256:…"}
```

`decision` is `approve` or `reject`. The digest on screen is the
digest in the body. The app does not let the operator edit it. A
notification tap is not a decision. The screen shows the digest and
waits for an explicit button. Silence is not approval. A 409
`stale_digest` means the action changed. Reload the task and stop.

The server records the principal as `client:watch`. Do not send
`actor` in an attempt to look like the operator. The body field is
ignored for this client.

## Speech

Push to talk. The microphone is live only while the finger is on the
button and the watch app is in the foreground. There is no background
wake word. watchOS will not give this app one.

Use `SFSpeechRecognizer` with `requiresOnDeviceRecognition = true`.
If `supportsOnDeviceRecognition` is false for the locale, show that
locale as unavailable and do not send audio to Apple or to the mini.
The request body is the transcript string. Do not upload audio, a
partial hypothesis stream, or a recording file.

A chat receipt may include `reply` when the turn is `complete`. Do not
speak it in this build. Playback stays later. Do not AirPlay to a
HomePod. When a later build is told to speak, use `AVSpeechSynthesizer`
on the watch.

## Screens

1. **Enroll** (iPhone). Pick the p12, type the password, pin the CA,
   save the mini's private host and port. A button runs
   `GET /v1/system/capabilities` and shows the principal.
2. **Talk** (watch). Hold to speak. Release sends one voice turn.
   Show the status from the table above. One turn at a time.
3. **House** (watch and phone). Health and queue. Empty and error
   states are real screens, not blank views.
4. **Approval** (watch and phone). One open approval at a time, digest
   visible, approve and reject. Disabled when the scope is missing or
   the watch is locked. The watch must be unlocked to decide.

Keep the phone and the watch on the same API client. A decision on the
phone is the same request as a decision on the watch.

## Security checks before calling the app done

- A build contains no token, no p12, no CA key, and no LAN address.
- The binary does not reference `TWO_API_TOKEN` or `TWO_EDGE_TOKEN`.
- Server trust fails when the pinned CA is replaced.
- Client-certificate challenge is answered only with the enrolled
  identity.
- Keychain items are device-only and not synchronizable.
- The voice screen cannot construct `profile: self-build`.
- The app does not request `tasks:control` routes.
- Background modes do not include audio recording.
- Logs and screenshots paths do not include the transcript after the
  request completes. The on-screen confirmation can show it until the
  operator leaves the screen.

## Tests the Xcode agent runs

Unit-test the API client against a fixture `URLProtocol`:

- Capabilities decode, including `allowed_harness_profiles`.
- Voice turn encodes only `text` and `profile`.
- 403, 409 `profile_not_executable`, 401, and 422 map to the UI states
  above.
- A diff fixture with `source_included: false` does not render a patch.
- Decide request uses the digest from the task projection unchanged.

On a watch simulator or a device, with Caddy and `two api` running on
the mini or a stand-in that speaks this JSON:

- Enrollment, then capabilities shows `client:watch`.
- A chat turn returns `202` and a receipt. The coding task list does
  not gain a row. Do not speak `reply`. `home-action` returns `202`
  when the climate binding is enabled, and `409`
  `profile_not_executable` when it is not. An out-of-band climate
  write stays `awaiting_approval` until approve or reject posts the
  same `action_digest`.
- Approve and reject against a fixture approval, including a stale
  digest.
- Airplane mode shows unreachable, and does not queue an approval
  decision for later.

## Explicitly later

- OIDC Authorization Code plus PKCE, or device code, after ADR 0016.
- Speech playback. Climate execution is ADR 0022. Chat storage is B20.
- AirPlay of a spoken reply to a HomePod group.
- A client key generated on the watch instead of a PKCS#12 from the mini.
