import { APIRequestContext } from '@playwright/test';
import { loginViaApi, type RoleName } from './auth';

/**
 * Correct fixture factory for the Samana ERP test suites.
 *
 * Critical detail: the DRF *create* serializers for Customer, Booking and Payment omit the
 * numeric `id` from their response (they only return the string `customer_id` / `booking_id` /
 * `payment_id`). The *list/retrieve* serializers DO return `id`. So every create helper here
 * resolves the numeric id via a list/retrieve call — do NOT rely on `body.id` from a POST.
 */

let counter = 0;
export function uid(tag: string): string {
  counter += 1;
  return `${Date.now().toString(36)}${Math.floor(Math.random() * 1e8).toString(36)}${counter}${tag}`;
}

export function randomDigits(n: number): string {
  let s = '';
  for (let i = 0; i < n; i++) s += Math.floor(Math.random() * 10);
  return s;
}

export function csrf(token: string): Record<string, string> {
  return { 'X-CSRFToken': token };
}

/** Log in via the DRF API and return a CSRF token valid for the current session. */
export async function apiLogin(request: APIRequestContext, role: RoleName): Promise<string> {
  return loginViaApi(request, role);
}

export async function createCustomer(
  request: APIRequestContext, token: string, tag: string,
): Promise<{ id: number; cnic: string; customerId: string }> {
  const d = randomDigits(13);
  const cnic = `${d.slice(0, 5)}-${d.slice(5, 12)}-${d.slice(12)}`;
  const phone = `+92-3${randomDigits(9)}`;
  const email = `qa-${uid('mail')}@example.com`;
  const res = await request.post('/api/customers/', {
    data: { first_name: 'QA', last_name: `Buyer-${tag}`, email, phone, cnic },
    headers: csrf(token),
  });
  if (res.status() !== 201) throw new Error(`create customer: HTTP ${res.status()} ${await res.text()}`);
  // Resolve numeric id via search (create serializer omits id).
  const list = await (await request.get(`/api/customers/?search=${encodeURIComponent(cnic)}`)).json();
  const row = list.find((c: any) => c.cnic === cnic);
  if (!row) throw new Error('created customer not found by cnic');
  return { id: row.id, cnic, customerId: row.customer_id };
}

export async function createProject(
  request: APIRequestContext, token: string, tag: string,
): Promise<number> {
  const res = await request.post('/api/projects/', {
    data: { name: `QA Proj ${tag}`, location: 'Lahore' },
    headers: csrf(token),
  });
  if (res.status() !== 201) throw new Error(`create project: HTTP ${res.status()} ${await res.text()}`);
  const body = await res.json();
  return body.id;
}

export async function createPlot(
  request: APIRequestContext, token: string, projectId: number, tag: string,
  opts: { price?: string; holdingDeposit?: string; status?: string } = {},
): Promise<{ id: number; plotNumber: string }> {
  const plotNumber = `P-${tag}`;
  const res = await request.post('/api/plots/', {
    data: {
      plot_number: plotNumber, project: projectId, size_marla: '5.00',
      price: opts.price ?? '108000.00',
      holding_deposit: opts.holdingDeposit ?? '0.00',
      status: opts.status ?? 'available',
    },
    headers: csrf(token),
  });
  if (res.status() !== 201) throw new Error(`create plot: HTTP ${res.status()} ${await res.text()}`);
  const body = await res.json();
  return { id: body.id, plotNumber };
}

export async function createBooking(
  request: APIRequestContext, token: string,
  args: { customerId: number; plotId: number; totalAmount: string; advance: string },
): Promise<{ id: number; bookingId: string }> {
  const res = await request.post('/api/bookings/', {
    data: {
      customer: args.customerId, plot: args.plotId,
      total_amount: args.totalAmount, advance_paid: args.advance, source: 'walk_in',
    },
    headers: csrf(token),
  });
  if (res.status() !== 201) throw new Error(`create booking: HTTP ${res.status()} ${await res.text()}`);
  // Resolve numeric id via the plot's booking list (create serializer omits id).
  const list = await (await request.get(`/api/bookings/?plot=${args.plotId}`)).json();
  const row = list.find((b: any) => b.plot === args.plotId);
  if (!row) throw new Error('created booking not found by plot');
  return { id: row.id, bookingId: row.booking_id };
}

/** Convenience: full chain project → plot → customer → booking, all ids resolved. */
export async function seedBookingChain(
  request: APIRequestContext, token: string, tag: string,
  opts: { price?: string; holdingDeposit?: string; totalAmount?: string; advance?: string } = {},
) {
  const projectId = await createProject(request, token, tag);
  const plot = await createPlot(request, token, projectId, tag, {
    price: opts.price, holdingDeposit: opts.holdingDeposit,
  });
  const customer = await createCustomer(request, token, tag);
  const booking = await createBooking(request, token, {
    customerId: customer.id, plotId: plot.id,
    totalAmount: opts.totalAmount ?? opts.price ?? '108000.00',
    advance: opts.advance ?? '0.00',
  });
  return { projectId, plotId: plot.id, plotNumber: plot.plotNumber, customerId: customer.id, bookingId: booking.id, bookingApiId: booking.bookingId };
}
