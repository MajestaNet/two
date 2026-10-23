# ADR 0028 — Home-action speaks pinned Harness ACP

## Status

Accepted

## Context

ADR 0022 says DeepSeek Harness emits `climate.read`,
`climate.set_setpoint`, or `climate.set_mode`, and this process performs
the call. It does not send `execute` to the child. A plain assistant
reply is stored and does not touch a device. The install binds zones. It
does not register tools. An install-registered MCP server was rejected
because that would put an open tool list and the device credential in
the harness profile.

ADR 0011 launched that profile as `dsh acp --profile home-action`. ADR
0025 records that pin `dsh-v0.1.2-alpha.1` does not implement that CLI.
Its automation server is `dsh --profile acp`. Chat already uses that
client. Home-action production still built the old argv and looked up
`dsh` on `PATH`. The pinned wrapper is not on `PATH`, so the child never
started and the turn failed `internal` before any device I/O.

The pin also has no climate tool. A prompt that only names
`climate.read` produces an assistant sentence. ADR 0022 says that
sentence is not a device result.

## Decision

1. **Production home-action uses the same pinned client as chat.** When
   no argv is injected, the child is `dsh --profile acp` from
   `$TWO_DATA_DIR/harness/bin/dsh` (PATH still wins for tests), with
   `DSH_HOME`, the rendered `mac-qwen` provider, and
   `DSH_TELEMETRY_DISABLED=1`. The profile directory stays
   `$TWO_DATA_DIR/profiles/home-action`. One inference runs at a time, so
   this turn rewrites `$TWO_DATA_DIR/harness/home/cordis.patch.yml`
   before spawn. The next chat turn writes the chat patch back. Injected
   argv stays on the ADR 0011 JSONL fixture. Coding tasks stay there too.
2. **The session advertises only the three closed tools.** The worker
   passes one stdio server on `session/new` and `session/resume`. The
   server is this repository's `climate_mcp.py`. It lists `climate_read`,
   `climate_set_setpoint`, and `climate_set_mode`. It has no binding, no
   address, and no token. `tools/call` does not perform a device call; it
   waits until the client closes. The model-facing names are
   `mcp__climate__climate_read`, `mcp__climate__climate_set_setpoint`,
   and `mcp__climate__climate_set_mode`. The worker maps those back to
   the closed contract names before policy runs.
3. **This process still performs the call.** The first ACP `tool_call`
   whose title maps to a closed tool stops the child. The worker does
   not send `execute`. `interpret_tool` and the existing broker path
   allow, hold, or deny it. Any other tool fails the turn with
   `profile_tool_denied`. A permission request is rejected so the
   harness does not run the tool. A prompt that ends with assistant text
   and no climate tool is stored and does not touch a device.
4. **The patch disables shell, filesystem, web, and subagents.** It
   selects `mac-qwen` and names the zone ids. It does not contain the
   upstream, the unit address, or a token. `climate.yaml` still does not
   register tools.

## Consequences

- A home-action turn can reach Qwen and, when the model requests one of
  the three tools, the control plane performs it.
- ADR 0022 remains the tool contract and the rule that the harness does
  not perform device I/O. This ADR narrows the rejected MCP alternative
  to a credential-free advertisement of that same closed list.
- ADR 0025 still covers chat. ADR 0011 still covers the fixture dialect
  and coding-task argv.

## Alternatives rejected

- **Keep `dsh acp --profile home-action`.** The pin does not implement
  it, and `dsh` is not on `PATH`. Every live turn fails `internal`.
- **Treat an assistant sentence as a device command.** ADR 0022 already
  says a reply with no tool does not touch a device.
- **Let the MCP server perform the ECHONET or Home Assistant call.**
  That sends the binding into a process the model can invoke, which is
  the rejection in ADR 0022.
- **Reimplement the agent loop in Majesta Two.** Architecture forbids it.
