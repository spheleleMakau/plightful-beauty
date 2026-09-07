from datetime import datetime
from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q
from django.db.models.signals import post_save
from django.dispatch import receiver
from django.utils import timezone


class SiteSettings(models.Model):
    salon_name = models.CharField(max_length=255, default='Plightful Beauty')
    phone = models.CharField(max_length=50, blank=True)
    email = models.EmailField(blank=True)
    instagram = models.CharField(max_length=255, blank=True)

    def __str__(self):
        return self.salon_name


class Profile(models.Model):
    OWNER = 'owner'
    WORKER = 'worker'
    CUSTOMER = 'customer'
    ROLE_CHOICES = [(OWNER, 'Owner'), (WORKER, 'Worker'), (CUSTOMER, 'Customer')]
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='profile')
    role = models.CharField(max_length=20, choices=ROLE_CHOICES, default=CUSTOMER)
    phone = models.CharField(max_length=30, blank=True)

    def __str__(self):
        return f'{self.user.get_full_name() or self.user.username} ({self.get_role_display()})'


@receiver(post_save, sender=settings.AUTH_USER_MODEL)
def create_user_profile(sender, instance, created, **kwargs):
    if created:
        Profile.objects.get_or_create(
            user=instance,
            defaults={'role': Profile.OWNER if instance.is_superuser else Profile.CUSTOMER},
        )


class Worker(models.Model):
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='worker_profile')
    position = models.CharField(max_length=100, default='Beauty Specialist')
    phone = models.CharField(max_length=30, blank=True)
    joined_date = models.DateField(auto_now_add=True)
    is_active = models.BooleanField(default=True)

    def __str__(self):
        return self.user.get_full_name() or self.user.username


class Client(models.Model):
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='client_profile')
    full_name = models.CharField(max_length=150)
    phone = models.CharField(max_length=30)
    email = models.EmailField(blank=True)
    registered_at = models.DateTimeField(auto_now_add=True)
    notes = models.TextField(blank=True)

    @property
    def visits_count(self):
        return self.visits.count()

    @property
    def total_spent(self):
        return self.visits.aggregate(total=models.Sum('amount'))['total'] or 0

    @property
    def is_loyal(self):
        return self.visits_count >= 3

    def __str__(self):
        return self.full_name


class Service(models.Model):
    name = models.CharField(max_length=120)
    description = models.TextField(blank=True)
    duration_minutes = models.PositiveIntegerField(default=60)
    price = models.DecimalField(max_digits=10, decimal_places=2)
    is_active = models.BooleanField(default=True)

    def __str__(self):
        return self.name


class Appointment(models.Model):
    PENDING = 'pending'
    CONFIRMED = 'confirmed'
    CHECKED_IN = 'checked_in'
    IN_PROGRESS = 'in_progress'
    COMPLETED = 'completed'
    CANCELLED = 'cancelled'
    STATUS_CHOICES = [(PENDING, 'Pending'), (CONFIRMED, 'Confirmed'), (CHECKED_IN, 'Checked In'),
                      (IN_PROGRESS, 'In Progress'), (COMPLETED, 'Completed'), (CANCELLED, 'Cancelled')]
    client = models.ForeignKey(Client, on_delete=models.CASCADE, related_name='appointments')
    service = models.ForeignKey(Service, on_delete=models.PROTECT, related_name='appointments')
    worker = models.ForeignKey(Worker, on_delete=models.SET_NULL, null=True, blank=True, related_name='appointments')
    appointment_date = models.DateField()
    appointment_time = models.TimeField()
    notes = models.TextField(blank=True)
    inspiration_image_1 = models.ImageField(upload_to='inspiration/', blank=True, null=True)
    inspiration_image_2 = models.ImageField(upload_to='inspiration/', blank=True, null=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=PENDING)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['appointment_date', 'appointment_time']
        constraints = [models.UniqueConstraint(fields=['appointment_date', 'appointment_time', 'worker'], name='unique_worker_slot')]

    def clean(self):
        if self.appointment_date and self.appointment_time and datetime.combine(self.appointment_date, self.appointment_time) < datetime.now():
            raise ValidationError('Please choose a future appointment time.')
        clash = Appointment.objects.filter(appointment_date=self.appointment_date, appointment_time=self.appointment_time).exclude(pk=self.pk).exclude(status=self.CANCELLED)
        if clash.exists() and self.worker_id is None:
            raise ValidationError('That appointment time is already reserved.')

    def __str__(self):
        return f'{self.client} - {self.service} on {self.appointment_date}'


class WalkIn(models.Model):
    client = models.ForeignKey(Client, on_delete=models.CASCADE, related_name='walk_ins')
    service = models.ForeignKey(Service, on_delete=models.PROTECT, related_name='walk_ins')
    worker = models.ForeignKey(Worker, on_delete=models.SET_NULL, null=True, blank=True, related_name='walk_ins')
    style = models.CharField(max_length=150, blank=True)
    style_details = models.TextField(blank=True)
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    start_time = models.DateTimeField(default=timezone.now, editable=False)
    satisfaction = models.PositiveSmallIntegerField(null=True, blank=True)
    notes = models.TextField(blank=True)

    def clean(self):
        if self.amount is not None and self.amount < 0:
            raise ValidationError('Amount cannot be negative.')
        if self.satisfaction is not None and not 1 <= self.satisfaction <= 5:
            raise ValidationError('Satisfaction must be between 1 and 5.')

    @property
    def time_spent_minutes(self):
        if not self.start_time:
            return None
        return max(0, int((timezone.now() - self.start_time).total_seconds() // 60))

    @property
    def time_spent_display(self):
        minutes = self.time_spent_minutes
        if minutes is None:
            return 'Not started'
        return f'{minutes // 60}h {minutes % 60:02d}m'

    def __str__(self):
        return f'{self.client} walk-in'


class ClientVisit(models.Model):
    client = models.ForeignKey(Client, on_delete=models.CASCADE, related_name='visits')
    service = models.ForeignKey(Service, on_delete=models.PROTECT)
    worker = models.ForeignKey(Worker, on_delete=models.SET_NULL, null=True, blank=True)
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    visited_at = models.DateTimeField(auto_now_add=True)
    notes = models.TextField(blank=True)


class Review(models.Model):
    client = models.ForeignKey(Client, on_delete=models.CASCADE, related_name='reviews')
    appointment = models.OneToOneField(Appointment, on_delete=models.SET_NULL, null=True, blank=True)
    rating = models.PositiveSmallIntegerField()
    comment = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def clean(self):
        if not 1 <= self.rating <= 5:
            raise ValidationError('Rating must be between 1 and 5.')
