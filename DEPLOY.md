# Deploying Samana ERP on Hostinger (Docker)

This guide is for a **Hostinger VPS** (or any Docker host) running `docker compose`.
The stack: `db` (Postgres) · `web` (Django + gunicorn + whitenoise) · `scheduler`
(cron for notification reminders) · `caddy` (auto-HTTPS reverse proxy).

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

- `https://samanabuilders.com/` — corporate landing page.
- `https://samanabuilders.com/login/` — admin login.
- `docker compose exec web python manage.py check --deploy` — Django's production-settings check.

## Notifications & scheduler

The `scheduler` service runs `deploy/crontab` daily at 08:00, which calls
`send_installment_reminders --days=7 --cooldown=6` (installment reminders + overdue alerts,
deduped). Providers are only live when the matching `*_ENABLED=true` is set in `.env`.
Every attempt is logged in the ERP Notification Center.

## Updating

```bash
git pull                    # on the server
docker compose up -d --build
```

## Backups

Back up the Postgres volume and the config/settings that matter:

```bash
docker compose exec db pg_dump -U samana samana > samana-$(date +%F).sql
```
Optionally add this to a cron on the host. For DR, restore with `pg_restore`/`psql`.

## Troubleshooting

- **Redirect loop / Bad Request (400):** ensure `DJANGO_ALLOWED_HOSTS` includes the exact
  domains in `Caddyfile` and that `DJANGO_SECRET_KEY` is set.
- **Uploads 404:** media is served by Caddy from the shared `media` volume — both `web` and
  `caddy` mount it; if uploads vanish after a redeploy, the volume is intact (nothing is
  deleted on rebuild).
- **Emails/SMS not sending:** set the matching `*_ENABLED=true`; check the Notification Center
  row `error_message` for the exact provider reason (blank WhatsApp template is a common one).
