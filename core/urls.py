from django.urls import path
from . import views

urlpatterns = [
    path('', views.home, name='home'), path('website/', views.home, name='website_home'), path('about/', views.about, name='about'),
    path('services/', views.services, name='services'), path('gallery/', views.gallery, name='gallery'),
    path('contact/', views.contact, name='contact'), path('book/', views.book, name='book'),
    path('owner/login/', views.owner_login_redirect, name='owner_login'),
    path('booked-times/', views.booked_times, name='booked_times'),
    path('dashboard/', views.dashboard, name='dashboard'), path('owner/', views.owner_dashboard, name='owner_dashboard'), path('owner/preview/', views.owner_preview, name='owner_preview'),
    path('owner/appointments/', views.appointment_list, name='owner_appointments'), path('owner/appointments/<int:pk>/', views.appointment_manage, name='appointment_manage'), path('owner/appointments/<int:pk>/delete/', views.appointment_delete, name='appointment_delete'),
    path('owner/clients/', views.client_list, name='owner_clients'), path('owner/clients/new/', views.client_edit, name='client_create'), path('owner/clients/<int:pk>/', views.client_detail, name='client_detail'), path('owner/clients/<int:pk>/edit/', views.client_edit, name='client_edit'),
    path('owner/workers/', views.worker_list, name='owner_workers'), path('owner/workers/<int:pk>/', views.worker_detail, name='worker_detail'), path('owner/workers/new/', views.worker_create, name='worker_create'), path('owner/workers/<int:pk>/toggle/', views.worker_toggle, name='worker_toggle'), path('owner/services/new/', views.service_manage, name='service_create'), path('owner/services/<int:pk>/edit/', views.service_manage, name='service_edit'),
    path('walk-ins/new/', views.walk_in_create, name='walk_in_create'), path('reports.csv', views.report_csv, name='report_csv'),
]
