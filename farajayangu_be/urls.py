from django.contrib import admin
from django.urls import path, include

urlpatterns = [
    path('admin/', admin.site.urls),
    path('authentication/', include('apps.authentication.urls')),
    path('streaming/', include('apps.streaming.urls')),
    path('advertising/', include('apps.advertising.urls')),
    path('analytics/', include('apps.analytics.urls')),
    path('profile/', include('apps.profile.urls')),
]
