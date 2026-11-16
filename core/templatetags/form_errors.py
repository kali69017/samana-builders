from django import template

register = template.Library()


@register.inclusion_tag('includes/form_errors_summary.html')
def form_error_summary(form):
    items = []
    if not form:
        return {'items': items}
    for name, errors in form.errors.items():
        if name == '__all__':
            label = 'General'
        else:
            field = form.fields.get(name)
            label = field.label if field and field.label else name.replace('_', ' ').title()
        items.append({'label': label, 'errors': errors})
    return {'items': items}
