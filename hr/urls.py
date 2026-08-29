from django.urls import path
from . import views

urlpatterns = [
    # Home
    path('', views.hr_home_view, name='hr_home'),

    # Departments
    path('departments/', views.departments_view, name='hr_departments'),
    path('departments/create/', views.department_create_view, name='hr_department_create'),
    path('departments/<int:pk>/edit/', views.department_edit_view, name='hr_department_edit'),
    path('departments/<int:pk>/delete/', views.department_delete_view, name='hr_department_delete'),

    # Designations
    path('designations/', views.designations_view, name='hr_designations'),
    path('designations/create/', views.designation_create_view, name='hr_designation_create'),
    path('designations/<int:pk>/edit/', views.designation_edit_view, name='hr_designation_edit'),
    path('designations/<int:pk>/delete/', views.designation_delete_view, name='hr_designation_delete'),

    # Salary components
    path('salary-components/', views.salary_components_view, name='hr_salary_components'),
    path('salary-components/create/', views.salary_component_create_view, name='hr_salary_component_create'),
    path('salary-components/<int:pk>/edit/', views.salary_component_edit_view, name='hr_salary_component_edit'),
    path('salary-components/<int:pk>/delete/', views.salary_component_delete_view, name='hr_salary_component_delete'),

    # Employees
    path('employees/', views.employees_view, name='hr_employees'),
    path('employees/create/', views.employee_create_view, name='hr_employee_create'),
    path('employees/<int:pk>/', views.employee_detail_view, name='hr_employee_detail'),
    path('employees/<int:pk>/edit/', views.employee_edit_view, name='hr_employee_edit'),
    path('employees/<int:pk>/delete/', views.employee_delete_view, name='hr_employee_delete'),
    path('employees/<int:pk>/salary/add/', views.employee_salary_add_view, name='hr_employee_salary_add'),
    path('salary/<int:pk>/delete/', views.employee_salary_delete_view, name='hr_employee_salary_delete'),
    path('employee-profile/', views.employee_profile_create_view, name='hr_employee_profile_create'),

    # Payroll runs
    path('payroll/', views.payroll_runs_view, name='hr_payroll_runs'),
    path('payroll/create/', views.payroll_run_create_view, name='hr_payroll_run_create'),
    path('payroll/<int:pk>/', views.payroll_run_detail_view, name='hr_payroll_run_detail'),
    path('payroll/<int:pk>/generate/', views.payroll_run_generate_view, name='hr_payroll_run_generate'),
    path('payroll/<int:pk>/process/', views.payroll_run_process_view, name='hr_payroll_run_process'),
    path('payroll/<int:pk>/pay/', views.payroll_run_pay_view, name='hr_payroll_run_pay'),
    path('payroll-report/', views.payroll_report_view, name='hr_payroll_report'),

    # Salary slips
    path('slips/<int:pk>/', views.salary_slip_detail_view, name='hr_salary_slip_detail'),
    path('slips/<int:pk>/add-item/', views.salary_slip_add_item_view, name='hr_salary_slip_add_item'),
    path('slip-items/<int:pk>/remove/', views.salary_slip_remove_item_view, name='hr_salary_slip_remove_item'),

    # Attendance
    path('attendance/', views.attendance_view, name='hr_attendance'),
    path('attendance/create/', views.attendance_create_view, name='hr_attendance_create'),

    # Leave
    path('leaves/', views.leaves_view, name='hr_leaves'),
    path('leaves/create/', views.leave_create_view, name='hr_leave_create'),
    path('leaves/<int:pk>/approve/', views.leave_approve_view, name='hr_leave_approve'),

    # Employee self-service
    path('my-leave/', views.my_leave_view, name='hr_my_leave'),
    path('my-leave/apply/', views.my_leave_apply_view, name='hr_leave_apply'),
]
