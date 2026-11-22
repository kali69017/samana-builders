# Deploying Samana ERP on Hostinger (Docker)

This guide is for a **Hostinger VPS** (or any Docker host) running `docker compose`.
The stack: `db` (Postgres), `web` (Django + gunicorn + whitenoise), `worker`
(notification queue worker), `scheduler` (cron for reminders and retries) and
`caddy` (auto-HTTPS reverse proxy).

## Production release record: 2026-11-22

This release fixed two defects and then wiped the test data before handover.

- App directory: `/opt/samana`
- Branch: `main`
- Release commit: `40446b4`
- Booking delivery now accepts confirmed, active and completed bookings.
- Employees with salary slips cannot be deleted. Set them to Resigned or Terminated instead.
- Pre-deploy backup: `/root/backups/samana-before-fix-2026-11-22-131634.dump`, 344K.
- Images rebuilt: `web`, `worker`, `scheduler`.
- Services started: `db`, `web`, `worker`, `scheduler`, `caddy`.
- `migrate --check` reported no pending migrations.
- Finance integrity check passed before the wipe.
- Pre-wipe backup: `/root/backups/samana-before-wipe-2026-11-22-134148.dump`, 344K.
- Wipe removed 441 business rows from 73 tables and deleted 3 extra users.
- Only `superadmin` remains, with profile role `super_admin`.
- 29 account heads, 103 migrations, 308 auth permissions and 77 content types remain.
- Expense categories are empty after the wipe.
- Finance integrity check passed after the wipe with all balances at 0.00.
- All 37 menu pages returned HTTP 200 after the wipe.

## Production release record: 2026-11-18

This release has been executed on the server.

- App directory: `/opt/samana`
- Branch: `main`
- Legacy finance conversion fix commit: `7149a83`
- Postgres container: `samana-db-1`
- Database and user: both `samana`
- Production database was recreated empty.
- Production superuser username: `superadmin`. The password is not recorded here.
- Providers were kept off during release verification.

Backups created and kept:

- `/root/backups/samana-pre-release-2026-11-16.dump`
- `/root/backups/samana-before-clean-start-2026-11-18-082634.dump`, 314K
- `/root/backups/samana-2026-11-18.dump`, 326K, created by the manual backup test

Scratch validation results:

- `samana_scratch` was restored from `samana-pre-release-2026-11-16.dump`.
- Migration found legacy heads `0111 zeeshan` and `001 Bank Al-Falah Limited` and placed them under `1.9.1` and `1.1.1.3`. Production was wiped, so these did not carry forward.
- The restored database had 5 Payment vouchers crediting Accounts Receivable and 3 Refund vouchers debiting Accounts Receivable.
- Liability conversion dry run reported 8 corrections totalling 205,000.00.
- Liability conversion real run posted 8 corrections.
- Revenue remained 0.00.
- Customer Advances became 151,000.00.
- Customer Advances expected was 151,000.00.
- Scratch finance integrity check passed.
- `samana_empty` migrated and finance integrity check passed with all balances at 0.00.
- Empty database had five roots and the required Cash, Bank, Revenue and Customer Advances accounts.
- Both scratch databases were dropped after validation.

Clean start results:

- Final pre-clean backup was verified before the drop.
- `samana` was dropped and recreated empty.
- All migrations applied with no errors.
- `migrate --check` reported no pending migrations.
- Finance integrity check passed on the empty database.
- Superuser `superadmin` was created interactively.
- `collectstatic` copied 278 files.
- `web`, `worker`, `scheduler`, `db` and `caddy` started.
- Gunicorn started 3 workers with no errors.
- `https://samanabuilders.com/` returned HTTP 200 through Caddy.
- Queue dry run reported 0 rows.
- Retry dry run reported 0 candidates.
- Scheduler crontab showed the 08:00 reminder line and the 02:15 retry line.
- Host cron was installed at 02:00 with 14 day retention.
- The manual backup test created `/root/backups/samana-2026-11-18.dump`.
- `systemctl status cron` showed cron active and running.

Remaining manual check after the release:

- Log in as `superadmin`.
- Confirm the dashboard, Chart of Accounts, vouchers, payments, bookings, reports and Notification Center.
- Enable providers only when the business is ready.

### Legacy conversion is required on restored data

The restored production snapshot used the old receivable mapping. Migrating alone does not convert those vouchers. On a restored scratch or restored production copy, run the liability conversion before the integrity check:

```bash
docker compose run --rm -e DB_NAME=samana_scratch web python manage.py convert_to_customer_liability --dry-run
docker compose run --rm -e DB_NAME=samana_scratch web python manage.py convert_to_customer_liability
docker compose run --rm -e DB_NAME=samana_scratch web python manage.py finance_integrity_check
```

The command handles:

- Payment vouchers that credit Revenue.
- Payment vouchers that credit Accounts Receivable for undelivered bookings.
- Payment vouchers that credit Accounts Receivable for delivered bookings.
- Refund vouchers that debit Revenue before delivery.
- Refund vouchers that debit Accounts Receivable before delivery.
- Refund vouchers after delivery, which remain in Revenue.
- Payment vouchers with a paired CashBasisConversion voucher, which are not corrected twice.

The clean production start creates an empty database and needs no conversion.

## 1. Prepare the host

```
# Ubuntu/Debian VPS
apt-get update && apt-get install -y git
# Install Docker + compose (see hostinger / get.docker.com docs)
# docker and docker compose must be available as `docker compose`
```

## 2. Get the code + configure

```bash
git clone https://github.com/kali69017/samana-builders.git /opt/samana
cd /opt/samana

cp .env.example .env
nano .env   # set DJANGO_SECRET_KEY, DJANGO_ALLOWED_HOSTS, DB_PASSWORD,
            # EMAIL_*, SENDPK_*, WHATSAPP_*, AI_* as needed.
```

Point your domain's A record at the VPS IP (Caddy then provisions TLS automatically for
the domains in `Caddyfile`: `samanabuilders.com` / `www.samanabuilders.com`).

## 3. Build and start

```bash
docker compose up -d --build
docker compose ps           # expect: db, web, scheduler, caddy all Up
```

On first start the `web` service runs `migrate --noinput` and `collectstatic --noinput`
automatically, then launches gunicorn. Static is served by whitenoise; uploaded media is
served by Caddy from the shared `media` volume.

## 4. Create the admin account

```bash
docker compose exec web python manage.py createsuperuser
```

## 5. Verify

- `https://samanabuilders.com/` - corporate landing page.
- `https://samanabuilders.com/login/` - admin login.
- `docker compose exec web python manage.py check --deploy` - Django's production-settings check.

## Notifications & scheduler

The `scheduler` service runs `deploy/crontab` daily at 08:00, which calls
`send_installment_reminders --days=7 --cooldown=6` (installment reminders + overdue alerts,
deduped). Providers are only live when the matching `*_ENABLED=true` is set in `.env`.
Every attempt is logged in the ERP Notification Center.

## Updating

```bash
cd /opt/samana
git pull origin main
docker compose build web worker scheduler
docker compose up -d web worker scheduler
docker compose ps
```

The `worker` service drains the notification outbox continuously. The
`scheduler` service runs `deploy/crontab`: the 08:00 reminder line and the
02:15 retry line. Both use the same image and `x-app-env` environment as `web`.

## Production release validation on the server

Server facts for this procedure:

- App directory: `/opt/samana`
- Compose project: default project name, so the Postgres container is `samana-db-1`
- Database and user: both `samana`
- Services: `db`, `web`, `worker`, `scheduler`, `caddy`
- Pre-release dump: `/root/backups/samana-pre-release-2026-11-16.dump`

No provider is enabled for these checks.

### 1. Pull the release and build without starting it

```bash
cd /opt/samana
git pull origin main
docker compose build web worker scheduler
docker compose up -d db
```

### 2. Create the scratch and empty databases

```bash
docker compose exec -T db psql -U samana -d postgres -c "DROP DATABASE IF EXISTS samana_scratch;"
docker compose exec -T db psql -U samana -d postgres -c "DROP DATABASE IF EXISTS samana_empty;"
docker compose exec -T db psql -U samana -d postgres -c "CREATE DATABASE samana_scratch OWNER samana;"
docker compose exec -T db psql -U samana -d postgres -c "CREATE DATABASE samana_empty OWNER samana;"
docker exec -i samana-db-1 pg_restore -U samana -d samana_scratch --no-owner --no-privileges < /root/backups/samana-pre-release-2026-11-16.dump
```

### 3. Migrate both databases with the new code

```bash
docker compose run --rm -e DB_NAME=samana_scratch web python manage.py migrate --noinput
docker compose run --rm -e DB_NAME=samana_scratch web python manage.py convert_to_customer_liability --dry-run
docker compose run --rm -e DB_NAME=samana_scratch web python manage.py convert_to_customer_liability
docker compose run --rm -e DB_NAME=samana_scratch web python manage.py finance_integrity_check
docker compose run --rm -e DB_NAME=samana_empty web python manage.py migrate --noinput
docker compose run --rm -e DB_NAME=samana_empty web python manage.py finance_integrity_check
```

The restored database still contains legacy accrual vouchers. The liability
conversion is required on the scratch copy before the integrity check. The
empty database needs no conversion. The clean production start creates an empty
database, so it also needs no conversion.

### 4. Verify the empty database chart

```bash
docker compose run --rm -e DB_NAME=samana_empty web python manage.py shell -c "from finance.models import AccountHead; roots=list(AccountHead.objects.filter(parent__isnull=True).order_by('code').values_list('code','name')); print('ROOTS', roots); print('REQUIRED', list(AccountHead.objects.filter(code__in=['1.1.1.1','1.1.1.2','4.1.1','2.1.1']).order_by('code').values_list('code','name','system_role')))"
```

Expect five roots, `1.1.1.1 Cash`, `1.1.1.2 Bank`, `4.1.1 Plot Sales Revenue`,
and `2.1.1 Customer Advances & Bookings` with the `customer_advances` role.

### 5. Drop the scratch databases

```bash
docker compose exec -T db psql -U samana -d postgres -c "DROP DATABASE IF EXISTS samana_scratch;"
docker compose exec -T db psql -U samana -d postgres -c "DROP DATABASE IF EXISTS samana_empty;"
```

## Clean production start

The production database is being recreated. The dump in `/root/backups` is the
rollback source. Take a fresh dump before this section.

### 1. Stop writers and take a final dump

```bash
cd /opt/samana
docker compose stop web worker scheduler
mkdir -p /root/backups
docker exec samana-db-1 pg_dump -U samana -Fc samana > /root/backups/samana-before-clean-start-$(date +%F-%H%M%S).dump
```

### 2. Drop and recreate the database

```bash
docker compose exec -T db psql -U samana -d postgres -c "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname='samana' AND pid <> pg_backend_pid();"
docker compose exec -T db psql -U samana -d postgres -c "DROP DATABASE samana;"
docker compose exec -T db psql -U samana -d postgres -c "CREATE DATABASE samana OWNER samana;"
```

### 3. Migrate, create the admin, collect static

```bash
docker compose run --rm web python manage.py migrate --noinput
docker compose run --rm web python manage.py createsuperuser
docker compose run --rm web python manage.py collectstatic --noinput
```

### 4. Start all services

```bash
docker compose up -d web worker scheduler caddy
docker compose ps
docker compose logs --tail=100 web
docker compose logs --tail=50 worker
docker compose logs --tail=50 scheduler
```

### 5. Verification checklist

```bash
docker compose run --rm web python manage.py migrate --check
docker compose run --rm web python manage.py finance_integrity_check
docker compose run --rm web python manage.py process_notification_queue --dry-run
docker compose run --rm web python manage.py retry_failed_notifications --dry-run
curl -I https://samanabuilders.com/
```

Check manually:

- Login works and the dashboard loads.
- Chart of Accounts has the five roots, Cash, Bank, Revenue and Customer Advances.
- Vouchers, payments, bookings and reports load.
- Notification Center loads and the queue worker is up.
- No provider is enabled unless the business explicitly turns it on.

## Rollback

Restore the dump into the live database and return to the previous commit.

```bash
cd /opt/samana
docker compose stop web worker scheduler
docker compose exec -T db psql -U samana -d postgres -c "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname='samana' AND pid <> pg_backend_pid();"
docker compose exec -T db psql -U samana -d postgres -c "DROP DATABASE IF EXISTS samana;"
docker compose exec -T db psql -U samana -d postgres -c "CREATE DATABASE samana OWNER samana;"
docker exec -i samana-db-1 pg_restore -U samana -d samana --no-owner --no-privileges < /root/backups/samana-pre-release-2026-11-16.dump
git checkout f33888d
docker compose build web worker scheduler
docker compose up -d web worker scheduler caddy
docker compose ps
```

## Backups

Back up Postgres and keep 14 daily dumps. Add this line with `crontab -e` on
the host. Cron requires the percent signs to be escaped.

```cron
0 2 * * * cd /opt/samana && mkdir -p /root/backups && docker exec samana-db-1 pg_dump -U samana -Fc samana > /root/backups/samana-$(date +\%F).dump && find /root/backups -name 'samana-*.dump' -mtime +14 -delete
```

Restore a dump with:

```bash
docker exec -i samana-db-1 pg_restore -U samana -d samana --no-owner --no-privileges < /root/backups/samana-FILENAME.dump
```

## Troubleshooting

- **Redirect loop / Bad Request (400):** ensure `DJANGO_ALLOWED_HOSTS` includes the exact
  domains in `Caddyfile` and that `DJANGO_SECRET_KEY` is set.
- **Uploads 404:** media is served by Caddy from the shared `media` volume - both `web` and
  `caddy` mount it; if uploads vanish after a redeploy, the volume is intact (nothing is
  deleted on rebuild).
- **Emails/SMS not sending:** set the matching `*_ENABLED=true`; check the Notification Center
  row `error_message` for the exact provider reason (blank WhatsApp template is a common one).
- **Scratch integrity fails with Customer Advances mismatch:** the restored database still has legacy receivable vouchers. Run `convert_to_customer_liability --dry-run` and then the real command before `finance_integrity_check`.
- **Worker logs every 10 seconds:** this is expected. It prints `Processed 0 queued rows` each interval. It can be changed later to log only when rows are processed.
- **Scratch databases remain after validation:** drop `samana_scratch` and `samana_empty` before the clean start.
- **Host backup cron does not run:** check `systemctl status cron`, check `crontab -l`, and confirm the percent sign is escaped as `\%F` inside the crontab.
- **Restore needs the exact dump path:** use `ls -lh /root/backups/` and substitute the real filename in the `pg_restore` command.
