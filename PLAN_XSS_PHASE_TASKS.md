# Task plan (7 task blocks)

Tracking file for the multi-block assignment. Mark each item done / not done.

## Block A - XSS regression test
- A1 Test: create Project with XSS name, Plot, Phase (test DB)
- A2 Render pages, assert raw string never unescaped: properties list, project detail, plot list, plot create form (dropdowns), booking create form
- A3 Grep templates/JS for |safe, mark_safe, autoescape off, names in <script>/inline handlers
- A4 Fix hits with json_script / proper escaping; list hits + fixes

## Block B - phase_number
- B1 Add phase_number (PositiveIntegerField, null) to ProjectPhase
- B2 Unique (project, phase_number), nulls repeat
- B3 Data migration parse "Phase N"
- B4 ordering project, phase_number, name
- B5 serializer accept/return + validate > 0
- B6 tests: migration parse, uniqueness, cross-project, null
- B7 migrate on COPY of db.sqlite3, report rows

## Block C - project form UI
- C1 starts with zero phase cards
- C2 + Add Phase adds card w/ remove button
- C3 auto phase_number + "Phase N" prefill
- C4 fields: Phase Number*, Phase Name*, Status, Launch Date, Total Plots*, Price/Marla*, Description
- C5 status choices: Coming Soon, Booking Open, Inactive (no Sold Out)
- C6 remove disabled + tooltip if has plots/bookings; backend 400
- C7 field-level API errors
- C8 disable submit while submitting
- C9 tests: 0 phases, 2 phases, duplicate phase number, delete blocked phase

## Block D - derived values
- D1 total_plots read-only when phases exist, server-side sum; editable at zero phases
- D2 live counter "X of Y plots allocated" + "Plots created: N of X"
- D3 Sold Out derived (sold == total, total>0), computed property/annotated
- D4 project Completed/Inactive => phases cannot be Booking Open (400)
- D5 zero phases only when project Coming Soon
- D6 tests: sum rule, client total ignored, sold out, status conflict, zero-phase rule

## Block E - Silver Oak blocks
- E1 migration: set plot.block from Block A/B phases if empty
- E2 move plots to correct real phase, else phase=null + print numbers
- E3 pre-check (project, block, plot_number) collisions, list + stop
- E4 delete empty phases, refuse if plots/bookings remain
- E5 phase_number non-null
- E6 run on COPY, report before/after counts per block and phase
- E7 tests for migration logic

## Block F - plot form
- F1 phase dropdown empty on load, filtered by project, reset on change, required if project has phases
- F2 searchable project select (existing pattern)
- F3 feature dedupe + data migration remap, report mapping
- F4 section header Status -> Availability
- F5 block hint "e.g. A, B, C"
- F6 price auto-fill snapshot + price_overridden
- F7 tests: phase filtered, phase required, feature remap, snapshot

## Block G - verification
- G1 full suite counts + failures
- G2 makemigrations --check
- G3 walkthrough script results (8 scenarios)
- G4 list uncertainties/guesses
