from datetime import date, datetime, timedelta
from io import BytesIO
from decimal import Decimal
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.test import override_settings
from django.utils import timezone
from PIL import Image
from core.analytics import business_summary
from core.forms import AppointmentManageForm, BookingForm, WalkInManageForm, WorkerCreateForm
from core.models import Appointment, Client, Profile, Service, WalkIn, Worker


class SalonWorkflowTests(TestCase):
    def setUp(self):
        self.service = Service.objects.create(name='Test Service', price=Decimal('250.00'))
        self.customer = Client.objects.create(full_name='Test Client', phone='+27123456789')

    def test_booking_form_creates_client_and_appointment(self):
        future = date.today() + timedelta(days=3)
        form = BookingForm(data={'customer_name': 'New Client', 'phone': '+27111111111', 'email': 'new@example.com', 'service': self.service.pk, 'appointment_date': future, 'appointment_time': '10:00', 'notes': ''})
        self.assertTrue(form.is_valid(), form.errors)
        appointment = form.save()
        self.assertEqual(appointment.client.full_name, 'New Client')

    def test_double_booking_is_rejected(self):
        future = date.today() + timedelta(days=3)
        Appointment.objects.create(client=self.customer, service=self.service, paid_at=timezone.now(), appointment_date=future, appointment_time='11:00')
        form = BookingForm(data={'customer_name': 'Other', 'phone': '+27111111112', 'email': 'other@example.com', 'service': self.service.pk, 'appointment_date': future, 'appointment_time': '11:00', 'notes': ''})
        self.assertFalse(form.is_valid())

    def test_unpaid_booking_does_not_block_slot_until_pay_now(self):
        future = date.today() + timedelta(days=3)
        pending = Appointment.objects.create(client=self.customer, service=self.service, appointment_date=future, appointment_time='11:00')
        form = BookingForm(data={'customer_name': 'Other', 'phone': '+27111111112', 'email': 'other@example.com', 'service': self.service.pk, 'appointment_date': future, 'appointment_time': '11:00', 'notes': ''})
        self.assertTrue(form.is_valid(), form.errors)
        response = self.client.post(f'/book/{pending.pk}/pay/')
        self.assertEqual(response.status_code, 200)
        pending.refresh_from_db()
        self.assertIsNotNone(pending.paid_at)
        self.assertEqual(pending.status, Appointment.CONFIRMED)
        self.assertContains(response, 'BOOKING SECURED')
        self.assertContains(response, 'wa.me')

    def test_walk_in_duration_and_invalid_times(self):
        start = datetime.now()
        walk_in = WalkIn(client=self.customer, service=self.service, amount=Decimal('250'), start_time=timezone.now() - timedelta(hours=2, minutes=15))
        walk_in.full_clean()
        self.assertGreaterEqual(walk_in.time_spent_minutes, 135)
        self.assertEqual(walk_in.time_spent_display, '2h 15m')

    def test_dashboard_requires_login(self):
        response = self.client.get('/dashboard/')
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response.url.startswith('/admin/login/?next=/dashboard/'))

    def test_owner_dashboard_is_available_without_login(self):
        response = self.client.get('/owner/')
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'PRIVATE OWNER SPACE')

    def test_booking_accepts_two_inspiration_images(self):
        future = date.today() + timedelta(days=3)
        image_buffer = BytesIO()
        Image.new('RGB', (1, 1), 'white').save(image_buffer, format='PNG')
        image = SimpleUploadedFile('inspiration.png', image_buffer.getvalue(), content_type='image/png')
        form = BookingForm(data={'customer_name': 'Image Client', 'phone': '+27111111113', 'email': 'image@example.com', 'service': self.service.pk, 'appointment_date': future, 'appointment_time': '12:00', 'notes': ''}, files={'inspiration_image_1': image, 'inspiration_image_2': image})
        self.assertTrue(form.is_valid(), form.errors)
        appointment = form.save()
        self.assertTrue(appointment.inspiration_image_1.name.startswith('inspiration/'))
        self.assertTrue(appointment.inspiration_image_2.name.startswith('inspiration/'))
    
    def test_business_summary_counts_completed_revenue_once(self):
        future = date.today() + timedelta(days=3)
        Appointment.objects.create(client=self.customer, service=self.service, status=Appointment.COMPLETED, appointment_date=future, appointment_time='13:00')
        start = timezone.make_aware(datetime.combine(future, datetime.min.time()))
        WalkIn.objects.create(client=self.customer, service=self.service, amount=Decimal('100'), start_time=start)
        summary = business_summary(future, future)
        self.assertEqual(summary['revenue'], Decimal('350'))
        self.assertEqual(summary['clients_served'], 1)

    def test_business_summary_separates_cancelled_and_pending_appointments(self):
        future = date.today() + timedelta(days=3)
        Appointment.objects.create(client=self.customer, service=self.service, status=Appointment.CANCELLED, appointment_date=future, appointment_time='09:00')
        Appointment.objects.create(client=self.customer, service=self.service, status=Appointment.PENDING, appointment_date=future, appointment_time='10:00')

        summary = business_summary(future, future)

        self.assertEqual(summary['appointments'], 1)
        self.assertEqual(summary['pending'], 1)
        self.assertEqual(summary['cancelled'], 1)

    def test_owner_dashboard_excludes_past_appointments_from_next(self):
        past_client = Client.objects.create(full_name='Past Client', phone='+27111111115')
        future_client = Client.objects.create(full_name='Future Client', phone='+27111111116')
        past_time = (timezone.localtime() - timedelta(hours=1)).time().replace(second=0, microsecond=0)
        Appointment.objects.create(client=past_client, service=self.service, status=Appointment.PENDING, appointment_date=date.today(), appointment_time=past_time)
        Appointment.objects.create(client=future_client, service=self.service, status=Appointment.PENDING, appointment_date=date.today() + timedelta(days=1), appointment_time='10:00')
        owner = User.objects.create_user('next_owner', password='pass-123')
        Profile.objects.update_or_create(user=owner, defaults={'role': Profile.OWNER})
        self.client.login(username='next_owner', password='pass-123')

        response = self.client.get('/owner/')

        self.assertEqual(response.context['next_appointment'].client, future_client)

    def test_owner_dashboard_shows_worker_schedule_states(self):
        schedule_date = date.today() + timedelta(days=2)
        booked_user = User.objects.create_user('scheduled_worker', first_name='Booked', last_name='Worker')
        Profile.objects.update_or_create(user=booked_user, defaults={'role': Profile.WORKER})
        booked_worker = Worker.objects.create(user=booked_user, position='Senior Stylist')
        available_user = User.objects.create_user('available_schedule_worker', first_name='Available', last_name='Worker')
        Profile.objects.update_or_create(user=available_user, defaults={'role': Profile.WORKER})
        Worker.objects.create(user=available_user, position='Nail Artist')
        off_user = User.objects.create_user('off_schedule_worker', first_name='Off', last_name='Worker')
        Profile.objects.update_or_create(user=off_user, defaults={'role': Profile.WORKER})
        Worker.objects.create(user=off_user, is_active=False)
        Appointment.objects.create(client=self.customer, service=self.service, worker=booked_worker, appointment_date=schedule_date, appointment_time='10:00')
        owner = User.objects.create_user('schedule_owner', password='pass-123')
        Profile.objects.update_or_create(user=owner, defaults={'role': Profile.OWNER})
        self.client.login(username='schedule_owner', password='pass-123')

        response = self.client.get('/owner/', {'schedule_date': schedule_date.isoformat()})

        self.assertContains(response, 'Booked Worker')
        self.assertContains(response, 'Available Worker')
        self.assertContains(response, 'Off Worker')
        self.assertContains(response, 'Booked')
        self.assertContains(response, 'Available')
        self.assertContains(response, 'Not active today')

    def test_sign_in_routes_are_removed(self):
        owner = User.objects.create_user('owner_login', password='pass-123', is_staff=True)
        Profile.objects.update_or_create(user=owner, defaults={'role': Profile.OWNER})
        worker = User.objects.create_user('worker_login', password='pass-123')
        Profile.objects.update_or_create(user=worker, defaults={'role': Profile.WORKER})
        Worker.objects.create(user=worker)
        self.assertEqual(self.client.get('/owner/login/').status_code, 302)
        self.assertIn('/owner/', self.client.get('/owner/login/').url)
        self.assertEqual(self.client.get('/worker/login/').status_code, 404)
        self.assertEqual(self.client.get('/accounts/login/').status_code, 404)

    def test_owner_sees_only_owner_navigation(self):
        owner = User.objects.create_user('owner_nav', password='pass-123')
        Profile.objects.update_or_create(user=owner, defaults={'role': Profile.OWNER})
        self.client.login(username='owner_nav', password='pass-123')
        content = self.client.get('/owner/').content.decode()
        self.assertIn('Owner Dashboard', content)
        self.assertNotIn('Worker Login', content)
        self.assertNotIn('Worker Dashboard', content)
        self.assertNotIn('Owner Admin', content)

    def test_owner_can_hire_worker_with_secure_role(self):
        owner = User.objects.create_user('hiring_owner', password='pass-123')
        Profile.objects.update_or_create(user=owner, defaults={'role': Profile.OWNER})
        self.client.login(username='hiring_owner', password='pass-123')
        form = WorkerCreateForm(data={'first_name': 'Ava', 'last_name': 'Rose', 'username': 'ava_hired', 'email': 'ava@example.com', 'phone': '+27123456780', 'position': 'Nail Artist', 'password': 'temporary-123'})
        self.assertTrue(form.is_valid(), form.errors)
        worker = form.save()
        self.assertEqual(worker.position, 'Nail Artist')
        self.assertEqual(worker.user.profile.role, Profile.WORKER)
        self.assertTrue(worker.user.check_password('temporary-123'))

    def test_newly_hired_worker_appears_across_owner_views(self):
        owner = User.objects.create_user('everywhere_owner', password='pass-123')
        Profile.objects.update_or_create(user=owner, defaults={'role': Profile.OWNER})
        self.client.login(username='everywhere_owner', password='pass-123')

        response = self.client.post('/owner/workers/new/', {
            'first_name': 'Lerato',
            'last_name': 'Mokoena',
            'username': 'lerato_new',
            'email': 'lerato@example.com',
            'phone': '+27123456781',
            'position': 'Senior Stylist',
            'password': 'temporary-123',
        })

        self.assertRedirects(response, '/owner/workers/')
        worker = Worker.objects.get(user__username='lerato_new')
        self.assertTrue(worker.is_active)
        team_page = self.client.get('/owner/workers/').content.decode()
        dashboard_page = self.client.get('/owner/').content.decode()
        self.assertIn('lerato_new', team_page)
        self.assertIn('Lerato Mokoena', dashboard_page)
        self.assertIn('Senior Stylist', dashboard_page)

    def test_owner_team_shows_each_worker_once(self):
        owner = User.objects.create_user('team_owner', password='pass-123')
        Profile.objects.update_or_create(user=owner, defaults={'role': Profile.OWNER})
        self.client.login(username='team_owner', password='pass-123')
        worker_user = User.objects.create_user('team_worker', first_name='Ava', last_name='Rose')
        Profile.objects.update_or_create(user=worker_user, defaults={'role': Profile.WORKER})
        Worker.objects.create(user=worker_user, position='Nail Artist')

        response = self.client.get('/owner/workers/')

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content.decode().count('team_worker'), 1)

    def test_owner_report_downloads_as_pdf(self):
        owner = User.objects.create_user('report_owner', password='pass-123')
        Profile.objects.update_or_create(user=owner, defaults={'role': Profile.OWNER})
        self.client.login(username='report_owner', password='pass-123')

        response = self.client.get('/reports.csv?period=month')

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'application/pdf')
        self.assertTrue(response.content.startswith(b'%PDF'))
        self.assertIn('.pdf', response['Content-Disposition'])

    def test_service_management_is_owner_only_and_returns_to_dashboard(self):
        public_page = self.client.get('/services/')
        self.assertNotContains(public_page, 'Add service')
        self.assertNotContains(public_page, 'Edit service')

        owner = User.objects.create_user('service_owner', password='pass-123')
        Profile.objects.update_or_create(user=owner, defaults={'role': Profile.OWNER})
        self.client.login(username='service_owner', password='pass-123')
        response = self.client.post('/owner/services/new/', {
            'name': 'Signature Blowout',
            'description': 'A polished finish.',
            'duration_minutes': 60,
            'price': '350.00',
            'is_active': 'on',
        })

        self.assertRedirects(response, '/owner/')
        self.assertTrue(Service.objects.filter(name='Signature Blowout').exists())

        owner_services_page = self.client.get('/services/')
        self.assertNotContains(owner_services_page, 'Add service')
        self.assertNotContains(owner_services_page, 'Edit service')

    def test_assigned_worker_sees_client_details(self):
        worker_user = User.objects.create_user('assigned_worker', password='pass-123')
        Profile.objects.update_or_create(user=worker_user, defaults={'role': Profile.WORKER})
        worker = Worker.objects.create(user=worker_user, position='Braider')
        appointment = Appointment.objects.create(client=self.customer, service=self.service, worker=worker, appointment_date=date.today(), appointment_time=(datetime.now() + timedelta(hours=1)).time())
        self.client.login(username='assigned_worker', password='pass-123')
        response = self.client.get('/dashboard/')
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.customer.full_name)
        self.assertContains(response, appointment.service.name)
        self.assertContains(response, 'Assigned clients')

    def test_owner_team_analysis_updates_when_booking_is_assigned(self):
        owner = User.objects.create_user('analysis_owner', password='pass-123')
        Profile.objects.update_or_create(user=owner, defaults={'role': Profile.OWNER})
        worker_user = User.objects.create_user('analysis_worker', password='pass-123')
        Profile.objects.update_or_create(user=worker_user, defaults={'role': Profile.WORKER})
        worker = Worker.objects.create(user=worker_user, position='Braider')
        Appointment.objects.create(client=self.customer, service=self.service, worker=worker, appointment_date=date.today(), appointment_time=(datetime.now() + timedelta(hours=2)).time())
        self.client.login(username='analysis_owner', password='pass-123')
        response = self.client.get('/owner/')
        self.assertContains(response, '1</b> assigned')
        self.assertContains(response, '0.00')

    def test_superuser_can_access_owner_dashboard(self):
        owner = User.objects.create_superuser('super_owner', email='owner@example.com', password='pass-123')
        self.client.login(username='super_owner', password='pass-123')
        self.assertEqual(self.client.get('/owner/').status_code, 200)
        self.assertEqual(owner.profile.role, Profile.OWNER)

    def test_booking_rejects_time_when_only_worker_is_busy(self):
        future = date.today() + timedelta(days=4)
        worker_user = User.objects.create_user('busy_worker', password='pass-123')
        Profile.objects.update_or_create(user=worker_user, defaults={'role': Profile.WORKER})
        worker = Worker.objects.create(user=worker_user)
        Appointment.objects.create(client=self.customer, service=self.service, worker=worker, paid_at=timezone.now(), appointment_date=future, appointment_time='10:00')
        form = BookingForm(data={'customer_name': 'Busy Slot', 'phone': '+27111111114', 'email': 'busy@example.com', 'service': self.service.pk, 'appointment_date': future, 'appointment_time': '10:00', 'notes': ''})
        self.assertFalse(form.is_valid())
        self.assertIn('No worker is available', str(form.errors))

    def test_availability_endpoint_recommends_open_slots(self):
        future = date.today() + timedelta(days=4)
        worker_user = User.objects.create_user('slot_worker', password='pass-123')
        Profile.objects.update_or_create(user=worker_user, defaults={'role': Profile.WORKER})
        worker = Worker.objects.create(user=worker_user)
        Appointment.objects.create(client=self.customer, service=self.service, worker=worker, paid_at=timezone.now(), appointment_date=future, appointment_time='10:00')
        response = self.client.get('/booked-times/', {'date': future.isoformat(), 'service': self.service.pk})
        self.assertEqual(response.status_code, 200)
        self.assertIn('10:00', response.json()['booked_times'])
        self.assertTrue(response.json()['available_slots'])

    def test_assigned_walk_in_updates_owner_performance_and_roster(self):
        owner = User.objects.create_user('walkin_owner', password='pass-123')
        Profile.objects.update_or_create(user=owner, defaults={'role': Profile.OWNER})
        worker_user = User.objects.create_user('walkin_worker', password='pass-123', first_name='Walkin', last_name='Artist')
        Profile.objects.update_or_create(user=worker_user, defaults={'role': Profile.WORKER})
        worker = Worker.objects.create(user=worker_user)
        WalkIn.objects.create(client=self.customer, service=self.service, worker=worker, amount=Decimal('300'), start_time=timezone.now())
        self.client.login(username='walkin_owner', password='pass-123')
        response = self.client.get('/owner/')
        self.assertContains(response, 'Walkin Artist')
        self.assertContains(response, '1</b> assigned')
        self.assertContains(response, 'R 300.00')

    def test_owner_can_view_client_details_and_assign_available_worker(self):
        future = date.today() + timedelta(days=5)
        owner = User.objects.create_user('appointment_owner', password='pass-123')
        Profile.objects.update_or_create(user=owner, defaults={'role': Profile.OWNER})
        worker_user = User.objects.create_user('available_worker', password='pass-123', first_name='Available')
        Profile.objects.update_or_create(user=worker_user, defaults={'role': Profile.WORKER})
        worker = Worker.objects.create(user=worker_user)
        busy_user = User.objects.create_user('busy_owner_choice', password='pass-123', first_name='Busy')
        Profile.objects.update_or_create(user=busy_user, defaults={'role': Profile.WORKER})
        busy_worker = Worker.objects.create(user=busy_user)
        Appointment.objects.create(client=self.customer, service=self.service, worker=busy_worker, appointment_date=future, appointment_time='14:00')
        inactive_user = User.objects.create_user('inactive_owner_choice', password='pass-123', first_name='Inactive')
        Profile.objects.update_or_create(user=inactive_user, defaults={'role': Profile.WORKER})
        Worker.objects.create(user=inactive_user, is_active=False)
        appointment = Appointment.objects.create(client=self.customer, service=self.service, appointment_date=future, appointment_time='14:00', notes='Bring braid reference')
        self.client.login(username='appointment_owner', password='pass-123')
        response = self.client.get(f'/owner/appointments/{appointment.pk}/')
        self.assertContains(response, self.customer.phone)
        self.assertContains(response, 'Bring braid reference')
        response = self.client.post(f'/owner/appointments/{appointment.pk}/', {'worker': worker.pk, 'status': Appointment.CONFIRMED, 'notes': 'Assigned'})
        self.assertRedirects(response, '/owner/')
        dashboard = self.client.get(response.url)
        self.assertContains(dashboard, 'PRIVATE OWNER SPACE')
        appointment.refresh_from_db()
        self.assertEqual(appointment.worker, worker)

    def test_owner_can_reassign_walk_in_to_available_worker(self):
        first_user = User.objects.create_user('walkin_first', first_name='First')
        Profile.objects.update_or_create(user=first_user, defaults={'role': Profile.WORKER})
        first_worker = Worker.objects.create(user=first_user)
        second_user = User.objects.create_user('walkin_second', first_name='Second')
        Profile.objects.update_or_create(user=second_user, defaults={'role': Profile.WORKER})
        second_worker = Worker.objects.create(user=second_user)
        walk_in = WalkIn.objects.create(client=self.customer, service=self.service, worker=first_worker, amount=Decimal('250'))
        form = WalkInManageForm(instance=walk_in)

        self.assertIn(first_worker, form.fields['worker'].queryset)
        self.assertIn(second_worker, form.fields['worker'].queryset)
        form = WalkInManageForm({'worker': second_worker.pk, 'style': '', 'style_details': '', 'amount': '250.00', 'satisfaction': '', 'notes': ''}, instance=walk_in)
        self.assertTrue(form.is_valid(), form.errors)
        form.save()
        walk_in.refresh_from_db()
        self.assertEqual(walk_in.worker, second_worker)

    def test_worker_completing_walk_in_records_time_and_frees_worker(self):
        worker_user = User.objects.create_user('completion_worker', password='pass-123')
        Profile.objects.update_or_create(user=worker_user, defaults={'role': Profile.WORKER})
        worker = Worker.objects.create(user=worker_user)
        walk_in = WalkIn.objects.create(client=self.customer, service=self.service, worker=worker, amount=Decimal('250'))
        self.client.login(username='completion_worker', password='pass-123')

        response = self.client.post(f'/walk-ins/{walk_in.pk}/complete/')

        self.assertRedirects(response, '/dashboard/')
        walk_in.refresh_from_db()
        self.assertIsNotNone(walk_in.completed_at)
        self.assertIsNotNone(walk_in.time_spent_minutes)
        available_form = WalkInManageForm(instance=walk_in)
        self.assertIn(worker, available_form.fields['worker'].queryset)

    def test_worker_can_view_unassigned_appointment_and_assign_free_worker(self):
        future = date.today() + timedelta(days=5)
        worker_user = User.objects.create_user('queue_worker', password='pass-123', first_name='Queue')
        Profile.objects.update_or_create(user=worker_user, defaults={'role': Profile.WORKER})
        worker = Worker.objects.create(user=worker_user)
        appointment = Appointment.objects.create(client=self.customer, service=self.service, appointment_date=future, appointment_time='15:00')
        self.client.login(username='queue_worker', password='pass-123')
        response = self.client.get('/owner/appointments/')
        self.assertContains(response, self.customer.full_name)
        response = self.client.post(f'/owner/appointments/{appointment.pk}/', {'worker': worker.pk, 'status': Appointment.CONFIRMED, 'notes': ''})
        self.assertRedirects(response, '/owner/appointments/')
        appointment.refresh_from_db()
        self.assertEqual(appointment.worker, worker)

    def test_appointments_queue_hides_past_records_but_report_period_keeps_them(self):
        yesterday = timezone.localdate() - timedelta(days=1)
        old_appointment = Appointment.objects.create(client=self.customer, service=self.service, appointment_date=yesterday, appointment_time='10:00', status=Appointment.COMPLETED)
        today_appointment = Appointment.objects.create(client=self.customer, service=self.service, appointment_date=timezone.localdate(), appointment_time='11:00')
        owner = User.objects.create_user('history_owner', password='pass-123')
        Profile.objects.update_or_create(user=owner, defaults={'role': Profile.OWNER})
        self.client.login(username='history_owner', password='pass-123')

        queue_response = self.client.get('/owner/appointments/')
        self.assertNotContains(queue_response, f'/owner/appointments/{old_appointment.pk}/')
        self.assertContains(queue_response, f'/owner/appointments/{today_appointment.pk}/')

        report_response = self.client.get('/reports.csv', {'start': yesterday.isoformat(), 'end': timezone.localdate().isoformat()})
        self.assertEqual(report_response.status_code, 200)
        self.assertTrue(report_response.content.startswith(b'%PDF'))

    def test_busy_worker_is_not_available_for_assignment(self):
        future = date.today() + timedelta(days=6)
        worker_user = User.objects.create_user('already_busy', password='pass-123')
        Profile.objects.update_or_create(user=worker_user, defaults={'role': Profile.WORKER})
        worker = Worker.objects.create(user=worker_user)
        Appointment.objects.create(client=self.customer, service=self.service, worker=worker, paid_at=timezone.now(), appointment_date=future, appointment_time='10:00')
        appointment = Appointment.objects.create(client=self.customer, service=self.service, appointment_date=future, appointment_time='10:00')
        form = AppointmentManageForm(instance=appointment)
        self.assertNotIn(worker, form.fields['worker'].queryset)

    @override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend')
    def test_owner_can_delete_appointment_and_client_is_notified(self):
        future = date.today() + timedelta(days=7)
        owner = User.objects.create_user('delete_owner', password='pass-123')
        Profile.objects.update_or_create(user=owner, defaults={'role': Profile.OWNER})
        client = Client.objects.create(full_name='Email Client', phone='+27123456780', email='client@example.com')
        appointment = Appointment.objects.create(client=client, service=self.service, appointment_date=future, appointment_time='16:00')
        self.client.login(username='delete_owner', password='pass-123')
        response = self.client.post(f'/owner/appointments/{appointment.pk}/delete/')
        self.assertRedirects(response, '/owner/appointments/')
        self.assertFalse(Appointment.objects.filter(pk=appointment.pk).exists())

    def test_checked_in_appointment_appears_in_owner_clients_inside(self):
        owner = User.objects.create_user('inside_owner', password='pass-123')
        Profile.objects.update_or_create(user=owner, defaults={'role': Profile.OWNER})
        worker_user = User.objects.create_user('inside_worker', password='pass-123', first_name='Inside')
        Profile.objects.update_or_create(user=worker_user, defaults={'role': Profile.WORKER})
        worker = Worker.objects.create(user=worker_user)
        appointment = Appointment.objects.create(client=self.customer, service=self.service, worker=worker, status=Appointment.CHECKED_IN, appointment_date=date.today(), appointment_time='16:00')
        self.client.login(username='inside_owner', password='pass-123')
        response = self.client.get('/owner/')
        self.assertContains(response, appointment.client.full_name)
        self.assertContains(response, 'Checked In')
        self.assertContains(response, 'Inside')

