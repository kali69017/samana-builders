from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.db.models import Sum, Count
from django.shortcuts import render, redirect, get_object_or_404
from datetime import date

from core.models import AuditLog
from core.permissions import finance_or_above
from payments.models import Payment
from properties.models import Project
from .models import Expense
from .forms import ExpenseForm


def _expense_log(request, action, expense, extra=''):
    AuditLog.objects.create(
        user=request.user,
        action=action,
        model_name='Expense',
        object_id=str(expense.pk),
        description=f"{action} expense of {expense.amount} for {expense.project.name} on {expense.expense_date}{extra}",
    )


@login_required
@finance_or_above
def expenses_view(request):
    expenses = Expense.objects.select_related('project', 'created_by').all()
    total_expenses = expenses.aggregate(total=Sum('amount'))['total'] or 0
    expense_count = expenses.count()

    month_start = date.today().replace(day=1)
    month_expenses = expenses.filter(expense_date__gte=month_start).aggregate(t=Sum('amount'))['t'] or 0

    by_type = []
    for t_key, t_label in Expense.EXPENSE_TYPES:
        agg = expenses.filter(expense_type=t_key).aggregate(total=Sum('amount'), count=Count('id'))
        by_type.append({
            'key': t_key,
            'label': t_label,
            'total': agg['total'] or 0,
            'count': agg['count'] or 0,
        })

    project_rows = []
    project_names = []
    rev_data = []
    exp_data = []
    for project in Project.objects.exclude(status='inactive').order_by('name'):
        revenue = Payment.objects.filter(
            status='verified', booking__plot__project=project,
        ).aggregate(t=Sum('amount'))['t'] or 0
        spend = project.expenses.aggregate(t=Sum('amount'))['t'] or 0
        project_rows.append({
            'project': project,
            'revenue': revenue,
            'expenses': spend,
            'net': revenue - spend,
        })
        project_names.append(project.name)
        rev_data.append(float(revenue))
        exp_data.append(float(spend))

    return render(request, 'expenses.html', {
        'expenses': expenses,
        'total_expenses': total_expenses,
        'expense_count': expense_count,
        'month_expenses': month_expenses,
        'by_type': by_type,
        'project_rows': project_rows,
        'project_names': project_names,
        'rev_data': rev_data,
        'exp_data': exp_data,
    })


@login_required
@finance_or_above
def expense_create_view(request):
    if request.method == 'POST':
        form = ExpenseForm(request.POST)
        if form.is_valid():
            expense = form.save(commit=False)
            expense.created_by = request.user
            expense.save()
            _expense_log(request, 'create', expense)
            messages.success(request, 'Expense recorded successfully!')
            return redirect('expenses')
    else:
        form = ExpenseForm()

    return render(request, 'expense_form.html', {'form': form, 'title': 'Add Expense', 'mode': 'add'})


@login_required
@finance_or_above
def expense_edit_view(request, pk):
    expense = get_object_or_404(Expense, pk=pk)
    if request.method == 'POST':
        form = ExpenseForm(request.POST, instance=expense)
        if form.is_valid():
            form.save()
            _expense_log(request, 'update', expense)
            messages.success(request, 'Expense updated successfully!')
            return redirect('expenses')
    else:
        form = ExpenseForm(instance=expense)

    return render(request, 'expense_form.html', {'form': form, 'title': 'Edit Expense', 'expense': expense, 'mode': 'edit'})


@login_required
@finance_or_above
def expense_detail_view(request, pk):
    expense = get_object_or_404(
        Expense.objects.select_related('project', 'created_by'),
        pk=pk,
    )
    return render(request, 'expense_detail.html', {'expense': expense})


@login_required
@finance_or_above
def expense_delete_view(request, pk):
    expense = get_object_or_404(Expense, pk=pk)
    if request.method == 'POST':
        amt = expense.amount
        project = expense.project.name
        expense.delete()
        AuditLog.objects.create(
            user=request.user, action='delete', model_name='Expense',
            object_id=str(pk),
            description=f"Deleted expense of {amt} for {project}",
        )
        messages.success(request, 'Expense deleted successfully!')
        return redirect('expenses')

    return render(request, 'confirm_delete.html', {
        'object': expense,
        'title': 'Delete Expense',
        'cancel_url': 'expenses',
    })