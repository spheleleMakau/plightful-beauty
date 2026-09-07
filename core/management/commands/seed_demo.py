from datetime import date, timedelta
from django.core.management.base import BaseCommand
from django.contrib.auth.models import User
from core.models import Client, Service, Worker


class Command(BaseCommand):
    help = 'Load clearly labelled development data for Plightful Beauty.'

    def handle(self, *args, **options):
        services = [
            ('Silk Press', 'A polished, nourishing finish.', 120, 450),
            ('Protective Styling', 'Thoughtful styling for everyday ease.', 180, 650),
            ('Gel Manicure', 'A clean, lasting manicure.', 60, 280),
            ('Nails', 'Refined nail care for a beautifully finished look.', 60, 280),
            ('Installation', 'A seamless, polished installation tailored to you.', 180, 650),
            ('Braids', 'Protective braiding with a considered finish.', 180, 650),
            ('Braids & Nails', 'A complete braided look with matching nail care.', 240, 850),
        ]
        for name, description, duration, price in services:
            Service.objects.get_or_create(name=name, defaults={'description': description, 'duration_minutes': duration, 'price': price})
        for username, first_name, last_name in [('demo_worker', 'Demo', 'Worker')]:
            user, created = User.objects.get_or_create(username=username, defaults={'first_name': first_name, 'last_name': last_name})
            if created:
                user.set_password('demo-password-change-me'); user.save()
            Worker.objects.get_or_create(user=user, defaults={'position': 'Beauty Specialist', 'phone': '+27000000000'})
        for name, phone in [('Demo Client', '+27110000000'), ('Returning Demo Client', '+27110000001')]:
            Client.objects.get_or_create(phone=phone, defaults={'full_name': name, 'email': f'{phone[-4:]}@example.com'})
        self.stdout.write(self.style.SUCCESS('Demo data loaded. Demo accounts are for development only.'))