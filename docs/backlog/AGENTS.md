# docs/backlog

Dedicated, agent-executable implementation items. One file per item.

- `README.md` is the index: order, dependencies, status.
- `B01`–`B16` are the work. Do not merge two items in one PR unless the
  item file says they may land together.
- Point at `docs/architecture.md` instead of copying it.
- When an item is implemented, update its Status field and the index
  table in the same PR. Do not mark done unless `make ci` is green and
  the item's acceptance criteria pass.
- If implementation would disagree with the spec, stop and write an ADR.
