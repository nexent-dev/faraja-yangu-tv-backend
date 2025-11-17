from django.urls import path
from . import views

app_name = 'management'

urlpatterns = [
    path('summary/', views.get_dashboard_summary, name='get-dashboard-summary'),
    path('clients-stats/', views.get_dashboard_client_stats, name='get-dashboard-client-stats'),
    path('dashboard-analytics-chart/', views.get_dashboard_analytics_chart, name='get-dashboard-analytics-chart'),
]
