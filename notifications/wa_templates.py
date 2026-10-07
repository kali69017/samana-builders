"""Read, validate and compile the WhatsApp template provisioning spec.

``wa_templates.json`` is the single source of truth for the six transactional
templates this app sends. This module turns it into Graph API
``POST /{waba}/message_templates`` payloads and refuses to build one that Meta
would reject, so a typo surfaces at ``validate_spec`` time rather than as an
opaque ``(#100) Invalid parameter`` against the live WABA.

Two Meta asymmetries live here, both learned by hitting them:

  * ``language`` is a bare string when creating a template, but an object
    ``{"code": ...}`` when sending one. Do not "fix" one to match the other.
  * Templates must be **positional**. Creating a NAMED template that has
    variables is not possible through the Graph API: supplying ``example``
    fails with subcode 2388043, and omitting it creates the template only for
    Meta to reject it as INVALID_FORMAT. Verified against a live WABA.
    So the body uses ``{{1}}..{{N}}`` and ``parameters`` is the ordered
    contract — see ``parameter_order``.

Meta documents a wider ``sub_category`` enum than any given account accepts;
this one takes only the three below (BOOKING_STATUS is refused). Keep
``ACCEPTED_SUB_CATEGORIES`` honest to the live account, not to the docs.
"""
import json
import os
import re

SPEC_PATH = os.path.join(os.path.dirname(__file__), 'wa_templates.json')

# Graph enums. Kept verbatim so an invalid value is caught here, not remotely.
CATEGORIES = (
    'AUTHENTICATION',
    'FREE_SERVICE',
    'MARKETING',
    'UTILITY',
)
UTILITY_SUB_CATEGORIES = (
    'BOOKING_STATUS',
    'CALL_PERMISSIONS_REQUEST',
    'FLIGHT_DELAY_AND_GATE_CHANGE_ALERT',
    'FRAUD_ALERT',
    'ORDER_DETAILS',
    'ORDER_STATUS',
    'RICH_ORDER_STATUS',
)
# The subset this WABA actually accepts. Sending anything else fails with
# "Param sub_category must be one of {...}".
ACCEPTED_SUB_CATEGORIES = (
    'ORDER_DETAILS',
    'ORDER_STATUS',
    'RICH_ORDER_STATUS',
)
PARAMETER_FORMATS = ('NAMED', 'POSITIONAL')

NAME_RE = re.compile(r'^[a-z0-9_]+$')
# Positional: {{1}}, {{2}} ... Body indices must run 1..N with no gaps.
POSITIONAL_RE = re.compile(r'\{\{(\d+)\}\}')
# Named: {{customer_name}} — kept so a named entry is rejected with a clear
# message rather than an opaque "index 0 missing". The numeric \d+ alternative
# is excluded, otherwise this matches plain positional placeholders too.
NAMED_RE = re.compile(r'\{\{([A-Za-z_]\w*)\}\}')
# Literal braces that are not a placeholder at all, e.g. an example amount.
NON_PLACEHOLDER_RE = re.compile(r'\{\{(?!\d+\}\})')


def load_spec(path=None):
    """Parse the spec file. ``path`` exists so tests can feed a temporary one."""
    with open(path or SPEC_PATH, encoding='utf-8') as fh:
        return json.load(fh)


def templates(path=None):
    """The list of template entries, in file order."""
    return load_spec(path)['templates']


def spec_defaults(path=None):
    """File-wide defaults (allow_category_change, parameter_format)."""
    return dict(load_spec(path).get('_defaults') or {})


def body_indices(body):
    """Positional placeholder indices in a body, in the order they appear."""
    return [int(n) for n in POSITIONAL_RE.findall(body or '')]


def _entry_for(notification_type, path=None):
    for entry in templates(path):
        if entry['notification_type'] == notification_type:
            return entry
    return None


def template_name(notification_type, path=None):
    """The suggested_name for a notification type, or '' when unknown.

    Callers that need a template name should read it here rather than
    hardcoding a string. The names live in this spec and have changed before,
    and a stale literal fails in a confusing place — an empty parameter list,
    not "no such template".
    """
    entry = _entry_for(notification_type, path)
    return entry['suggested_name'] if entry else ''


def parameter_order(notification_type, path=None):
    """Ordered param_names for a notification type — the positional send order.

    ``send_typed`` uses this so the send order comes from the spec, never from
    the order a params dict happened to be built in.
    """
    entry = _entry_for(notification_type, path)
    if not entry:
        return []
    return [p['param_name'] for p in (entry.get('parameters') or [])]


def validate_entry(entry, path=None):
    """Reasons Meta would reject this entry. Empty list means safe to POST."""
    errors = []
    name = entry.get('suggested_name') or ''

    if not NAME_RE.match(name):
        errors.append(f"{name or '(blank)'}: name must be lowercase alphanumeric and underscores only")

    category = entry.get('category') or ''
    if category not in CATEGORIES:
        errors.append(f"{name}: category '{category}' is not one of {', '.join(CATEGORIES)}")

    sub_category = entry.get('sub_category') or ''
    if sub_category:
        if category != 'UTILITY':
            errors.append(
                f"{name}: sub_category '{sub_category}' is only valid on UTILITY templates, not {category}")
        elif sub_category not in UTILITY_SUB_CATEGORIES:
            errors.append(
                f"{name}: sub_category '{sub_category}' is not one of {', '.join(UTILITY_SUB_CATEGORIES)}")
        elif sub_category not in ACCEPTED_SUB_CATEGORIES:
            # In the documented enum, but refused by this account.
            errors.append(
                f"{name}: sub_category '{sub_category}' is documented but not accepted by this WABA "
                f"(allowed: {', '.join(ACCEPTED_SUB_CATEGORIES)})")

    declared = [p['param_name'] for p in (entry.get('parameters') or [])]
    dupes = sorted({p for p in declared if declared.count(p) > 1})
    if dupes:
        errors.append(f"{name}: parameter(s) declared more than once: {', '.join(dupes)}")

    param_format = entry.get('parameter_format') or spec_defaults(path).get('parameter_format', 'POSITIONAL')
    if param_format not in PARAMETER_FORMATS:
        errors.append(
            f"{name}: parameter_format '{param_format}' is not one of {', '.join(PARAMETER_FORMATS)}")

    body = entry.get('body') or ''
    if param_format == 'POSITIONAL':
        # NAMED_RE catches a {{customer_name}} left behind after the switch.
        if NAMED_RE.search(body):
            found_named = sorted(set(NAMED_RE.findall(body)))
            errors.append(
                f"{name}: body uses named placeholders ({', '.join(found_named)}) but this template is "
                "POSITIONAL. NAMED templates with variables cannot be created through the API — "
                "use {{1}}..{{N}}")
        elif NON_PLACEHOLDER_RE.search(body):
            # Catches "{{amount}}" and a stray "{{" — Meta would count it as a
            # variable we never supply an example for, and reject the template.
            errors.append(f"{name}: body has {{{{ ... }}}} that is neither a positional nor a "
                          f"named placeholder: {NON_PLACEHOLDER_RE.findall(body)}")
        indices = body_indices(body)
        expected = list(range(1, len(declared) + 1))
        if indices != expected:
            errors.append(
                f"{name}: body placeholders {indices or '[]'} must be "
                f"{expected} to match {len(declared)} declared parameter(s), in order")
    else:
        errors.append(
            f"{name}: parameter_format is {param_format}; only POSITIONAL is creatable via the Graph API")

    return errors


def validate_spec(path=None):
    """Every entry's errors, concatenated."""
    errors = []
    for entry in templates(path):
        errors.extend(validate_entry(entry, path))
    return errors


def body_component(entry):
    """The BODY component: the text plus one example value per placeholder.

    ``example.body_text`` is positional — a list of per-language example sets,
    each ordered to match {{1}}..{{N}} in the body. We ship en_US only. Note the
    brackets: ``[[v1, v2]]``, not ``[v1, v2]``; the flat form is refused.
    """
    component = {'type': 'BODY', 'text': entry['body']}
    examples = [p['example'] for p in (entry.get('parameters') or [])]
    if examples:
        component['example'] = {'body_text': [examples]}
    return component


def build_payload(entry, defaults=None, path=None):
    """Compile one entry into a POST /{waba}/message_templates body."""
    merged = {**spec_defaults(path), **(defaults or {})}
    payload = {
        'name': entry['suggested_name'],
        'language': entry['language'],
        'category': entry['category'],
        'parameter_format': merged.get('parameter_format', 'POSITIONAL'),
        'allow_category_change': bool(merged.get('allow_category_change', False)),
        'components': [body_component(entry)],
    }
    if entry.get('sub_category'):
        payload['sub_category'] = entry['sub_category']
    return payload


def build_payloads(path=None, only=None, **kwargs):
    """Compile every entry, optionally narrowed to specific template names."""
    return [
        build_payload(entry, path=path, **kwargs)
        for entry in templates(path)
        if not only or entry['suggested_name'] in only
    ]