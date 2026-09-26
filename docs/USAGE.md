# Samana Builders ERP — User Usage Guide

Complete step-by-step instructions for every module of the Samana Builders ERP.
This guide is written for the people who actually use the system every day:
receptionists, sales staff, accounts, HR, managers and administrators.

Each section answers three questions:

1. **What can I do here?**
2. **Who is allowed to do it?** (role-based access)
3. **How exactly do I do it?** (numbered steps)

---

## 1. User Roles and What Each Role Can Do

Your login is assigned exactly one role. Your role decides which menus you
see and which actions you are allowed to perform.

| Role | Typical user | Can do |
|---|---|---|
| **Super Admin** | System owner / IT | Everything, including user management, backups, payment verification |
| **Admin** | Senior management, office admin | Everything except role changes that are reserved; full user & backup access |
| **Management** | Directors, department heads | All business modules, delete actions, booking confirmations, payment verification, notifications |
| **Accounts** | Accountant, finance officer | Payments, receipts, expenses, finance, payroll view, reports, installment plans |
| **Sales** | Sales representative | Customers, properties, bookings, leads, agents — view & create; CANNOT view payments or confirm bookings |
| **HR** | HR officer | HR module (employees, salary, attendance, leave, payroll) |
| **Project Manager** | Construction PM | Milestones and project progress views |
| **Contractor** | Site contractor | Limited view access |
| **Staff** | General staff | Login, dashboard, profile, view customers/properties/bookings |

### Access summary by action

| Action | Who can do it |
|---|---|
| Login and view dashboard | All roles |
| Add / edit customers | All logged-in users |
| Delete a customer | Management, Admin, Super Admin (blocked if customer has bookings/ledger history) |
| Add / edit properties & plots | All logged-in users |
| Delete a project/plot | Management, Admin, Super Admin |
| Create a booking | All logged-in users |
| Confirm / transfer / delete a booking | Management, Admin, Super Admin |
| View / record payments | Accounts, Management, Admin, Super Admin |
| Verify / bounce / reverse payments | Admin, Super Admin |
| View / create expenses | Accounts, Management, Admin, Super Admin |
| View / create finance (ledger, budgets, project costs) | Accounts, Management, Admin, Super Admin |
| Manage HR (employees, payroll, attendance, leave) | HR, Management, Admin, Super Admin |
| View payroll / salary slips | HR, Accounts, Management, Admin, Super Admin |
| Process payroll run | HR, Management, Admin, Super Admin |
| Send notifications | Management, Admin, Super Admin |
| Manage users (create, edit, roles, deactivate) | Admin, Super Admin |
| View audit logs | Management, Admin, Super Admin |
| Database backup & restore | Admin, Super Admin |
| Company settings | Admin, Super Admin |
| AI Assistant (chat) | All logged-in users |
| AI Insights (business analytics) | Accounts, Management, Admin, Super Admin |
| AI HR tools | HR, Management, Admin, Super Admin |

> If you do not have permission for a page, the system shows "You do not have
> permission to access this page" and returns you to the dashboard.

---

## 2. Logging In and First Steps

### 2.1 Log in

1. Open the ERP in your browser (ask your administrator for the address).
2. You will see the company website. Click **Staff Login** (top-right).
3. Enter your **Username** and **Password**.
4. Click **Sign In** (or press Enter).

> **Trouble logging in?** After 5 failed attempts your account is locked for
> 15 minutes for security. Wait, or ask an Admin to check your account.

### 2.2 What you see after login — the Dashboard

The Dashboard is your home screen. It shows:

- Key numbers (total customers, bookings, revenue, available plots)
- Charts of revenue trends and sales
- Quick links to recent activity

### 2.3 Change your password or profile

1. Click your **name/avatar** in the sidebar (bottom).
2. Click **My Profile**.
3. Update your details and click **Save**.
4. Use the **Change Password** option to set a new password.
5. You can also change the color **Theme** of the interface here.

### 2.4 Log out

1. Click your **name/avatar** in the sidebar.
2. Click **Logout**.
3. Always log out on shared computers.

---

## 3. Customers Module

The Customers module keeps the master record of every buyer.

### 3.1 View the customer list

1. Click **Customers** in the sidebar.
2. All customers appear in a table with their ID (CUS-0001), name, phone,
   CNIC, and status.
3. Use the **search box** to find a customer by name, phone or CNIC.
4. Click a customer's row to open their full profile.

### 3.2 Add a new customer (who: any logged-in user)

1. Go to **Customers**.
2. Click **Add Customer** (top-right).
3. Fill in the form:

   | Field | Notes |
   |---|---|
   | First / Last name | Required |
   | Phone | Required — must be a valid Pakistani mobile (03XX-XXXXXXX) |
   | CNIC | Required — 13 digits, will be checked for duplicates |
   | Email | Optional |
   | Address | Optional |
   | Customer photo | Optional (JPG/PNG up to 5 MB) |
   | Source | Website / Walk-in / Referral / Agent / Other |

4. Click **Save Customer**.
5. The new customer appears in the list with the next CUS- number.

### 3.3 Add a nominee (beneficiary) to a customer

1. Open the customer's profile.
2. Scroll to the **Nominee** section.
3. Fill in nominee name, CNIC and relation.
4. Click **Save Nominee**.

### 3.4 Edit a customer (who: any logged-in user)

1. Open **Customers**, find the customer.
2. Click the **Edit** (pencil) icon on their row, or open the profile and
   click **Edit**.
3. Change the fields you need to change.
4. Click **Save Customer**.

### 3.5 View / print a customer profile PDF

1. Open the customer profile.
2. Click **Download Profile PDF**.
3. The PDF opens in a new tab — save or print it.

### 3.6 Delete a customer (who: Management, Admin, Super Admin)

> **IMPORTANT RULE:** A customer who has bookings or payment history CANNOT
> be deleted. The system blocks it to protect financial records.

1. Open the customer profile.
2. Click **Delete Customer**.
3. Confirm in the popup.
4. If the customer has bookings or ledger history, the system refuses the
   delete. In that case: do NOT delete — just mark them inactive or stop
   transacting with them.
5. Deletion is recorded in **Audit Logs**.

---

## 4. Properties Module

The Properties module manages **projects** (societies/buildings) and the
**plots** inside them.

### 4.1 View properties

1. Click **Properties** in the sidebar.
2. You see all projects with their plots.
3. Plots are color-coded by status (Available / Reserved / Booked / Sold).

### 4.2 Add a new project (who: any logged-in user)

1. Go to **Properties**.
2. Click **Add Project**.
3. Fill in: project name, location, total plots, description, and a cover
   image if available.
4. Click **Save Project**.

### 4.3 Edit / delete a project

- **Edit** (any logged-in user): open the project → **Edit** → change fields → **Save**.
- **Delete** (Management, Admin, Super Admin only): open the project →
  **Delete** → confirm. Deleting a project does not delete its plots.

### 4.4 Add a new plot (who: any logged-in user)

1. Go to **Properties**.
2. Click **Add Plot**.
3. Fill in:

   | Field | Notes |
   |---|---|
   | Project | Select the project |
   | Block / Phase | e.g. Block A |
   | Plot number | e.g. 45 |
   | Plot size | e.g. 5 Marla / 10 Marla |
   | Plot type | Residential / Commercial |
   | Price | Sale price in PKR |
   | Status | Coming Soon / Booking Open / Under Construction / Completed / Inactive |
   | Facing, corner, park-facing | Optional details that affect price |

4. Click **Save Plot**.
5. The plot now appears in the project with status **Available** (or the
   status you chose).

### 4.5 Edit / delete a plot

- **Edit** (any logged-in user): open the plot → **Edit** → change → **Save**.
- **Delete** (Management, Admin, Super Admin): open the plot → **Delete** →
  confirm. A plot that is already booked cannot normally be removed.

### 4.6 Reserve a plot for a customer (any logged-in user)

1. Go to **Properties**.
2. Click **Reserve Plot**.
3. Choose the **customer**, the **plot**, and enter the **token amount**
   (earnest money).
4. Click **Reserve**.
5. The plot status changes to **Reserved**.
6. A reservation must be converted to a booking (see Bookings) before it
   expires, or it is released.

---

## 5. Bookings Module

A booking is the official sale agreement: customer + plot + price + payment
plan.

### 5.1 Booking lifecycle

```
Pending → Confirmed → Active → Completed
                    ↘ Cancelled (only if no verified payments)
```

### 5.2 View bookings

1. Click **Bookings** in the sidebar.
2. All bookings appear with booking ID (BKG-0001), customer, plot, amount
   and status.
3. Use search/filters to narrow down.

### 5.3 Create a new booking (who: any logged-in user)

1. Go to **Bookings**.
2. Click **Add Booking**.
3. Fill the form:

   | Field | Notes |
   |---|---|
   | Customer | Select from dropdown |
   | Plot | Select — only **Available** plots are shown |
   | Total amount | Sale price |
   | Advance paid | Amount received so far |
   | Source | Website / Walk-in / Referral / Agent / Other |
   | Agent | Optional — if sale came through an agent |
   | Installment plan | Pick a template (e.g. 36 monthly) or leave blank |

4. Click **Save Booking**.
5. The booking is created with status **Pending** and the plot becomes
   **Booked**.

> The system prevents double-booking: a plot that is already booked/sold
> cannot be selected again.

### 5.4 View a booking detail

1. Click the booking ID in the list.
2. You see customer & plot info, the payment plan (installments), all
   payments made, and the receipts.

### 5.5 Edit a booking (any logged-in user)

1. Open the booking.
2. Click **Edit**.
3. Change fields (e.g. amount, plan, advance) and **Save**.

### 5.6 Confirm a booking (who: Management, Admin, Super Admin)

1. Open the booking with status **Pending**.
2. Click **Confirm Booking**.
3. Status changes to **Confirmed** (or **Active** if payments are flowing).
4. Confirming is safe to repeat — an already-confirmed booking stays
   confirmed.

### 5.7 Cancel a booking (who: Management, Admin, Super Admin)

> **IMPORTANT RULE:** If the customer has paid money that was **verified**,
> you cannot cancel directly — you must first process a **Refund**
> (see Refunds). This protects customer money.

1. Open the booking.
2. Click **Cancel Booking**.
3. If there are no verified payments, it cancels immediately.
4. If verified payments exist, the system asks you to process a refund
   first. Create the refund, get it approved, then cancel.

### 5.8 Transfer a booking (who: Management, Admin, Super Admin)

1. Open the booking.
2. Click **Transfer Booking**.
3. Choose the new customer.
4. Confirm. The booking now belongs to the new customer (receipts and
   payments history are preserved).

### 5.9 Print the booking invoice

1. Open the booking.
2. Click **Download Invoice** (PDF).
3. Save or print.

---

## 6. Payments Module

The Payments module records and verifies every rupee that comes in.

### 6.1 Payment lifecycle

```
Draft → Pending Verification → Verified
                             → Rejected
                             → Bounced (cheque) → Reversed
```

### 6.2 View payments (who: Accounts, Management, Admin, Super Admin)

1. Click **Payments** in the sidebar.
2. Every payment is listed with amount, method, status, and booking.

### 6.3 Record a new payment (who: Accounts, Management, Admin, Super Admin)

1. Go to **Payments**.
2. Click **Record Payment**.
3. Fill in:

   | Field | Notes |
   |---|---|
   | Booking | Select the booking the money is for |
   | Amount | Must be within the remaining due |
   | Method | Cash / Bank Transfer / Cheque / Credit Card |
   | Payment type | Advance / Installment / Receipt |
   | Reference / notes | Cheque number, transaction ID etc. |
   | Date | Payment date |

4. Click **Save Payment**.
5. The payment is saved as **Pending Verification** and the booking's
   received amount updates.

### 6.4 Verify a payment (who: Admin, Super Admin)

> This is the critical step: verification confirms the money is real and
> posts it to the customer's ledger. A receipt is generated automatically.

1. Open **Payments**, find the **Pending Verification** payment.
2. Click **Verify**.
3. The payment becomes **Verified**, the ledger updates, and a **Receipt**
   (RCPT-xxxx) is created.
4. Print the receipt via **Receipts**.

### 6.5 Reject a payment (Admin, Super Admin)

1. Open the pending payment.
2. Click **Reject**, add a reason.
3. Status becomes **Rejected**; nothing is posted to the ledger.

### 6.6 Mark a cheque bounced (Admin, Super Admin)

1. Open the payment.
2. Click **Bounce**.
3. The system **reverses** everything that payment had posted (advance,
   installments, receipt) so the books stay correct.

### 6.7 Reverse a payment (Admin, Super Admin)

Use when a verified payment must be undone (wrong amount, duplicate).
Click **Reverse** on the payment — ledger and receipts are reversed.

### 6.8 Receipts

1. Go to **Payments** → open any **Verified** payment.
2. Click **View Receipt** (or download the PDF).
3. Receipts are numbered and printable.

---

## 7. Installment Plans & Installments

### 7.1 What installment plans are

A plan is a payment schedule (e.g. "36 monthly installments of PKR 100,000").
Plans are attached to bookings and generate the list of installments the
customer must pay.

### 7.2 View plans and installments (who: Accounts, Management, Admin, Super Admin)

1. Click **Installment Plans** in the sidebar.
2. Open a plan to see every installment (number, due date, amount, status).

### 7.3 Installment statuses

- **Pending** — not yet due/paid
- **Partial** — partly paid
- **Paid** — fully paid
- **Overdue** — due date passed, not paid

### 7.4 Mark an installment paid (Accounts, Management, Admin, Super Admin)

1. Open the plan → find the installment.
2. Click **Mark Paid**.
3. Confirm — a verified payment is created against that installment.

### 7.5 Reschedule an installment (Accounts, Management, Admin, Super Admin)

1. Open the installment.
2. Click **Reschedule**.
3. Pick the new due date and click **Save** (e.g. customer requests an
   extension).

---

## 8. Leads Module (CRM)

Leads are potential buyers who contacted you (website form, walk-in, referral).

### 8.1 Lead lifecycle

```
New → Contacted → Qualified → Converted (becomes a customer)
                        ↘ Lost
```

### 8.2 View leads (who: any logged-in user)

1. Click **Leads** in the sidebar.
2. All leads are listed with name, phone, source, status and assigned
   salesperson.

### 8.3 Add a lead

- **From the website:** any visitor can submit the **Book Now** / lead form
  on the corporate site — it lands here automatically.
- **Manually** (any logged-in user): go to **Leads** → **Add Lead** → fill
  name, phone, email, source → **Save**.

### 8.4 Update lead status / assign owner (any logged-in user)

1. Open the lead.
2. Click **Update Status**.
3. Choose New / Contacted / Qualified / Lost.
4. Assign a salesperson if needed.
5. **Save**.

### 8.5 Add a follow-up note (any logged-in user)

1. Open the lead.
2. In the **Notes** section, type your note.
3. Click **Add Note**. Every note is timestamped with the author.

### 8.6 Convert a lead to a customer (any logged-in user)

> Requires a valid CNIC and phone — the system rejects empty or duplicate
> CNICs.

1. Open the lead.
2. Click **Convert to Customer**.
3. Confirm the CNIC and phone details.
4. The customer is created, the lead is marked **Converted**, and the
   customer appears in the Customers module.

### 8.7 Delete a lead (who: Management, Admin, Super Admin)

1. Open the lead.
2. Click **Delete** → confirm.

---

## 9. Agents Module

Agents are external sales agents who bring customers.

### 9.1 View agents (any logged-in user)

1. Click **Agents** in the sidebar.
2. Each agent shows their ID (AGT-xxxx), name, phone, commission rate and
   sales.

### 9.2 Add an agent (who: Management, Admin, Super Admin)

1. Go to **Agents**.
2. Click **Add Agent**.
3. Fill: name, phone, CNIC, commission rate (%).
4. Click **Save Agent**.

### 9.3 Edit agent details (Management, Admin, Super Admin)

1. Open the agent.
2. Click **Edit** → change → **Save**.

### 9.4 Delete an agent (Management, Admin, Super Admin)

1. Open the agent.
2. Click **Delete** → confirm. Existing bookings keep the agent name (they
   are not deleted).

---

## 10. Expenses & Finance Module

### 10.1 Expenses (who: Accounts, Management, Admin, Super Admin)

**Add an expense:**

1. Click **Expenses** in the sidebar.
2. Click **Add Expense**.
3. Choose the **expense category** (or add one), enter amount, date,
   description, and attach a receipt image if available.
4. Click **Save**.

**Edit / delete:** open the expense → **Edit** or **Delete**.
(Delete is restricted to Management and above for finance settings.)

### 10.2 Finance module (who: Accounts, Management, Admin, Super Admin)

The Finance module covers:

- **Offices** — company offices (head office, site offices)
- **Expense categories** — how expenses are classified
- **Office expenses** — expenses per office, with **approve** and **pay**
  workflow (approval restricted to Management and above)
- **Project costs** — money spent per project (construction, materials)
- **Project finance** — per-project budget and investment tracking
- **Ledger** — the full financial ledger (all verified payments, expenses,
  transfers)

**Ledger steps:**

1. Click **Finance** in the sidebar.
2. Click **Ledger**.
3. Filter by date range, account, or type.
4. Every verified transaction appears here — this is the book of record.

---

## 11. Reports

### 11.1 Financial Reports (who: Accounts, Management, Admin, Super Admin)

1. Click **Reports → Financial** in the sidebar.
2. See revenue, collections, expenses and net position.
3. Use the date filters and click **Generate** to refresh.

### 11.2 Receivables Aging (Accounts, Management, Admin, Super Admin)

1. Click **Reports → Receivables**.
2. Shows who owes money, how much, and how overdue (30/60/90+ days).
3. Use this every week to chase overdue installments.

### 11.3 Sales Report (Accounts, Management, Admin, Super Admin)

1. Click **Reports → Sales**.
2. Shows bookings, revenue and collections by period/project.

---

## 12. HR Module

### 12.1 HR structure

```
Departments → Designations → Employees → Salary components
                                     ↘ Attendance
                                     ↘ Leaves
                                     ↘ Payroll runs → Salary slips
```

### 12.2 Departments (who: HR, Management, Admin, Super Admin)

1. Click **HR** in the sidebar.
2. Click **Departments**.
3. **Add Department**: name + description → **Save**.
4. Edit / delete from the same screen.

### 12.3 Designations (HR, Management, Admin, Super Admin)

1. Click **Designations** under HR.
2. **Add Designation**: title + department → **Save**.

### 12.4 Salary components (HR, Management, Admin, Super Admin)

1. Click **Salary Components** under HR.
2. Add components like Basic Salary, House Rent, Medical, Conveyance,
   Tax Deduction — each with a type (earning / deduction).

### 12.5 Employees (view: HR, Accounts, Management, Admin, Super Admin; manage: HR, Management, Admin, Super Admin)

**Add an employee:**

1. Go to **HR → Employees**.
2. Click **Add Employee**.
3. Fill: name, CNIC, phone, email, department, designation, joining date,
   and employment status (Active / On Leave / Resigned / Terminated).
4. Click **Save**.
5. Employee gets an ID like EMP-00001.

**Add salary to an employee:**

1. Open the employee.
2. Click **Add Salary**.
3. Set basic salary and pick components/amounts.
4. **Save**.

**Edit / delete:** from the employee screen (delete is HR/Management+).

### 12.6 Attendance (view: HR, Accounts, Management, Admin, Super Admin; manage: HR, Management, Admin, Super Admin)

1. Click **HR → Attendance**.
2. Click **Add Attendance**.
3. Pick employee, date, status (Present / Absent / Leave / Half Day).
4. **Save**.
5. Use the filters to see attendance by month.

### 12.7 Leaves (view: HR, Accounts, Management, Admin, Super Admin; manage: HR, Management, Admin, Super Admin)

1. Click **HR → Leaves**.
2. **Add Leave**: employee, leave type, from/to dates, reason → **Save**.
3. **Approve / Reject**: open the pending leave → choose **Approve** or
   **Reject** → **Save**. The employee's status updates.

### 12.8 Payroll runs (process: HR, Management, Admin, Super Admin; view/pay: HR, Accounts, Management, Admin, Super Admin)

1. Click **HR → Payroll**.
2. Click **New Payroll Run**: choose month/year → **Create**.
3. Click **Generate** to create a salary slip for every active employee.
4. Review each slip — add or remove earning/deduction items if needed.
5. Click **Process** to finalize the run (status: Draft → Processed).
6. Click **Pay** to mark it paid (Accounts can do this too).
7. Download individual **Salary Slips** (PDF) for employees.

### 12.9 Payroll report

1. Click **HR → Payroll Report**.
2. Pick a month to see total payroll, per-department totals and
   per-employee breakdown.

---

## 13. AI Module

The AI module uses OpenRouter (an AI gateway) to help you work faster.
Every AI action is logged for audit.

### 13.1 AI Assistant (who: all logged-in users)

1. Click **AI Assistant** in the sidebar.
2. Type a question in the chat box, e.g.:
   - "What is our total revenue?"
   - "How many plots are available?"
   - "Who is the highest paying customer?"
3. Press **Send** (or click one of the suggested questions).
4. The assistant answers using your REAL data — it queries the ERP database.

### 13.2 AI Insights (who: Accounts, Management, Admin, Super Admin)

1. Click **AI Insights** in the sidebar.
2. Click **Generate Insights**.
3. The AI produces a business summary: revenue position, collections,
   receivables, available inventory and recommendations.

### 13.3 AI HR tools (who: HR, Management, Admin, Super Admin)

Under **AI HR** you get five tools:

| Tool | What it does |
|---|---|
| **HR Assistant** | Chat about the workforce ("How many employees in Sales?") |
| **Leave Review** | Paste a leave application — AI checks policy and flags issues |
| **Payroll Insights** | Explains a payroll run (totals, deductions, anomalies) |
| **Attendance Insights** | Summarizes attendance patterns and absenteeism |
| **Job Description** | Drafts a job description for a role |

**To use any tool:** open **AI HR** → pick the tool → fill the form
(question / month / file) → click the action button → read the AI result.

> If the AI service is off or the key is missing, the tools show a clear
> message instead of failing silently.

---

## 14. Notifications

### 14.1 View notifications (who: Management, Admin, Super Admin)

1. Click **Notifications** in the sidebar.
2. See SMS/email sent for bookings, payments, reminders.

### 14.2 Send a manual notification (Management, Admin, Super Admin)

1. Click **Notifications**.
2. Click **Send Notification**.
3. Choose recipient (customer), channel (SMS/Email), write the message.
4. Click **Send**.

---

## 15. User Management (who: Admin, Super Admin)

### 15.1 Create a user

1. Click **Users** in the sidebar.
2. Click **Add User**.
3. Fill: name, username, email, password, and **role** (Sales, Accounts,
   HR, Management, etc.).
4. Click **Save**.
5. Tell the user their username and password.

### 15.2 Change a user's role

1. **Users** → open the user.
2. Click **Edit** → pick the new role → **Save**.
3. The user's menu changes at their next login.

### 15.3 Deactivate a user

1. **Users** → open the user.
2. Click **Deactivate** (or **Activate**).
3. A deactivated user cannot log in. No data is deleted.

> Never delete a user who has created records — deactivate instead.

---

## 16. Audit Logs (who: Management, Admin, Super Admin)

1. Click **Audit Logs** in the sidebar.
2. Every important action is listed: who did what, to which record, when.
3. Use the search/filters to investigate changes.

> This is your compliance and safety net. If a record changes mysteriously,
> Audit Logs shows who did it.

---

## 17. Database Backup (who: Admin, Super Admin)

1. Click **Backup** in the sidebar.
2. **Download Backup** — saves a full copy of the database to your computer.
3. **Restore Latest** — roll the system back to the most recent backup.
4. **Upload & Restore** — restore from a backup file you saved earlier.

> Make a backup every week and before any big data import. Keep backups off
> the office computer (cloud drive or external disk).

---

## 18. Settings (who: Admin, Super Admin)

### 18.1 Company settings

1. Click **Settings → Company**.
2. Update company name, logo, address, phone, email, tax number.
3. Click **Save**. Changes appear on receipts and invoices.

### 18.2 Project milestones (view: all logged-in; manage: Management+)

1. Click **Milestones** in the sidebar.
2. **Add Milestone**: project, title, date, status.
3. Update as construction progresses so the team sees real progress.

---

## 19. Customer Portal (who: all logged-in users)

1. Click **Portal** in the sidebar.
2. Look up a customer to see their bookings, payments and receipts in one
   place — useful at the front desk.

---

## 20. Quick Troubleshooting

| Problem | What to do |
|---|---|
| "You do not have permission" | Your role doesn't cover that page — ask Admin to change your role |
| Account locked | 5 wrong passwords → locked 15 min; wait or ask Admin |
| Cannot delete a customer | They have bookings/payments — deactivate/inactive instead |
| Cannot cancel a booking | Verified payments exist — process a Refund first |
| Plot not in booking form | It is already booked/reserved — pick another plot |
| AI says service unavailable | Check the AI key/settings with Admin; ERP still works normally |
| Duplicate CNIC error | That customer already exists — search before adding |

---

_End of guide. For administrator-level topics (deployment, backups, API),
see the developer documentation._
