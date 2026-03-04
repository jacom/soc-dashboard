from django.urls import path
from . import views

app_name = 'incidents'

urlpatterns = [
    path('', views.incident_list, name='list'),
    path('create/', views.incident_create, name='create'),
    path('<int:pk>/', views.incident_detail, name='detail'),
    path('<int:pk>/edit/', views.incident_edit, name='edit'),
    path('<int:pk>/delete/', views.incident_delete, name='delete'),
    path('sync-thehive/', views.sync_thehive, name='sync_thehive'),
    path('export/csv/', views.export_incidents_csv, name='export_csv'),
]
