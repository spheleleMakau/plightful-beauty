from io import BytesIO
from datetime import date, timedelta
from decimal import Decimal
from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.core.mail import send_mail
from django.db.models import Count, F, Q, Sum
from django.shortcuts import get_object_or_404, redirect, render
from django.http import HttpResponse
from django.http import JsonResponse
from django.utils import timezone
from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
from .analytics import business_summary
from .availability import available_workers, recommended_slots
from .forms import AppointmentManageForm, BookingForm, ClientManageForm, ServiceManageForm, WalkInForm, WorkerCreateForm
from .models import Appointment, Client, Profile, Service, WalkIn, Worker


def owner_required(view_func):
    @login_required
    def wrapped(request, *args, **kwargs):
        profile = getattr(request.user, 'profile', None)
        if not (profile and profile.role == Profile.OWNER):
            raise PermissionDenied
        return view_func(request, *args, **kwargs)
    return wrapped


def owner_or_worker_required(view_func):
    @login_required
    def wrapped(request, *args, **kwargs):
        profile = getattr(request.user, 'profile', None)
        if request.user.is_staff or (profile and profile.role in (Profile.OWNER, Profile.WORKER)):
            return view_func(request, *args, **kwargs)
        raise PermissionDenied
    return wrapped


def notify_client(appointment, subject, message):
    if appointment.client.email:
        send_mail(subject, message, settings.DEFAULT_FROM_EMAIL, [appointment.client.email], fail_silently=True)


def can_manage_appointment(request, appointment):
    profile = getattr(request.user, 'profile', None)
    if request.user.is_staff or (profile and profile.role == Profile.OWNER):
        return True
    worker = get_object_or_404(Worker, user=request.user)
    return appointment.worker_id in (None, worker.pk)


def selected_period(request):
    today = date.today()
    period = request.GET.get('period', 'today')
    if period == 'week':
        return today - timedelta(days=today.weekday()), today
    if period == 'month':
        return today.replace(day=1), today
    try:
        start = date.fromisoformat(request.GET.get('start', ''))
        end = date.fromisoformat(request.GET.get('end', ''))
        if start <= end:
            return start, end
    except ValueError:
        pass
    return today, today


def home(request):
    return render(request, 'core/home.html')


def owner_login_redirect(request):
    return redirect('owner_dashboard')

def about(request): return render(request, 'core/about.html')
def services(request): return render(request, 'core/services.html', {'services': Service.objects.filter(is_active=True)})
def gallery(request): return render(request, 'core/gallery.html')
def contact(request): return render(request, 'core/contact.html')


def book(request):
    remembered = request.session.get('booking_customer', {})
    form = BookingForm(request.POST or None, request.FILES or None, initial={
        'customer_name': getattr(getattr(request.user, 'client_profile', None), 'full_name', '') or remembered.get('customer_name', ''),
        'phone': getattr(getattr(request.user, 'client_profile', None), 'phone', '') or remembered.get('phone', ''),
        'email': getattr(request.user, 'email', '') if request.user.is_authenticated else remembered.get('email', ''),
    })
    if request.method == 'POST' and form.is_valid():
        appointment = form.save()
        notify_client(appointment, 'Your Plightful Beauty booking request was received', f'We received your request for {appointment.service.name} on {appointment.appointment_date} at {appointment.appointment_time}. The salon will confirm the appointment after reviewing the request.')
        request.session['booking_customer'] = {
            'customer_name': form.cleaned_data['customer_name'],
            'phone': form.cleaned_data['phone'],
            'email': form.cleaned_data['email'],
        }
        return render(request, 'core/booking_confirmation.html', {'appointment': appointment})
    return render(request, 'core/book.html', {'form': form})

def booked_times(request):
    selected_date = request.GET.get('date')
    service_id = request.GET.get('service')
    try:
        service = Service.objects.get(pk=service_id, is_active=True) if service_id else None
        duration = service.duration_minutes if service else 60
        selected_date = date.fromisoformat(selected_date) if selected_date else None
    except (Service.DoesNotExist, ValueError):
        selected_date = None
        duration = 60
    if not selected_date:
        return JsonResponse({'booked_times': [], 'available_slots': [], 'message': 'Choose a date and service first.'})
    booked = Appointment.objects.filter(appointment_date=selected_date).exclude(status=Appointment.CANCELLED).order_by('appointment_time')
    available = recommended_slots(selected_date, duration)
    return JsonResponse({
        'booked_times': [item.appointment_time.strftime('%H:%M') for item in booked],
        'available_slots': available,
        'workers_available': any(slot['workers'] for slot in available) if Worker.objects.filter(is_active=True).exists() else True,
    })

@login_required
def dashboard(request):
    profile = getattr(request.user, 'profile', None)
    if profile and profile.role == 'customer':
        appointments = Appointment.objects.filter(client__user=request.user)
        return render(request, 'core/customer_dashboard.html', {'appointments': appointments})
    if profile and profile.role == 'worker':
        worker = get_object_or_404(Worker, user=request.user)
        today = date.today()
        appointments = Appointment.objects.filter(worker=worker, appointment_date=today).select_related('client', 'service')
        assigned_appointments = Appointment.objects.filter(worker=worker, appointment_date__gte=today).exclude(status=Appointment.CANCELLED).select_related('client', 'service')
        completed = Appointment.objects.filter(worker=worker, status=Appointment.COMPLETED)
        context = {
            'appointments': appointments,
            'worker': worker,
            'assigned_clients': Client.objects.filter(appointments__worker=worker).distinct().order_by('full_name'),
            'completed_count': completed.count(),
            'revenue_generated': completed.aggregate(total=Sum('service__price'))['total'] or 0,
            'upcoming_count': assigned_appointments.count(),
            'upcoming_appointments': assigned_appointments,
            'recent_history': completed.select_related('client', 'service').order_by('-appointment_date', '-appointment_time')[:8],
        }
        return render(request, 'core/worker_dashboard.html', context)
    if not request.user.is_staff and not (profile and profile.role == 'owner'):
        return redirect('home')
    return owner_dashboard(request)


@owner_required
def owner_dashboard(request):
    start, end = selected_period(request)
    now = timezone.localtime()
    today = now.date()
    summary = business_summary(start, end)
    appointments = Appointment.objects.filter(appointment_date__range=(start, end)).exclude(status=Appointment.CANCELLED).select_related('client', 'service', 'worker')
    walk_ins = WalkIn.objects.filter(start_time__date__range=(start, end)).select_related('client', 'service', 'worker')
    current_walk_ins = WalkIn.objects.filter(start_time__date=today).select_related('client', 'service', 'worker')
    checked_in_appointments = Appointment.objects.filter(
        appointment_date=today,
        status__in=[Appointment.CHECKED_IN, Appointment.IN_PROGRESS],
    ).select_related('client', 'service', 'worker')
    summary.update({
        'active_workers': Worker.objects.filter(is_active=True).count(),
        'loyal_clients': Client.objects.filter(
            Q(appointments__status=Appointment.COMPLETED, appointments__appointment_date__range=(start, end)) |
            Q(walk_ins__start_time__date__range=(start, end))
        ).annotate(
            completed_count=Count('appointments', filter=Q(appointments__status=Appointment.COMPLETED, appointments__appointment_date__range=(start, end)), distinct=True),
            walk_in_count=Count('walk_ins', filter=Q(walk_ins__start_time__date__range=(start, end)), distinct=True),
        ).annotate(total_visits=F('completed_count') + F('walk_in_count')).filter(total_visits__gte=3).count(),
    })
    summary['average_ticket'] = (summary['revenue'] / summary['clients_served']).quantize(Decimal('0.01')) if summary['clients_served'] else Decimal('0.00')
    summary['satisfaction'] = round(summary['average_satisfaction'], 1) if summary['average_satisfaction'] is not None else '—'
    future_statuses = [Appointment.PENDING, Appointment.CONFIRMED, Appointment.CHECKED_IN, Appointment.IN_PROGRESS]
    upcoming_filter = Q(appointment_date__gt=today) | Q(appointment_date=today, appointment_time__gte=now.time())
    next_appointment = Appointment.objects.filter(upcoming_filter, status__in=future_statuses).select_related('client', 'service', 'worker').order_by('appointment_date', 'appointment_time').first()
    upcoming_appointments = Appointment.objects.filter(upcoming_filter, status__in=future_statuses).select_related('client', 'service', 'worker').order_by('appointment_date', 'appointment_time')
    worker_performance = list(Worker.objects.filter(is_active=True).select_related('user').annotate(
        assigned_services=Count('appointments', filter=Q(appointments__appointment_date__range=(start, end)) & ~Q(appointments__status=Appointment.CANCELLED)),
        completed_services=Count('appointments', filter=Q(appointments__status=Appointment.COMPLETED, appointments__appointment_date__range=(start, end))),
        generated_revenue=Sum('appointments__service__price', filter=Q(appointments__status=Appointment.COMPLETED, appointments__appointment_date__range=(start, end))),
    ).order_by('-completed_services', 'user__last_name'))
    walk_in_metrics = {
        item['worker_id']: item for item in walk_ins.values('worker_id').annotate(
            walk_in_count=Count('id'), walk_in_revenue=Sum('amount')
        ) if item['worker_id']
    }
    for worker in worker_performance:
        metrics = walk_in_metrics.get(worker.pk, {})
        worker.walk_in_count = metrics.get('walk_in_count', 0)
        worker.walk_in_revenue = metrics.get('walk_in_revenue') or Decimal('0.00')
        worker.total_assigned = worker.assigned_services + worker.walk_in_count
        worker.total_revenue = (worker.generated_revenue or Decimal('0.00')) + worker.walk_in_revenue
    worker_performance.sort(key=lambda worker: (-worker.total_assigned, worker.user.last_name))
    workers_in_salon = Worker.objects.filter(
        Q(is_active=True) & (Q(walk_ins__start_time__date=today) | Q(appointments__appointment_date=today, appointments__status__in=[Appointment.CHECKED_IN, Appointment.IN_PROGRESS]))
    ).distinct().select_related('user')
    schedule_date = request.GET.get('schedule_date', today.isoformat())
    try:
        schedule_date = date.fromisoformat(schedule_date)
    except ValueError:
        schedule_date = today
    schedule_appointments = Appointment.objects.filter(
        appointment_date=schedule_date,
        worker__isnull=False,
    ).exclude(status=Appointment.CANCELLED).select_related('client', 'service', 'worker').order_by('appointment_time')
    appointments_by_worker = {}
    for appointment in schedule_appointments:
        appointments_by_worker.setdefault(appointment.worker_id, []).append(appointment)
    worker_schedule = []
    for worker in Worker.objects.select_related('user').order_by('-is_active', 'user__first_name', 'user__last_name'):
        worker_appointments = appointments_by_worker.get(worker.pk, [])
        worker_schedule.append({
            'worker': worker,
            'appointments': worker_appointments,
            'status': 'off' if not worker.is_active else ('booked' if worker_appointments else 'available'),
        })
    return render(request, 'core/owner_dashboard.html', {'summary': summary, 'appointments': appointments, 'calendar_appointments': upcoming_appointments, 'upcoming_appointments': upcoming_appointments, 'walk_ins': walk_ins, 'current_walk_ins': current_walk_ins, 'checked_in_appointments': checked_in_appointments, 'next_appointment': next_appointment, 'worker_performance': worker_performance, 'workers_in_salon': workers_in_salon, 'worker_schedule': worker_schedule, 'schedule_date': schedule_date, 'start': start, 'end': end})


def owner_preview(request):
    if not settings.DEBUG:
        raise PermissionDenied
    today = date.today()
    summary = {'appointments': 0, 'completed_appointments': 0, 'revenue': 0, 'walk_ins': 0, 'pending': 0, 'cancelled': 0, 'active_workers': 0, 'loyal_clients': 0}
    return render(request, 'core/owner_preview.html', {'summary': summary, 'start': today, 'end': today, 'preview_mode': True})


@owner_or_worker_required
def appointment_list(request):
    appointments = Appointment.objects.select_related('client', 'service', 'worker').all()
    profile = getattr(request.user, 'profile', None)
    if not request.user.is_staff and profile and profile.role == Profile.WORKER:
        worker = get_object_or_404(Worker, user=request.user)
        appointments = appointments.filter(Q(worker=worker) | Q(worker__isnull=True))
    status = request.GET.get('status')
    query = request.GET.get('q')
    if status:
        appointments = appointments.filter(status=status)
    if query:
        appointments = appointments.filter(Q(client__full_name__icontains=query) | Q(client__phone__icontains=query))
    return render(request, 'core/owner_appointments.html', {'appointments': appointments, 'status': status, 'query': query or '', 'statuses': Appointment.STATUS_CHOICES})


@owner_or_worker_required
def appointment_manage(request, pk):
    appointment = get_object_or_404(Appointment.objects.select_related('client', 'service', 'worker'), pk=pk)
    if not can_manage_appointment(request, appointment):
        raise PermissionDenied
    is_owner = getattr(getattr(request.user, 'profile', None), 'role', None) == Profile.OWNER
    form = AppointmentManageForm(request.POST or None, instance=appointment, is_owner=is_owner)
    if request.method == 'POST' and form.is_valid():
        updated = form.save()
        notify_client(updated, 'Your Plightful Beauty appointment was updated', f'Your appointment for {updated.service.name} on {updated.appointment_date} at {updated.appointment_time} is now {updated.get_status_display()}. Assigned worker: {updated.worker or "To be confirmed"}.')
        messages.success(request, 'Appointment updated and the client was notified when an email was available.')
        return redirect('owner_dashboard' if is_owner else 'owner_appointments')
    return render(request, 'core/appointment_manage.html', {'form': form, 'appointment': appointment, 'is_owner': is_owner})


@owner_or_worker_required
def appointment_delete(request, pk):
    appointment = get_object_or_404(Appointment.objects.select_related('client', 'service', 'worker'), pk=pk)
    if not can_manage_appointment(request, appointment):
        raise PermissionDenied
    if request.method == 'POST':
        notify_client(appointment, 'Your Plightful Beauty appointment was cancelled', f'Your appointment for {appointment.service.name} on {appointment.appointment_date} at {appointment.appointment_time} has been cancelled. Please contact the salon if you need help booking another time.')
        appointment.delete()
        messages.success(request, 'Appointment deleted and the client was notified when an email was available.')
    return redirect('owner_appointments')


@owner_required
def client_list(request):
    clients = Client.objects.annotate(
        appointment_total=Count('appointments', filter=~Q(appointments__status=Appointment.CANCELLED), distinct=True),
        walk_in_total=Count('walk_ins', distinct=True),
        visit_total=Count('visits', distinct=True),
    ).order_by('full_name')
    query = request.GET.get('q')
    if query:
        clients = clients.filter(Q(full_name__icontains=query) | Q(phone__icontains=query) | Q(email__icontains=query))
    return render(request, 'core/owner_clients.html', {'clients': clients, 'query': query or ''})


@owner_required
def client_detail(request, pk):
    client = get_object_or_404(Client, pk=pk)
    return render(request, 'core/client_detail.html', {'client': client, 'appointments': client.appointments.select_related('service', 'worker'), 'walk_ins': client.walk_ins.select_related('service', 'worker'), 'visits': client.visits.select_related('service', 'worker')})


@owner_required
def client_edit(request, pk=None):
    client = get_object_or_404(Client, pk=pk) if pk else None
    form = ClientManageForm(request.POST or None, instance=client)
    if request.method == 'POST' and form.is_valid():
        client = form.save(); messages.success(request, 'Client saved.'); return redirect('client_detail', pk=client.pk)
    return render(request, 'core/form.html', {'form': form, 'title': 'Edit client' if client else 'Add client'})


@owner_required
def service_manage(request, pk=None):
    service = get_object_or_404(Service, pk=pk) if pk else None
    form = ServiceManageForm(request.POST or None, instance=service)
    if request.method == 'POST' and form.is_valid():
        form.save(); messages.success(request, 'Service saved.'); return redirect('owner_dashboard')
    return render(request, 'core/form.html', {'form': form, 'title': 'Edit service' if service else 'Add service'})


@owner_required
def worker_list(request):
    workers = Worker.objects.select_related('user').annotate(appointment_total=Count('appointments'))
    return render(request, 'core/owner_workers.html', {'workers': workers})


@owner_required
def worker_detail(request, pk):
    worker = get_object_or_404(Worker.objects.select_related('user'), pk=pk)
    today = date.today()
    month_start = today.replace(day=1)
    daily_appointments = Appointment.objects.filter(worker=worker, appointment_date=today).exclude(status=Appointment.CANCELLED).select_related('client', 'service')
    daily_walk_ins = WalkIn.objects.filter(worker=worker, start_time__date=today).select_related('client', 'service')
    monthly_appointments = Appointment.objects.filter(worker=worker, appointment_date__range=(month_start, today)).exclude(status=Appointment.CANCELLED)
    monthly_walk_ins = WalkIn.objects.filter(worker=worker, start_time__date__range=(month_start, today))
    future_appointments = Appointment.objects.filter(worker=worker, appointment_date__gt=today).exclude(status=Appointment.CANCELLED).select_related('client', 'service').order_by('appointment_date', 'appointment_time')
    daily_records = []
    for day in range(1, today.day + 1):
        record_date = month_start.replace(day=day)
        appointments = monthly_appointments.filter(appointment_date=record_date)
        walk_ins = monthly_walk_ins.filter(start_time__date=record_date)
        completed = appointments.filter(status=Appointment.COMPLETED)
        daily_records.append({'date': record_date, 'people': completed.values('client').distinct().count() + walk_ins.values('client').distinct().count(), 'completed': completed.count(), 'walk_ins': walk_ins.count(), 'revenue': (completed.aggregate(total=Sum('service__price'))['total'] or 0) + (walk_ins.aggregate(total=Sum('amount'))['total'] or 0)})
    monthly_completed = monthly_appointments.filter(status=Appointment.COMPLETED)
    return render(request, 'core/worker_detail.html', {'worker': worker, 'daily_appointments': daily_appointments, 'future_appointments': future_appointments, 'daily_walk_ins': daily_walk_ins, 'daily_people': daily_appointments.filter(status=Appointment.COMPLETED).values('client').distinct().count() + daily_walk_ins.values('client').distinct().count(), 'daily_completed': daily_appointments.filter(status=Appointment.COMPLETED).count(), 'daily_revenue': (daily_appointments.filter(status=Appointment.COMPLETED).aggregate(total=Sum('service__price'))['total'] or 0) + (daily_walk_ins.aggregate(total=Sum('amount'))['total'] or 0), 'monthly_people': monthly_completed.values('client').distinct().count() + monthly_walk_ins.values('client').distinct().count(), 'monthly_completed': monthly_completed.count(), 'monthly_revenue': (monthly_completed.aggregate(total=Sum('service__price'))['total'] or 0) + (monthly_walk_ins.aggregate(total=Sum('amount'))['total'] or 0), 'daily_records': daily_records})


@owner_required
def worker_create(request):
    form = WorkerCreateForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        form.save(); messages.success(request, 'Worker hired and account created.'); return redirect('owner_workers')
    return render(request, 'core/form.html', {'form': form, 'title': 'Hire a worker'})


@owner_required
def worker_toggle(request, pk):
    worker = get_object_or_404(Worker, pk=pk)
    if request.method == 'POST':
        worker.is_active = not worker.is_active
        worker.save(update_fields=['is_active'])
        worker.user.is_active = worker.is_active
        worker.user.save(update_fields=['is_active'])
        messages.success(request, f'{worker} is now {"active" if worker.is_active else "inactive"}.')
    return redirect('owner_workers')

@owner_required
def walk_in_create(request):
    form = WalkInForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        form.save(); messages.success(request, 'Walk-in saved successfully.'); return redirect('owner_dashboard')
    return render(request, 'core/form.html', {'form': form, 'title': 'Record a walk-in'})

@owner_required
def report_csv(request):
    start, end = selected_period(request)
    summary = business_summary(start, end)
    buffer = BytesIO()
    document = SimpleDocTemplate(buffer, pagesize=A4, rightMargin=18 * mm, leftMargin=18 * mm, topMargin=18 * mm, bottomMargin=18 * mm)
    palette = {
        'ink': colors.HexColor('#1f2028'),
        'gold': colors.HexColor('#b38a55'),
        'pink': colors.HexColor('#d96798'),
        'blush': colors.HexColor('#f3e5e9'),
        'line': colors.HexColor('#e6dcda'),
        'muted': colors.HexColor('#77747a'),
    }
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle('ReportTitle', parent=styles['Title'], fontName='Helvetica-Bold', fontSize=22, leading=26, textColor=palette['ink'], alignment=TA_LEFT, spaceAfter=5)
    subtitle_style = ParagraphStyle('ReportSubtitle', parent=styles['Normal'], fontName='Helvetica', fontSize=9, leading=13, textColor=palette['muted'])
    section_style = ParagraphStyle('ReportSection', parent=styles['Heading2'], fontName='Helvetica-Bold', fontSize=11, leading=14, textColor=palette['gold'], spaceBefore=18, spaceAfter=8)
    body_style = ParagraphStyle('ReportBody', parent=styles['Normal'], fontName='Helvetica', fontSize=9, leading=12, textColor=palette['ink'])
    story = [Paragraph('Plightful Beauty', title_style), Paragraph('Owner performance report', subtitle_style), Paragraph(f'{start.strftime("%d %B %Y")} - {end.strftime("%d %B %Y")}', subtitle_style), Spacer(1, 8)]
    metrics = [
        ['Metric', 'Value'],
        ['Revenue', f'R {summary["revenue"]}'],
        ['Appointments', str(summary['appointments'])],
        ['Completed appointments', str(summary['completed_appointments'])],
        ['Walk-ins', str(summary['walk_ins'])],
        ['Clients served', str(summary['clients_served'])],
        ['Average satisfaction', f'{summary["average_satisfaction"] or "-"} / 5'],
    ]
    metrics_table = Table(metrics, colWidths=[105 * mm, 55 * mm], repeatRows=1)
    metrics_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), palette['ink']), ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'), ('FONTNAME', (0, 1), (-1, -1), 'Helvetica'),
        ('FONTSIZE', (0, 0), (-1, -1), 9), ('BACKGROUND', (0, 1), (-1, -1), colors.white),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, palette['blush']]), ('TEXTCOLOR', (0, 1), (0, -1), palette['muted']),
        ('TEXTCOLOR', (1, 1), (1, -1), palette['ink']), ('ALIGN', (1, 1), (1, -1), 'RIGHT'),
        ('GRID', (0, 0), (-1, -1), 0.4, palette['line']), ('BOTTOMPADDING', (0, 0), (-1, -1), 8), ('TOPPADDING', (0, 0), (-1, -1), 8),
    ]))
    story.extend([Paragraph('Period summary', section_style), metrics_table, Paragraph('Popular services', section_style)])
    services = [['Service', 'Completed appointments']]
    services.extend([[item['service__name'], str(item['total'])] for item in summary['popular_services']] or [['No completed services in this period', '-']])
    services_table = Table(services, colWidths=[105 * mm, 55 * mm], repeatRows=1)
    services_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), palette['pink']), ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'), ('FONTSIZE', (0, 0), (-1, -1), 9),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, palette['blush']]), ('ALIGN', (1, 1), (1, -1), 'RIGHT'),
        ('GRID', (0, 0), (-1, -1), 0.4, palette['line']), ('BOTTOMPADDING', (0, 0), (-1, -1), 8), ('TOPPADDING', (0, 0), (-1, -1), 8),
    ]))
    story.append(services_table)
    document.build(story)
    response = HttpResponse(buffer.getvalue(), content_type='application/pdf')
    response['Content-Disposition'] = f'attachment; filename="plightful-report-{start}.pdf"'
    return response
