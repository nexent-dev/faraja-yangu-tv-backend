from django.urls import path
from . import views

app_name = 'management'

urlpatterns = [
    path('summary/', views.get_dashboard_summary, name='get-dashboard-summary'),
    path('clients-stats/', views.get_dashboard_client_stats, name='get-dashboard-client-stats'),
    path('dashboard-analytics-chart/', views.get_dashboard_analytics_chart, name='get-dashboard-analytics-chart'),
    
    path('interceptor/ads/', views.get_interceptor_ads, name='get-interceptor-ads'),
    path('interceptor/ads/create/', views.create_interceptor_ad, name='create-interceptor-ad'),
    path('interceptor/ad/<int:pk>/', views.get_interceptor_ad, name='delete-interceptor-ad'),
    path('interceptor/ads/<int:pk>/', views.delete_interceptor_ad, name='delete-interceptor-ad'),
    path('interceptor/ads/<int:pk>/update/', views.update_interceptor_ad, name='update-interceptor-ad'),
    path('interceptor/ads/<int:pk>/toggle/', views.toggle_interceptor_ad, name='toggle-interceptor-ad'),
]
