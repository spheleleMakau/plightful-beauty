from datetime import date, datetime
from django import forms
from django.contrib.auth.forms import AuthenticationForm
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.core.validators import RegexValidator
from .models import Appointment, Client, Profile, Service, WalkIn, Worker
from .availability import available_workers, worker_is_available

phone_validator = RegexValidator(r'^\+?[0-9 ()-]{7,20}$', 'Enter a valid phone number.')


class OwnerLoginForm(AuthenticationForm):
    def confirm_login_allowed(self, user):
        super().confirm_login_allowed(user)
        profile = getattr(user, 'profile', None)
        if not (profile and profile.role == Profile.OWNER):
            raise ValidationError('This sign-in is for salon owners only.')


class WorkerLoginForm(AuthenticationForm):
    def confirm_login_allowed(self, user):
        super().confirm_login_allowed(user)
        profile = getattr(user, 'profile', None)
        worker = getattr(user, 'worker_profile', None)
        if not (profile and profile.role == 'worker' and worker and worker.is_active):
            raise ValidationError('This sign-in is for active salon workers only.')


class BookingForm(forms.ModelForm):
    customer_name = forms.CharField(max_length=150, label='Your name')
    phone = forms.CharField(max_length=30, validators=[phone_validator])
    email = forms.EmailField()

    class Meta:
        model = Appointment
        fields = ['customer_name', 'phone', 'email', 'service', 'appointment_date', 'appointment_time', 'inspiration_image_1', 'inspiration_image_2', 'notes']
        widgets = {'appointment_date': forms.DateInput(attrs={'type': 'date'}), 'appointment_time': forms.TimeInput(attrs={'type': 'time'}), 'notes': forms.Textarea(attrs={'rows': 3})}
        help_texts = {'inspiration_image_1': 'Optional: upload a picture of your first inspiration look.', 'inspiration_image_2': 'Optional: upload one more inspiration picture.'}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['service'].queryset = Service.objects.filter(is_active=True)
        self.fields['appointment_date'].widget.attrs['min'] = date.today().isoformat()

    def clean(self):
        cleaned = super().clean()
        appointment_date = cleaned.get('appointment_date')
        appointment_time = cleaned.get('appointment_time')
        if appointment_date and appointment_date < date.today():
            self.add_error('appointment_date', 'Please choose today or a future date.')
        if appointment_date == date.today() and appointment_time and appointment_time <= datetime.now().time():
            self.add_error('appointment_time', 'Please choose a later time today.')
        if appointment_date and appointment_time:
            service = cleaned.get('service')
            duration = service.duration_minutes if service else 60
            if Appointment.objects.filter(
                appointment_date=appointment_date,
                appointment_time=appointment_time,
                worker__isnull=True,
            ).exclude(status=Appointment.CANCELLED).exists():
                raise forms.ValidationError('That time is no longer available. Please choose another.')
            if Worker.objects.filter(is_active=True).exists() and not available_workers(appointment_date, appointment_time, duration):
                raise forms.ValidationError('No worker is available at that time. Please choose one of the recommended slots.')
        return cleaned

    def save(self, commit=True):
        client = Client.objects.filter(phone=self.cleaned_data['phone']).first()
        if client is None and self.cleaned_data.get('email'):
            client = Client.objects.filter(email__iexact=self.cleaned_data['email']).first()
        if client is None:
            client = Client(phone=self.cleaned_data['phone'], full_name=self.cleaned_data['customer_name'], email=self.cleaned_data['email'])
        client.full_name, client.email = self.cleaned_data['customer_name'], self.cleaned_data['email']
        client.save()
        appointment = super().save(commit=False)
        appointment.client = client
        if commit:
            appointment.save()
        return appointment


class WalkInForm(forms.ModelForm):
    client_name = forms.CharField(max_length=150, label='Client name')
    phone = forms.CharField(max_length=30, validators=[phone_validator])

    class Meta:
        model = WalkIn
        fields = ['client_name', 'phone', 'service', 'worker', 'style', 'style_details', 'amount', 'satisfaction', 'notes']

    def save(self, commit=True):
        client, _ = Client.objects.get_or_create(
            phone=self.cleaned_data['phone'],
            defaults={'full_name': self.cleaned_data['client_name']},
        )
        client.full_name = self.cleaned_data['client_name']
        client.save(update_fields=['full_name'])
        walk_in = super().save(commit=False)
        walk_in.client = client
        if commit:
            walk_in.save()
        return walk_in


class AppointmentManageForm(forms.ModelForm):
    class Meta:
        model = Appointment
        fields = ['worker', 'status', 'notes']
        widgets = {'notes': forms.Textarea(attrs={'rows': 3})}

    def __init__(self, *args, **kwargs):
        self.is_owner = kwargs.pop('is_owner', False)
        super().__init__(*args, **kwargs)
        appointment = self.instance
        if self.is_owner:
            self.fields['worker'].queryset = Worker.objects.select_related('user').order_by('user__first_name', 'user__last_name')
        elif appointment.pk and appointment.service_id and appointment.appointment_date and appointment.appointment_time:
            self.fields['worker'].queryset = Worker.objects.filter(
                pk__in=[worker.pk for worker in available_workers(
                    appointment.appointment_date,
                    appointment.appointment_time,
                    appointment.service.duration_minutes,
                    exclude_appointment_id=appointment.pk,
                )]
            )
        else:
            self.fields['worker'].queryset = Worker.objects.filter(is_active=True)

    def clean_worker(self):
        worker = self.cleaned_data.get('worker')
        appointment = self.instance
        if not self.is_owner and worker and appointment.service_id and not worker_is_available(
            worker,
            appointment.appointment_date,
            appointment.appointment_time,
            appointment.service.duration_minutes,
            exclude_appointment_id=appointment.pk,
        ):
            raise forms.ValidationError('This worker is no longer available for the appointment slot.')
        return worker


class ClientManageForm(forms.ModelForm):
    class Meta:
        model = Client
        fields = ['full_name', 'phone', 'email', 'notes']


class ServiceManageForm(forms.ModelForm):
    class Meta:
        model = Service
        fields = ['name', 'description', 'duration_minutes', 'price', 'is_active']


class WorkerCreateForm(forms.Form):
    first_name = forms.CharField(max_length=150, label='First name')
    last_name = forms.CharField(max_length=150, label='Last name')
    username = forms.CharField(max_length=150, help_text='Used by the worker to sign in.')
    email = forms.EmailField()
    phone = forms.CharField(max_length=30, validators=[phone_validator])
    position = forms.CharField(max_length=100, initial='Beauty Specialist')
    password = forms.CharField(min_length=8, widget=forms.PasswordInput, help_text='Give the worker a temporary password.')

    def clean_username(self):
        username = self.cleaned_data['username']
        if User.objects.filter(username=username).exists():
            raise forms.ValidationError('That username is already in use.')
        return username

    def save(self):
        user = User.objects.create_user(username=self.cleaned_data['username'], email=self.cleaned_data['email'], password=self.cleaned_data['password'], first_name=self.cleaned_data['first_name'], last_name=self.cleaned_data['last_name'])
        profile = getattr(user, 'profile', None)
        if profile is None:
            profile, _ = Profile.objects.get_or_create(user=user)
        profile.role = Profile.WORKER
        profile.phone = self.cleaned_data['phone']
        profile.save(update_fields=['role', 'phone'])
        return Worker.objects.create(user=user, position=self.cleaned_data['position'], phone=self.cleaned_data['phone'])
