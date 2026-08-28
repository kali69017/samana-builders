"""DeepSeek AI services built on LangChain.

Every function degrades gracefully: if AI is disabled, no API key is
configured, or the provider call fails, the caller receives a structured
``AiResult`` with ``ok=False`` and a human-readable ``error`` instead of an
unhandled exception. This keeps the ERP usable even when the AI layer is
down, and makes the API endpoints testable without network access.
"""
import json
import time

from django.conf import settings
from django.utils import timezone

from .models import AiInteractionLog


class AiDisabledError(Exception):
    """Raised when AI is not configured/enabled."""


def _llm():
    """Return a configured DeepSeek chat model, or None when unavailable."""
    if not getattr(settings, 'AI_ENABLED', False):
        return None
    api_key = getattr(settings, 'DEEPSEEK_API_KEY', '')
    if not api_key:
        return None
    try:
        from langchain_deepseek import ChatDeepSeek
        return ChatDeepSeek(
            model=getattr(settings, 'DEEPSEEK_MODEL', 'deepseek-chat'),
            api_key=api_key,
            base_url=getattr(settings, 'DEEPSEEK_BASE_URL', 'https://api.deepseek.com'),
            temperature=0.3,
            timeout=60,
        )
    except Exception:
        return None


def _invoke(system_prompt, user_prompt, feature, user=None):
    """Run a chat completion and record an AiInteractionLog row."""
    start = time.monotonic()
    model_name = getattr(settings, 'DEEPSEEK_MODEL', 'deepseek-chat')

    llm = _llm()
    if llm is None:
        AiInteractionLog.objects.create(
            user=user, feature=feature, prompt=user_prompt,
            model=model_name, status='disabled',
            error_message='AI is not configured. Set AI_ENABLED and DEEPSEEK_API_KEY.',
        )
        raise AiDisabledError('AI is not configured. Set AI_ENABLED and DEEPSEEK_API_KEY.')

    try:
        from langchain_core.messages import HumanMessage, SystemMessage
        response = llm.invoke([
            SystemMessage(content=system_prompt),
            HumanMessage(content=user_prompt),
        ])
        text = response.content if hasattr(response, 'content') else str(response)
        latency = int((time.monotonic() - start) * 1000)
        AiInteractionLog.objects.create(
            user=user, feature=feature, prompt=user_prompt,
            response=text, model=model_name, status='success', latency_ms=latency,
        )
        return text
    except Exception as exc:
        latency = int((time.monotonic() - start) * 1000)
        AiInteractionLog.objects.create(
            user=user, feature=feature, prompt=user_prompt,
            model=model_name, status='failed',
            error_message=str(exc), latency_ms=latency,
        )
        raise


def _erp_context_blurb():
    """Compact current business snapshot fed to the LLM as grounding data."""
    from bookings.models import Booking, Installment
    from customers.models import Customer
    from properties.models import Plot, Project
    from payments.models import Payment
    from django.db.models import Sum

    total_revenue = Booking.objects.aggregate(t=Sum('advance_paid'))['t'] or 0
    pending_payments = Payment.objects.filter(status='pending').count()
    overdue_installments = Installment.objects.filter(status='overdue').count()
    overdue_amount = Installment.objects.filter(status='overdue').aggregate(
        t=Sum('amount'))['t'] or 0
    available_plots = Plot.objects.filter(status='available').count()
    booked_plots = Plot.objects.filter(status='booked').count()

    top_defaulters = []
    for inst in Installment.objects.filter(status='overdue').select_related(
        'plan__booking__customer'
    )[:8]:
        name = inst.plan.booking.customer.full_name
        top_defaulters.append(f"{name} (installment {inst.installment_number}, Rs. {inst.amount})")

    return (
        f"Total customers: {Customer.objects.count()}\n"
        f"Active projects: {Project.objects.exclude(status='inactive').count()}\n"
        f"Total bookings: {Booking.objects.count()}\n"
        f"Total revenue (advance paid): Rs. {total_revenue:,.0f}\n"
        f"Pending payments awaiting verification: {pending_payments}\n"
        f"Overdue installments: {overdue_installments} totaling Rs. {overdue_amount:,.0f}\n"
        f"Available plots: {available_plots}, booked plots: {booked_plots}\n"
        f"Top defaulters: {', '.join(top_defaulters) if top_defaulters else 'none'}\n"
        f"Today: {timezone.localdate().isoformat()}"
    )


def _assistant_language_instruction():
    """Global assistant language from CompanySettings (English or Roman Urdu)."""
    from core.models import CompanySettings
    lang = CompanySettings.load().ai_language
    if lang == 'roman_urdu':
        return (
            "Respond in ROMAN URDU (Urdu written in Latin/English letters, e.g. "
            "'Aap ka total revenue 50 lakh rupees hai'). Keep business terms "
            "(revenue, booking, plot, installment) in English where natural. "
            "Use Rs. and Pakistani formatting for money. Numbers stay in digits."
        )
    return "Respond in clear English."


def ask_assistant(question, user=None):
    """Natural-language Q&A over live ERP data, in the global AI language."""
    system = (
        "You are the AI assistant for Samana Builders & Developers, a Pakistani "
        "real estate ERP. Answer the user's question using ONLY the business data "
        "provided below. Be concise, factual, and friendly. If the data does not "
        "contain the answer, say you don't have that information. Use Rs. and "
        "Pakistani formatting for money. Do not invent numbers.\n"
        + _assistant_language_instruction() + "\n\n"
        "CURRENT BUSINESS DATA:\n" + _erp_context_blurb()
    )
    return _invoke(system, question, 'assistant', user=user)


def score_lead(lead, user=None):
    """Score a lead 0-100 with a hot/warm/cold tier and a one-line reason."""
    system = (
        "You are a real estate sales qualification engine for a Pakistani property "
        "developer. Score the lead 0-100 based on budget, source, status, and any "
        "notes. Return ONLY valid JSON with keys: score (int 0-100), tier "
        "(\"hot\"|\"warm\"|\"cold\"), reason (one short sentence). "
        "Hot = ready to buy within weeks, warm = interested but needs follow-up, "
        "cold = early/likely lost."
    )
    payload = (
        f"Lead: {lead.display_name}\n"
        f"Source: {lead.get_source_display()}\n"
        f"Status: {lead.get_status_display()}\n"
        f"Budget: {lead.budget or 'not specified'}\n"
        f"Contacted: {'yes' if lead.is_contacted else 'no'}\n"
        f"Notes: {lead.notes or 'none'}\n"
        f"Project interest: {lead.interest_project.name if lead.interest_project else 'any'}"
    )
    raw = _invoke(system, payload, 'lead_score', user=user)
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return {'score': None, 'tier': 'unknown', 'reason': raw.strip()[:200]}


def generate_property_description(plot, user=None):
    """Marketing copy for a plot/project."""
    system = (
        "You are a property marketing copywriter for Samana Builders & Developers. "
        "Write a compelling 2-3 sentence description for the plot below. Mention "
        "size, price, and location. Pakistani English tone. No markdown, no emojis."
    )
    payload = (
        f"Plot: {plot.plot_number}\n"
        f"Project: {plot.project.name} ({plot.project.location})\n"
        f"Type: {plot.get_plot_type_display()}\n"
        f"Size: {plot.size_marla} marla\n"
        f"Price: Rs. {plot.price:,.0f}\n"
        f"Features: {', '.join(f.name for f in plot.features.all()) or 'standard'}\n"
        f"Block: {plot.block or 'n/a'} | Corner: {'yes' if plot.is_corner else 'no'}"
    )
    return _invoke(system, payload, 'property_description', user=user)


def draft_reminder(installment, user=None):
    """Personalized reminder message for a customer's installment."""
    booking = installment.plan.booking
    customer = booking.customer
    system = (
        "You are a collection assistant for Samana Builders & Developers. Write a "
        "polite, professional WhatsApp/SMS reminder (max 3 sentences) for a "
        "customer about their upcoming/overdue installment. Use the exact amounts "
        "given. No markdown, no emojis."
    )
    payload = (
        f"Customer: {customer.full_name}\n"
        f"Booking: {booking.booking_id}\n"
        f"Plot: {booking.plot.plot_number} ({booking.plot.project.name})\n"
        f"Installment: #{installment.installment_number}\n"
        f"Due date: {installment.due_date}\n"
        f"Amount: Rs. {installment.amount:,.0f}\n"
        f"Late fee so far: Rs. {installment.late_fee:,.0f}\n"
        f"Status: {installment.get_status_display()}"
    )
    return _invoke(system, payload, 'reminder_draft', user=user)


def generate_insights(user=None, focus=None):
    """Narrative business insights from the live dashboard data.

    focus (optional): 'revenue' | 'collections' | 'inventory' | 'hr' | None
    — narrows the analysis to one area instead of the general overview.
    Replies in the global AI language (English or Roman Urdu).
    """
    lang = _assistant_language_instruction()
    if focus == 'revenue':
        system = (
            "You are a business analyst for a Pakistani real estate developer. Based "
            "on the CURRENT BUSINESS DATA provided, write 3-5 concise insights about "
            "REVENUE HEALTH: total revenue, monthly momentum, booking conversion, and "
            "what management should do to grow revenue. Be specific with numbers. "
            "No markdown headers.\n" + lang
        )
    elif focus == 'collections':
        system = (
            "You are a collections analyst for a Pakistani real estate developer. Based "
            "on the CURRENT BUSINESS DATA provided, write 3-5 concise insights about "
            "COLLECTIONS RISK: overdue installments, pending payment verification, top "
            "defaulters, and concrete collection actions. Be specific with numbers. "
            "No markdown headers.\n" + lang
        )
    elif focus == 'inventory':
        system = (
            "You are a sales strategist for a Pakistani real estate developer. Based "
            "on the CURRENT BUSINESS DATA provided, write 3-5 concise insights about "
            "INVENTORY: available vs booked plots, project mix, pricing opportunities, "
            "and what to sell next. Be specific with numbers. No markdown headers.\n" + lang
        )
    elif focus == 'hr':
        system = (
            "You are an HR analyst for a Pakistani real estate developer. Based "
            "on the CURRENT BUSINESS DATA provided, write 3-5 concise insights about "
            "the WORKFORCE: headcount, payroll cost, leave patterns, and HR actions. "
            "Be specific with numbers. No markdown headers.\n" + lang
        )
        return _invoke(system, _hr_context_blurb(), 'insights', user=user)
    else:
        system = (
            "You are a business analyst for a Pakistani real estate developer. Based "
            "on the CURRENT BUSINESS DATA provided, write 3-5 concise insights "
            "(max 2 sentences each) covering revenue health, collections risk, "
            "inventory, and any action the management should take. Be specific with "
            "numbers. No markdown headers.\n" + lang
        )
    return _invoke(system, _erp_context_blurb(), 'insights', user=user)


# ─── HR AI FEATURES ──────────────────────────────────────────────────────────

def _hr_context_blurb():
    """Compact HR snapshot (headcount, payroll, attendance, leave)."""
    from hr.models import Department, Employee, Leave, PayrollRun, SalarySlip
    from django.db.models import Count, Sum

    active = Employee.objects.filter(status='active')
    dept_lines = []
    for dept in Department.objects.annotate(employee_count=Count('employees')):
        dept_lines.append(f"{dept.name}: {dept.employee_count}")
    last_run = PayrollRun.objects.order_by('-year', '-month').first()
    payroll_total = 0
    if last_run:
        payroll_total = SalarySlip.objects.filter(run=last_run).aggregate(
            t=Sum('net'))['t'] or 0

    pending_leaves = Leave.objects.filter(status='pending').count()
    today_leaves = Leave.objects.filter(status='approved').count()

    emp_lines = []
    for e in active.select_related('department', 'designation')[:15]:
        emp_lines.append(
            f"{e.employee_id} {e.full_name} — {e.department.name if e.department else 'no dept'}"
            f" ({e.designation.title if e.designation else 'no role'})"
        )

    return (
        f"Total employees: {Employee.objects.count()} (active: {active.count()})\n"
        f"Departments: {', '.join(dept_lines) if dept_lines else 'none'}\n"
        f"Latest payroll run: {last_run.period_label if last_run else 'none'} "
        f"totaling Rs. {payroll_total:,.0f}\n"
        f"Pending leave requests: {pending_leaves}\n"
        f"Employees on approved leave: {today_leaves}\n"
        f"Active employees: {'; '.join(emp_lines) if emp_lines else 'none'}\n"
        f"Today: {timezone.localdate().isoformat()}"
    )


def ask_hr_assistant(question, user=None):
    """Natural-language Q&A over live HR data, in the global AI language."""
    system = (
        "You are the HR assistant for Samana Builders & Developers. Answer the "
        "user's question using ONLY the HR data provided below (employees, "
        "departments, payroll, attendance, leave). Be concise and factual. If "
        "the data does not contain the answer, say you don't have that "
        "information. Use Rs. for money. Do not invent numbers.\n"
        + _assistant_language_instruction() + "\n\n"
        "CURRENT HR DATA:\n" + _hr_context_blurb()
    )
    return _invoke(system, question, 'hr_assistant', user=user)


def draft_leave_review(leave, decision, user=None):
    """Draft an approve/reject message for a leave request."""
    system = (
        "You are an HR manager for Samana Builders & Developers. Write a short, "
        "professional email (3-4 sentences) informing the employee of the leave "
        "decision. Be warm on approval, constructive on rejection. Use the "
        "exact dates and days given. No markdown, no emojis."
    )
    payload = (
        f"Employee: {leave.employee.full_name}\n"
        f"Leave type: {leave.get_leave_type_display()}\n"
        f"Dates: {leave.start_date} to {leave.end_date} ({leave.days} days)\n"
        f"Reason: {leave.reason or 'not provided'}\n"
        f"Decision: {decision}"
    )
    return _invoke(system, payload, 'leave_review', user=user)


def analyze_payroll(payroll_run, user=None):
    """Spot anomalies and summarize a payroll run."""
    system = (
        "You are a payroll analyst. Review the payroll run data below and "
        "report: total gross/net paid, number of slips, any unusually large "
        "earnings or deductions, and anything that looks like an error or "
        "needs review. Be specific with numbers. Max 5 bullet points. No markdown headers."
    )
    items = []
    for slip in payroll_run.slips.select_related('employee').all()[:25]:
        items.append(
            f"{slip.employee.employee_id} {slip.employee.full_name}: "
            f"gross Rs. {slip.gross:,.0f}, deductions Rs. {slip.total_deductions:,.0f}, "
            f"net Rs. {slip.net:,.0f}"
        )
    payload = (
        f"Payroll run: {payroll_run.period_label} (status: {payroll_run.status})\n"
        f"Slips: {payroll_run.slip_count}\n"
        f"Total gross: Rs. {payroll_run.total_gross:,.0f}\n"
        f"Total net: Rs. {payroll_run.total_net:,.0f}\n\n"
        + ("\n".join(items) if items else "No slips in this run.")
    )
    return _invoke(system, payload, 'payroll_insights', user=user)


def analyze_attendance(month=None, year=None, user=None):
    """Monthly attendance summary and absenteeism patterns."""
    from hr.models import Attendance, Leave
    from django.db.models import Count

    today = timezone.localdate()
    month = month or today.month
    year = year or today.year

    statuses = {s[0]: 0 for s in Attendance.STATUS_CHOICES}
    for row in Attendance.objects.filter(date__year=year, date__month=month).values(
        'status'
    ).annotate(count=Count('id')):
        statuses[row['status']] = row['count']

    total = sum(statuses.values())
    leaves = Leave.objects.filter(
        start_date__year=year, start_date__month=month, status='approved'
    ).count()

    system = (
        "You are an HR analyst. Summarize the attendance for the month below: "
        "attendance rate, absenteeism, leave load, and 1-2 recommendations. "
        "Be specific with numbers. Max 4 sentences. No markdown headers."
    )
    payload = (
        f"Month: {year}-{month:02d}\n"
        f"Attendance records: {total}\n"
        f"Status breakdown: {statuses}\n"
        f"Approved leaves in month: {leaves}"
    )
    return _invoke(system, payload, 'attendance_insights', user=user)


def generate_job_description(designation=None, department=None, user=None):
    """Draft a job description for an open position."""
    system = (
        "You are an HR copywriter for Samana Builders & Developers, a Pakistani "
        "real estate developer. Write a professional job description (150-200 "
        "words) with: role title, key responsibilities (6-8 bullets), required "
        "qualifications, and preferred skills. Pakistani professional tone. "
        "No markdown headers."
    )
    payload = (
        f"Designation: {designation or 'General'}\n"
        f"Department: {department or 'General'}\n"
        f"Company: Samana Builders & Developers (real estate, Lahore Pakistan)"
    )
    return _invoke(system, payload, 'job_description', user=user)
