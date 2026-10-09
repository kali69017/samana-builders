"""Tests for the project-cost → ledger path (FIN-PC-01) and the FIN-EC-03
ledger/source reconciliation warning.

FIN-PC-01: ``ProjectCost.status`` defaulted to ``'pending'``, which was not a
member of ``STATUS_CHOICES``, and the project-cost screen had no action column
and the API had no ``pay`` action. ``post_to_ledger`` returns ``None`` unless
``status == 'paid'``, so a project cost could never reach the ledger from any
user-facing entry point.
"""
from datetime import date
from decimal import Decimal

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from core.models import UserProfile
from properties.models import Project

from .models import Office, OfficeExpense, ProjectCost, Voucher


class ProjectCostLedgerPathTest(TestCase):
    """FIN-PC-01: a project cost must be able to reach the ledger."""

    def setUp(self):
        self.finance = User.objects.create_user('pcfin', 'pcf@example.com', 'pass12345')
        UserProfile.objects.create(user=self.finance, role='accounts')
        self.supervisor = User.objects.create_user('pcsup', 'pcs@example.com', 'pass12345')
        UserProfile.objects.create(user=self.supervisor, role='management')
        self.project = Project.objects.create(name='PC Project', location='Lahore')

    def _cost(self, status='pending', amount=Decimal('33000.00')):
        return ProjectCost.objects.create(
            project=self.project, cost_category='material', amount=amount,
            cost_date=date(2026, 7, 20), payment_method='bank_transfer',
            status=status, created_by=self.finance, vendor='Steel Co',
        )

    # ── the invalid model default ────────────────────────────────────────
    def test_status_default_is_a_valid_choice(self):
        """The default must render a label, not the raw string 'pending'."""
        cost = ProjectCost.objects.create(
            project=self.project, amount=Decimal('100.00'), cost_date=date.today(),
        )
        valid = {c[0] for c in ProjectCost.STATUS_CHOICES}
        self.assertIn(cost.status, valid)
        self.assertNotEqual(cost.get_status_display(), cost.status)

    def test_created_cost_is_pending_and_unposted(self):
        cost = self._cost()
        self.assertEqual(cost.status, 'pending')
        self.assertIsNone(cost.post_to_ledger())
        self.assertFalse(Voucher.objects.filter(
            reference_type='ProjectCost', reference_id=cost.pk).exists())

    # ── the web pay transition ───────────────────────────────────────────
    def test_pay_view_posts_voucher_once(self):
        cost = self._cost()
        self.client.force_login(self.supervisor)
        resp = self.client.post(reverse('finance_project_cost_pay', args=[cost.pk]))
        self.assertEqual(resp.status_code, 302)
        cost.refresh_from_db()
        self.assertEqual(cost.status, 'paid')
        voucher = Voucher.objects.get(reference_type='ProjectCost', reference_id=cost.pk)
        self.assertEqual(voucher.status, 'posted')
        self.assertEqual(voucher.total_debit, Decimal('33000.00'))
        self.assertEqual(voucher.total_debit, voucher.total_credit)
        self.assertTrue(voucher.is_balanced)

    def test_pay_view_is_idempotent(self):
        cost = self._cost()
        url = reverse('finance_project_cost_pay', args=[cost.pk])
        self.client.force_login(self.supervisor)
        self.client.post(url)
        self.client.post(url)
        self.assertEqual(Voucher.objects.filter(
            reference_type='ProjectCost', reference_id=cost.pk).count(), 1)

    def test_approve_view_sets_approved_without_posting(self):
        cost = self._cost()
        self.client.force_login(self.supervisor)
        self.client.post(reverse('finance_project_cost_approve', args=[cost.pk]))
        cost.refresh_from_db()
        self.assertEqual(cost.status, 'approved')
        self.assertFalse(Voucher.objects.filter(
            reference_type='ProjectCost', reference_id=cost.pk).exists())

    def test_finance_role_cannot_pay_or_approve(self):
        cost = self._cost()
        self.client.force_login(self.finance)
        self.client.post(reverse('finance_project_cost_pay', args=[cost.pk]))
        cost.refresh_from_db()
        self.assertEqual(cost.status, 'pending')

    # ── the UI actually offers the actions ───────────────────────────────
    def test_list_shows_actions_for_pending_cost(self):
        self._cost()
        self.client.force_login(self.supervisor)
        resp = self.client.get(reverse('finance_project_costs'))
        self.assertContains(resp, reverse('finance_project_cost_approve', args=[1]))
        self.assertContains(resp, reverse('finance_project_cost_pay', args=[1]))

    def test_list_hides_pay_once_paid(self):
        cost = self._cost(status='paid')
        self.client.force_login(self.supervisor)
        resp = self.client.get(reverse('finance_project_costs'))
        self.assertNotContains(resp, reverse('finance_project_cost_pay', args=[cost.pk]))

    def test_edit_link_is_reachable_from_the_list(self):
        cost = self._cost()
        self.client.force_login(self.finance)
        resp = self.client.get(reverse('finance_project_costs'))
        self.assertContains(resp, reverse('finance_project_cost_edit', args=[cost.pk]))
        self.assertEqual(
            self.client.get(reverse('finance_project_cost_edit', args=[cost.pk])).status_code,
            200)

    # ── the REST path ────────────────────────────────────────────────────
    def test_api_pay_posts_voucher(self):
        cost = self._cost()
        self.client.force_login(self.finance)
        resp = self.client.post(f'/api/project-costs/{cost.pk}/pay/')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(Voucher.objects.filter(
            reference_type='ProjectCost', reference_id=cost.pk).count(), 1)

    def test_api_pay_is_idempotent(self):
        cost = self._cost()
        self.client.force_login(self.finance)
        self.client.post(f'/api/project-costs/{cost.pk}/pay/')
        self.client.post(f'/api/project-costs/{cost.pk}/pay/')
        self.assertEqual(Voucher.objects.filter(
            reference_type='ProjectCost', reference_id=cost.pk).count(), 1)

    def test_api_approve_on_paid_cost_conflicts(self):
        cost = self._cost(status='paid')
        self.client.force_login(self.finance)
        resp = self.client.post(f'/api/project-costs/{cost.pk}/approve/')
        # 400 is the house convention for an illegal transition, matching the
        # sibling draft->paid guard (tests/finance/finance.spec.ts FIN-SEC-03).
        self.assertEqual(resp.status_code, 400)
        cost.refresh_from_db()
        self.assertEqual(cost.status, 'paid')


class LedgerReconciliationTest(TestCase):
    """FIN-EC-03: editing a paid source does not rewrite the immutable voucher,
    so the divergence must be surfaced rather than hidden."""

    def setUp(self):
        self.user = User.objects.create_superuser('recon', 'r@example.com', 'pass12345')
        self.office = Office.objects.create(name='HO', office_type='head_office')
        self.project = Project.objects.create(name='RP', location='Lahore')

    def _paid_expense(self, amount=Decimal('15000.25')):
        exp = OfficeExpense.objects.create(
            office=self.office, amount=amount, status='paid',
            expense_date=date(2026, 6, 15), payment_method='bank_transfer',
            created_by=self.user,
        )
        exp.post_to_ledger()
        return exp

    def test_in_sync_expense_is_not_flagged(self):
        exp = self._paid_expense()
        self.assertFalse(exp.ledger_out_of_sync)
        self.assertIsNotNone(exp.posted_voucher)

    def test_amount_edit_flags_out_of_sync(self):
        exp = self._paid_expense()
        exp.amount = Decimal('99999.00')
        exp.save()
        exp.refresh_from_db()
        self.assertTrue(exp.ledger_out_of_sync)
        # The voucher itself is untouched — the ledger is the book of record.
        self.assertEqual(exp.posted_voucher.total_debit, Decimal('15000.25'))

    def test_unpaid_source_is_never_flagged(self):
        exp = OfficeExpense.objects.create(
            office=self.office, amount=Decimal('500.00'), status='pending',
            expense_date=date.today(), created_by=self.user,
        )
        self.assertIsNone(exp.posted_voucher)
        self.assertFalse(exp.ledger_out_of_sync)

    def test_edit_form_shows_mismatch_banner(self):
        exp = self._paid_expense()
        exp.amount = Decimal('99999.00')
        exp.save()
        self.client.force_login(self.user)
        resp = self.client.get(reverse('finance_office_expense_edit', args=[exp.pk]))
        self.assertContains(resp, 'no longer matches the ledger')
        self.assertContains(resp, '15000.25')
        # The mismatch banner supersedes the generic immutability note, so the
        # user is not shown two stacked warnings.
        self.assertNotContains(resp, 'will not rewrite')
        self.assertEqual(len(resp.context['posted_voucher'].lines.all()), 2)

    def test_edit_form_hides_mismatch_banner_when_in_sync(self):
        exp = self._paid_expense()
        self.client.force_login(self.user)
        resp = self.client.get(reverse('finance_office_expense_edit', args=[exp.pk]))
        self.assertNotContains(resp, 'no longer matches the ledger')
        self.assertContains(resp, 'will not rewrite')

    def test_list_flags_mismatch(self):
        exp = self._paid_expense()
        exp.amount = Decimal('99999.00')
        exp.save()
        self.client.force_login(self.user)
        resp = self.client.get(reverse('finance_office_expenses'))
        self.assertContains(resp, 'Ledger mismatch')

    def test_project_cost_mismatch_is_flagged(self):
        cost = ProjectCost.objects.create(
            project=self.project, amount=Decimal('500.00'), status='paid',
            cost_date=date.today(), payment_method='bank_transfer',
            created_by=self.user,
        )
        cost.post_to_ledger()
        self.assertFalse(cost.ledger_out_of_sync)
        cost.amount = Decimal('700.00')
        cost.save()
        cost.refresh_from_db()
        self.assertTrue(cost.ledger_out_of_sync)
        self.client.force_login(self.user)
        self.assertContains(
            self.client.get(reverse('finance_project_costs')), 'Ledger mismatch')
        self.assertContains(
            self.client.get(reverse('finance_project_cost_edit', args=[cost.pk])),
            'no longer matches the ledger')

    def test_voucher_totals_helpers(self):
        exp = self._paid_expense()
        voucher = exp.posted_voucher
        self.assertEqual(voucher.total_debit, Decimal('15000.25'))
        self.assertEqual(voucher.total_credit, Decimal('15000.25'))
        self.assertTrue(voucher.is_balanced)


class PaidSourceCannotBeReopenedTest(TestCase):
    """A paid source has a posted, locked voucher, so the status must not fall
    back to an unposted state. The UI hides the button, but the URL is directly
    reachable — the view itself has to refuse."""

    def setUp(self):
        self.supervisor = User.objects.create_superuser('reop', 'r@example.com', 'pass12345')
        self.office = Office.objects.create(name='HO', office_type='head_office')
        self.project = Project.objects.create(name='RP', location='Lahore')

    def _paid_expense(self):
        exp = OfficeExpense.objects.create(
            office=self.office, amount=Decimal('15500.25'), status='paid',
            expense_date=date(2026, 6, 15), payment_method='bank_transfer',
            created_by=self.supervisor,
        )
        exp.post_to_ledger()
        return exp

    def _paid_cost(self):
        cost = ProjectCost.objects.create(
            project=self.project, amount=Decimal('33000.00'), status='paid',
            cost_date=date(2026, 7, 20), payment_method='bank_transfer',
            created_by=self.supervisor,
        )
        cost.post_to_ledger()
        return cost

    def test_approve_view_refuses_a_paid_office_expense(self):
        exp = self._paid_expense()
        voucher = exp.posted_voucher
        self.client.force_login(self.supervisor)
        resp = self.client.post(
            reverse('finance_office_expense_approve', args=[exp.pk]),
            {'action': 'approve'})
        self.assertEqual(resp.status_code, 302)
        exp.refresh_from_db()
        self.assertEqual(exp.status, 'paid', 'a posted expense must not revert')
        self.assertEqual(voucher.status, 'posted')
        self.assertTrue(voucher.is_locked)

    def test_approve_view_refuses_to_unapprove_a_paid_office_expense(self):
        """The action=else branch flipped it back to pending; that must be blocked too."""
        exp = self._paid_expense()
        self.client.force_login(self.supervisor)
        self.client.post(
            reverse('finance_office_expense_approve', args=[exp.pk]),
            {'action': 'revert'})
        exp.refresh_from_db()
        self.assertEqual(exp.status, 'paid')

    def test_approve_view_refuses_a_paid_project_cost(self):
        cost = self._paid_cost()
        voucher = cost.posted_voucher
        self.client.force_login(self.supervisor)
        self.client.post(
            reverse('finance_project_cost_approve', args=[cost.pk]),
            {'action': 'approve'})
        cost.refresh_from_db()
        self.assertEqual(cost.status, 'paid')
        self.assertTrue(voucher.is_locked)

    def test_api_approve_refuses_a_paid_office_expense(self):
        exp = self._paid_expense()
        self.client.force_login(self.supervisor)
        resp = self.client.post(f'/api/office-expenses/{exp.pk}/approve/')
        self.assertEqual(resp.status_code, 400)
        exp.refresh_from_db()
        self.assertEqual(exp.status, 'paid')

    def test_unpaid_source_can_still_be_approved(self):
        """The guard must not break the normal pending -> approved path."""
        exp = OfficeExpense.objects.create(
            office=self.office, amount=Decimal('500.00'), status='pending',
            expense_date=date.today(), payment_method='cash',
            created_by=self.supervisor,
        )
        self.client.force_login(self.supervisor)
        self.client.post(
            reverse('finance_office_expense_approve', args=[exp.pk]),
            {'action': 'approve'})
        exp.refresh_from_db()
        self.assertEqual(exp.status, 'approved')
        self.assertEqual(exp.approved_by, self.supervisor)


class DeletingAPaidSourceOrphansItsVoucherTest(TestCase):
    """CONFIRMED BUG — still open as of 2026-09-29. Not a regression guard for
    correct behaviour: these tests *characterise the defect* so it cannot be
    forgotten, and they will need rewriting once a void/reverse path exists.

    Deleting a paid source removes the source row but leaves its posted, locked
    voucher in the ledger, and that voucher then cannot be corrected through the
    application at all:

      * ``VoucherViewSet.destroy`` refuses auto-generated vouchers
        (``reference_id is not None``) and refuses posted/locked ones → HTTP 400;
      * there is no HTML delete route for a voucher and no void/reverse action;
      * ``Voucher`` is not registered in the Django admin.

    So the ledger is permanently misstated and the only remedy is a direct DB
    delete. ``TestCase`` rolls back, which is the only reason this is safe to
    assert here: the identical scenario driven over HTTP would permanently
    pollute the dev database with a row that no endpoint can remove.
    """

    def setUp(self):
        self.supervisor = User.objects.create_superuser('orph', 'o@example.com', 'pass12345')
        self.office = Office.objects.create(name='HO-orphan', office_type='head_office')
        self.project = Project.objects.create(name='RP-orphan', location='Lahore')

    def _paid_cost(self):
        cost = ProjectCost.objects.create(
            project=self.project, amount=Decimal('41000.00'), status='paid',
            cost_date=date(2026, 8, 1), payment_method='bank_transfer',
            created_by=self.supervisor,
        )
        cost.post_to_ledger()
        return cost

    def _paid_expense(self):
        exp = OfficeExpense.objects.create(
            office=self.office, amount=Decimal('12000.00'), status='paid',
            expense_date=date(2026, 8, 1), payment_method='bank_transfer',
            created_by=self.supervisor,
        )
        exp.post_to_ledger()
        return exp

    def test_html_delete_of_a_paid_cost_orphans_its_voucher(self):
        cost = self._paid_cost()
        voucher = cost.posted_voucher
        self.assertIsNotNone(voucher, 'paying a cost must post a voucher')
        self.assertEqual(voucher.status, 'posted')

        self.client.force_login(self.supervisor)
        resp = self.client.post(reverse('finance_project_cost_delete', args=[cost.pk]))
        self.assertEqual(resp.status_code, 302)
        self.assertFalse(ProjectCost.objects.filter(pk=cost.pk).exists())
        self.assertTrue(
            Voucher.objects.filter(pk=voucher.pk).exists(),
            'BUG: the paid cost was deleted but its posted voucher survives, '
            'so the ledger still reports spend for a cost that no longer exists',
        )

    def test_orphaned_voucher_cannot_be_deleted_through_the_api(self):
        """The orphan is unreachable: no endpoint can remove it."""
        cost = self._paid_cost()
        voucher = cost.posted_voucher
        self.client.force_login(self.supervisor)
        self.client.post(reverse('finance_project_cost_delete', args=[cost.pk]))

        resp = self.client.delete(f'/api/vouchers/{voucher.pk}/')
        self.assertEqual(resp.status_code, 400)
        self.assertIn('cannot be deleted', resp.json()['error'].lower())
        self.assertTrue(
            Voucher.objects.filter(pk=voucher.pk).exists(),
            'BUG: no correction path — the orphan survives every available endpoint',
        )

    def test_api_delete_of_a_paid_expense_orphans_its_voucher(self):
        """Same defect on the API path. ``OfficeExpense`` has no HTML delete
        route at all, so the DRF ModelViewSet delete is the only entry point."""
        exp = self._paid_expense()
        voucher = exp.posted_voucher
        self.assertIsNotNone(voucher, 'paying an expense must post a voucher')

        self.client.force_login(self.supervisor)
        resp = self.client.delete(f'/api/office-expenses/{exp.pk}/')
        self.assertEqual(resp.status_code, 204)
        self.assertFalse(OfficeExpense.objects.filter(pk=exp.pk).exists())
        self.assertTrue(
            Voucher.objects.filter(pk=voucher.pk).exists(),
            'BUG: the paid expense was deleted but its posted voucher survives',
        )

    def test_unpaid_source_deletes_cleanly(self):
        """A source that never reached the ledger must still be deletable —
        the delete view is not broken, it just ignores the ledger link."""
        cost = ProjectCost.objects.create(
            project=self.project, amount=Decimal('900.00'), status='pending',
            cost_date=date(2026, 8, 1), payment_method='cash',
            created_by=self.supervisor,
        )
        self.assertFalse(cost.posted_voucher)
        self.client.force_login(self.supervisor)
        resp = self.client.post(reverse('finance_project_cost_delete', args=[cost.pk]))
        self.assertEqual(resp.status_code, 302)
        self.assertFalse(ProjectCost.objects.filter(pk=cost.pk).exists())
        self.assertEqual(Voucher.objects.count(), 0, 'nothing was posted, so nothing to orphan')
