import { test, expect, APIRequestContext } from '@playwright/test';
import { loginViaApi } from '../helpers/auth';

/**
 * Samana ERP — Agents (sales/dealer) browser suite.
 *
 * Drives the real rendered UI (Django templates via `core/views_crm.py`) with
 * `page` + `storageState` (admin, the super_admin role) for: create (auto
 * AGT-XXXXX id + commission_rate), edit, detail (commission earned / paid /
 * balance), commission payment, and delete. Cross-checks the AGT id and
 * commission rate against the DRF `/api/agents/` contract.
 *
 * Field labels / button names are taken verbatim from `templates/agents.html`,
 * `agent_form.html` (via `base_form.html`), `agent_detail.html` and
 * `agent_commission_form.html`.
 *
 * Run with `DJANGO_DEBUG=True python manage.py runserver` on :8000 (CONVENTIONS.md).
 */

// ══════════════════════════════════════════════════════════════════════════
// Helpers
// ══════════════════════════════════════════════════════════════════════════

let seq = 0;
/** Monotonic, run-unique timestamp string (never repeats within a run). */
function uniq(): string {
  return `${Date.now()}${String(seq++).padStart(3, '0')}`;
}

function makePhone(): string {
  return `+92-300-${uniq().slice(-7)}`;
}

function makeEmail(): string {
  return `qa+${uniq()}@example.com`;
}

/** Agents created during this worker's run (deleted in afterAll). */
const createdAgents: number[] = [];

/**
 * Create an agent via the DRF API (admin) and register it for cleanup. Retries
 * on 500: `Agent.save()` derives the next `AGT-XXXXX` id via `select_for_update`
 * on the last row, which races under parallel execution.
 */
async function createAgentViaApi(
  request: APIRequestContext,
  token: string,
  overrides: Record<string, unknown> = {},
): Promise<{ id: number; agentId: string; name: string; phone: string; commissionRate: string }> {
  for (let attempt = 0; attempt < 6; attempt++) {
    const payload = {
      name: `QA Agent ${uniq()}`,
      phone: makePhone(),
      commission_rate: '5.00',
      ...overrides,
    };
    const res = await request.post('/api/agents/', {
      data: payload,
      headers: { 'X-CSRFToken': token },
    });
    if (res.status() === 201) {
      const body = await res.json();
      createdAgents.push(body.id);
      return {
        id: body.id,
        agentId: body.agent_id,
        name: body.name,
        phone: body.phone,
        commissionRate: body.commission_rate,
      };
    }
    if (res.status() !== 500) {
      expect(res.status(), `create agent failed: ${await res.text()}`).toBe(201);
    }
    // else: 500 (auto-id race) → retry with a fresh phone.
  }
  throw new Error('createAgentViaApi: could not create agent after retries');
}

/** Resolve an agent pk by its unique phone and register it for cleanup (UI creates). */
async function agentIdByPhone(request: APIRequestContext, phone: string): Promise<number> {
  const rows = await (await request.get('/api/agents/')).json();
  const row = rows.find((r: { phone: string }) => r.phone === phone);
  expect(row, `agent with phone ${phone} not found`).toBeTruthy();
  createdAgents.push(row.id);
  return row.id;
}

// ══════════════════════════════════════════════════════════════════════════
// HP — happy path
// ══════════════════════════════════════════════════════════════════════════

test.describe('AGT — Happy path', () => {
  test.beforeEach(async ({ page }) => { await loginViaApi(page.request, 'admin'); });

  test('AGT-HP-01 — Create agent (auto AGT id + commission rate)', async ({ page, request }) => {
    const token = await loginViaApi(request, 'admin');
    const name = `QA Agent ${uniq()}`;
    const phone = makePhone();
    const email = makeEmail();

    await page.goto('/agents/create/');
    await page.getByLabel('Name').fill(name);
    await page.getByLabel('Phone').fill(phone);
    await page.getByLabel('Email').fill(email);
    await page.getByLabel('Commission rate').fill('5');
    await page.getByRole('button', { name: 'Create' }).click();

    await expect(page).toHaveURL(/\/agents\/$/);
    await expect(page.getByText(/Agent AGT-\d{5} created successfully!/i).first()).toBeVisible();

    // Persisted with a generated AGT-XXXXX id and the entered commission rate.
    const id = await agentIdByPhone(request, phone);
    const body = await (await request.get(`/api/agents/${id}/`)).json();
    expect(body.agent_id).toMatch(/^AGT-\d{5}$/);
    expect(body.commission_rate).toBe('5.00');
    expect(body.name).toBe(name);
  });

  test('AGT-HP-02 — Edit agent', async ({ page, request }) => {
    const token = await loginViaApi(request, 'admin');
    const agent = await createAgentViaApi(request, token);
    const newName = `QA Agent Edit ${uniq()}`;
    const newRate = '12.50';

    await page.goto(`/agents/${agent.id}/edit/`);
    await page.getByLabel('Name').fill(newName);
    await page.getByLabel('Commission rate').fill(newRate);
    await page.getByRole('button', { name: 'Update' }).click();

    await expect(page).toHaveURL(/\/agents\/$/);
    await expect(page.getByText(/Agent updated successfully!/i).first()).toBeVisible();

    const body = await (await request.get(`/api/agents/${agent.id}/`)).json();
    expect(body.name).toBe(newName);
    expect(body.commission_rate).toBe(newRate);
  });

  test('AGT-HP-03 — Detail: commission earned / paid / balance', async ({ page, request }) => {
    const token = await loginViaApi(request, 'admin');
    const agent = await createAgentViaApi(request, token, { commission_rate: '5.00' });

    await page.goto(`/agents/${agent.id}/`);

    await expect(page.getByText(agent.agentId)).toBeVisible();
    await expect(page.getByText('Commission Rate')).toBeVisible();
    await expect(page.getByText('5.00%')).toBeVisible();

    // No bookings or payments yet → all three commission figures are zero.
    await expect(page.getByText('Commission Earned')).toBeVisible();
    await expect(page.getByText('Commission Paid')).toBeVisible();
    await expect(page.getByText('Balance Due')).toBeVisible();
    await expect(page.getByText('Rs. 0').first()).toBeVisible();
  });

  test('AGT-HP-04 — Record commission payment', async ({ page, request }) => {
    const token = await loginViaApi(request, 'admin');
    const agent = await createAgentViaApi(request, token);

    await page.goto(`/agents/${agent.id}/commission-payment/`);
    await page.getByLabel('Amount').fill('5000');
    await page.getByLabel('Method').fill('Bank Transfer');
    await page.getByLabel('Reference').fill(`CHQ-${uniq()}`);
    await page.getByRole('button', { name: /Save Payment/ }).click();

    await expect(page).toHaveURL(new RegExp(`/agents/${agent.id}/$`));
    await expect(page.getByText(/Commission payment of Rs\./i).first()).toBeVisible();

    // Commission Paid = 5000; Balance Due = earned(0) − paid(5000) = −5000.
    await expect(page.getByText('Rs. 5000').first()).toBeVisible();
    await expect(page.getByText('Rs. -5000').first()).toBeVisible();
  });

  test('AGT-HP-05 — Delete agent', async ({ page, request }) => {
    const token = await loginViaApi(request, 'admin');
    const agent = await createAgentViaApi(request, token);

    await page.goto(`/agents/${agent.id}/delete/`);
    await expect(page.getByText('Confirm Deletion')).toBeVisible();
    await page.getByRole('button', { name: /Yes, Delete/ }).click();

    await expect(page).toHaveURL(/\/agents\/$/);
    await expect(page.getByText(/Agent deleted successfully!/i).first()).toBeVisible();

    // Hard-deleted.
    const res = await request.get(`/api/agents/${agent.id}/`);
    expect(res.status()).toBe(404);
  });
});

// ══════════════════════════════════════════════════════════════════════════
// EC — edge cases / boundaries
// ══════════════════════════════════════════════════════════════════════════

test.describe('AGT — Edge cases', () => {
  test.beforeEach(async ({ page }) => { await loginViaApi(page.request, 'admin'); });

  test('AGT-EC-01 — Commission rate above 100 rejected', async ({ page }) => {
    await page.goto('/agents/create/');
    await page.getByLabel('Name').fill(`QA Agent ${uniq()}`);
    await page.getByLabel('Commission rate').fill('150');
    await page.getByRole('button', { name: 'Create' }).click();

    await expect(page).toHaveURL(/\/agents\/create\/$/);
    await expect(page.getByText('Commission rate must be between 0 and 100.')).toBeVisible();
  });

  test('AGT-EC-02 — Negative commission rate rejected', async ({ page }) => {
    await page.goto('/agents/create/');
    await page.getByLabel('Name').fill(`QA Agent ${uniq()}`);
    await page.getByLabel('Commission rate').fill('-5');
    await page.getByRole('button', { name: 'Create' }).click();

    await expect(page).toHaveURL(/\/agents\/create\/$/);
    await expect(page.getByText('Commission rate must be between 0 and 100.')).toBeVisible();
  });

  test('AGT-EC-03 — Duplicate phone (HTML form diverges from API serializer)', async ({
    page,
    request,
  }) => {
    // CODE-CONFIRMED divergence: AgentForm (core/forms.py) has no clean_phone and
    // Agent.phone is not unique, so the HTML form accepts a duplicate phone that
    // the DRF serializer (core/serializers.py validate_phone) rejects. We assert
    // the actual behaviour on both sides.
    const token = await loginViaApi(request, 'admin');
    const existing = await createAgentViaApi(request, token);
    const dupeName = `QA Agent Dup ${uniq()}`;

    // HTML: creating a second agent with the same phone currently succeeds.
    await page.goto('/agents/create/');
    await page.getByLabel('Name').fill(dupeName);
    await page.getByLabel('Phone').fill(existing.phone);
    await page.getByLabel('Commission rate').fill('5');
    await page.getByRole('button', { name: 'Create' }).click();
    await expect(page).toHaveURL(/\/agents\/$/);
    await expect(page.getByText(/created successfully!/i).first()).toBeVisible();

    // API: the serializer rejects the same duplicate phone.
    const apiDup = await request.post('/api/agents/', {
      data: { name: `QA Agent ApiDup ${uniq()}`, phone: existing.phone, commission_rate: '5.00' },
      headers: { 'X-CSRFToken': token },
    });
    expect(apiDup.status()).toBe(400);

    // Register the UI-created duplicate for cleanup (resolved by its unique name,
    // since the phone is now shared by two agents).
    const rows = await (await request.get('/api/agents/')).json();
    const dup = rows.find((r: { name: string }) => r.name === dupeName);
    expect(dup, `duplicate agent ${dupeName} persisted`).toBeTruthy();
    createdAgents.push(dup.id);
  });
});

// ══════════════════════════════════════════════════════════════════════════
// Cleanup — afterAll deletes every agent this worker created.
// ══════════════════════════════════════════════════════════════════════════

test.afterAll(async ({ playwright }) => {
  const request = await playwright.request.newContext({ baseURL: 'http://127.0.0.1:8000' });
  try {
    const token = await loginViaApi(request, 'admin');
    for (const id of createdAgents) {
      await request.delete(`/api/agents/${id}/`, { headers: { 'X-CSRFToken': token } }).catch(() => {});
    }
  } finally {
    await request.dispose();
  }
});
