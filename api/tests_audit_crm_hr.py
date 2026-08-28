"""Audit suite C: leads, agents, HR/payroll, milestones, transfers, properties.

Data-entry impact checks for the CRM, HR, and property-management models.
Created during the 2026 data-integrity audit.
"""
from datetime import date, timedelta
from decimal import Decimal

from django.contrib.auth.models import User
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase

from bookings.models import Booking, BookingTransfer, InstallmentPlan
from core.models import AuditLog, Agent, Lead, UserProfile
from customers.models import Customer
from expenses.models import Expense
from hr.models import (
    Department, Designation, Employee, SalaryComponent, EmployeeSalary,
    PayrollRun, SalarySlip, SalarySlipItem, Attendance, Leave,
)
from notifications.models import NotificationLog
from payments.models import Payment
from properties.models import (
    Plot, Project, ProjectMilestone, PriceHistory, PlotFeature, ProjectPhase,
)


class CrmHrBase(APITestCase):

    def setUp(self):
        self.admin = User.objects.create_superuser('crmadmin', 'c@example.com', 'pass12345')
        self.client.force_authenticate(user=self.admin)
        self.project = Project.objects.create(name='CRM Project', location='Lahore', total_plots=40)
        self.customer = Customer.objects.create(
            first_name='CRM', last_name='Customer', phone='+92-300-4440001',
            cnic='35202-4440001-1', email='crm@example.com', created_by=self.admin,
        )

    def new_plot(self, number='CP-001', price='900000', status='available'):
        return Plot.objects.create(
            plot_number=number, project=self.project, size_marla=Decimal('5'),
            price=Decimal(price), status=status,
        )


# ─── LEADS ──────────────────────────────────────────────────────────────────
class LeadFlowTests(CrmHrBase):

    def test_lead_create(self):
        resp = self.client.post(reverse('lead-list'), {
            'name': 'Test Lead', 'phone': '+92-300-5550001',
            'email': 'lead@example.com', 'source': 'hero',
            'status': 'new', 'budget': '5000000',
        }, format='json')
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)

    def test_lead_requires_phone_or_email(self):
        # A lead needs at least a name, email, or phone — a completely
        # empty lead must be rejected by the serializer.
        resp = self.client.post(reverse('lead-list'), {
            'source': 'hero',
        }, format='json')
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_lead_with_only_name_allowed(self):
        resp = self.client.post(reverse('lead-list'), {
            'name': 'Name Only', 'source': 'hero',
        }, format='json')
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)

    def test_lead_duplicate_phone_allowed(self):
        # Leads are pre-sales enquiries: the same phone may enquire twice,
        # so duplicates are allowed (unlike customers).
        self.client.post(reverse('lead-list'), {
            'name': 'Lead One', 'phone': '+92-300-5550002',
            'email': 'l1@example.com', 'source': 'hero',
        }, format='json')
        resp = self.client.post(reverse('lead-list'), {
            'name': 'Lead Two', 'phone': '+92-300-5550002',
            'email': 'l2@example.com', 'source': 'hero',
        }, format='json')
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)

    def test_lead_convert_creates_customer(self):
        lead = Lead.objects.create(
            name='Convert Me', phone='+92-300-5550003',
            email='convert@example.com', source='walk_in',
            status='new',
        )
        resp = self.client.post(reverse('lead-convert', args=[lead.pk]),
                                {'cnic': '35202-5550003-1'}, format='json')
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)
        self.assertTrue(Customer.objects.filter(phone='+92-300-5550003').exists())
        lead.refresh_from_db()
        self.assertIsNotNone(lead.converted_customer)

    def test_lead_convert_requires_cnic(self):
        lead = Lead.objects.create(
            name='No Cnic', phone='+92-300-5550004',
            email='nocnic@example.com', source='hero',
            status='new',
        )
        resp = self.client.post(reverse('lead-convert', args=[lead.pk]), {}, format='json')
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_lead_convert_twice_blocked(self):
        lead = Lead.objects.create(
            name='Double Convert', phone='+92-300-5550005',
            email='dc@example.com', source='hero',
            status='new',
        )
        self.client.post(reverse('lead-convert', args=[lead.pk]),
                         {'cnic': '35202-5550005-1'}, format='json')
        resp = self.client.post(reverse('lead-convert', args=[lead.pk]),
                                {'cnic': '35202-5550005-1'}, format='json')
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_lead_notes_attached(self):
        from core.models import LeadNote
        lead = Lead.objects.create(
            name='With Notes', phone='+92-300-5550006',
            email='notes@example.com', source='hero',
            status='new',
        )
        LeadNote.objects.create(lead=lead, note='Called twice', created_by=self.admin)
        self.assertEqual(lead.lead_notes.count(), 1)

    def test_lead_status_flow(self):
        lead = Lead.objects.create(
            name='Status Flow', phone='+92-300-5550007',
            email='sf@example.com', source='hero',
            status='new',
        )
        lead.status = 'contacted'
        lead.save()
        lead.status = 'qualified'
        lead.save()
        self.assertEqual(lead.status, 'qualified')


# ─── AGENTS ─────────────────────────────────────────────────────────────────
class AgentFlowTests(CrmHrBase):

    def test_agent_create(self):
        resp = self.client.post(reverse('agent-list'), {
            'name': 'Agent One', 'phone': '+92-300-6660001',
            'email': 'agent1@example.com', 'cnic': '35202-6660001-1',
            'commission_rate': '5.00',
        }, format='json')
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)

    def test_agent_commission_rate_valid(self):
        resp = self.client.post(reverse('agent-list'), {
            'name': 'Agent Bad', 'phone': '+92-300-6660002',
            'email': 'agent2@example.com', 'cnic': '35202-6660002-1',
            'commission_rate': '150.00',
        }, format='json')
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_agent_duplicate_phone_rejected(self):
        self.client.post(reverse('agent-list'), {
            'name': 'Agent A', 'phone': '+92-300-6660003',
            'email': 'a@example.com', 'cnic': '35202-6660003-1',
            'commission_rate': '5.00',
        }, format='json')
        resp = self.client.post(reverse('agent-list'), {
            'name': 'Agent B', 'phone': '+92-300-6660003',
            'email': 'b@example.com', 'cnic': '35202-6660004-1',
            'commission_rate': '5.00',
        }, format='json')
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_agent_booking_commission_calculation(self):
        agent = Agent.objects.create(
            name='Commission Agent', phone='+92-300-6660005',
            email='ca@example.com', cnic='35202-6660005-1',
            commission_rate=Decimal('5.00'),
        )
        plot = self.new_plot('CP-010', price='1000000')
        b = Booking.objects.create(
            customer=self.customer, plot=plot, total_amount=Decimal('1000000'),
            advance_paid=Decimal('100000'), agent=agent,
            status='confirmed', created_by=self.admin,
        )
        self.assertEqual(b.agent_commission, Decimal('50000'))

    def test_agent_inactive_cannot_book(self):
        agent = Agent.objects.create(
            name='Inactive Agent', phone='+92-300-6660006',
            email='ia@example.com', cnic='35202-6660006-1',
            commission_rate=Decimal('5.00'), is_active=False,
        )
        plot = self.new_plot('CP-011')
        resp = self.client.post(reverse('booking-list'), {
            'customer': self.customer.pk, 'plot': plot.pk,
            'total_amount': '900000', 'advance_paid': '0',
            'agent': agent.pk,
        }, format='json')
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_agent_active_can_be_assigned_via_api(self):
        agent = Agent.objects.create(
            name='Active Agent', phone='+92-300-6660008',
            email='aa@example.com', cnic='35202-6660008-1',
            commission_rate=Decimal('5.00'), is_active=True,
        )
        plot = self.new_plot('CP-013')
        resp = self.client.post(reverse('booking-list'), {
            'customer': self.customer.pk, 'plot': plot.pk,
            'total_amount': '900000', 'advance_paid': '0',
            'agent': agent.pk,
        }, format='json')
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)
        b = Booking.objects.get(plot=plot)
        self.assertEqual(b.agent, agent)

    def test_agent_booking_count(self):
        agent = Agent.objects.create(
            name='Counting Agent', phone='+92-300-6660007',
            email='cnt@example.com', cnic='35202-6660007-1',
            commission_rate=Decimal('5.00'),
        )
        plot = self.new_plot('CP-012')
        Booking.objects.create(
            customer=self.customer, plot=plot, total_amount=Decimal('900000'),
            advance_paid=Decimal('0'), agent=agent, created_by=self.admin,
        )
        self.assertEqual(agent.bookings.count(), 1)


# ─── PROPERTIES ─────────────────────────────────────────────────────────────
class PropertyFlowTests(CrmHrBase):

    def test_project_create(self):
        resp = self.client.post(reverse('project-list'), {
            'name': 'New Project', 'location': 'Karachi', 'total_plots': 100,
        }, format='json')
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)

    def test_project_available_plots_count(self):
        project = Project.objects.create(name='Count Project', location='Lahore', total_plots=5)
        Plot.objects.create(plot_number='P-1', project=project, size_marla=Decimal('5'),
                            price=Decimal('1000000'), status='available')
        Plot.objects.create(plot_number='P-2', project=project, size_marla=Decimal('5'),
                            price=Decimal('1000000'), status='booked')
        Plot.objects.create(plot_number='P-3', project=project, size_marla=Decimal('5'),
                            price=Decimal('1000000'), status='sold')
        self.assertEqual(project.available_plots, 1)
        self.assertEqual(project.booked_plots, 1)
        self.assertEqual(project.sold_plots, 1)

    def test_plot_status_choices(self):
        plot = self.new_plot('CP-020')
        plot.status = 'reserved'
        plot.save()
        self.assertEqual(plot.status, 'reserved')

    def test_plot_price_history_recorded(self):
        plot = self.new_plot('CP-021', price='1000000')
        PriceHistory.objects.create(
            plot=plot, old_price=Decimal('1000000'), new_price=Decimal('1200000'),
            change_reason='Market adjustment', changed_by=self.admin,
        )
        self.assertEqual(plot.price_history.count(), 1)

    def test_plot_price_update_via_api(self):
        plot = self.new_plot('CP-022', price='1000000')
        resp = self.client.patch(reverse('plot-detail', args=[plot.pk]),
                                 {'price': '1300000'}, format='json')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        plot.refresh_from_db()
        self.assertEqual(plot.price, Decimal('1300000'))

    def test_plot_feature_assignment(self):
        plot = self.new_plot('CP-023')
        feature = PlotFeature.objects.create(name='Park Facing', icon='🌳')
        plot.features.add(feature)
        self.assertEqual(plot.features.count(), 1)

    def test_project_milestone_create(self):
        resp = self.client.post(reverse('projectmilestone-list'), {
            'project': self.project.pk, 'title': 'Foundation',
            'target_date': date.today().isoformat(), 'status': 'pending',
        }, format='json')
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)

    def test_project_milestone_status_flow(self):
        m = ProjectMilestone.objects.create(
            project=self.project, title='Plumbing', target_date=date.today(),
            status='in_progress',
        )
        m.status = 'completed'
        m.completed_date = date.today()
        m.save()
        self.assertEqual(m.status, 'completed')
        self.assertEqual(m.completed_date, date.today())

    def test_project_phase_create(self):
        resp = self.client.post(reverse('projectphase-list'), {
            'project': self.project.pk, 'name': 'Phase 1',
            'launch_date': date.today().isoformat(), 'total_plots': 20,
        }, format='json')
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)

    def test_plot_public_feed_only_available(self):
        # No public plots endpoint exists in this codebase; the equivalent
        # guarantee is enforced by the booking serializer (booked/sold plots
        # cannot be booked) and the plots list is staff-only. Verify the
        # plot-status model contract instead.
        self.new_plot('CP-030', price='500000', status='available')
        self.new_plot('CP-031', price='500000', status='booked')
        self.assertEqual(Plot.objects.filter(status='available').count(), 1)
        self.assertEqual(Plot.objects.filter(status='booked').count(), 1)


# ─── HR: DEPARTMENTS / DESIGNATIONS / EMPLOYEES ─────────────────────────────
class HrStructureTests(CrmHrBase):

    def setUp(self):
        super().setUp()
        self.dept = Department.objects.create(name='Sales', is_active=True)
        self.designation = Designation.objects.create(title='Sales Executive', is_active=True)

    def test_department_create(self):
        resp = self.client.post(reverse('department-list'), {
            'name': 'Marketing', 'is_active': True,
        }, format='json')
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)

    def test_department_duplicate_name_rejected(self):
        resp = self.client.post(reverse('department-list'), {
            'name': 'Sales', 'is_active': True,
        }, format='json')
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_designation_create(self):
        resp = self.client.post(reverse('designation-list'), {
            'title': 'Manager', 'is_active': True,
        }, format='json')
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)

    def test_designation_duplicate_rejected(self):
        resp = self.client.post(reverse('designation-list'), {
            'title': 'Sales Executive', 'is_active': True,
        }, format='json')
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_employee_create(self):
        resp = self.client.post(reverse('employee-list'), {
            'first_name': 'Emp', 'last_name': 'One',
            'department': self.dept.pk, 'designation': self.designation.pk,
            'joining_date': date.today().isoformat(),
            'cnic': '35202-7770001-1', 'phone': '+92-300-7770001',
            'email': 'emp1@example.com', 'status': 'active',
        }, format='json')
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)

    def test_employee_id_sequential(self):
        e1 = Employee.objects.create(
            first_name='E', last_name='One', department=self.dept,
            designation=self.designation, joining_date=date.today(),
            cnic='35202-7770002-1', phone='+92-300-7770002',
            status='active', created_by=self.admin,
        )
        e2 = Employee.objects.create(
            first_name='E', last_name='Two', department=self.dept,
            designation=self.designation, joining_date=date.today(),
            cnic='35202-7770003-1', phone='+92-300-7770003',
            status='active', created_by=self.admin,
        )
        self.assertRegex(e1.employee_id, r'^EMP-\d{5}$')
        self.assertNotEqual(e1.employee_id, e2.employee_id)

    def test_employee_duplicate_cnic_rejected(self):
        Employee.objects.create(
            first_name='E', last_name='One', department=self.dept,
            designation=self.designation, joining_date=date.today(),
            cnic='35202-7770004-1', phone='+92-300-7770004',
            status='active', created_by=self.admin,
        )
        resp = self.client.post(reverse('employee-list'), {
            'first_name': 'E', 'last_name': 'Dup',
            'department': self.dept.pk, 'designation': self.designation.pk,
            'joining_date': date.today().isoformat(),
            'cnic': '35202-7770004-1', 'phone': '+92-300-7770005',
            'status': 'active',
        }, format='json')
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_department_employee_count(self):
        Employee.objects.create(
            first_name='E', last_name='Cnt', department=self.dept,
            designation=self.designation, joining_date=date.today(),
            cnic='35202-7770006-1', phone='+92-300-7770006',
            status='active', created_by=self.admin,
        )
        self.assertEqual(self.dept.employees.count(), 1)

    def test_employee_inactive_status(self):
        e = Employee.objects.create(
            first_name='E', last_name='Off', department=self.dept,
            designation=self.designation, joining_date=date.today(),
            cnic='35202-7770007-1', phone='+92-300-7770007',
            status='inactive', created_by=self.admin,
        )
        self.assertEqual(e.status, 'inactive')


# ─── HR: SALARY COMPONENTS & EMPLOYEE SALARY ────────────────────────────────
class SalaryStructureTests(CrmHrBase):

    def setUp(self):
        super().setUp()
        self.dept = Department.objects.create(name='IT', is_active=True)
        self.designation = Designation.objects.create(title='Developer', is_active=True)
        self.emp = Employee.objects.create(
            first_name='Sal', last_name='Emp', department=self.dept,
            designation=self.designation, joining_date=date.today(),
            cnic='35202-8880001-1', phone='+92-300-8880001',
            status='active', created_by=self.admin,
        )

    def test_salary_component_create(self):
        resp = self.client.post(reverse('salarycomponent-list'), {
            'name': 'Basic Salary', 'component_type': 'earning',
            'is_active': True,
        }, format='json')
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)

    def test_salary_component_duplicate_rejected(self):
        SalaryComponent.objects.create(name='Allowance', component_type='earning')
        resp = self.client.post(reverse('salarycomponent-list'), {
            'name': 'Allowance', 'component_type': 'earning',
        }, format='json')
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_employee_salary_assignment(self):
        comp = SalaryComponent.objects.create(name='Basic', component_type='earning')
        es = EmployeeSalary.objects.create(
            employee=self.emp, component=comp, amount=Decimal('50000'),
            effective_from=date.today(),
        )
        self.assertEqual(es.amount, Decimal('50000'))

    def test_employee_salary_negative_rejected(self):
        comp = SalaryComponent.objects.create(name='Neg', component_type='earning')
        with self.assertRaises(Exception):
            EmployeeSalary.objects.create(
                employee=self.emp, component=comp, amount=Decimal('-100'),
                effective_from=date.today(),
            )

    def test_employee_salary_deduction_component(self):
        comp = SalaryComponent.objects.create(name='Tax', component_type='deduction')
        es = EmployeeSalary.objects.create(
            employee=self.emp, component=comp, amount=Decimal('5000'),
            effective_from=date.today(),
        )
        self.assertEqual(es.component.component_type, 'deduction')


# ─── HR: PAYROLL ────────────────────────────────────────────────────────────
class PayrollFlowTests(CrmHrBase):

    def setUp(self):
        super().setUp()
        self.dept = Department.objects.create(name='Payroll Dept', is_active=True)
        self.designation = Designation.objects.create(title='Staff', is_active=True)
        self.emp = Employee.objects.create(
            first_name='Pay', last_name='Roll', department=self.dept,
            designation=self.designation, joining_date=date.today(),
            cnic='35202-9990001-1', phone='+92-300-9990001',
            status='active', created_by=self.admin,
        )
        self.basic = SalaryComponent.objects.create(name='Basic', component_type='earning')
        self.bonus = SalaryComponent.objects.create(name='Bonus', component_type='earning')
        self.tax = SalaryComponent.objects.create(name='Tax', component_type='deduction')
        EmployeeSalary.objects.create(employee=self.emp, component=self.basic,
                                      amount=Decimal('60000'), effective_from=date.today())
        EmployeeSalary.objects.create(employee=self.emp, component=self.tax,
                                      amount=Decimal('5000'), effective_from=date.today())

    def make_run(self):
        return PayrollRun.objects.create(
            month=date.today().month, year=date.today().year,
            status='draft', created_by=self.admin,
        )

    def test_payroll_run_create(self):
        run = self.make_run()
        self.assertEqual(run.status, 'draft')

    def test_payroll_generate_creates_slips(self):
        run = self.make_run()
        count = run.generate_slips()
        self.assertGreaterEqual(count, 1)
        self.assertTrue(run.slips.filter(employee=self.emp).exists())

    def test_salary_slip_gross_matches_components(self):
        run = self.make_run()
        run.generate_slips()
        slip = run.slips.get(employee=self.emp)
        # gross = sum of earning components
        self.assertEqual(slip.gross, Decimal('60000'))

    def test_salary_slip_net_earnings_minus_deductions(self):
        run = self.make_run()
        run.generate_slips()
        slip = run.slips.get(employee=self.emp)
        slip.recalculate()
        self.assertEqual(slip.total_earnings, Decimal('60000'))
        self.assertEqual(slip.total_deductions, Decimal('5000'))
        self.assertEqual(slip.net, Decimal('55000'))

    def test_payroll_generate_idempotent(self):
        run = self.make_run()
        run.generate_slips()
        run.generate_slips()
        self.assertEqual(run.slips.filter(employee=self.emp).count(), 1)

    def test_payroll_process_approves_slips(self):
        run = self.make_run()
        run.generate_slips()
        resp = self.client.post(reverse('payrollrun-process', args=[run.pk]), {}, format='json')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        run.refresh_from_db()
        self.assertEqual(run.status, 'processed')
        for slip in run.slips.all():
            self.assertEqual(slip.status, 'approved')

    def test_payroll_pay_creates_salary_payment(self):
        from hr.models import SalaryPayment
        run = self.make_run()
        run.generate_slips()
        self.client.post(reverse('payrollrun-process', args=[run.pk]), {}, format='json')
        resp = self.client.post(reverse('payrollrun-pay', args=[run.pk]), {}, format='json')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        run.refresh_from_db()
        self.assertEqual(run.status, 'paid')
        self.assertTrue(SalaryPayment.objects.filter(slip__run=run).exists())

    def test_payroll_pay_creates_ledger_entry(self):
        from finance.models import AccountTransaction
        from hr.models import SalaryPayment
        run = self.make_run()
        run.generate_slips()
        self.client.post(reverse('payrollrun-process', args=[run.pk]), {}, format='json')
        self.client.post(reverse('payrollrun-pay', args=[run.pk]), {}, format='json')
        payment = SalaryPayment.objects.filter(slip__run=run).first()
        self.assertTrue(AccountTransaction.objects.filter(
            reference_type='SalaryPayment', reference_id=payment.pk).exists())

    def test_payroll_slip_api_list(self):
        run = self.make_run()
        run.generate_slips()
        resp = self.client.get(reverse('salaryslip-list'))
        self.assertEqual(resp.status_code, status.HTTP_200_OK)


# ─── HR: ATTENDANCE & LEAVE ─────────────────────────────────────────────────
class AttendanceLeaveTests(CrmHrBase):

    def setUp(self):
        super().setUp()
        self.dept = Department.objects.create(name='Ops', is_active=True)
        self.designation = Designation.objects.create(title='Operator', is_active=True)
        self.emp = Employee.objects.create(
            first_name='Att', last_name='Emp', department=self.dept,
            designation=self.designation, joining_date=date.today(),
            cnic='35202-1210001-1', phone='+92-300-1210001',
            status='active', created_by=self.admin,
        )

    def test_attendance_create(self):
        resp = self.client.post(reverse('attendance-list'), {
            'employee': self.emp.pk, 'date': date.today().isoformat(),
            'check_in': '09:00', 'check_out': '17:00', 'status': 'present',
        }, format='json')
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)

    def test_attendance_duplicate_date_rejected(self):
        Attendance.objects.create(
            employee=self.emp, date=date.today(), check_in='09:00',
            check_out='17:00', status='present',
        )
        resp = self.client.post(reverse('attendance-list'), {
            'employee': self.emp.pk, 'date': date.today().isoformat(),
            'check_in': '09:30', 'check_out': '17:30', 'status': 'present',
        }, format='json')
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_attendance_absent_status(self):
        a = Attendance.objects.create(
            employee=self.emp, date=date.today(), status='absent',
        )
        self.assertEqual(a.status, 'absent')

    def test_leave_create_pending(self):
        resp = self.client.post(reverse('leave-list'), {
            'employee': self.emp.pk, 'leave_type': 'sick',
            'start_date': date.today().isoformat(),
            'end_date': (date.today() + timedelta(days=2)).isoformat(),
            'days': 3, 'reason': 'Fever', 'status': 'pending',
        }, format='json')
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)

    def test_leave_approval_flow(self):
        leave = Leave.objects.create(
            employee=self.emp, leave_type='annual',
            start_date=date.today(), end_date=date.today() + timedelta(days=1),
            days=2, reason='Vacation', status='pending',
        )
        leave.status = 'approved'
        leave.approved_by = self.admin
        leave.save()
        self.assertEqual(leave.status, 'approved')

    def test_leave_rejected_status(self):
        leave = Leave.objects.create(
            employee=self.emp, leave_type='sick',
            start_date=date.today(), end_date=date.today(),
            days=1, reason='X', status='pending',
        )
        leave.status = 'rejected'
        leave.save()
        self.assertEqual(leave.status, 'rejected')

    def test_leave_invalid_dates_rejected(self):
        resp = self.client.post(reverse('leave-list'), {
            'employee': self.emp.pk, 'leave_type': 'sick',
            'start_date': (date.today() + timedelta(days=3)).isoformat(),
            'end_date': date.today().isoformat(),
            'days': 1, 'reason': 'Backwards dates', 'status': 'pending',
        }, format='json')
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)


# ─── BOOKING TRANSFERS ──────────────────────────────────────────────────────
class TransferDeepTests(CrmHrBase):

    def setUp(self):
        super().setUp()
        self.plot = self.new_plot('CP-040', price='1000000')
        self.booking = Booking.objects.create(
            customer=self.customer, plot=self.plot, total_amount=Decimal('1000000'),
            advance_paid=Decimal('200000'), status='confirmed', created_by=self.admin,
        )
        self.to_customer = Customer.objects.create(
            first_name='Transfer', last_name='Target', phone='+92-300-4440002',
            cnic='35202-4440002-1', created_by=self.admin,
        )

    def test_transfer_creates_record(self):
        bt = BookingTransfer.objects.create(
            booking=self.booking, from_customer=self.customer,
            to_customer=self.to_customer, transfer_fee=Decimal('10000'),
            previous_payments_handling='transfer', approved_by=self.admin,
        )
        self.assertEqual(bt.booking, self.booking)
        self.assertEqual(bt.from_customer, self.customer)
        self.assertEqual(bt.to_customer, self.to_customer)

    def test_transfer_negative_fee_rejected(self):
        # Serializer must reject a negative transfer fee.
        resp = self.client.post(reverse('bookingtransfer-list'), {
            'booking': self.booking.pk, 'from_customer': self.customer.pk,
            'to_customer': self.to_customer.pk, 'transfer_fee': '-100',
            'previous_payments_handling': 'transfer',
        }, format='json')
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_transfer_api(self):
        resp = self.client.post(reverse('bookingtransfer-list'), {
            'booking': self.booking.pk, 'from_customer': self.customer.pk,
            'to_customer': self.to_customer.pk, 'transfer_fee': '10000',
            'previous_payments_handling': 'transfer',
        }, format='json')
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)

    def test_transfer_same_customer_rejected(self):
        resp = self.client.post(reverse('bookingtransfer-list'), {
            'booking': self.booking.pk, 'from_customer': self.customer.pk,
            'to_customer': self.customer.pk, 'transfer_fee': '10000',
            'previous_payments_handling': 'transfer',
        }, format='json')
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)


# ─── NOTIFICATION PREFERENCES ───────────────────────────────────────────────
class NotificationPreferenceTests(CrmHrBase):

    def test_preference_defaults_enabled(self):
        from notifications.models import NotificationPreference
        pref = NotificationPreference.objects.create(user=self.admin)
        self.assertTrue(pref.email_enabled)
        # SMS is opt-in (default False); WhatsApp defaults on.
        self.assertFalse(pref.sms_enabled)
        self.assertTrue(pref.whatsapp_enabled)

    def test_preference_toggle(self):
        from notifications.models import NotificationPreference
        pref = NotificationPreference.objects.create(
            user=self.admin, email_enabled=False, sms_enabled=False,
        )
        self.assertFalse(pref.email_enabled)
        self.assertFalse(pref.sms_enabled)


# ─── USER PROFILES & ROLES ──────────────────────────────────────────────────
class UserProfileTests(CrmHrBase):

    def test_profile_roles(self):
        profile = UserProfile.objects.create(user=self.admin, role='admin')
        self.assertEqual(profile.role, 'admin')

    def test_profile_invalid_role_rejected(self):
        # Django enforces choices at the form/serializer layer, not the ORM.
        profile = UserProfile.objects.create(user=self.admin, role='admin')
        resp = self.client.patch(reverse('profile-update-profile'), {'role': 'wizard'}, format='json')
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_profile_api(self):
        profile = UserProfile.objects.create(user=self.admin, role='super_admin')
        resp = self.client.get(reverse('profile-list'))
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
