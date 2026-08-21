from django.urls import path
from . import views

urlpatterns = [
    # Ledger
    path('ledger/', views.ledger_view, name='finance_ledger'),

    # Offices
    path('offices/', views.offices_view, name='finance_offices'),
    path('offices/create/', views.office_create_view, name='finance_office_create'),
    path('offices/<int:pk>/edit/', views.office_edit_view, name='finance_office_edit'),
    path('offices/<int:pk>/delete/', views.office_delete_view, name='finance_office_delete'),

    # Expense categories
    path('expense-categories/', views.expense_categories_view, name='finance_expense_categories'),
    path('expense-categories/create/', views.expense_category_create_view, name='finance_expense_category_create'),
    path('expense-categories/<int:pk>/edit/', views.expense_category_edit_view, name='finance_expense_category_edit'),
    path('expense-categories/<int:pk>/delete/', views.expense_category_delete_view, name='finance_expense_category_delete'),

    # Office expenses
    path('office-expenses/', views.office_expenses_view, name='finance_office_expenses'),
    path('office-expenses/create/', views.office_expense_create_view, name='finance_office_expense_create'),
    path('office-expenses/<int:pk>/edit/', views.office_expense_edit_view, name='finance_office_expense_edit'),
    path('office-expenses/<int:pk>/approve/', views.office_expense_approve_view, name='finance_office_expense_approve'),
    path('office-expenses/<int:pk>/pay/', views.office_expense_pay_view, name='finance_office_expense_pay'),
    path('office-expense-report/', views.office_expense_report_view, name='finance_office_expense_report'),

    # Project costs
    path('project-costs/', views.project_costs_view, name='finance_project_costs'),
    path('project-costs/create/', views.project_cost_create_view, name='finance_project_cost_create'),
    path('project-costs/<int:pk>/edit/', views.project_cost_edit_view, name='finance_project_cost_edit'),
    path('project-costs/<int:pk>/delete/', views.project_cost_delete_view, name='finance_project_cost_delete'),

    # Project finance (budget + investment)
    path('projects/', views.project_finance_view, name='finance_project_finance'),
    path('projects/<int:pk>/budget/', views.project_budget_edit_view, name='finance_project_budget'),
    path('projects/<int:pk>/investment/', views.project_investment_edit_view, name='finance_project_investment'),
]
