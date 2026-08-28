# Samana Builders - Real Estate Management ERP

A comprehensive Real Estate Management ERP + Corporate Website for **Samana Builders & Developers (Pvt.) Ltd.**

## Technology Stack

- **Backend:** Python Django + Django REST Framework
- **Frontend:** Django Templates (Professional Blue Theme) | React.js (planned)
- **Database:** SQLite (dev) | PostgreSQL (production)
- **API:** RESTful API via DRF

## ERP Modules

| Module | Description |
|--------|-------------|
| Customer Management | Auto-generated IDs (CUS-XXXXX), search, booking history |
| Property Inventory | Projects & plots with status tracking (Available/Reserved/Booked/Sold) |
| Booking & Ledger | Full workflow with balance tracking |
| Payment Verification | Pending → Verified/Rejected with audit trail |
| Dashboard | Real-time stats, quick actions, recent activity |
| Audit Logs | Full action history with timestamps and IP tracking |
| Role-Based Access | Super Admin, Admin, Sales, Accounts, Management |

## Features

- Auto-generated IDs for customers, bookings, and payments
- CNIC validation (XXXXX-XXXXXXX-X format)
- Payment workflow with verification/rejection
- Role-based permission decorators
- Full CRUD for all entities
- Search and filter capabilities
- Audit trail logging all user actions
- REST API endpoints at `/api/`

## Quick Start

```bash
# Clone the repository
git clone https://github.com/kali69017/SamanaBuilders.git
cd SamanaBuilders

# Create virtual environment
python -m venv venv
venv\Scripts\activate  # Windows
# source venv/bin/activate  # Linux/Mac

# Install dependencies
pip install -r requirements.txt

# Run migrations
python manage.py migrate

# Create superuser
python manage.py createsuperuser

# Start development server
python manage.py runserver
```

## Default Login

- **URL:** http://127.0.0.1:8000/login/
- **Admin:** `admin` / `admin123`

## API Endpoints

| Endpoint | Description |
|----------|-------------|
| `/api/customers/` | Customer CRUD |
| `/api/projects/` | Project CRUD |
| `/api/plots/` | Plot CRUD |
| `/api/bookings/` | Booking CRUD |
| `/api/payments/` | Payment CRUD |
| `/api/receipts/` | Receipt CRUD |

## Project Structure

```
Samana Builders/
├── samana_erp/          # Django project settings
├── core/                # Dashboard, auth, permissions, audit logs
├── customers/           # Customer management module
├── properties/          # Projects & plots module
├── bookings/            # Bookings & installment plans
├── payments/            # Payments & verification workflow
├── api/                 # REST API URL routing
├── templates/           # HTML templates (Professional Blue theme)
└── themes/              # Theme samples
```

## AI Assistant (LangChain + DeepSeek)

The ERP ships with an AI layer powered by [LangChain](https://www.langchain.com/) and the DeepSeek chat API.

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/ai/assistant/` | POST | Natural-language Q&A over live ERP data (revenue, bookings, overdue, inventory) |
| `/api/ai/lead-score/` | POST | Scores a lead 0-100 with hot/warm/cold tier and reason |
| `/api/ai/property-description/` | POST | Generates marketing copy for a plot |
| `/api/ai/reminder-draft/` | POST | Drafts a personalized installment reminder message |
| `/api/ai/insights/` | GET | Business insights narrative (finance/management roles) |
| `/api/ai/health/` | GET | AI configuration status |
| `/api/ai/hr/assistant/` | POST | HR Q&A (headcount, departments, payroll, leave) — HR roles |
| `/api/ai/hr/leave-review/` | POST | Drafts approve/reject email for a leave request — HR roles |
| `/api/ai/hr/payroll/` | POST | Payroll anomaly detection and summary — payroll roles |
| `/api/ai/hr/attendance/` | POST | Monthly attendance rate + absenteeism analysis — HR roles |
| `/api/ai/hr/job-description/` | POST | Generates a job description for a role — HR roles |

UI pages: `/ai/` (chat assistant), `/ai/insights/` (business analysis) and
`/ai/hr/` (HR tools), all in the sidebar.

### Configuration

Add to `.env` (gitignored):

```
AI_ENABLED=True
DEEPSEEK_API_KEY=sk-...
DEEPSEEK_MODEL=deepseek-chat
DEEPSEEK_BASE_URL=https://api.deepseek.com
```

Every AI call is logged to the `AiInteractionLog` table (visible in Django admin).
Scheduled daily insights: `python manage.py ai_daily_insights` (cron-friendly).
When AI is disabled or the provider is unreachable, all endpoints degrade
gracefully with a structured error instead of crashing the ERP.

## Testing

```bash
python manage.py test
```

## License

Private - Samana Builders & Developers (Pvt.) Ltd.
