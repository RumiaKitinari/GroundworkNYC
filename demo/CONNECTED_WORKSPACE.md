# Connected Account Workspace

## Workflow

- **Properties:** save up to four individual properties per concept and transaction type; compare prices, floor area, kitchen information, customer access and area scores. Records outside the current search remain saved and are labeled unavailable rather than silently removed.
- **Overview:** search property IDs, addresses and neighborhoods. A separate selected-property layer stays visible at wider zoom levels, without changing Streets, Aerial, 3D, zoom, pan or fullscreen controls.
- **Economics:** copy the selected lease rent explicitly, leaving the search budget unchanged. Save up to twelve named scenarios (including Conservative, Expected and Optimistic), reload/remove them and compare their profit curves, break-even volume, capacity utilization and operating losses. Lease and purchase assumptions remain separate. Purchase financing is not inferred.
- **Menu Studio:** review section balance; record comma-separated ingredients and preparation complexity; see ingredients shared across dishes. Configure portions in a guest basket and explicitly transfer its spend to Economics. Ingredient cost remains separate from the full variable-cost assumption, which also needs labor, packaging and other expenses. No basket is presented as an observed customer order.
- **Decision Report:** selected property, saved property alternatives, menu prices/costs, guest basket, financial assumptions and scenario results, a profit-volume graphic, integrated-release identifier and outstanding checks. Print waits for scenario calculations before enabling export.
- **Settings:** save a name and company in the private workspace. Guests remain device-only; signed-in users see account synchronization status. Reconnection retries synchronization; logout attempts to flush pending changes first.

## Database And Privacy

The existing Flask account store is `instance/accounts.sqlite3`, not browser-only storage. Passwords are hashed. `account_workspaces` contains one JSON workspace per session-owned account ID, with an incrementing revision. Its JSON contract now accepts optional `plans` and `profile` fields without changing existing brief, shortlist or menu records.

Workspace reads/writes require authentication; writes require CSRF and a matching revision. The revision check/write now runs inside `BEGIN IMMEDIATE` to prevent concurrent writes accepting the same revision. Payloads are bounded at 500 KB; counts, text lengths, financial ranges and menu planning values are validated. Responses use `Cache-Control: no-store`. Browser storage is a device-side draft/recovery copy, namespaced by account, not the authority used for fresh-browser restoration.

Concurrent-session reconciliation compares the previous server version, current server version and this editor's draft. Independent remote edits survive; explicit local deletions are not unioned back into existence. On a conflicting edit to the same field, this editor's draft wins. These rules are covered by `backend/tests/frontend_planning.test.cjs`.

These are local accounts. Deployment needs a persistent private database volume, secret management, backups, HTTPS and production account protections; copying the public repository alone does not transfer account data. Do not commit the instance database, secrets or private workspaces.

## Verification

- `demo/test_auth.py` and `demo/test_workspace_planning.py`: authentication, CSRF, revision conflicts, backward compatibility, invalid payload rejection, fresh-login persistence and isolation between two accounts using temporary databases.
- Chrome and WebKit desktop/mobile checks: property shortlist, selected marker at wide zoom, menu pricing and preparation notes, guest basket transfer, three saved scenario overlays, report contents and settings profile. A fresh browser context with no local storage restores the account workspace from a temporary test database. No test accounts are written to the live account database.
- Existing full dashboard regression checks retain all eleven views and all three map styles.

## Evidence Boundaries

Synthetic property scenarios remain explicitly synthetic. Economic calculations use user-entered assumptions, not a trained revenue forecast. Research survival artifacts are not silently deployed or converted to verified success probabilities. These workflow changes do not retrain or change the scoring methodology.
