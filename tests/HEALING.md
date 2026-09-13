# Browser-suite healing patterns (proven)

These are the systematic bugs in the generated browser suites and their fixes. Apply them to
every `tests/browser/*.browser.spec.ts`, then RUN the suite with `--workers=1` and iterate until
green (except the intentional confirmed-bug REDs marked `// CONFIRMED BUG`).

Reference clean suite: `tests/browser/bookings.browser.spec.ts` (15 green + 2 confirmed REDs).

## Pattern 1 — fixture ID resolution (the #1 cause of 400s)
DRF **create** serializers omit the numeric `id`:
- `CustomerCreateSerializer` returns `customer_id` (string) only.
- `BookingCreateSerializer` returns no `id`/`booking_id`.
- `PaymentCreateSerializer` returns `payment_id` (string) only.

So `const body = await res.json(); body.id` is `undefined`, which then POSTs `customer: null` /
`plot: null` and 400s downstream. **Fix:** after creating, resolve the numeric id via a list GET:
```ts
// customer
const list = await (await req.get(`/api/customers/?search=${encodeURIComponent(cnic)}`)).json();
const id = list.find(c => c.cnic === cnic).id;
// booking
const list = await (await req.get(`/api/bookings/?plot=${plotId}`)).json();
const id = list.find(b => b.plot === plotId).id;
```
A correct shared factory already exists: `tests/helpers/fixtures.ts` (`createCustomer`, `createProject`, `createPlot`, `createBooking`, `seedBookingChain`). Prefer importing it over local helpers.

## Pattern 2 — `<select>` fields have no `for`, so `getByLabel` fails
Form `<select>` labels are rendered without a `for` attribute. **Fix:** use
`page.locator('select[name="plot"]')` / `select[name="customer"]` / `select[name="payment_method"]`
instead of `getByLabel('Plot')` etc. Text/number/date inputs DO have labels, so `getByLabel` is fine
for those.

## Pattern 3 — API verify requires `action`
`POST /api/payments/{id}/verify/` requires `data: { action: 'verify' }` (else 400). It returns JSON
(200/400), never a redirect. The WEB flow (`/payments/{id}/verify/`) is a Django view that redirects
(302). Do not mix them up:
- API verify: `request.post('/api/payments/'+id+'/verify/', { data: { action: 'verify' }, headers: csrf(token) })`.
- Web verify: drive the UI button, or expect 302 from `/payments/{id}/verify/`.

## Pattern 4 — money serialization is inconsistent
DRF returns Decimal strings for most money (`"300000.00"`), but bare numbers for `current_balance`
and `remaining_balance` (computed properties). Assert those as numbers (`toBe(700000)`), not strings.

## Pattern 5 — seed state / shared users
Re-run `seed_roles.py` before a run. RED escalation tests must restore state in `finally` (they
mutate `qa_sales` role / `qa_customer` profile). Prefer having RED tests operate on throwaway users
they create themselves, not the shared seeded users.

## Pattern 6 — page auth must be done FRESH, not via storageState (CRITICAL)
`test.use({ storageState: 'tests/.auth/<role>.json' })` is fragile: the saved `sessionid` goes
stale (Django session rotation / server restarts / repeated runs), so `page.goto('/protected/')`
redirects to `/login/?next=...` — the test is logged out even though the `request` fixture works
(it logs in fresh). **Fix:** log the PAGE in fresh in a `beforeEach` using `page.request` (which
shares the page's cookies):

```ts
test.beforeEach(async ({ page }) => { await loginViaApi(page.request, 'admin'); });
```

Replace every `test.use({ storageState: 'tests/.auth/<role>.json' })` with the matching
`test.beforeEach(async ({ page }) => { await loginViaApi(page.request, '<role>'); })`.
EXCEPTIONS to leave untouched:
- `test.use({ storageState: { cookies: [], origins: [] } })` — used by the auth/login tests that
  must start logged OUT.
- A `test.use({ storageState: \`tests/.auth/${role}.json\` })` inside a loop (dashboard role matrix):
  instead do the login inside the loop body via `await loginViaApi(page.request, role)`.

Ensure `loginViaApi` is imported from `../helpers/auth` in every file.

## Run command
```
env -u PYTHONPATH DJANGO_DEBUG=True /d/samana/.venv312/Scripts/python.exe tests/fixtures/seed_roles.py
npx playwright test tests/browser/<suite>.spec.ts --workers=1 --reporter=line
```
Server must be running with DJANGO_DEBUG=True. Never weaken a `// CONFIRMED BUG` assertion to make it green.
