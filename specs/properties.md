# Properties — Test Plan

> Scenario IDs are the contract Phase C test names must match. Read with
> `docs/qa/properties_analysis.md` and `docs/qa/_shared-context.md`. Line refs are
> to the files as of writing. "Web" = server-rendered views in `core/views.py`;
> "API" = DRF ViewSets in `properties/api_views.py`.

## 1. Scope & roles

This plan covers the inventory backbone of the ERP: `Project` → `ProjectPhase` →
`Plot` (pricing, statuses, `total_cost = price + development + lease + other`
charges), `PriceHistory`, `ProjectMilestone`, the public availability endpoint,
and the web + API surfaces that create/edit/delete them. It deliberately probes
the two places where the web and API layers disagree: **role authorization** (web
`plot_create`/`plot_edit`/`project_create`/`reservation_create` are `@login_required`
only, while the API restricts writes to super_admin/admin/management) and
**deletion guards** (web views guard, API ViewSets do not).

Roles exercised (see `_shared-context.md` §Roles):
- **superuser** — always treated as `super_admin`; allowed everywhere.
- **management** (`management`) — allowed to create/edit/delete via web and write via API.
- **sales** (`sales`) — **expected to be denied** write access, but the web layer
  currently lets it create projects/plots and edit any plot. Scenarios PROP-SEC-02
  through -05 assert this defect; PROP-SEC-06 and -11 assert the parts that *are*
  correctly denied.

## 2. Preconditions & fixtures

Create the three users in a Django shell (or via `createsuperuser` + admin):

```python
from django.contrib.auth.models import User
from core.models import UserProfile
def make(u, role):
    usr = User.objects.create_user(username=u, password='Passw0rd!123', is_staff=True)
    UserProfile.objects.create(user=usr, role=role)
    return usr
make('mgmt', 'management')
make('sales', 'sales')
# superuser: admin / admin123 (default) — is_superuser=True → super_admin
```

**Timestamped uniqueness**: every project/plot/milestone created in a scenario
must use a unique suffix, e.g. `PROP-TEST-{epoch}` or `{scenario_id}-{ts}`, so
`Plot.unique_together = ['project', 'plot_number']` never collides across runs.
Use a fresh project per scenario; never assume a plot number is free.

**ORM-only charge setup** (the three charge fields + `holding_deposit` cannot be
set via form/serializer/admin — see PROP-EC-07):

```python
from decimal import Decimal
from properties.models import Plot
p = Plot.objects.get(pk=PID)
p.development_charge = Decimal('150000.00')
p.lease_charge = Decimal('50000.00')
p.other_charges = Decimal('25000.00')
p.holding_deposit = Decimal('100000.00')
p.save()
```

**Money assertion**: assert `Decimal` values exactly (e.g. `Decimal('500000.00')`),
never via float.

### URLs exercised (relative to `http://127.0.0.1:8000`)

Web:
- `GET /properties/` — list + filters (`properties`)
- `GET|POST /properties/project/create/` (`project_create`)
- `GET|POST /properties/project/<pk>/edit/` (`project_edit`)
- `GET|POST /properties/project/<pk>/delete/` (`project_delete`)
- `GET|POST /properties/plot/create/` (`plot_create`)
- `GET|POST /properties/plot/<pk>/edit/` (`plot_edit`)
- `GET|POST /properties/plot/<pk>/delete/` (`plot_delete`)
- `GET /properties/plot/<pk>/` (`plot_detail`)
- `GET|POST /properties/reserve/` (`reservation_create`)
- `GET /projects/milestones/`, `GET|POST /projects/milestones/create/`, `GET|POST /projects/milestones/<pk>/edit/`

API (session-authenticated; prefix with `/api`):
- `GET|POST /projects/` · `GET|PUT|PATCH|DELETE /projects/<id>/`
- `GET|POST /plots/` · `GET|PUT|PATCH|DELETE /plots/<id>/` · `POST /plots/<id>/change_status/`
- `GET /plots/list/` (public, AllowAny)
- `GET /price-history/` · `GET /project-milestones/` · `POST /project-milestones/<id>/set_status/`

## 3. Scenario catalog

### HP — happy path

**PROP-HP-01 — Create project (web)**
- Preconditions: logged in as `mgmt`. A timestamped unique name ready.
- Steps: GET `/properties/` → click "+ Add Project" → fill name/location/description/total_plots/status → submit.
- Expected: 302 redirect to `/properties/`; success message; project appears in Projects table; `AuditLog` row with `action='create'`, `model_name='Project'`, `description` containing the name.
- Evidence on failure: no AuditLog row; project missing from list; form error not surfaced.

**PROP-HP-02 — Create plot (web)**
- Preconditions: `mgmt`; an existing project (from HP-01). Unique plot number.
- Steps: GET `/properties/` → "+ Add Plot" → fill plot_number, project, plot_type, size_marla, price, status → submit.
- Expected: 302 to `/properties/`; plot listed with `Rs. {price}`; `plot.status == 'available'`; `plot.total_cost == plot.price` (charges default 0); `AuditLog` `action='create'`, `model_name='Plot'`.
- Evidence on failure: plot absent; `total_cost != price`; no AuditLog.

**PROP-HP-03 — `total_cost = price + charges` with ORM-set charges**
- Preconditions: plot created in HP-02. Shell-set charges per §2 (dev 150000 + lease 50000 + other 25000).
- Steps: reload `/properties/plot/<pk>/` and compute `plot.total_cost`.
- Expected: `total_charges == Decimal('225000.00')`; `total_cost == price + Decimal('225000.00')` exactly. Booking create form then treats this `total_cost` as the floor (see PROP-EC-08 for the negative case).
- Evidence on failure: wrong `total_cost`; charges not reflected.

**PROP-HP-04 — Plot `available → reserved` via reservation (web)**
- Preconditions: `mgmt`; an `available` plot; a customer exists.
- Steps: POST `/properties/reserve/` with plot + customer + valid dates.
- Expected: reservation saved; `plot.status == 'reserved'`; plot badge shows "Reserved"; `AuditLog` `action='create'`, `model_name='Reservation'`.
- Evidence on failure: plot still `available`; no AuditLog.

**PROP-HP-05 — Plot `available → booked` via booking (web)**
- Preconditions: `mgmt`; an `available` plot; a customer.
- Steps: POST booking create with `plot` = that plot, `total_amount ≥ plot.total_cost`, `advance_paid ≥ plot.holding_deposit` and `> 0`.
- Expected: booking created; `plot.status == 'booked'`; a verified `Payment` + `Receipt` auto-created; plot badge "Booked".
- Evidence on failure: plot not `booked`; missing auto-payment/receipt.

**PROP-HP-06 — Edit project (web)**
- Preconditions: `mgmt`; a project.
- Steps: GET `/properties/project/<pk>/edit/` → change name/location/status → submit.
- Expected: 302; changes persisted; `AuditLog` `action='update'`, `model_name='Project'`.
- Evidence on failure: stale values; no AuditLog.

**PROP-HP-07 — Edit plot (web)**
- Preconditions: `mgmt`; an `available` plot.
- Steps: GET `/properties/plot/<pk>/edit/` → change price (e.g. 500000 → 600000) and/or size → submit.
- Expected: 302; `plot.price == Decimal('600000.00')`; `AuditLog` `action='update'`, `model_name='Plot'`.
- Evidence on failure: price unchanged; no AuditLog.

**PROP-HP-08 — Milestone create (web)**
- Preconditions: `mgmt`; a project.
- Steps: GET `/projects/milestones/create/` → fill title, project, milestone_type, start_date, target_date, completion_percent, status, order → submit.
- Expected: milestone created with all fields persisted (including the new `start_date`, `milestone_type`, `completion_percent`, `progress_date`); appears in `/projects/milestones/` with progress bar reflecting `completion_percent`.
- Evidence on failure: new fields blank after save; milestone missing from list.

**PROP-HP-09 — Milestone edit (web)**
- Preconditions: `mgmt`; milestone from HP-08.
- Steps: GET `/projects/milestones/<pk>/edit/` → change `completion_percent`/`status`/`target_date` → submit.
- Expected: changes persisted; list progress bar updates.
- Evidence on failure: stale values.

**PROP-HP-10 — Plot detail (web)**
- Preconditions: `mgmt`; a plot with a booking and a price-history row.
- Steps: GET `/properties/plot/<pk>/`.
- Expected: renders plot fields, related bookings/reservations/documents, and price history (last `changed_at` first).
- Evidence on failure: missing sections; price history empty when rows exist.

### EC — edge case / boundary

**PROP-EC-01 — Duplicate `plot_number` within a project rejected (web)**
- Preconditions: `mgmt`; a plot `P1` with `plot_number='A-1'` in project `PRJ`.
- Steps: POST `/properties/plot/create/` with same project + `plot_number='A-1'`.
- Expected: form re-renders with a field error (from `ModelForm.validate_unique`); no second plot; HTTP 200 (not 500).
- Evidence on failure: 500 traceback; duplicate row created.

**PROP-EC-02 — Duplicate `plot_number` within a project via API (raw 500)**
- Preconditions: `mgmt` (API write role); plot `A-1` in `PRJ`.
- Steps: `POST /api/plots/` with `{"project": PRJ_id, "plot_number": "A-1", "size_marla": "10.00", "price": "500000.00"}`.
- Expected (current defect): HTTP **500** with `IntegrityError: UNIQUE constraint failed` (unique_together) — the API does not run `validate_unique`, so it returns a 500, not a 400.
- Evidence on failure: a 400 returned (means it was fixed); or a duplicate row without error.

**PROP-EC-03 — Same `plot_number` across different projects allowed**
- Preconditions: two projects `PRJ_A`, `PRJ_B`.
- Steps: create `plot_number='A-1'` in both.
- Expected: both save successfully (unique_together is per-project).
- Evidence on failure: second save raises IntegrityError.

**PROP-EC-04 — Negative/zero `price` rejected (web)**
- Preconditions: `mgmt`.
- Steps: POST `/properties/plot/create/` with `price=0` then `price=-100`.
- Expected: both rejected with "Price must be greater than 0"; no plot created.
- Evidence on failure: plot saved with 0/negative price.

**PROP-EC-05 — Negative/zero `size_marla` rejected (web)**
- Preconditions: `mgmt`.
- Steps: POST `/properties/plot/create/` with `size_marla=0` then `-5`.
- Expected: rejected with "Size must be greater than 0"; no plot.
- Evidence on failure: plot saved.

**PROP-EC-06 — Negative/zero `price` rejected (API)**
- Preconditions: `mgmt`.
- Steps: `POST /api/plots/` with `"price": 0` and again `"price": -1`.
- Expected: HTTP 400 with `price` validation error (`validate_price`).
- Evidence on failure: 201 created; 500.

**PROP-EC-07 — Charge fields absent from form/serializer/admin (ORM-only)**
- Preconditions: `mgmt`; a plot.
- Steps: (a) GET `/properties/plot/create/` and `/properties/plot/<pk>/edit/` — confirm no input for `development_charge`/`lease_charge`/`other_charges`; (b) `GET /api/plots/<pk>/` — response omits those keys; (c) Django admin Plot change page — fieldsets omit them; (d) `holding_deposit` **is** present in form + serializer + admin.
- Expected: charges absent in all three surfaces but present as model fields; `holding_deposit` present everywhere. This means the pricing guard inputs (`total_cost` components) can only be set via ORM/shell/migration.
- Evidence on failure: a charge input appears in form/admin; `development_charge` key present in API response.

**PROP-EC-08 — Negative charge via ORM drives `total_cost` below `price`**
- Preconditions: `mgmt`; plot with `price=500000.00`. Shell-set `development_charge=-200000.00`.
- Steps: compute `plot.total_cost`; then attempt a booking with `total_amount=500000.00` (equal to price).
- Expected (defect): `total_cost == Decimal('300000.00')` (below price); the booking floor silently lowers, so `total_amount=500000.00` passes even though charges are "negative". No validation rejects negative charges anywhere.
- Evidence on failure: `total_cost == price` (charge ignored); booking rejected.

**PROP-EC-09 — Reservation expiry never processed**
- Preconditions: `mgmt`; a plot reserved via a `Reservation` whose `expires_at` is in the past (set via ORM/shell).
- Steps: wait/no-op; reload `/properties/`; run `python manage.py help` / search for an `expired` transition job.
- Expected (defect): `plot.status` stays `reserved` forever; no management command or cron marks the reservation `expired`. (The only `expired` path is reservation `convert` when the plot was already taken.)
- Evidence on failure: a command/cron exists that flips it; plot becomes `available`.

**PROP-EC-10 — `plot_edit` has no status guard (booked/sold plot re-listed)**
- Preconditions: `mgmt`; a plot currently `booked` (has a booking) or `sold`.
- Steps: GET `/properties/plot/<pk>/edit/` → change `status` to `available` → submit.
- Expected (defect): 302 success; `plot.status == 'available'` while the booking still references it — the plot is re-listed as "Available" and "Book"-able in `/properties/`.
- Evidence on failure: edit blocked with an error (means fixed).

**PROP-EC-11 — Price-history not written on web plot edit**
- Preconditions: `mgmt`; a plot with no price history.
- Steps: change `price` via `/properties/plot/<pk>/edit/` (web), then query `PriceHistory.objects.filter(plot=plot)`; separately change price via `PUT/PATCH /api/plots/<pk>/` and query again.
- Expected: web edit writes **no** `PriceHistory` row (defect); API edit writes one (`change_reason='API update'`, `changed_by` set).
- Evidence on failure: web edit produced a row (fixed); API edit produced none.

**PROP-EC-12 — `Project.booked_plots` counts reserved as booked**
- Preconditions: a project with one `reserved` plot and zero `booked` plots.
- Steps: evaluate `project.booked_plots`.
- Expected (defect): returns `1` (counts `status__in=['booked','reserved']`), so "booked" stats over-count reserved inventory. `available_plots`/`sold_plots` only count their own status.
- Evidence on failure: returns 0.

**PROP-EC-13 — Properties search input dead**
- Preconditions: `mgmt`; multiple plots with distinct `plot_number`s.
- Steps: GET `/properties/?search=<substring>` matching a known plot number.
- Expected (defect): the result set is identical to no-search — `properties_view` never reads `search` (`core/views.py:836-843`), so the box filters nothing.
- Evidence on failure: the list narrows to matches.

**PROP-EC-14 — Milestone `completion_percent` > 100 accepted**
- Preconditions: `mgmt`; a milestone.
- Steps: POST `/projects/milestones/<pk>/edit/` with `completion_percent=250` (bypassing the HTML `max=100`).
- Expected (defect): 302 success; `completion_percent == Decimal('250.00')` (no server-side 0–100 clamp).
- Evidence on failure: rejected with validation error.

**PROP-EC-15 — `on_hold` status invisible and never set**
- Preconditions: a plot with `status='on_hold'` (via ORM).
- Steps: (a) open `/properties/` and inspect the status filter dropdown; (b) try to transition it via any UI/API trigger.
- Expected (defect): `on_hold` is absent from the filter options (only available/reserved/booked/sold/cancelled listed); no view/API ever sets `on_hold`; the plot's badge falls to the `else` "danger" branch.
- Evidence on failure: `on_hold` appears in the dropdown.

### SEC — negative & security (prioritized)

**PROP-SEC-01 — Stored XSS via project name in Delete confirm**
- Preconditions: `sales` (or any staff) logged in — `project_create` is open to them. A second session as `mgmt` (victim).
- Steps:
  1. As `sales`, POST `/properties/project/create/` with
     `name = x');alert(document.domain);//` (and a valid `location`).
  2. The project is saved. Open `/properties/` — the Projects table renders
     `onclick="return confirm('Delete project \'x&#x27;);alert(document.domain);//\'? ...');"`
     (template `properties.html:123`; the single quotes become `&#x27;`).
  3. As `mgmt` (victim), click the **Delete** link for that project.
- Expected (defect): the browser decodes `&#x27;` back to `'` inside the attribute, so the
  JS `confirm('...')` string is terminated early and `alert(document.domain)` executes
  (a dialog showing the host). This is **stored** XSS: the malicious project name fires in
  the context of any user who clicks Delete — including management/admin, and even `sales`
  (the Delete link is rendered for every role; only the server-side `project_delete_view`
  is role-gated).
- Evidence on failure: an `alert` (or a chosen payload marker) fires in the victim session;
  the Delete confirm is bypassed. Fix check: name is escaped via `escapejs`/`json_script` or
  a `data-*` + `addEventListener` pattern, and no dialog fires.

**PROP-SEC-02 — `sales` can create a project (role gap)**
- Preconditions: `sales` logged in.
- Steps: GET `/properties/` (note "+ Add Project" is visible, not `{% if %}`-gated) → POST `/properties/project/create/` with valid fields.
- Expected (defect): 302 success; project created; `AuditLog` written. `project_create_view` is `@login_required` only (`core/views.py:855`), so a `sales` user can create projects.
- Evidence on failure: 302 to `/dashboard/` with "denied" message (means fixed).

**PROP-SEC-03 — `sales` can create a plot and set price (role gap)**
- Preconditions: `sales`; an existing project.
- Steps: POST `/properties/plot/create/` with a project + `price=9999999.00`.
- Expected (defect): 302 success; plot created with that price. `plot_create_view` is `@login_required` only (`core/views.py:927`) — sales can set prices.
- Evidence on failure: denied/redirect to dashboard.

**PROP-SEC-04 — `sales` can edit any plot's price/status (role gap)**
- Preconditions: `sales`; a `booked` plot owned by another flow.
- Steps: GET `/properties/plot/<pk>/edit/` → change `price` or `status` → submit.
- Expected (defect): 302 success; the change persists. `plot_edit_view` is `@login_required` only (`core/views.py:948`) — no role gate and no status/ownership guard, so a sales user can re-price or re-list any plot by `pk`.
- Evidence on failure: denied/redirect.

**PROP-SEC-05 — `sales` can create a reservation (role gap)**
- Preconditions: `sales`; an `available` plot; a customer.
- Steps: POST `/properties/reserve/` with plot + customer.
- Expected (defect): 302 success; `plot.status == 'reserved'`. `reservation_create_view` is `@login_required` only (`core/views.py:1448`).
- Evidence on failure: denied/redirect.

**PROP-SEC-06 — `sales` cannot delete project/plot (positive control)**
- Preconditions: `sales`; a project without plots, and an `available` plot without bookings.
- Steps: POST `/properties/project/<pk>/delete/` and `/properties/plot/<pk>/delete/`.
- Expected: both redirect to `/dashboard/` with a denial message; nothing deleted. `project_delete_view`/`plot_delete_view` carry `@management_or_above` (`core/views.py:900,971`).
- Evidence on failure: the object is deleted (means the guard regressed).

**PROP-SEC-07 — API DELETE `/projects/<id>/` has no deletion guard (cascades)**
- Preconditions: `mgmt` (API write role). A project with ≥1 plot, where that plot has a booking + verified payment.
- Steps: `DELETE /api/projects/<id>/`.
- Expected (defect): HTTP 204; the project **and** its plots, bookings, payments are cascade-deleted (only `Plot.phase` is `SET_NULL`). The web view blocks this (`core/views.py:906-912`), but `ProjectViewSet` has no `destroy` override — so the API silently erases financial history.
- Evidence on failure: query counts — project/plot/booking/payment rows all zeroed after the call.

**PROP-SEC-08 — API DELETE `/plots/<id>/` has no booking guard (cascades)**
- Preconditions: `mgmt`; a plot with a booking + verified payment.
- Steps: `DELETE /api/plots/<id>/`.
- Expected (defect): HTTP 204; plot, its bookings and payments cascade-deleted. `PlotViewSet` has no destroy guard (the web `plot_delete_view` blocks it, `core/views.py:976-981`).
- Evidence on failure: booking/payment rows gone; or 400 if fixed.

**PROP-SEC-09 — `change_status` accepts illegal transition (sold → available), no audit**
- Preconditions: `mgmt`; a plot.
- Steps: (a) `POST /api/plots/<id>/change_status/` with `{"status":"sold"}`; (b) then `{"status":"available"}`.
- Expected (defect): both return 200 and persist. The action validates the value against `STATUS_CHOICES` but not the *transition* (`api_views.py:115-125`): `sold → available` succeeds, `old_status` is fetched but unused, and **no** `AuditLog` or `PriceHistory` row is written. A sold plot can be silently re-listed.
- Evidence on failure: `plot.status == 'available'` after a sold status; zero AuditLog rows referencing the change.

**PROP-SEC-10 — `PriceHistoryViewSet` readable by any staff incl. `sales`**
- Preconditions: `sales`; at least one `PriceHistory` row (created by an API plot price change).
- Steps: `GET /api/price-history/`.
- Expected (defect): HTTP 200 with the full list — `old_price`, `new_price`, `change_reason`, and `changed_by`/`changed_by_name`. `PriceHistoryViewSet` uses `IsAuthenticated` (read-only) rather than `ReadOnlyForLowerRoles`, so `sales` can read all price history and the identity of who changed prices.
- Evidence on failure: 403 returned (means fixed); or `changed_by_name` present to a sales session.

**PROP-SEC-11 — `sales` API write blocked (positive control)**
- Preconditions: `sales`.
- Steps: `POST /api/projects/` and `POST /api/plots/` with valid bodies; also `DELETE /api/plots/<id>/`.
- Expected: HTTP 403 for all writes (`ReadOnlyForLowerRoles` restricts writes to super_admin/admin/management); GETs still 200.
- Evidence on failure: a write returns 201/204 (means the API gate regressed to match the web layer).

### API — API contract

**PROP-API-01 — `GET /api/projects/` list + status filter**
- Preconditions: any authenticated user; two projects with different statuses.
- Steps: `GET /api/projects/` then `GET /api/projects/?status=booking_open`.
- Expected: 200; list includes `available_plots`/`booked_plots`/`sold_plots` (read-only) and `status_display`; `?status=` narrows the list.
- Evidence on failure: wrong filters; computed fields missing.

**PROP-API-02 — `POST /api/projects/` (management create)**
- Preconditions: `mgmt`.
- Steps: `POST /api/projects/` with name/location/status.
- Expected: 201; `id`, `created_at` present; `total_plots` defaults 0.
- Evidence on failure: 4xx/5xx.

**PROP-API-03 — `GET /api/plots/` list + filters**
- Preconditions: any authenticated user; plots across projects/statuses/types.
- Steps: `GET /api/plots/`, `?project=`, `?status=`, `?plot_type=`.
- Expected: 200; filters applied; response includes `project_name`, `status_display`; excludes charge fields (`development_charge` etc.).
- Evidence on failure: charge keys present; filters ignored.

**PROP-API-04 — `POST /api/plots/` create + validation**
- Preconditions: `mgmt`.
- Steps: `POST /api/plots/` with valid body; then with `price<=0` and `size_marla<=0`.
- Expected: 201 for valid; 400 for invalid (`validate_price`/`validate_size_marla`); created plot `status='available'`.
- Evidence on failure: invalid body accepted.

**PROP-API-05 — `GET /api/plots/<id>/` detail**
- Preconditions: any authenticated user; a plot with price history + features.
- Steps: `GET /api/plots/<id>/`.
- Expected: 200; `PlotDetailSerializer` shape — `features` array, `price_history` (last 10, `-changed_at`), `project_phase_name`.
- Evidence on failure: detail fields missing.

**PROP-API-06 — `PUT/PATCH /api/plots/<id>/` writes PriceHistory on price change**
- Preconditions: `mgmt`; a plot.
- Steps: `PATCH /api/plots/<id>/` changing `price`.
- Expected: 200; a `PriceHistory` row `{old_price, new_price, change_reason='API update', changed_by=mgmt}`; changing a non-price field writes none.
- Evidence on failure: no PriceHistory row on price change.

**PROP-API-07 — `POST /api/plots/<id>/change_status/` (valid + invalid value)**
- Preconditions: `mgmt`; a plot.
- Steps: `POST .../change_status/` with `{"status":"booked"}` then `{"status":"bogus"}`.
- Expected: 200 for a valid choice; 400 with the choices list for an invalid value. (Transition-validity and audit are covered by PROP-SEC-09.)
- Evidence on failure: invalid value accepted.

**PROP-API-08 — `GET /api/plots/list/` (public, available-only, capped)**
- Preconditions: anonymous (no session); ≥21 `available` plots and some `booked`/`sold`.
- Steps: `GET /api/plots/list/` unauthenticated.
- Expected: 200; contains only `status='available'` plots; at most 20 rows; no booked/sold plot appears.
- Evidence on failure: booked/sold present; more than 20 rows; 401/403.

**PROP-API-09 — `GET /api/price-history/` read-only list + plot filter**
- Preconditions: any authenticated user; multiple price-history rows.
- Steps: `GET /api/price-history/` and `?plot=<id>`.
- Expected: 200; list filtered by plot; `changed_by_name` populated. (Role exposure covered by PROP-SEC-10.)
- Evidence on failure: filter ignored.

**PROP-API-10 — `GET/POST /api/project-milestones/` omits new fields**
- Preconditions: `mgmt`.
- Steps: `GET /api/project-milestones/`; then `POST` with `start_date`, `milestone_type`, `completion_percent`, `progress_date` in the body.
- Expected (defect): `ProjectMilestoneSerializer` fields omit `start_date`/`milestone_type`/`completion_percent`/`progress_date` (`serializers.py:104-106`); the response never returns them and the POST body silently drops them even though the model + web form carry them.
- Evidence on failure: those keys present in the response.

**PROP-API-11 — `POST /api/project-milestones/<id>/set_status/` (no transition guard/audit)**
- Preconditions: `mgmt`; a milestone.
- Steps: `POST .../set_status/` with `{"status":"completed"}` then `{"status":"pending"}` then `{"status":"bogus"}`.
- Expected (defect): `completed` sets `completed_date=today`; `completed → pending` succeeds with `completed_date=None` (no guard); `bogus` → 400. No AuditLog is written for any of it.
- Evidence on failure: `completed_date` not cleared on revert; an AuditLog row appears.

## 4. Data isolation rules

- All project/plot/milestone names and plot numbers carry a unique timestamp/suffix
  (`{scenario_id}-{ts}`). Never reuse a plot number within a project across runs.
- One project per scenario; do not depend on a previous scenario's project still
  existing (several scenarios intentionally delete/cascade).
- Cleanup order matters after destructive scenarios (PROP-SEC-07/-08): restore via a
  fresh migration/fixture or recreate seed data rather than relying on the deleted rows.
- Money values are asserted exactly as `Decimal`; use `Decimal('500000.00')`, not floats.
- Charge fields and `holding_deposit` are set via Django shell (`Plot.objects...`) since
  no form/serializer/admin exposes them (see PROP-EC-07).

## 5. Coverage checklist (for the master map)

```
PROP-HP-01  Create project (web)
PROP-HP-02  Create plot (web)
PROP-HP-03  total_cost = price + charges (ORM-set charges)
PROP-HP-04  Plot available → reserved via reservation (web)
PROP-HP-05  Plot available → booked via booking (web)
PROP-HP-06  Edit project (web)
PROP-HP-07  Edit plot (web)
PROP-HP-08  Milestone create (web)
PROP-HP-09  Milestone edit (web)
PROP-HP-10  Plot detail (web)
PROP-EC-01  Duplicate plot_number within project rejected (web)
PROP-EC-02  Duplicate plot_number within project via API (raw 500)
PROP-EC-03  Same plot_number across projects allowed
PROP-EC-04  Negative/zero price rejected (web)
PROP-EC-05  Negative/zero size_marla rejected (web)
PROP-EC-06  Negative/zero price rejected (API)
PROP-EC-07  Charge fields absent from form/serializer/admin (ORM-only)
PROP-EC-08  Negative charge via ORM drives total_cost below price
PROP-EC-09  Reservation expiry never processed
PROP-EC-10  plot_edit has no status guard (booked/sold re-listed)
PROP-EC-11  Price-history not written on web plot edit
PROP-EC-12  Project.booked_plots counts reserved as booked
PROP-EC-13  Properties search input dead
PROP-EC-14  Milestone completion_percent > 100 accepted
PROP-EC-15  on_hold status invisible and never set
PROP-SEC-01 Stored XSS via project name in Delete confirm
PROP-SEC-02 sales can create a project (role gap)
PROP-SEC-03 sales can create a plot and set price (role gap)
PROP-SEC-04 sales can edit any plot price/status (role gap)
PROP-SEC-05 sales can create a reservation (role gap)
PROP-SEC-06 sales cannot delete project/plot (positive control)
PROP-SEC-07 API DELETE /projects/<id>/ no deletion guard (cascades)
PROP-SEC-08 API DELETE /plots/<id>/ no booking guard (cascades)
PROP-SEC-09 change_status accepts sold→available, no audit
PROP-SEC-10 PriceHistoryViewSet readable by sales (IsAuthenticated)
PROP-SEC-11 sales API write blocked (positive control)
PROP-API-01 GET /api/projects/ list + status filter
PROP-API-02 POST /api/projects/ create
PROP-API-03 GET /api/plots/ list + filters
PROP-API-04 POST /api/plots/ create + validation
PROP-API-05 GET /api/plots/<id>/ detail
PROP-API-06 PUT/PATCH /api/plots/<id>/ writes PriceHistory
PROP-API-07 POST /api/plots/<id>/change_status/
PROP-API-08 GET /api/plots/list/ (public, available-only, capped)
PROP-API-09 GET /api/price-history/ list + plot filter
PROP-API-10 GET/POST /api/project-milestones/ omits new fields
PROP-API-11 POST /api/project-milestones/<id>/set_status/
```
