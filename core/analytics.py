from datetime import date
from django.db.models import Avg, Count, Sum
from .models import Appointment, WalkIn


def business_summary(start_date, end_date):
    if isinstance(start_date, str):
        start_date = date.fromisoformat(start_date)
    if isinstance(end_date, str):
        end_date = date.fromisoformat(end_date)
    all_appointments = Appointment.objects.filter(appointment_date__range=(start_date, end_date))
    appointments = all_appointments.exclude(status=Appointment.CANCELLED)
    completed = appointments.filter(status=Appointment.COMPLETED)
    walk_ins = WalkIn.objects.filter(start_time__date__range=(start_date, end_date))
    appointment_revenue = completed.aggregate(value=Sum('service__price'))['value'] or 0
    walk_in_revenue = walk_ins.aggregate(value=Sum('amount'))['value'] or 0
    served_client_ids = set(completed.values_list('client_id', flat=True)) | set(walk_ins.values_list('client_id', flat=True))
    return {
        'appointments': appointments.count(),
        'walk_ins': walk_ins.count(),
        'completed_appointments': completed.count(),
        'pending': appointments.filter(status=Appointment.PENDING).count(),
        'cancelled': all_appointments.filter(status=Appointment.CANCELLED).count(),
        'revenue': appointment_revenue + walk_in_revenue,
        'clients_served': len(served_client_ids),
        'average_satisfaction': walk_ins.aggregate(value=Avg('satisfaction'))['value'],
        'popular_services': list(completed.values('service__name').annotate(total=Count('id')).order_by('-total')[:5]),
    }