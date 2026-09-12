from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static
from core import views as core_views
from core import views_crm, views_settings
from bookings import views_installments
from payments import views_workflow

urlpatterns = [
    path('admin/', admin.site.urls),
    path('api/', include('api.urls')),
    
    # Authentication
    path('login/', core_views.login_view, name='login'),
        path('logout/', core_views.logout_view, name='logout'),
        path('password-reset/', core_views.password_reset_request_view, name='password_reset_request'),
        path('password-reset/verify/', core_views.password_reset_verify_view, name='password_reset_verify'),
    
    # Dashboard
    path('dashboard/', core_views.dashboard_view, name='dashboard'),
    path('dashboard/revenue-trend/', core_views.revenue_trend_view, name='revenue_trend_data'),
    path('reports/financial/', core_views.financial_reports_view, name='financial_reports'),
    path('api/plan-templates/', core_views.plan_templates_api_view, name='plan_templates_api'),
    
    # Customers
    path('customers/', core_views.customers_view, name='customers'),
    path('customers/create/', core_views.customer_create_view, name='customer_create'),
    path('customers/create-profile/', core_views.customer_profile_create_view, name='customer_profile_create'),
    path('customers/<int:pk>/', core_views.customer_detail_view, name='customer_detail'),
    path('customers/<int:pk>/edit/', core_views.customer_edit_view, name='customer_edit'),
    path('customers/<int:pk>/nominee/', core_views.customer_nominee_manage_view, name='customer_nominee_manage'),
    path('customers/<int:pk>/delete/', core_views.customer_delete_view, name='customer_delete'),
    
    # Properties
    path('properties/', core_views.properties_view, name='properties'),
    path('properties/project/create/', core_views.project_create_view, name='project_create'),
    path('properties/project/<int:pk>/edit/', core_views.project_edit_view, name='project_edit'),
    path('properties/project/<int:pk>/delete/', core_views.project_delete_view, name='project_delete'),
    path('properties/plot/create/', core_views.plot_create_view, name='plot_create'),
    path('properties/reserve/', core_views.reservation_create_view, name='reservation_create'),
    path('properties/plot/<int:pk>/edit/', core_views.plot_edit_view, name='plot_edit'),
        path('properties/plot/<int:pk>/', core_views.plot_detail_view, name='plot_detail'),
        path('properties/plot/<int:pk>/delete/', core_views.plot_delete_view, name='plot_delete'),
    
    # Bookings
    path('bookings/', core_views.bookings_view, name='bookings'),
    path('bookings/create/', core_views.booking_create_view, name='booking_create'),
    path('bookings/<int:pk>/', core_views.booking_detail_view, name='booking_detail'),
    path('bookings/<int:pk>/edit/', core_views.booking_edit_view, name='booking_edit'),
    path('bookings/<int:pk>/confirm/', core_views.booking_confirm_view, name='booking_confirm'),
    path('bookings/<int:pk>/delete/', core_views.booking_delete_view, name='booking_delete'),
    path('bookings/<int:pk>/cancel/', core_views.booking_cancel_view, name='booking_cancel'),
    path('bookings/<int:pk>/reopen/', core_views.booking_reopen_view, name='booking_reopen'),
    
    path('bookings/<int:pk>/transfer/', core_views.booking_transfer_view, name='booking_transfer'),

    # Payments
    path('payments/', core_views.payments_view, name='payments'),
    path('payments/create/', core_views.payment_create_view, name='payment_create'),
    path('payments/<int:pk>/', core_views.payment_detail_view, name='payment_detail'),
    
    # Receipts
    path('receipts/<int:pk>/', core_views.receipt_detail_view, name='receipt_detail'),
    path('receipts/<int:pk>/pdf/', core_views.receipt_pdf_view, name='receipt_pdf'),

    # PDF Downloads
    path('bookings/<int:pk>/invoice/', core_views.invoice_pdf_view, name='invoice_pdf'),
    path('customers/<int:pk>/pdf/', core_views.customer_profile_pdf_view, name='customer_profile_pdf'),

    # Users & Admin
    path('users/', core_views.users_view, name='users'),
    path('users/create/', core_views.user_create_view, name='user_create'),
    path('users/<int:pk>/edit/', core_views.user_edit_view, name='user_edit'),
    path('users/<int:pk>/role/', core_views.user_role_update_view, name='user_role_update'),
    path('users/<int:pk>/toggle-active/', core_views.user_deactivate_view, name='user_deactivate'),
    path('audit-logs/', core_views.audit_logs_view, name='audit_logs'),

    # Notifications
    path('', include('notifications.urls')),

    # Expenses
    path('expenses/', include('expenses.urls')),

    # HR & Payroll
    path('hr/', include('hr.urls')),

    # Finance
    path('finance/', include('finance.urls')),

    # Leads (CRM)
    path('leads/', views_crm.leads_view, name='leads'),
    path('leads/create/', views_crm.lead_create_view, name='lead_create'),
    path('leads/<int:pk>/', views_crm.lead_detail_view, name='lead_detail'),
    path('leads/<int:pk>/edit/', views_crm.lead_edit_view, name='lead_edit'),
    path('leads/<int:pk>/delete/', views_crm.lead_delete_view, name='lead_delete'),
    path('leads/<int:pk>/status/', views_crm.lead_status_update_view, name='lead_status_update'),
    path('leads/<int:pk>/note/', views_crm.lead_note_add_view, name='lead_note_add'),
    path('leads/<int:pk>/convert/', views_crm.lead_convert_view, name='lead_convert'),

    # Agents
    path('agents/', views_crm.agents_view, name='agents'),
    path('agents/create/', views_crm.agent_create_view, name='agent_create'),
    path('agents/<int:pk>/', views_crm.agent_detail_view, name='agent_detail'),
    path('agents/<int:pk>/edit/', views_crm.agent_edit_view, name='agent_edit'),
        path('agents/<int:pk>/commission-payment/', views_crm.agent_commission_payment_view, name='agent_commission_payment'),
        path('agents/<int:pk>/delete/', views_crm.agent_delete_view, name='agent_delete'),

    # Installment plans
    path('installment-plans/', views_installments.installment_plans_view, name='installment_plans'),
    path('installment-plans/<int:pk>/', views_installments.installment_plan_detail_view, name='installment_plan_detail'),
    path('installments/<int:pk>/mark-paid/', views_installments.installment_mark_paid_view, name='installment_mark_paid'),
    path('installments/<int:pk>/reschedule/', views_installments.installment_reschedule_view, name='installment_reschedule'),

    # Payment verification workflow
    path('payments/<int:pk>/verify/', views_workflow.payment_verify_view, name='payment_verify'),
    path('payments/<int:pk>/reject/', views_workflow.payment_reject_view, name='payment_reject'),
    path('payments/<int:pk>/bounce/', views_workflow.payment_bounce_view, name='payment_bounce'),
    path('payments/<int:pk>/reverse/', views_workflow.payment_reverse_view, name='payment_reverse'),

    # Refunds
    path('refunds/', views_workflow.refunds_view, name='refunds'),
    path('refunds/create/', views_workflow.refund_create_view, name='refund_create'),
    path('refunds/<int:pk>/approve/', views_workflow.refund_approve_view, name='refund_approve'),
    path('refunds/<int:pk>/process/', views_workflow.refund_process_view, name='refund_process'),

    # Reports & settings
    path('reports/receivables/', views_settings.receivables_aging_view, name='receivables_aging'),
    path('reports/sales/', views_settings.sales_report_view, name='sales_report'),
    path('settings/company/', views_settings.company_settings_view, name='company_settings'),
    path('projects/milestones/', views_settings.milestones_view, name='milestones'),
    path('projects/milestones/create/', views_settings.milestone_create_view, name='milestone_create'),
    path('projects/milestones/<int:pk>/edit/', views_settings.milestone_edit_view, name='milestone_edit'),
        path('projects/milestones/<int:pk>/', views_settings.milestone_detail_view, name='milestone_detail'),
        path('projects/milestones/<int:pk>/delete/', views_settings.milestone_delete_view, name='milestone_delete'),

    # Backup
    path('backup/', core_views.backup_view, name='backup'),
    path('backup/download/', core_views.backup_download_view, name='backup_download'),
    path('backup/restore/latest/', core_views.backup_restore_latest_view, name='backup_restore_latest'),
    path('backup/restore/upload/', core_views.backup_restore_upload_view, name='backup_restore_upload'),
    
    # Profile
    path('profile/', core_views.profile_view, name='profile'),
    path('api/save-theme/', core_views.save_theme_view, name='save_theme'),

    # Customer Portal (Django template)
    path('portal/', core_views.portal_view, name='portal'),

    # AI Assistant pages
    path('ai/', core_views.ai_assistant_page_view, name='ai_assistant_page'),
    path('ai/insights/', core_views.ai_insights_page_view, name='ai_insights_page'),
    path('ai/hr/', core_views.ai_hr_page_view, name='ai_hr_page'),

    # Corporate website (Django templates). Served last so it only matches the bare root path.
    path('', core_views.corporate_home_view, name='corporate_home'),
    path('lead/submit/', core_views.lead_submit_view, name='lead_submit'),
]

urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)