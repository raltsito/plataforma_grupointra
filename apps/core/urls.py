from django.urls import include, path
from . import views

urlpatterns = [
    path('dashboard/', views.dashboard_view, name='dashboard'),
    path('', include('apps.core.autenticacion.urls')),
]
