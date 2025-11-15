from django.urls import path
from . import views

app_name = 'advertising'

urlpatterns = [
    # Add your URL patterns here
    path('get-carousel-ads/', views.get_carousel_ads, name='get-carousel-ads'),
]
