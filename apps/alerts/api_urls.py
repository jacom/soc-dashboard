from django.urls import path, include
from rest_framework.routers import DefaultRouter
from . import api_views
from .webhook_views import wazuh_webhook

router = DefaultRouter()
router.register(r'', api_views.AlertViewSet, basename='alert')

urlpatterns = [
    path('wazuh-webhook/', wazuh_webhook, name='wazuh_webhook'),
] + router.urls
