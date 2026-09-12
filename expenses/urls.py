from django.urls import path
from . import views

urlpatterns = [
    path('', views.expenses_view, name='expenses'),
    path('create/', views.expense_create_view, name='expense_create'),
    path('<int:pk>/edit/', views.expense_edit_view, name='expense_edit'),
    path('<int:pk>/', views.expense_detail_view, name='expense_detail'),
    path('<int:pk>/delete/', views.expense_delete_view, name='expense_delete'),
    path('<int:pk>/approve/', views.expense_approve_view, name='expense_approve'),
    path('<int:pk>/reject/', views.expense_reject_view, name='expense_reject'),
    path('<int:pk>/mark-paid/', views.expense_mark_paid_view, name='expense_mark_paid'),
]