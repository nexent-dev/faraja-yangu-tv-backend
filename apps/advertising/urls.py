from django.urls import path
from . import views

app_name = 'advertising'

urlpatterns = [
    # Add your URL patterns here
    path('get-carousel-ads/', views.get_carousel_ads, name='get-carousel-ads'),
    path('create-carousel-ad/', views.create_carousel_ad, name='create-carousel-ad'),
    path('update-carousel-ad/<int:pk>/', views.update_carousel_ad, name='update-carousel-ad'),
    path('delete-carousel-ad/<int:pk>/', views.delete_carousel_ad, name='delete-carousel-ad'),
]
