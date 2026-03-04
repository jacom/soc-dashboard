from django.urls import path
from . import views

app_name = 'alerts'

urlpatterns = [
    path('', views.alert_list, name='list'),
    path('<int:pk>/', views.alert_detail, name='detail'),
    path('<int:pk>/analyze/', views.analyze_alert_view, name='analyze'),
    path('<int:pk>/reanalyze/', views.reanalyze_alert_view, name='reanalyze'),
    path('<int:pk>/analyze-chat/', views.analyze_chat_view, name='analyze_chat'),
    path('<int:pk>/ai-status/', views.ai_status_view, name='ai_status'),
    path('<int:pk>/raw/', views.alert_raw_data, name='raw_data'),
    path('<int:pk>/push-thehive/', views.push_to_thehive, name='push_thehive'),
    path('fetch-wazuh/', views.fetch_wazuh, name='fetch_wazuh'),
    path('bulk-dismiss/', views.bulk_dismiss, name='bulk_dismiss'),
    path('bulk-undismiss/', views.bulk_undismiss, name='bulk_undismiss'),
    path('export/csv/', views.export_alerts_csv, name='export_csv'),
]
