# Properties Module — QA Analysis

> Read in conjunction with `docs/qa/_shared-context.md`. Line references are to the
> files as they exist at the time of writing. "Web" = server-rendered views in
> `core/views.py`; "API" = DRF ViewSets in `properties/api_views.py` and
> `bookings/api_views.py`.

## 1. Business purpose & user journeys

The properties module is the inventory backbone of the ERP: it models the real-estate
supply side (`Project` → `ProjectPhase` → `Plot`), the pricing that drives every
booking guard (`Plot.total_cost` = price + development/lease/other charges), the
audit trail of price changes (`PriceHistory`), construction/payment milestones
(`ProjectMilestone`), and the CSV import scaffold (`PlotImport`). Everything downstream
— bookings, payments, reservations, revenue — hangs off a `Plot`, so a bug here (wrong
status, wrong price, a deleted plot) propagates into financial history.

Real user journeys (role labels from `_shared-context.md`):

- **Add a project** — staff/sales → `/properties/` → "+ Add Project" → `project_create_view` → saved + AuditLog → redirect `/properties/`. (`core/views.py:855`)
- **Edit a project** — management/admin/super_admin → edit → `project_edit_view` (`core/views.py:876`).
- **Delete a project** — management/admin/super_admin → `project_delete_view`; blocked if the project still has plots (`core/views.py:906`).
- **Add/edit a plot** — any logged-in staff → `plot_create_view` / `plot_edit_view` (`core/views.py:927`, `948`).
- **Reserve a plot for a customer** — staff → `/properties/reserve/` → `reservation_create_view`; plot flips to `reserved` (`core/views.py:1449`).
- **Book an available plot** — staff → `booking_create_view`; plot flips to `booked`, a verified down-payment + receipt is auto-created (`core/views.py:1041`).
- **View plot detail + price history** — staff → `plot_detail_view` (`core/views.py:996`).
- **Public availability** — anonymous visitors hit `plots_list_api` (only `available` plots, capped at 20) (`properties/api_views.py:147`).

## 2. Data model

### Project (`properties/models.py:5`)
`name` (CharField 200, req), `description` (TextField blank), `location` (CharField 200,
req), `total_plots` (PositiveInteger, default 0 — manually entered, NOT derived), `status`
(choices `coming_soon/booking_open/under_construction/completed/inactive`, default
`booking_open`), `created_at`/`updated_at`. Computed: `available_plots` (count
`status='available'`), `booked_plots` (count `status__in=['booked','reserved']`),
`sold_plots` (count `status='sold'`). No `clean()`, no unique constraints, no delete guard
at model level (guard lives in the view only — see §4).

### ProjectPhase (`models.py:41`)
FK→Project (CASCADE, `phases`), `name`, `description`, `launch_date` (DateField req),
`total_plots` (PositiveInt default 0), `is_active` (bool default True), `price_per_marla`
(Decimal 15,2 default 0). No validation on `price_per_marla` (can be 0/negative).

### PlotFeature (`models.py:54`)
`name` (100, req), `icon` (50, blank). Used as a M2M label on plots.

### PlotDocument (`models.py:62`)
FK→Plot (CASCADE, `documents`), `title`, `file` (`plot_documents/%Y/%m/`), `uploaded_at`.
No size/type validation on the upload.

### Plot (`models.py:69`) — the core entity
- `plot_number` (CharField 50, req), `project` (FK CASCADE, `plots`), `phase`
  (FK→ProjectPhase, **SET_NULL**, null/blank), `plot_type` (`residential/commercial/industrial`,
  default residential), `size_marla` (Decimal 10,2 req), `size_sqft` (Decimal 10,2 null/blank),
  `price` (Decimal 15,2 req), `status` (6 states, default `available`), `block`,
  `street_number`, `is_corner`, `is_park_facing`, `facing_direction`, `features` (M2M blank),
  `holding_deposit` (Decimal 15,2 default 0), `development_charge`/`lease_charge`/
  `other_charges` (Decimal 15,2 default 0), `description` (TextField blank), timestamps.
- **STATUS_CHOICES** (`models.py:70-77`): `available`, `reserved`, `on_hold`, `booked`,
  `sold`, `cancelled`. Note: `on_hold` is a valid state that no view/API ever sets.
- Computed (`models.py:110-129`): `total_charges` = development + lease + other;
  `total_cost` = `price` + `total_charges`. Both coerce via `Decimal(x or 0)`.
- `unique_together = ['project', 'plot_number']` (`models.py:132`) → duplicate numbers
  **within** a project rejected at DB level; same number across different projects allowed.
- Indexes on `status` and `(project, status)` (`models.py:134-137`). Ordering `project, plot_number`.
- **No `clean()`, no model-level `save()` guards, no signals.** Validity of price/size is
  enforced only in the form and serializer (see §5).

### ProjectMilestone (`models.py:140`)
FK→Project (CASCADE, `milestones`), `title` (200), `description`, `target_date` (null),
`completed_date` (null), `status` (`pending/in_progress/completed/delayed`, default pending),
`start_date` (null), `milestone_type` (`construction/payment/development/documentation/handover/other`,
default construction), `completion_percent` (Decimal 5,2, null/blank, help "0-100" — **no
server-side 0–100 clamp**), `progress_date` (null), `order` (PositiveInt default 0), timestamps.
Ordering `order, target_date`.

### PriceHistory (`models.py:181`)
FK→Plot (CASCADE, `price_history`), `old_price`, `new_price` (Decimal 15,2 req),
`change_reason` (100 blank), `changed_by` (FK User SET_NULL), `changed_at` auto. Ordering
`-changed_at`. Admin marks it read-only (no add/change) (`admin.py:65-69`).

### PlotImport (`models.py:194`)
FK→Project (CASCADE), `file` (`plot_imports/`), `uploaded_by`, `uploaded_at`, `status`
(pending/processing/completed/failed), `error_log`, `plots_created`, `plots_failed`.
Scaffold only — no processing view/command found in this module.

## 3. Roles & permissions

Web views (all `@login_required` first):

| Action | Allowed role(s) | Enforced by | Consistent? |
|---|---|---|---|
| `properties_view` (list) | any staff | `@login_required` `core/views.py:831` | — |
| `project_create_view` | **any staff (incl. sales/hr/staff)** | `@login_required` only `core/views.py:855` | ⚠️ no role gate |
| `project_edit_view` | management+ | `@management_or_above` `core/views.py:877` | ⚠️ create/edit split |
| `project_delete_view` | management+ | `@management_or_above` `core/views.py:900` | ✓ (plus plot guard) |
| `plot_create_view` | **any staff** | `@login_required` only `core/views.py:927` | ⚠️ no role gate |
| `plot_edit_view` | **any staff** | `@login_required` only `core/views.py:948` | ⚠️ edit unguarded, delete guarded |
| `plot_delete_view` | management+ | `@management_or_above` `core/views.py:971` | ✓ (plus booking guard) |
| `plot_detail_view` | any staff | `@login_required` `core/views.py:995` | ✓ read-only |
| `reservation_create_view` | **any staff** | `@login_required` only `core/views.py:1448` | ⚠️ no role gate |

**Key authorization inconsistency:** creating/editing plots and projects — the surface that
sets prices, charges, and statuses — is open to **every authenticated staff member**
including `sales`, while *deleting* them requires `management`. The web layer is also
inconsistent with the API, where `ReadOnlyForLowerRoles` restricts all writes to
`super_admin/admin/management` (`properties/api_views.py:28-39`). The UI matches the
permissive web behavior (the "+ Add Project"/"+ Add Plot"/"Edit" buttons are not
`{% if %}`-gated in `templates/properties.html:23-24,122`), so a `sales` user can change a
booked plot's price or status.

API permissions:

- `ProjectViewSet`, `ProjectPhaseViewSet`, `PlotViewSet`, `PlotFeatureViewSet`,
  `ProjectMilestoneViewSet`: `ReadOnlyForLowerRoles` (read = any authenticated; write =
  super_admin/admin/management) (`properties/api_views.py:45,58,71,131,167`).
- `PriceHistoryViewSet`: `IsAuthenticated` (read-only) (`api_views.py:137`) — any staff,
  including `sales`, can read all price history.
- `plots_list_api`: `AllowAny` (`api_views.py:148`) — public, only `available` plots,
  truncated to 20.
- Dead code: `IsAdminOrSuperAdmin` is defined (`api_views.py:15-25`) but used by nothing.

Object-level gating: plots/projects are global inventory, not user-owned, so there is no
ownership IDOR per se. The risk is **role** IDOR: any `pk` is reachable by any role that
passes the (often absent) role check.

## 4. Business rules, state machines, invariants

### Plot status state machine

`available → reserved → booked → sold`, with `on_hold` and `cancelled` as auxiliary states.
There is **no central state machine**; transitions are scattered across web views and API
actions, and several of them bypass validation entirely.

| Transition | Trigger | Location |
|---|---|---|
| `available → booked` | booking created (web) | `core/views.py:1061-1064` |
| `available/reserved/on_hold → booked` | booking created (API) — any status not in `booked/sold/cancelled` | `bookings/api_views.py:69-74` |
| `available → reserved` | reservation created (web) | `core/views.py:1460-1463` |
| `booked → available` | booking deleted (no payments) | `core/views.py:1229-1232` |
| `booked → available` | booking cancelled (no verified payments) | `core/views.py:1273-1275` |
| `booked → available` | booking API delete | `bookings/api_views.py:139-142` |
| `booked → available` | booking API cancel | `bookings/api_views.py:176-178` |
| `booked → reserved` | booking reopened | `core/views.py:1306-1308` |
| `reserved → booked` | reservation converted to booking | `bookings/api_views.py:435-436` |
| `reserved → expired` (reservation) | convert fails because plot taken | `bookings/api_views.py:418-420` |
| **any → any** | `PlotViewSet.change_status` action | `properties/api_views.py:115-125` |
| **any → any** | plot edit form (web) — no status guard | `core/views.py:948-967` |

### Invariants (and where they are / aren't enforced)

1. **`total_cost = price + development + lease + other`** — defined as a property
   (`models.py:120-129`), used as the booking floor in the web form (`bookings/forms.py:67-74`)
   and API serializer (`bookings/serializers.py:147-153`).
2. **Booking `total_amount ≥ plot.total_cost`** — enforced on booking create/edit (form +
   serializer), NOT on plot edit. Editing a plot's price/charges downward after a booking
   exists does not re-validate the booking.
3. **Booking `advance_paid ≥ plot.holding_deposit`** — same two enforcement points
   (`bookings/forms.py:80-87`, `bookings/serializers.py:155-162`).
4. **Confirm requires `advance_paid > 0`** — `core/views.py:1336`, `bookings/api_views.py:207`.
   Note: confirming a booking does **not** touch plot status (plot is already `booked`).
5. **A project with plots cannot be deleted** — `core/views.py:906-912` (view-level only;
   no `ProtectedError`/`on_delete=PROTECT`, and no DB constraint, so a direct
   `Project.delete()` in shell/admin would still cascade).
6. **A plot with bookings or reservations cannot be deleted** — `core/views.py:976-981`
   (view-level only).
7. **A booking cannot delete/cancel while verified payments exist** — `core/views.py:1221`,
   `1259-1267`; `bookings/api_views.py:132-138,167-174`.
8. **A plot can only be booked if available/reserved** — form queryset
   (`bookings/forms.py:31`), API `validate` blocks `booked/sold/cancelled`
   (`bookings/serializers.py:166-180`) and `perform_create` re-checks under
   `select_for_update()` (`bookings/api_views.py:69-71`).

### Side effects

- Booking create (web) additionally auto-creates a **verified** down-payment `Payment` +
  `Receipt` (`core/views.py:1096-1116`) and (API) the same (`bookings/api_views.py:78-100`).
- AuditLog on: project create/edit/delete, plot create/edit/delete (web), plot create/update
  (API), reservation create, booking create/confirm/cancel/reopen. **Missing:** the
  `PlotViewSet.change_status` action writes no AuditLog (`api_views.py:115-125`).
- Price history is written only by the API `perform_update` (`api_views.py:102-113`),
  **not** by the web `plot_edit_view`.

### Inconsistencies (summary)

- Web `plot_edit_view` sets no `PriceHistory`; API `perform_update` does. Price changes made
  in the UI never appear in the price-history table.
- The three charge fields and `holding_deposit` are absent from the web `PlotForm`
  (`forms.py:36-39`), from `PlotSerializer`/`PlotDetailSerializer` (`serializers.py:19-24`,
  `48-53`), and from `PlotAdmin.fieldsets` (`admin.py:25-42`). They can only be set via
  ORM/shell/migration, yet they are the "single source of truth" for booking pricing.
- `PlotSerializer`/`PlotDetailSerializer` expose `price` + `holding_deposit` but not the
  charge fields, so API consumers cannot see or set `total_cost` components.
- `ProjectMilestoneSerializer` omits the new `start_date`, `milestone_type`,
  `completion_percent`, `progress_date` fields (`serializers.py:104-106`) even though the
  model, form, and web UI carry them.
- `Project.booked_plots` counts `reserved` as booked (`models.py:31`); there is no separate
  `reserved`/`on_hold`/`cancelled` counter, and `total_plots` is a free-form integer, so the
  project stats never reconcile.

## 5. Edge cases (go deep)

- **Negative/zero price:** rejected by form (`forms.py:59-63`) and serializer
  (`serializers.py:26-29`). But `price` is only "must be > 0" — `Decimal('0.001')` is accepted
  and stored as `0.00` after quantization (no minimum magnitude).
- **Negative charges:** `development_charge`, `lease_charge`, `other_charges`, and
  `holding_deposit` have **no validation anywhere** (not in form/serializer/admin). A negative
  charge (via shell/ORM) drives `total_cost` below `price`, silently undermining the booking
  floor invariant.
- **Huge money values:** Decimal(15,2) caps at 13 integer digits (~9.9 trillion). Values
  beyond that raise `decimal.InvalidOperation`/`DataError` (DB) — not caught by the form
  (a `NumberInput` string is coerced by the DecimalField, which does enforce max_digits, so
  the form rejects; the raw `.save()` path does not).
- **Float precision:** `BookingCreateSerializer.validate_advance_paid` compares
  `value > float(total)` (`bookings/serializers.py:127`), converting a Decimal(15,2) to a
  float — lossy for large totals and a latent off-by-one in the "advance ≤ total" check.
- **Duplicate plot number:** same project → rejected by `unique_together` (`models.py:132`);
  across projects → allowed. The web form catches it via `ModelForm` `validate_unique`
  (returns a friendly error); the **API does not** run unique_together validation, so a
  duplicate POST returns a raw 500 `IntegrityError` rather than a 400.
- **Invalid status value:** web form/select restrict to choices; the `change_status` action
  validates against `STATUS_CHOICES` (`api_views.py:119-121`) — but does not validate the
  *transition* (e.g. `sold → available` is accepted), does not clear/release bookings, and
  does not audit.
- **Deleting a plot with bookings:** blocked at view level (`core/views.py:976`), but only if
  the related managers `plot.bookings`/`plot.reservations` are non-empty. A plot that is
  `booked`/`sold` with **zero** booking rows (e.g. status set manually) can still be deleted.
- **Editing a booked/sold plot:** `plot_edit_view` has no guard — a user can change a booked
  plot's `status` to `available` (re-listing it for booking while a booking still references
  it) or to `sold`, or lower its `price` below existing booking totals.
- **Reservation expiry:** `expires_at` defaults to +7 days in the form
  (`bookings/forms.py:107`) but **nothing ever expires a reservation** — no cron/management
  command marks `expired`, and the plot stays `reserved` forever. The only code path that sets
  `expired` is `convert` when the plot is already taken (`bookings/api_views.py:418-420`).
- **Reservation double-book (API):** `ReservationSerializer.validate` only rejects
  `booked`/`sold` (`bookings/serializers.py:66-72`), so an API caller can create a reservation
  on an already-`reserved` or `on_hold`/`cancelled` plot. Also the API `perform_create`
  (`bookings/api_views.py:391-392`) does **not** set `plot.status='reserved'`, unlike the web
  view — so API-created reservations never mark the plot reserved.
- **`change_status` concurrency / audit:** sets status without `select_for_update`, without
  `update_fields`, and fetches `old_status` but never uses it (`api_views.py:122-125`).
- **`on_hold` state:** valid in the model, absent from every transition trigger and from the
  `properties.html` status filter dropdown (`templates/properties.html:59-63`), which lists
  only available/reserved/booked/sold/cancelled.
- **Search box does nothing:** `properties.html:67` renders a `name="search"` input, but
  `properties_view` only reads `project` and `status` (`core/views.py:836-843`) and never
  puts `search` into context — the filter is dead.
- **Public `plots_list_api` leak:** correctly filters `status='available'`, but the `Plot`
  queryset is not `.select_related`-cached with the serializer's `project.name`/`phase.name`
  lookups — minor N+1 (not a leak).
- **Milestone `completion_percent`:** no 0–100 validation server-side; the form's `min`/`max`
  are HTML attributes only (`forms.py:141`). `set_status` sets `completed_date` but never
  touches `progress_date`/`completion_percent`, and does not audit.

## 6. Cross-cutting risks

- **XSS (stored, medium):** `templates/properties.html:123` builds
  `onclick="return confirm('Delete project \'{{ project.name }}\'?...')"`. Django autoescapes
  `'` to `&#x27;`, which the browser decodes back to `'` inside the attribute, so a project
  named `x');alert(1);//` breaks out of the JS string. Since `project_create_view` is open to
  any authenticated staff, this is a stored-XSS vector against all users who open the
  properties list. Mitigation: use `data-*` + `addEventListener`, or
  `escapejs`/`json_script` for the name.
- **XSS (general):** `plot.description`, `project.description`, milestone `title`/`description`
  are rendered with autoescaping (`plot_detail.html:61`, etc.) — safe by default; no
  `|safe`/`mark_safe`/`innerHTML` in these templates.
- **CSRF:** all web state-changing forms POST through `{% csrf_token %}` (e.g.
  `reservation_form.html:44`); no `@csrf_exempt` on properties views. DRF endpoints rely on
  session-auth CSRF. No gap found.
- **IDOR / broken object-level authorization:** the real exposure is **role** IDOR, not
  ownership — `plot_create/plot_edit/project_create/reservation_create` are unguarded by role
  (`core/views.py:855,927,948,1448`), and `plot_edit`/`change_status` let a low-privilege
  user mutate price/status of any `pk`. No ownership check is possible/needed (global
  inventory), but a role check is missing.
- **Sensitive data exposure:** public `plots_list_api` exposes only `available` plots
  (deliberate, good), but the full `PlotSerializer` includes `price`, `holding_deposit`,
  `block`, `street_number`, `facing_direction`, `description` to **any authenticated user**
  (read via `ReadOnlyForLowerRoles`), and `PriceHistoryViewSet` (all price history,
  `changed_by` username) is readable by any authenticated staff (`api_views.py:137`). CNIC is
  not on Plot, but plot-level financials are broadly readable to `sales`.
- **Accessibility:** the properties list relies on `<div class="table-actions">` links (fine),
  but the inline `onclick="window.location=..."` row (`plot_detail.html:86`) and the
  `onclick` confirm links are not keyboard-operable. Empty `<label>`s with `floating-group`
  placeholders may have insufficient association. No `aria-*` labels found.

## 7. API surface

Registered under the default DRF router (`api/urls.py`). Base paths are the model names.

| Method + path | ViewSet / action | Permission | Request fields | Response / notes |
|---|---|---|---|---|
| GET/POST `/api/projects/` | `ProjectViewSet` | `ReadOnlyForLowerRoles` | name, location, total_plots, status | `status` query filter; `available_plots/booked_plots/sold_plots` read-only |
| GET/PUT/PATCH/DELETE `/api/projects/{id}/` | `ProjectViewSet` | write: admin/management | — | no delete guard (cascades plots) |
| GET/POST `/api/projectphases/` | `ProjectPhaseViewSet` | `ReadOnlyForLowerRoles` | project, name, launch_date, total_plots, price_per_marla, is_active | `project` query filter |
| GET/POST `/api/plots/` | `PlotViewSet` | `ReadOnlyForLowerRoles` | plot_number, project, phase, block, street_number, plot_type, size_marla, size_sqft, price, holding_deposit, status, is_corner, is_park_facing, facing_direction, features, description | **no charge fields**; `validate_price`/`validate_size_marla` > 0; no unique_together validation |
| GET `/api/plots/{id}/` | `PlotViewSet.retrieve` → `PlotDetailSerializer` | read | — | price history (last 10) + features |
| PUT/PATCH `/api/plots/{id}/` | `PlotViewSet` | admin/management | same as create | writes `PriceHistory` on price change (`api_views.py:102-113`) |
| DELETE `/api/plots/{id}/` | `PlotViewSet` | admin/management | — | **no booking guard** — cascades bookings/payments |
| POST `/api/plots/{id}/change_status/` | `PlotViewSet.change_status` | admin/management | `status` | validates value, **not transition**; no audit |
| GET/POST `/api/plotfeatures/` | `PlotFeatureViewSet` | `ReadOnlyForLowerRoles` | name, icon | — |
| GET `/api/pricehistory/` | `PriceHistoryViewSet` (read-only) | `IsAuthenticated` | — | `plot` query filter |
| GET `/api/plots/public/` (or similar) | `plots_list_api` function | `AllowAny` | — | only `available`, capped 20 |
| GET/POST `/api/projectmilestones/` | `ProjectMilestoneViewSet` | `ReadOnlyForLowerRoles` | title, project, description, target_date, status, order | **omits start_date/milestone_type/completion_percent/progress_date** |
| POST `/api/projectmilestones/{id}/set_status/` | `ProjectMilestoneViewSet.set_status` | admin/management | `status` | sets `completed_date` if `completed`; no transition guard/audit |

Note: `ProjectViewSet` DELETE and `PlotViewSet` DELETE are **not** protected by the same
deletion guards as the web views — a management user deleting a project via the API cascades
all plots/bookings/payments (only `phase` is `SET_NULL`).

## 8. Test data & fixtures needed

- **Roles:** a `sales` user (no write per API), a `management` user (write per API), and a
  superuser, to exercise the web/API authorization split (§3).
- **Projects:** one with plots (to test the delete guard), one empty (to test deletion), one
  `inactive` (bulk-create form excludes it, `forms.py:86`).
- **Plots:** unique `plot_number` per project; duplicate `plot_number` across two projects
  (should be allowed); duplicate within one project (web form should reject, API should 500).
- **Pricing fixtures:** a plot with `development_charge/lease_charge/other_charges` set (only
  possible via ORM) to exercise `total_cost`; a plot with `holding_deposit > 0` to test the
  advance floor.
- **Status fixtures:** one plot per status, including `on_hold` (verify it's invisible in the
  filter and never transitions).
- **Reservation fixtures:** an `active` reservation with `expires_at` in the past (assert the
  plot stays `reserved` — current behavior) and one on a `reserved` plot via API (double-book).
- **Isolation:** plot numbers must be unique within a project across tests; use per-test
  projects or timestamped names so `unique_together` doesn't collide. Money values must be
  asserted exactly as `Decimal` (per `_shared-context.md`), never via float.

## 9. Key files (for traceability)

- `properties/models.py` — Project/ProjectPhase/PlotFeature/PlotDocument/Plot/ProjectMilestone/PriceHistory/PlotImport; status choices, `total_charges`/`total_cost`, `unique_together`.
- `properties/forms.py` — `ProjectForm`, `ProjectPhaseForm`, `PlotForm` (price/size validation), `PlotBulkCreateForm`, `ProjectMilestoneForm`.
- `properties/serializers.py` — `PlotSerializer`/`PlotDetailSerializer` (omit charge fields), `ProjectSerializer`, `ProjectMilestoneSerializer` (omits new milestone fields), price-history.
- `properties/api_views.py` — ViewSets, `ReadOnlyForLowerRoles`, `change_status`, `plots_list_api`, `set_status`.
- `properties/admin.py` — `PlotAdmin.fieldsets` omit charge fields; `PriceHistory` read-only.
- `properties/views.py` — empty placeholder.
- `properties/templatetags/property_tags.py` — `money` filter.
- `core/views.py` — `properties_view` (831), `project_create/edit/delete_view` (855/876/901), `plot_create/edit/delete/detail_view` (927/948/972/996), `reservation_create_view` (1449), and booking flows that mutate plot status (1041/1217/1247/1298/1329).
- `bookings/models.py` — `Reservation` (related_name `reservations`, `expires_at`, token check constraint), `Booking`.
- `bookings/forms.py` — `BookingForm` (plot status queryset, total_cost + deposit checks), `ReservationForm` (+7d expiry).
- `bookings/serializers.py` — `ReservationSerializer.validate`, `BookingCreateSerializer` (total_cost/advance floor, float comparison).
- `bookings/api_views.py` — `BookingViewSet.perform_create/destroy/cancel/confirm`, `ReservationViewSet.convert` (plot status transitions).
- `samana_erp/urls.py` — route map for properties/plot/project/reservation + milestones.
- `templates/properties.html`, `plot_detail.html`, `plot_form.html`, `project_form.html`, `reservation_form.html` — UI, filter dropdowns, XSS sink.
- `properties/tests.py` — sparse coverage (forms + list/create/filter only).
