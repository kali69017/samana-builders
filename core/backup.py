import csv
import io
import zipfile
from datetime import date, datetime, time
from decimal import Decimal
from pathlib import Path

from django.apps import apps
from django.conf import settings
from django.db import connection, models, transaction
from django.utils import timezone


def _serialize(value):
    if value is None:
        return ''
    if isinstance(value, bool):
        return '1' if value else '0'
    if hasattr(value, 'isoformat'):
        return value.isoformat()
    if isinstance(value, models.Model):
        return str(value.pk)
    if isinstance(value, (dict, list)):
        import json
        return json.dumps(value)
    return str(value)


def table_to_csv(model):
    """Serialize all rows of a model to CSV (one file per DB table)."""
    fields = [f for f in model._meta.concrete_fields]
    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow([f.name for f in fields])
    for obj in model.objects.all():
        writer.writerow([_serialize(getattr(obj, f.name)) for f in fields])
    return out.getvalue()


def customers_media_csv():
    """CSV listing media filenames saved against each customer."""
    from customers.models import Customer
    from payments.models import PaymentAttachment, Receipt

    attachment_files = {}
    for pa in PaymentAttachment.objects.select_related('payment__booking__customer').all():
        customer_id = pa.payment.booking.customer_id
        attachment_files.setdefault(customer_id, []).append(pa.file.name)

    receipt_files = {}
    for r in Receipt.objects.select_related('payment__booking__customer').all():
        if r.pdf_file:
            customer_id = r.payment.booking.customer_id
            receipt_files.setdefault(customer_id, []).append(r.pdf_file.name)

    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow([
        'customer_id', 'full_name', 'email', 'phone',
        'customer_document', 'customer_image',
        'payment_attachments', 'receipt_pdfs', 'all_media_files',
    ])
    for c in Customer.objects.all():
        docs = []
        if c.document:
            docs.append(c.document.name)
        if c.image:
            docs.append(c.image.name)
        atts = attachment_files.get(c.id, [])
        pdfs = receipt_files.get(c.id, [])
        all_media = docs + atts + pdfs
        writer.writerow([
            c.customer_id, c.full_name, c.email or '', c.phone,
            '; '.join(docs), '; '.join(atts), '; '.join(pdfs), '; '.join(all_media),
        ])
    return out.getvalue()


def media_manifest_rows():
    """Rows linking every stored file to its owning record (model, id, field, file)."""
    rows = [['model', 'object_id', 'field', 'file']]
    for model in apps.get_models():
        for f in model._meta.concrete_fields:
            if isinstance(f, models.FileField):
                for obj in model.objects.all():
                    value = getattr(obj, f.name)
                    if value:
                        rows.append([model._meta.db_table, obj.pk, f.name, value.name])
    return rows


def build_backup_zip():
    """Full DB dump (CSV per table) + media folder + media manifest as a ZIP."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as zf:
        for model in apps.get_models():
            zf.writestr(f'database/{model._meta.db_table}.csv', table_to_csv(model))

        # Media filenames saved against each customer
        zf.writestr('database/customers_media.csv', customers_media_csv())

        # Manifest mapping every media file to its record
        manifest_out = io.StringIO()
        manifest_writer = csv.writer(manifest_out)
        manifest_writer.writerows(media_manifest_rows())
        zf.writestr('media/manifest.csv', manifest_out.getvalue())

        # Full media folder
        media_root = Path(settings.MEDIA_ROOT)
        if media_root.exists():
            for path in sorted(media_root.rglob('*')):
                if path.is_file():
                    zf.write(str(path), f'media/{path.relative_to(media_root).as_posix()}')

        zf.writestr(
            'backup_info.txt',
            'Samana Builders - Real Estate ERP Backup\n'
            f'Generated: {timezone.now().isoformat()}\n'
            f"Database Engine: {settings.DATABASES['default']['ENGINE']}\n"
            f"Media Root: {settings.MEDIA_ROOT}\n",
        )
    return buf.getvalue()


# ─── RESTORE ──────────────────────────────────────────────────────────────────

_NUMERIC = (models.IntegerField, models.AutoField, models.BigAutoField,
            models.SmallIntegerField, models.BigIntegerField,
            models.PositiveIntegerField, models.PositiveSmallIntegerField,
            models.PositiveBigIntegerField)


def _convert(raw, field):
    """Convert a single CSV cell string into the Python type the field expects."""
    if raw == '':
        if isinstance(field, (models.CharField, models.TextField, models.FileField,
                              models.ImageField, models.BinaryField)):
            # Round-trip NULL back to NULL for nullable text/file fields.
            # The DB serializer writes None as '' in the CSV; restoring it as an
            # empty string would collide with UNIQUE constraints ('' != NULL).
            return None if getattr(field, 'null', False) else ''
        return None
    if isinstance(field, _NUMERIC):
        try:
            return int(raw)
        except (TypeError, ValueError):
            return None
    if isinstance(field, models.BooleanField):
        return raw in ('1', 'true', 'True', '1.0')
    if isinstance(field, models.DateTimeField):
        return datetime.fromisoformat(raw.replace('Z', '+00:00'))
    if isinstance(field, models.DateField):
        return date.fromisoformat(raw)
    if isinstance(field, models.TimeField):
        return time.fromisoformat(raw)
    if isinstance(field, (models.DecimalField, models.FloatField)):
        try:
            return Decimal(raw) if isinstance(field, models.DecimalField) else float(raw)
        except (TypeError, ValueError, ArithmeticError):
            return None
    if isinstance(field, models.JSONField):
        return raw
    return raw


def _field_by_column(model):
    """Map db column name -> model concrete field."""
    return {f.column: f for f in model._meta.concrete_fields}


def _restore_table(model, header, rows):
    """Insert CSV rows for one table. Returns number of rows inserted."""
    field_by_name = {f.name: f for f in model._meta.concrete_fields}
    fields = [field_by_name[h] for h in header if h in field_by_name]
    if not fields:
        return 0
    columns = [f.column for f in fields]

    vendor = connection.vendor
    if vendor == 'sqlite':
        placeholder = '?'
    else:
        placeholder = '%s'

    sql = 'INSERT INTO {table} ({cols}) VALUES ({ph})'.format(
        table=model._meta.db_table,
        cols=', '.join('"' + c + '"' if vendor in ('postgresql', 'sqlite') else '`' + c + '`' for c in columns),
        ph=', '.join([placeholder] * len(columns)),
    )

    params = []
    for row in rows:
        p = [(_convert(row.get(f.name, ''), f)) for f in fields]
        params.append(p)

    with connection.cursor() as cursor:
        cursor.executemany(sql, params)
    return len(params)


def _dependency_order(model_by_table):
    """Topological order so parents (FK targets) are inserted before children."""
    tables = list(model_by_table)
    table_to_model = model_by_table
    deps = {}
    for table, model in table_to_model.items():
        d = set()
        for f in model._meta.concrete_fields:
            if isinstance(f, models.ForeignKey) and f.related_model:
                target = f.related_model._meta.db_table
                if target in table_to_model and target != table:
                    d.add(target)
        deps[table] = d

    ordered = []
    temp = set()
    perm = set()

    def visit(tbl):
        if tbl in perm:
            return
        if tbl in temp:
            return
        temp.add(tbl)
        for dep in deps.get(tbl, ()):
            if dep in table_to_model:
                visit(dep)
        temp.discard(tbl)
        perm.add(tbl)
        ordered.append(tbl)

    for t in tables:
        visit(t)
    return ordered


def _reset_sequences(models_restored):
    vendor = connection.vendor
    with connection.cursor() as cursor:
        for model in models_restored:
            pk = model._meta.pk
            if not pk or not isinstance(pk, models.AutoField):
                continue
            table = model._meta.db_table
            try:
                if vendor == 'sqlite':
                    cursor.execute('SELECT COALESCE(MAX("{}"), 0) FROM "{}"'.format(pk.column, table))
                    max_id = cursor.fetchone()[0] or 0
                    existing = cursor.execute(
                        'SELECT seq FROM sqlite_sequence WHERE name = ?', (table,)
                    ).fetchone()
                    if existing:
                        cursor.execute('UPDATE sqlite_sequence SET seq = ? WHERE name = ?', (max_id, table))
                    else:
                        cursor.execute('INSERT INTO sqlite_sequence (name, seq) VALUES (?, ?)', (table, max_id))
                elif vendor == 'postgresql':
                    max_id = cursor.execute(
                        'SELECT COALESCE(MAX("{0}"), 0) FROM "{1}"'.format(pk.column, table)
                    ).fetchone()[0] or 0
                    cursor.execute(
                        'SELECT setval(pg_get_serial_sequence(%s, %s), %s, true)',
                        (table, pk.column, max_id or 1),
                    )
            except Exception:
                continue


def restore_from_backup(data):
    """Restore the entire database + media from a created backup ZIP.

    Django framework tables (sessions, migrations, admin log, permissions,
    content types) are deliberately NOT restored: wiping sessions logs every
    user out mid-request and restoring stale migration/permission rows can
    corrupt Django's schema bookkeeping. They are left untouched.
    """
    # Tables that must never be wiped/restored (Django-managed metadata).
    FRAMEWORK_TABLES = {
        'django_session',
        'django_migrations',
        'django_admin_log',
        'auth_permission',
        'django_content_type',
    }

    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        csv_names = [n for n in zf.namelist()
                     if n.startswith('database/') and n.endswith('.csv')]
        model_by_file = {}
        model_by_table = {}
        all_models = list(apps.get_models())
        for name in csv_names:
            table = Path(name).stem
            if table in FRAMEWORK_TABLES:
                continue
            for model in all_models:
                if model._meta.db_table == table:
                    model_by_file[name] = model
                    model_by_table[table] = model
                    break

        order = _dependency_order(model_by_table)

        restored_counts = {}
        with transaction.atomic():
            # Wipe existing rows for the tables we are restoring (reverse of insert order)
            for table in reversed(order):
                model = model_by_table[table]
                with connection.cursor() as cursor:
                    cursor.execute('DELETE FROM "{0}"'.format(model._meta.db_table))

            for table in order:
                model = model_by_table[table]
                name = 'database/{}.csv'.format(table)
                if name not in zf.namelist():
                    continue
                with zf.open(name, 'r') as fh:
                    raw = io.TextIOWrapper(fh, encoding='utf-8', newline='')
                    reader = csv.reader(raw)
                    try:
                        header = next(reader)
                    except StopIteration:
                        continue
                    rows = []
                    for line in reader:
                        if not line or all(v == '' for v in line):
                            continue
                        rows.append(dict(zip(header, line)))
                if rows:
                    restored_counts[table] = _restore_table(model, header, rows)

            _reset_sequences(list(model_by_table.values()))

            # Restore media files
            media_root = Path(settings.MEDIA_ROOT)
            media_root.mkdir(parents=True, exist_ok=True)
            media_written = 0
            for name in zf.namelist():
                if name.startswith('media/') and not name.endswith('/'):
                    rel = Path(name).relative_to('media')
                    dest = media_root / rel
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    with zf.open(name) as src, dest.open('wb') as out:
                        out.write(src.read())
                    media_written += 1

    return {
        'tables': restored_counts,
        'total_rows': sum(restored_counts.values()),
        'media_files': media_written,
    }
