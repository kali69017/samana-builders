"""Finance ERP views: office expenses, project costs/budget/investment, ledger."""
from datetime import date
from decimal import Decimal

from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Sum
from django.http import HttpResponse
from django.shortcuts import render, redirect, get_object_or_404
from django.utils.dateparse import parse_date
from django.views.decorators.http import require_POST

from core.models import AuditLog
from core.permissions import (
    admin_or_above, finance_or_above, management_or_above, MANAGEMENT_ROLES,
)
from properties.models import Project
from bookings.models import Booking
from .models import (
    AccountHead, Office, ExpenseCategory, OfficeExpense,
    ProjectBudget, ProjectCost, ProjectInvestment, Voucher,
    VoucherDeletionLog,
)
from .forms import (
    OfficeForm, ExpenseCategoryForm, OfficeExpenseForm, ProjectCostForm,
    ProjectBudgetForm, ProjectInvestmentForm, AccountHeadForm, VoucherForm,
    VoucherLineFormSet, CashBankVoucherForm, ContraLineFormSet,
    CASH_BANK_VOUCHER_KINDS,
)
from .reports import build_ledger_report


def _log(request, action, model, object_id, description):
    AuditLog.objects.create(
        user=request.user, action=action, model_name=model,
        object_id=str(object_id), description=description,
        ip_address=request.META.get('REMOTE_ADDR'),
    )


def _validation_messages(exc):
    if hasattr(exc, 'message_dict'):
        out = []
        for msgs in exc.message_dict.values():
            out.extend(msgs)
        return out
    return getattr(exc, 'messages', [str(exc)])


def _is_supervisor(request):
    """True for supervisor-tier users (management or above) — spec §3.6."""
    role = getattr(getattr(request.user, 'profile', None), 'role', None)
    return request.user.is_superuser or role in MANAGEMENT_ROLES


# ─── OFFICES ─────────────────────────────────────────────────────────────────
@login_required
@finance_or_above
def offices_view(request):
    offices = Office.objects.all()
    return render(request, 'finance/offices.html', {'offices': offices})


@login_required
@finance_or_above
def office_create_view(request):
    if request.method == 'POST':
        form = OfficeForm(request.POST)
        if form.is_valid():
            office = form.save()
            _log(request, 'create', 'Office', office.pk, f'Created office {office.name}')
            messages.success(request, 'Office created successfully!')
            return redirect('finance_offices')
    else:
        form = OfficeForm()
    return render(request, 'finance/office_form.html', {'form': form, 'title': 'Add Office'})


@login_required
@finance_or_above
def office_edit_view(request, pk):
    office = get_object_or_404(Office, pk=pk)
    if request.method == 'POST':
        form = OfficeForm(request.POST, instance=office)
        if form.is_valid():
            form.save()
            _log(request, 'update', 'Office', pk, f'Updated office {office.name}')
            messages.success(request, 'Office updated successfully!')
            return redirect('finance_offices')
    else:
        form = OfficeForm(instance=office)
    return render(request, 'finance/office_form.html', {'form': form, 'title': 'Edit Office', 'office': office})


@login_required
@management_or_above
def office_delete_view(request, pk):
    office = get_object_or_404(Office, pk=pk)
    if request.method == 'POST':
        # Dependency guard: refuse deletion while the office still owns
        # expenses or ledger transactions.
        dependents = []
        if office.expenses.exists():
            dependents.append(f"{office.expenses.count()} office expense(s)")
        if office.transactions.exists():
            dependents.append(f"{office.transactions.count()} ledger transaction(s)")
        if dependents:
            messages.error(
                request,
                f"Cannot delete office '{office.name}' — it still has "
                f"{' and '.join(dependents)}. Delete or reassign those records first."
            )
            return redirect('finance_offices')
        office.delete()
        _log(request, 'delete', 'Office', pk, f'Deleted office {office.name}')
        messages.success(request, 'Office deleted successfully!')
        return redirect('finance_offices')
    return render(request, 'confirm_delete.html', {'object': office, 'title': 'Delete Office', 'cancel_url': 'finance_offices'})


# ─── EXPENSE CATEGORIES ──────────────────────────────────────────────────────
def expense_category_usage(category):
    """Count every record that references this category through any FK."""
    total = 0
    for relation in category._meta.related_objects:
        accessor = relation.get_accessor_name()
        if not accessor:
            continue
        manager = getattr(category, accessor, None)
        if manager is not None and hasattr(manager, 'count'):
            total += manager.count()
    return total


@login_required
@finance_or_above
def expense_categories_view(request):
    categories = list(ExpenseCategory.objects.all())
    for category in categories:
        category.used_count = expense_category_usage(category)
    return render(request, 'finance/expense_categories.html', {'categories': categories})


@login_required
@finance_or_above
def expense_category_create_view(request):
    if request.method == 'POST':
        form = ExpenseCategoryForm(request.POST)
        if form.is_valid():
            cat = form.save()
            _log(request, 'create', 'ExpenseCategory', cat.pk, f'Created category {cat.name}')
            messages.success(request, 'Category created successfully!')
            return redirect('finance_expense_categories')
    else:
        form = ExpenseCategoryForm()
    return render(request, 'finance/expense_category_form.html', {'form': form, 'title': 'Add Category'})


@login_required
@finance_or_above
def expense_category_edit_view(request, pk):
    cat = get_object_or_404(ExpenseCategory, pk=pk)
    if request.method == 'POST':
        form = ExpenseCategoryForm(request.POST, instance=cat)
        if form.is_valid():
            form.save()
            _log(request, 'update', 'ExpenseCategory', pk, f'Updated category {cat.name}')
            messages.success(request, 'Category updated successfully!')
            return redirect('finance_expense_categories')
    else:
        form = ExpenseCategoryForm(instance=cat)
    return render(request, 'finance/expense_category_form.html', {'form': form, 'title': 'Edit Category', 'category': cat})


@login_required
@finance_or_above
def expense_category_delete_view(request, pk):
    cat = get_object_or_404(ExpenseCategory, pk=pk)
    if request.method == 'POST':
        used = expense_category_usage(cat)
        if used:
            messages.error(
                request,
                f'This category is used by {used} records. Deactivate it instead.',
            )
            return redirect('finance_expense_categories')
        try:
            cat.delete()
        except Exception as exc:
            messages.error(request, str(exc))
            return redirect('finance_expense_categories')
        _log(request, 'delete', 'ExpenseCategory', pk, f'Deleted category {cat.name}')
        messages.success(request, 'Category deleted successfully!')
        return redirect('finance_expense_categories')
    return render(request, 'confirm_delete.html', {
        'object': cat, 'title': 'Delete Category',
        'cancel_url': 'finance_expense_categories',
    })


@login_required
@finance_or_above
@require_POST
def expense_category_toggle_active_view(request, pk):
    cat = get_object_or_404(ExpenseCategory, pk=pk)
    cat.is_active = not cat.is_active
    cat.save(update_fields=['is_active'])
    action = 'activated' if cat.is_active else 'deactivated'
    _log(request, 'update', 'ExpenseCategory', pk,
         f'{action.title()} category {cat.name}')
    messages.success(request, f'Category {action} successfully.')
    return redirect('finance_expense_categories')


# ─── OFFICE EXPENSES ─────────────────────────────────────────────────────────
@login_required
@finance_or_above
def office_expenses_view(request):
    office_filter = request.GET.get('office', '')
    status_filter = request.GET.get('status', '')
    expenses = OfficeExpense.objects.select_related('office', 'category', 'approved_by').all()
    if office_filter:
        expenses = expenses.filter(office_id=office_filter)
    if status_filter:
        expenses = expenses.filter(status=status_filter)
    context = {
        'expenses': expenses,
        'offices': Office.objects.filter(is_active=True),
        'office_filter': office_filter,
        'status_filter': status_filter,
        'total_amount': expenses.aggregate(t=Sum('amount'))['t'] or 0,
    }
    return render(request, 'finance/office_expenses.html', context)


@login_required
@finance_or_above
def office_expense_create_view(request):
    if request.method == 'POST':
        form = OfficeExpenseForm(request.POST)
        if form.is_valid():
            expense = form.save(commit=False)
            expense.created_by = request.user
            expense.save()
            if expense.status == 'paid':
                expense.post_to_ledger()
            _log(request, 'create', 'OfficeExpense', expense.pk, f'Created office expense of {expense.amount}')
            messages.success(request, 'Office expense recorded successfully!')
            return redirect('finance_office_expenses')
    else:
        form = OfficeExpenseForm()
    return render(request, 'finance/office_expense_form.html', {'form': form, 'title': 'Add Office Expense'})


@login_required
@finance_or_above
def office_expense_edit_view(request, pk):
    expense = get_object_or_404(OfficeExpense, pk=pk)
    if request.method == 'POST':
        form = OfficeExpenseForm(request.POST, instance=expense)
        if form.is_valid():
            form.save()
            if expense.status == 'paid':
                expense.post_to_ledger()
            _log(request, 'update', 'OfficeExpense', pk, f'Updated office expense of {expense.amount}')
            messages.success(request, 'Office expense updated successfully!')
            return redirect('finance_office_expenses')
    else:
        form = OfficeExpenseForm(instance=expense)
    # FIN-EC-03: a posted voucher is immutable; surface the posted voucher so the
    # template can warn that edits won't rewrite it and offer the unlock path.
    return render(request, 'finance/office_expense_form.html', {
        'form': form, 'title': 'Edit Office Expense', 'expense': expense,
        'posted_voucher': expense.posted_voucher,
    })


@login_required
@management_or_above
def office_expense_approve_view(request, pk):
    expense = get_object_or_404(OfficeExpense, pk=pk)
    if request.method == 'POST':
        action = request.POST.get('action', 'approve')
        if expense.status == 'paid':
            # The voucher is posted and locked, so the source must not fall back
            # to an unposted state — that would silently desync it from the ledger.
            messages.error(
                request,
                'A paid office expense is already posted to the ledger and cannot '
                'be sent back for approval.')
        else:
            expense.status = 'approved' if action == 'approve' else 'pending'
            expense.approved_by = request.user if action == 'approve' else None
            expense.save()
            _log(request, 'update', 'OfficeExpense', pk, f'{expense.get_status_display()} office expense of {expense.amount}')
            messages.success(request, f'Office expense {expense.get_status_display()}.')
    return redirect('finance_office_expenses')


@login_required
@management_or_above
def office_expense_pay_view(request, pk):
    expense = get_object_or_404(OfficeExpense, pk=pk)
    if request.method == 'POST':
        if expense.status == 'paid':
            messages.info(request, 'This office expense is already paid.')
        elif expense.status != 'approved':
            messages.error(
                request,
                f'Only approved expenses can be paid (current status: {expense.get_status_display()}).',
            )
        else:
            expense.status = 'paid'
            expense.save()
            expense.post_to_ledger()
            _log(request, 'update', 'OfficeExpense', pk, f'Paid office expense of {expense.amount}')
            messages.success(request, 'Office expense marked as paid and posted to ledger.')
    return redirect('finance_office_expenses')


# ─── PROJECT COSTS ───────────────────────────────────────────────────────────
@login_required
@finance_or_above
def project_costs_view(request):
    project_filter = request.GET.get('project', '')
    category_filter = request.GET.get('category', '')
    costs = ProjectCost.objects.select_related('project').all()
    if project_filter:
        costs = costs.filter(project_id=project_filter)
    if category_filter:
        costs = costs.filter(cost_category=category_filter)
    context = {
        'costs': costs,
        'projects': Project.objects.exclude(status='inactive'),
        'project_filter': project_filter,
        'category_filter': category_filter,
        'total_amount': costs.aggregate(t=Sum('amount'))['t'] or 0,
    }
    return render(request, 'finance/project_costs.html', context)


@login_required
@finance_or_above
def project_cost_create_view(request):
    if request.method == 'POST':
        form = ProjectCostForm(request.POST)
        if form.is_valid():
            cost = form.save(commit=False)
            cost.created_by = request.user
            cost.save()
            if cost.status == 'paid':
                cost.post_to_ledger()
            _log(request, 'create', 'ProjectCost', cost.pk, f'Created project cost of {cost.amount}')
            messages.success(request, 'Project cost recorded successfully!')
            return redirect('finance_project_costs')
    else:
        form = ProjectCostForm()
    return render(request, 'finance/project_cost_form.html', {'form': form, 'title': 'Add Project Cost'})


@login_required
@finance_or_above
def project_cost_edit_view(request, pk):
    cost = get_object_or_404(ProjectCost, pk=pk)
    if request.method == 'POST':
        form = ProjectCostForm(request.POST, instance=cost)
        if form.is_valid():
            form.save()
            if cost.status == 'paid':
                cost.post_to_ledger()
            _log(request, 'update', 'ProjectCost', pk, f'Updated project cost of {cost.amount}')
            messages.success(request, 'Project cost updated successfully!')
            return redirect('finance_project_costs')
    else:
        form = ProjectCostForm(instance=cost)
    return render(request, 'finance/project_cost_form.html', {
        'form': form, 'title': 'Edit Project Cost', 'cost': cost,
        'posted_voucher': cost.posted_voucher,
    })


@login_required
@management_or_above
def project_cost_approve_view(request, pk):
    cost = get_object_or_404(ProjectCost, pk=pk)
    if request.method == 'POST':
        action = request.POST.get('action', 'approve')
        if cost.status == 'paid':
            messages.error(request, 'A paid project cost is already posted to the ledger.')
        else:
            cost.status = 'approved' if action == 'approve' else 'pending'
            cost.save()
            _log(request, 'update', 'ProjectCost', pk, f'{cost.get_status_display()} project cost of {cost.amount}')
            messages.success(request, f'Project cost {cost.get_status_display()}.')
    return redirect('finance_project_costs')


@login_required
@management_or_above
def project_cost_pay_view(request, pk):
    """Mark the cost paid and post its Cash/Bank Payment voucher exactly once.

    Mirrors ``office_expense_pay_view``. ``ProjectCost.post_to_ledger`` is keyed on
    ``(reference_type, reference_id)``, so re-paying never double-posts (FIN-EC-03).
    """
    cost = get_object_or_404(ProjectCost, pk=pk)
    if request.method == 'POST':
        if cost.status == 'paid':
            messages.info(request, 'This project cost is already paid.')
        elif cost.status != 'approved':
            messages.error(
                request,
                f'Only approved project costs can be paid (current status: {cost.get_status_display()}).',
            )
        else:
            cost.status = 'paid'
            cost.save()
            cost.post_to_ledger()
            _log(request, 'update', 'ProjectCost', pk, f'Paid project cost of {cost.amount}')
            messages.success(request, 'Project cost marked as paid and posted to ledger.')
    return redirect('finance_project_costs')


@login_required
@management_or_above
def project_cost_delete_view(request, pk):
    cost = get_object_or_404(ProjectCost, pk=pk)
    if request.method == 'POST':
        try:
            cost.delete()
        except ValidationError as exc:
            messages.error(request, ' '.join(_validation_messages(exc)))
            return redirect('finance_project_costs')
        _log(request, 'delete', 'ProjectCost', pk, f'Deleted project cost of {cost.amount}')
        messages.success(request, 'Project cost deleted successfully!')
        return redirect('finance_project_costs')
    return render(request, 'confirm_delete.html', {'object': cost, 'title': 'Delete Project Cost', 'cancel_url': 'finance_project_costs'})


# ─── PROJECT BUDGET & INVESTMENT ─────────────────────────────────────────────
@login_required
@finance_or_above
def project_finance_view(request):
    projects = Project.objects.exclude(status='inactive').prefetch_related('costs')
    rows = []
    for project in projects:
        budget = getattr(project, 'budget', None)
        investment = getattr(project, 'investment', None)
        costs = project.costs.filter(status='paid')
        total_cost = costs.aggregate(t=Sum('amount'))['t'] or 0
        revenue = Booking.objects.filter(plot__project=project).aggregate(t=Sum('advance_paid'))['t'] or 0
        rows.append({
            'project': project,
            'budget': budget,
            'investment': investment,
            'total_cost': total_cost,
            'revenue': revenue,
            'profit': revenue - total_cost,
            'remaining_budget': (budget.total_budget - total_cost) if budget else None,
        })
    return render(request, 'finance/project_finance.html', {'rows': rows})


@login_required
@finance_or_above
def project_budget_edit_view(request, pk):
    project = get_object_or_404(Project, pk=pk)
    budget, _ = ProjectBudget.objects.get_or_create(project=project)
    if request.method == 'POST':
        form = ProjectBudgetForm(request.POST, instance=budget)
        if form.is_valid():
            form.save()
            _log(request, 'update', 'ProjectBudget', budget.pk, f'Updated budget for {project.name}')
            messages.success(request, f'Budget for {project.name} updated.')
            return redirect('finance_project_finance')
    else:
        form = ProjectBudgetForm(instance=budget)
    return render(request, 'finance/project_budget_form.html', {'form': form, 'project': project, 'title': f'Budget - {project.name}'})


@login_required
@finance_or_above
def project_investment_edit_view(request, pk):
    project = get_object_or_404(Project, pk=pk)
    investment, _ = ProjectInvestment.objects.get_or_create(project=project)
    if request.method == 'POST':
        form = ProjectInvestmentForm(request.POST, instance=investment)
        if form.is_valid():
            form.save()
            _log(request, 'update', 'ProjectInvestment', investment.pk, f'Updated investment for {project.name}')
            messages.success(request, f'Investment for {project.name} updated.')
            return redirect('finance_project_finance')
    else:
        form = ProjectInvestmentForm(instance=investment)
    return render(request, 'finance/project_investment_form.html', {'form': form, 'project': project, 'title': f'Investment - {project.name}'})


# ─── LEDGER & REPORTS ────────────────────────────────────────────────────────
def _ledger_from_request(request):
    """Build the ledger report + raw filter params from GET args."""
    head_id = request.GET.get('head') or ''
    date_from = request.GET.get('date_from') or ''
    date_to = request.GET.get('date_to') or ''
    head = get_object_or_404(AccountHead, pk=head_id) if head_id else None
    report = build_ledger_report(
        head=head,
        date_from=parse_date(date_from) if date_from else None,
        date_to=parse_date(date_to) if date_to else None,
    )
    return report, {
        'head_id': str(head_id),
        'date_from': date_from,
        'date_to': date_to,
    }


@login_required
@finance_or_above
def finance_home_view(request):
    return redirect('finance_ledger')


@login_required
@finance_or_above
def ledger_view(request):
    report, params = _ledger_from_request(request)
    context = {
        'report': report,
        'heads': AccountHead.objects.all(),
        **params,
    }
    return render(request, 'finance/ledger.html', context)


@login_required
@finance_or_above
def ledger_export_excel_view(request):
    from openpyxl import Workbook
    report, params = _ledger_from_request(request)
    wb = Workbook()
    ws = wb.active
    ws.title = 'Ledger'
    # A running balance is only meaningful for a single account / roll-up, so the
    # column is omitted in the all-accounts view (same rule as ledger.html).
    has_head = report['head'] is not None
    header = ['Date', 'Voucher', 'Type', 'Account', 'Narration', 'Debit', 'Credit']
    if has_head:
        header.append('Ledger balance')
    ws.append(header)
    for row in report['rows']:
        values = [
            row['date'].strftime('%Y-%m-%d'), row['voucher_number'], row['voucher_type'],
            f"{row['account'].code} {row['account'].name}", row['narration'],
            float(row['debit']), float(row['credit']),
        ]
        if has_head:
            values.append(float(row['balance']))
        ws.append(values)
    ws.append([])
    width = len(header)

    def footer(label, value, column):
        """Write a `label / value` summary row padded to the header width."""
        row = [''] * width
        row[4] = label
        row[column] = value
        ws.append(row)

    if has_head:
        footer('Opening balance', float(report['opening_balance']), width - 1)
        footer('Ledger balance', float(report['closing_balance']), width - 1)
    else:
        footer('Posting lines', len(report['rows']), 5)
    footer('Total debit', float(report['total_debit']), 5)
    footer('Total credit', float(report['total_credit']), 6)
    response = HttpResponse(
        content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
    response['Content-Disposition'] = 'attachment; filename="ledger.xlsx"'
    wb.save(response)
    return response


@login_required
@finance_or_above
def ledger_export_pdf_view(request):
    from payments.pdf_utils import render_to_pdf
    report, params = _ledger_from_request(request)
    pdf = render_to_pdf('finance/ledger_pdf.html', {'report': report, **params})
    if not pdf:
        messages.error(request, 'Could not generate the ledger PDF.')
        return redirect('finance_ledger')
    response = HttpResponse(pdf, content_type='application/pdf')
    response['Content-Disposition'] = 'attachment; filename="ledger.pdf"'
    return response


@login_required
@finance_or_above
def office_expense_report_view(request):
    month = request.GET.get('month', date.today().strftime('%Y-%m'))
    try:
        year, mon = int(month[:4]), int(month[5:7])
    except (ValueError, IndexError):
        year, mon = date.today().year, date.today().month
    expenses = OfficeExpense.objects.filter(expense_date__year=year, expense_date__month=mon).select_related('office', 'category')
    by_office = expenses.values('office__name').annotate(total=Sum('amount')).order_by('-total')
    by_category = expenses.values('category__name').annotate(total=Sum('amount')).order_by('-total')
    context = {
        'expenses': expenses,
        'month': f'{year}-{mon:02d}',
        'by_office': by_office,
        'by_category': by_category,
        'total': expenses.aggregate(t=Sum('amount'))['t'] or 0,
    }
    return render(request, 'finance/office_expense_report.html', context)


# ─── VOUCHERS (double-entry) ─────────────────────────────────────────────────
@login_required
@finance_or_above
def vouchers_view(request):
    vouchers = (
        Voucher.objects.select_related('created_by').prefetch_related('lines').all()
    )
    type_filter = request.GET.get('type', '')
    status_filter = request.GET.get('status', '')
    if type_filter:
        vouchers = vouchers.filter(voucher_type=type_filter)
    if status_filter:
        vouchers = vouchers.filter(status=status_filter)
    context = {
        'vouchers': vouchers,
        'type_filter': type_filter,
        'status_filter': status_filter,
        'voucher_types': Voucher.TYPE_CHOICES,
        'voucher_statuses': Voucher.STATUS_CHOICES,
        'can_delete_vouchers': _can_delete_vouchers(request),
    }
    return render(request, 'finance/vouchers.html', context)


def _can_delete_vouchers(request):
    if request.user.is_superuser:
        return True
    return getattr(getattr(request.user, 'profile', None), 'role', None) in (
        'super_admin', 'admin',
    )


@login_required
@finance_or_above
def voucher_detail_view(request, pk):
    voucher = get_object_or_404(
        Voucher.objects
        .select_related('created_by', 'locked_by', 'unlocked_by')
        .prefetch_related('lines__account_head', 'audit_logs__actor'),
        pk=pk,
    )
    return render(request, 'finance/voucher_detail.html', {
        'voucher': voucher,
        'can_post': _is_supervisor(request),
        'can_unlock': _is_supervisor(request),
        'can_delete': _can_delete_vouchers(request) and voucher.is_manual,
    })


@login_required
@admin_or_above
def voucher_delete_view(request, pk):
    """Delete a manual voucher after a reason and immutable snapshot."""
    voucher = get_object_or_404(Voucher, pk=pk)
    if not voucher.is_manual:
        messages.error(
            request,
            'Only manual vouchers can be deleted. Correct the source record instead.',
        )
        return redirect('finance_voucher_detail', pk=pk)
    if request.method == 'POST':
        reason = (request.POST.get('reason') or '').strip()
        try:
            log = voucher.delete_manual_voucher(request.user, reason)
        except ValidationError as exc:
            messages.error(request, ' '.join(_validation_messages(exc)))
            return render(request, 'finance/voucher_delete.html', {
                'voucher': voucher, 'reason': reason,
            })
        _log(request, 'delete', 'Voucher', log.voucher_number,
             f'Deleted manual voucher {log.voucher_number}: {reason}')
        messages.success(
            request,
            f'Voucher {log.voucher_number} deleted. The number is retired and will not be reused.',
        )
        return redirect('finance_vouchers')
    return render(request, 'finance/voucher_delete.html', {'voucher': voucher})


@login_required
@admin_or_above
def deleted_vouchers_view(request):
    return render(request, 'finance/deleted_vouchers.html', {
        'deletions': VoucherDeletionLog.objects.select_related(
            'deleted_by', 'created_by').all(),
    })


def _contra_errors(form, formset, cash_account):
    errors = []
    total = Decimal('0.00')
    for line_form in formset.forms:
        cleaned = getattr(line_form, 'cleaned_data', None)
        if not cleaned:
            continue
        account = cleaned.get('account_head')
        amount = cleaned.get('amount')
        if account is None or amount is None:
            continue
        if account.pk == cash_account.pk:
            errors.append('A contra account cannot be the cash or bank account.')
        total += amount
    if total <= 0:
        errors.append('Enter at least one contra line with an amount greater than zero.')
    return errors, total


def _cash_voucher_lines(voucher_type, cash_account, formset):
    entries = []
    total = Decimal('0.00')
    for line_form in formset.forms:
        cleaned = line_form.cleaned_data
        if not cleaned:
            continue
        account = cleaned['account_head']
        amount = cleaned['amount']
        narration = cleaned.get('narration', '')
        if amount <= 0:
            continue
        total += amount
        entries.append((account, amount, narration))
    if not entries:
        return []
    if voucher_type in ('CR', 'BR'):
        lines = [(cash_account, total, Decimal('0.00'), '')]
        lines.extend((account, Decimal('0.00'), amount, narration)
                     for account, amount, narration in entries)
    else:
        lines = []
        lines.extend((account, amount, Decimal('0.00'), narration)
                     for account, amount, narration in entries)
        lines.append((cash_account, Decimal('0.00'), total, ''))
    return lines


@login_required
@finance_or_above
def voucher_create_view(request):
    requested_type = request.POST.get('voucher_type') if request.method == 'POST' else request.GET.get('type', '')
    if request.method == 'GET' and not requested_type:
        return render(request, 'finance/voucher_choose.html', {
            'title': 'New Voucher',
            'voucher_types': [
                ('CR', 'Cash Receipt'), ('CP', 'Cash Payment'),
                ('BR', 'Bank Receipt'), ('BP', 'Bank Payment'),
                ('JV', 'Journal Voucher'),
            ],
        })
    is_cash_bank = requested_type in CASH_BANK_VOUCHER_KINDS
    formset = None

    if request.method == 'POST':
        if is_cash_bank:
            form = CashBankVoucherForm(request.POST)
            if any(key.endswith('-debit') or key.endswith('-credit')
                   for key in request.POST):
                form.add_error(None, 'Debit and credit fields are not valid for a cash or bank voucher.')
            formset = ContraLineFormSet(request.POST, prefix='lines')
            if form.is_valid() and formset.is_valid():
                errors, _total = _contra_errors(
                    form, formset, form.cleaned_data['cash_bank_account'],
                )
                for error in errors:
                    form.add_error(None, error)
                if not errors:
                    with transaction.atomic():
                        voucher = form.save(commit=False)
                        voucher.created_by = request.user
                        voucher.save()
                        for head, debit, credit, narration in _cash_voucher_lines(
                            voucher.voucher_type, voucher.cash_bank_account, formset,
                        ):
                            from .models import VoucherLine
                            VoucherLine.objects.create(
                                voucher=voucher, account_head=head,
                                debit=debit, credit=credit, narration=narration,
                            )
                    _log(request, 'create', 'Voucher', voucher.pk,
                         f'Created voucher {voucher.voucher_number}')
                    messages.success(request, f'Voucher {voucher.voucher_number} created as a draft.')
                    return redirect('finance_voucher_detail', pk=voucher.pk)
        else:
            form = VoucherForm(request.POST)
            if 'cash_bank_account' in request.POST:
                form.add_error(None, 'Cash or bank account is not valid for a journal voucher.')
            formset = VoucherLineFormSet(request.POST, prefix='lines')
            if form.is_valid() and formset.is_valid():
                lines = [
                    line_form.cleaned_data for line_form in formset.forms
                    if line_form.cleaned_data and not line_form.cleaned_data.get('DELETE')
                ]
                debit = sum((line['debit'] or Decimal('0.00') for line in lines), Decimal('0.00'))
                credit = sum((line['credit'] or Decimal('0.00') for line in lines), Decimal('0.00'))
                if not lines:
                    form.add_error(None, 'Enter at least one journal line.')
                elif debit != credit:
                    form.add_error(
                        None,
                        f'Journal is not balanced: debit {debit} does not equal credit {credit}.',
                    )
                else:
                    with transaction.atomic():
                        voucher = form.save(commit=False)
                        voucher.created_by = request.user
                        voucher.save()
                        formset.instance = voucher
                        formset.save()
                    _log(request, 'create', 'Voucher', voucher.pk,
                         f'Created voucher {voucher.voucher_number}')
                    messages.success(request, f'Voucher {voucher.voucher_number} created as a draft.')
                    return redirect('finance_voucher_detail', pk=voucher.pk)
    else:
        if is_cash_bank:
            form = CashBankVoucherForm(initial={'voucher_type': requested_type})
            formset = ContraLineFormSet(prefix='lines')
        else:
            form = VoucherForm(initial={'voucher_type': requested_type} if requested_type else None)
            formset = VoucherLineFormSet(prefix='lines')

    account_kinds = {
        str(head.pk): head.account_kind
        for head in AccountHead.objects.filter(account_kind__in=['cash', 'bank'])
    }
    return render(request, 'finance/voucher_form.html', {
        'form': form, 'formset': formset, 'title': 'New Voucher',
        'is_cash_bank': is_cash_bank, 'account_kinds': account_kinds,
    })


@login_required
@management_or_above
def voucher_post_view(request, pk):
    voucher = get_object_or_404(Voucher, pk=pk)
    if request.method == 'POST':
        try:
            voucher.post(request.user)
        except ValidationError as exc:
            messages.error(request, ' '.join(_validation_messages(exc)))
        else:
            _log(request, 'update', 'Voucher', voucher.pk,
                 f'Posted voucher {voucher.voucher_number}')
            messages.success(request, f'Voucher {voucher.voucher_number} posted and locked.')
    return redirect('finance_voucher_detail', pk=pk)


@login_required
@management_or_above
def voucher_unlock_view(request, pk):
    voucher = get_object_or_404(Voucher, pk=pk)
    if request.method == 'POST':
        reason = request.POST.get('reason', '')
        try:
            voucher.unlock(request.user, reason=reason)
        except ValidationError as exc:
            messages.error(request, ' '.join(_validation_messages(exc)))
        else:
            _log(request, 'update', 'Voucher', voucher.pk,
                 f'Unlocked voucher {voucher.voucher_number}: {reason}')
            messages.success(request, f'Voucher {voucher.voucher_number} unlocked.')
    return redirect('finance_voucher_detail', pk=pk)


# ─── CHART OF ACCOUNTS ───────────────────────────────────────────────────────
def _flatten_heads():
    """Return [(head, depth), ...] in tree order for template indentation."""
    from collections import defaultdict
    heads = list(AccountHead.objects.select_related('parent').all())
    by_parent = defaultdict(list)
    for head in heads:
        by_parent[head.parent_id].append(head)
    ordered = []

    def walk(parent_id, depth):
        for head in by_parent.get(parent_id, []):
            ordered.append((head, depth))
            walk(head.pk, depth + 1)

    walk(None, 0)
    return ordered


@login_required
@finance_or_above
def account_heads_view(request):
    heads = _flatten_heads()
    for head, _depth in heads:
        if head.parent_id is None:
            head.can_delete = False
            head.delete_blocked_reason = 'Level 1 root accounts are fixed and cannot be deleted.'
        elif head.children.exists():
            head.can_delete = False
            head.delete_blocked_reason = 'This account has children and cannot be deleted.'
        elif head.voucher_lines.exists():
            head.can_delete = False
            head.delete_blocked_reason = 'This account has ledger entries and cannot be deleted.'
        else:
            head.can_delete = True
            head.delete_blocked_reason = ''
    return render(request, 'finance/account_heads.html', {'heads': heads})


@login_required
@finance_or_above
def account_head_create_view(request):
    if request.method == 'POST':
        form = AccountHeadForm(request.POST)
        if form.is_valid():
            head = form.save()
            _log(request, 'create', 'AccountHead', head.pk,
                 f'Created account head {head.code} {head.name}')
            messages.success(request, 'Account head created successfully!')
            return redirect('finance_account_heads')
    else:
        form = AccountHeadForm()
    return render(request, 'finance/account_head_form.html', {
        'form': form, 'title': 'Add Account Head',
    })


@login_required
@finance_or_above
def account_head_edit_view(request, pk):
    head = get_object_or_404(AccountHead, pk=pk)
    if head.parent_id is None:
        messages.error(request, 'Level 1 root accounts are fixed and cannot be edited.')
        return redirect('finance_account_heads')
    if request.method == 'POST':
        form = AccountHeadForm(request.POST, instance=head)
        if form.is_valid():
            form.save()
            _log(request, 'update', 'AccountHead', pk,
                 f'Updated account head {head.code} {head.name}')
            messages.success(request, 'Account head updated successfully!')
            return redirect('finance_account_heads')
    else:
        form = AccountHeadForm(instance=head)
    return render(request, 'finance/account_head_form.html', {
        'form': form, 'title': 'Edit Account Head', 'head': head,
    })


@login_required
@management_or_above
def account_head_delete_view(request, pk):
    head = get_object_or_404(AccountHead, pk=pk)
    if request.method == 'POST':
        try:
            head.delete()
        except ValidationError as exc:
            messages.error(request, ' '.join(_validation_messages(exc)))
            return redirect('finance_account_heads')
        _log(request, 'delete', 'AccountHead', pk,
             f'Deleted account head {head.code} {head.name}')
        messages.success(request, 'Account head deleted successfully!')
        return redirect('finance_account_heads')
    return render(request, 'confirm_delete.html', {
        'object': head, 'title': 'Delete Account Head',
        'cancel_url': 'finance_account_heads',
    })
