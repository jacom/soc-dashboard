from django.contrib import admin
from django.urls import path, include
from django.contrib.auth import views as auth_views

urlpatterns = [
    path('admin/', admin.site.urls),
    path('login/', auth_views.LoginView.as_view(template_name='registration/login.html'), name='login'),
    path('logout/', auth_views.LogoutView.as_view(), name='logout'),
    path('', include('apps.core.urls')),
    path('alerts/', include('apps.alerts.urls')),
    path('incidents/', include('apps.incidents.urls')),
    path('notifications/', include('apps.notifications.urls')),
    path('api/alerts/', include('apps.alerts.api_urls')),
    path('api/incidents/', include('apps.incidents.api_urls')),
    path('api/notifications/', include('apps.notifications.api_urls')),
    path('api-auth/', include('rest_framework.urls')),
    path('settings/', include('apps.config.urls')),
]
