# Playwright test conventions (Samana ERP)

Read this before writing any spec. Auth helpers live in `tests/helpers/auth.ts`.

## Import paths (from `tests/<app>/<app>.spec.ts`)
```ts
import { test, expect } from '@playwright/test';
import { loginViaApi, loginViaUi, ROLES, RoleName } from '../helpers/auth';
```

## Test naming — MUST match scenario IDs
- `test.describe('<Category>')` groups by HP / EC / SEC / API / A11Y.
- `test('<ID> — <title>', ...)` where `<ID>` is the exact scenario id from `specs/<app>.md`
  (e.g. `CUS-HP-01`, `BOOK-EC-01`). This is the contract; do not rename.

## Two flavors
- **API scenarios** → `test('<ID>', async ({ request }) => {...})`. Authenticate with
  `const token = await loginViaApi(request, 'accounts');`. The `request` context keeps the
  session cookie; GET needs no CSRF, unsafe writes pass `headers: { 'X-CSRFToken': token }`.
- **UI scenarios** → `test.use({ storageState: 'tests/.auth/<role>.json' })` on the `describe`
  (or a `test.describe` per role) and use `page`.

## Locators & assertions (non-negotiable)
- Role/label-based locators ONLY: `getByRole`, `getByLabel`, `getByText`, `getByPlaceholder`.
  No CSS/XPath unless a `data-testid` is genuinely absent AND a role locator is impossible.
- Web-first assertions only: `await expect(locator).toBeVisible()`, `.toHaveText(...)`,
  `.toHaveURL(...)`, `.toContainText(...)`. NEVER `waitForTimeout` for assertions.
- Money asserted EXACTLY: DRF returns Decimal strings like `"75000.00"`; assert against those,
  never `Math.floor`/loose floats. (Portal endpoints `float()` money — assert those accordingly.)

## Bug scenarios (confirmed defects) — write them RED on purpose
Confirmed bugs are in `docs/qa/findings-confirmed.md`. For those scenarios, assert the CORRECT
behavior (e.g. a sales user must NOT be able to set `role=super_admin`), which will FAIL because
the app is buggy. Add a comment `// CONFIRMED BUG: see docs/qa/findings-confirmed.md F1`. Do NOT
weaken the assertion to make it green. Do NOT use `test.fixme` for these — they must stay red.

## Data isolation
- Unique, timestamped data (`QA-${Date.now()}`) for anything created.
- `afterEach`/`afterAll` deletes records the test created (via API or a cleanup helper), unless
  the spec is explicitly read-only. Never wipe shared tables.

## Non-deterministic modules
- `ai` and `notifications`: assert SHAPE only (structure/presence/error/empty-state), never exact
  LLM prose or live SMS/email content. If AI is disabled (`AI_ENABLED=False`), assert the 503/`ok:false`
  contract.

## Style
- One `test` per scenario; keep each independent and order-free.
- Prefer `request` for pure data-plane/security checks; use `page` only for real UI flows.
