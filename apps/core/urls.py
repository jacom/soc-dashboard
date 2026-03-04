from django.urls import path
from . import views

app_name = 'core'

urlpatterns = [
    path('', views.dashboard, name='dashboard'),
    path('check-update/', views.check_update, name='check_update'),
    path('do-update/', views.do_update, name='do_update'),
]
