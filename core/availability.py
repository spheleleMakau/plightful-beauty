from datetime import datetime, time, timedelta

from django.db.models import Q
from django.utils import timezone

from .models import Appointment, WalkIn, Worker


OPENING_TIME = time(9, 0)
CLOSING_TIME = time(18, 0)
SLOT_MINUTES = 30


def _overlaps(start, duration_minutes, other_start, other_duration):
    if isinstance(start, str):
        start = datetime.strptime(start, '%H:%M').time()
    if isinstance(other_start, str):
        other_start = datetime.strptime(other_start, '%H:%M').time()
    end = (datetime.combine(datetime.today(), start) + timedelta(minutes=duration_minutes)).time()
    other_end = (datetime.combine(datetime.today(), other_start) + timedelta(minutes=other_duration)).time()
    return start < other_end and other_start < end


def worker_is_available(worker, appointment_date, appointment_time, duration_minutes, exclude_appointment_id=None, exclude_walk_in_id=None):
    if not worker.is_active:
        return False
    appointments = Appointment.objects.filter(
        appointment_date=appointment_date,
        paid_at__isnull=False,
        status__in=[
            Appointment.PENDING,
            Appointment.CONFIRMED,
            Appointment.CHECKED_IN,
            Appointment.IN_PROGRESS,
        ],
    ).filter(Q(worker=worker) | Q(worker__isnull=True)).select_related('service')
    for appointment in appointments:
        if appointment.pk == exclude_appointment_id:
            continue
        duration = appointment.service.duration_minutes
        if appointment.worker_id is None or appointment.worker_id == worker.pk:
            if _overlaps(appointment_time, duration_minutes, appointment.appointment_time, duration):
                return False

    walk_ins = WalkIn.objects.filter(worker=worker, start_time__date=appointment_date, completed_at__isnull=True).exclude(pk=exclude_walk_in_id).select_related('service')
    for walk_in in walk_ins:
        if walk_in.start_time.time() <= appointment_time:
            return False
    return True


def available_workers(appointment_date, appointment_time, duration_minutes, exclude_appointment_id=None, exclude_walk_in_id=None):
    workers = Worker.objects.filter(is_active=True)
    if not workers.exists():
        return list(workers)
    return [
        worker for worker in workers
        if worker_is_available(worker, appointment_date, appointment_time, duration_minutes, exclude_appointment_id, exclude_walk_in_id)
    ]


def recommended_slots(appointment_date, duration_minutes):
    today = timezone.localdate()
    current_time = timezone.localtime().time()
    cursor = datetime.combine(appointment_date, OPENING_TIME)
    closing = datetime.combine(appointment_date, CLOSING_TIME)
    slots = []
    while cursor + timedelta(minutes=duration_minutes) <= closing and len(slots) < 5:
        if appointment_date > today or (appointment_date == today and cursor.time() > current_time):
            workers = available_workers(appointment_date, cursor.time(), duration_minutes)
            if workers or not Worker.objects.filter(is_active=True).exists():
                slots.append({'time': cursor.strftime('%H:%M'), 'workers': len(workers)})
        cursor += timedelta(minutes=SLOT_MINUTES)
    return slots