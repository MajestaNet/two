# docs/backlog

Dedicated, agent-executable implementation items. One file per item.

- `README.md` is the index: order, dependencies, status.
- [B01](B01-mac-inference-appliance.md)–[B17](B17-github-export.md) are
  the original numbered items; B14 is now the secure first-party mobile
  client direction from ADR 0015. [B18](B18-streamlined-lan-setup.md)
  is operator-path convenience (ADR 0013). [B19](B19-persisted-work-graph.md)
  is the persisted work graph around DeepSeek Harness (ADR 0014).
  [B20](B20-chat-profile-resume.md) resumes harness profile `chat` on
  the single inference slot (ADR 0021). It is done.
  [B21](B21-climate-home-action.md) executes the closed climate tools
  on `home-action` (ADR 0022) and leaves the slot default off.
  [B22](B22-tv-home-action.md) executes the closed television tools
  on the same profile (ADR 0029) and leaves that slot default off.
  [B23](B23-utterance-routing.md) routes an omitted profile and repeats
  one closed action for `all` (ADR 0030). The device slots stay off.
  [B24](B24-local-operator-console.md) is the loopback operator window
  (ADR 0031, ADR 0032). It stays default off and does not replace B14.
  Landing any of these items does not close architecture §21 item 20.
  Do not merge two items in one PR unless the item file says they may
  land together.
- Point at `docs/architecture.md` instead of copying it.
- When an item is implemented, update its Status field and the index
  table in the same PR. Do not mark done unless `make ci` is green and
  the item's acceptance criteria pass.
- If implementation would disagree with the spec, stop and write an ADR.
