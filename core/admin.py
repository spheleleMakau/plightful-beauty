from django.contrib import admin
from .models import Appointment, Client, ClientVisit, Profile, Review, Service, SiteSettings, WalkIn, Worker


@admin.register(SiteSettings)
class SiteSettingsAdmin(admin.ModelAdmin):
    list_display = ('salon_name', 'phone', 'email')


@admin.register(Profile)
class ProfileAdmin(admin.ModelAdmin):
    list_display = ('user', 'role', 'phone')
    list_filter = ('role',)
    search_fields = ('user__username', 'user__first_name', 'user__last_name')


@admin.register(Worker)
class WorkerAdmin(admin.ModelAdmin):
    list_display = ('user', 'position', 'joined_date', 'is_active')
    list_filter = ('is_active', 'position')
    search_fields = ('user__first_name', 'user__last_name', 'user__username')


@admin.register(Client)
class ClientAdmin(admin.ModelAdmin):
    list_display = ('full_name', 'phone', 'email', 'registered_at')
    search_fields = ('full_name', 'phone', 'email')


@admin.register(Service)
class ServiceAdmin(admin.ModelAdmin):
    list_display = ('name', 'price', 'duration_minutes', 'is_active')
    list_filter = ('is_active',)
    search_fields = ('name',)


@admin.register(Appointment)
class AppointmentAdmin(admin.ModelAdmin):
    list_display = ('appointment_date', 'appointment_time', 'client', 'service', 'worker', 'status')
    list_filter = ('status', 'appointment_date', 'service')
    search_fields = ('client__full_name', 'client__phone')


@admin.register(WalkIn)
class WalkInAdmin(admin.ModelAdmin):
    list_display = ('client', 'service', 'worker', 'amount', 'start_time', 'time_inside', 'satisfaction')
    list_filter = ('service', 'worker', 'start_time')
    search_fields = ('client__full_name', 'client__phone')

    @admin.display(description='Time inside')
    def time_inside(self, obj):
        return obj.time_spent_display


@admin.register(ClientVisit)
class ClientVisitAdmin(admin.ModelAdmin):
    list_display = ('client', 'service', 'worker', 'amount', 'visited_at')
    list_filter = ('service', 'worker')


@admin.register(Review)
class ReviewAdmin(admin.ModelAdmin):
    list_display = ('client', 'rating', 'created_at')
    list_filter = ('rating', 'created_at')
