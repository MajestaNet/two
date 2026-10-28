# ADR 0042 — Ecovacs device list is GET

## Status

Accepted. Amends ADR 0038 decision 6. Does not add a host, a second
transport, or the vendor MCP process.

## Context

ADR 0038 sends the Access Key in the JSON body of every Open API call
and refuses a query string. `two vacuum robots` posted
`/robot/deviceList` that way. The official Open API answers that path
with GET and `ak` as a query parameter. POST returns HTML 404. A live
Australian account returned `Bob` and `Lynne` on GET
`https://open.ecovacs.com/robot/deviceList?ak=…` and rejected the same
key on `.cn`.

Control (`/robot/ctl`) already succeeds as POST with the key in the
JSON body.

## Decision

1. **List is GET.** `vacuum` listing calls only
   `GET https://<api_host>/robot/deviceList?ak=…` on
   `open.ecovacs.com` or `open.ecovacs.cn`. Redirects stay refused.
2. **Control stays POST JSON.** `vacuum.read`, `vacuum.clean`, and
   `vacuum.dock` still POST `/robot/ctl` with `ak` in the body, not the
   query string.
3. **The key still never reaches the harness.** It remains the value of
   `token_env`. Listing may place it on that one official query
   parameter because the vendor contract requires it.

## Consequences

- Architecture §5.2 and setup record the GET exception for listing.
- A POST list is not retried. An empty list is success with no names.
