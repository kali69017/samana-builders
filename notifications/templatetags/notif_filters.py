"""Template filters for the Notification Center (PII masking)."""
import re

from django import template

register = template.Library()


@register.filter
def mask_contact(contact):
    """Mask an email or Pakistani phone so the raw value never leaves the server
    for non-privileged viewers (e.g. a**@***.com, +92300 ••••••)."""
    value = (contact or '').strip()
    if not value:
        return value

    # Email: keep the first char of the local part and the TLD, mask the rest.
    if '@' in value and '.' in value.split('@')[-1]:
        local, domain = value.split('@', 1)
        domain_name, _, tld = domain.rpartition('.')
        if not local:
            return value
        masked_local = local[0] + '**'
        masked_domain = '***'
        if domain_name:
            masked_domain = domain_name[0] + '***'
        return f'{masked_local}@{masked_domain}.{tld}'

    # Phone: keep country code + first 2 digits of subscriber, mask the rest.
    digits = re.sub(r'\D', '', value)
    if digits:
        if len(digits) >= 11:
            return f'+{digits[:3]} {digits[3:5]} ••••••••••'
        return digits[:4] + '••••••'

    return value