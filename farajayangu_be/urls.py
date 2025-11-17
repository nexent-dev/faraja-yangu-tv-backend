from django.contrib import admin
from django.urls import path, include

def trigger_error(request):
    division_by_zero = 1 / 0
    return HttpResponse("Error triggered!")

urlpatterns = [
    path('admin/', admin.site.urls),
    path('sentry-debug/', trigger_error),
    path('authentication/', include('apps.authentication.urls')),
    path('streaming/', include('apps.streaming.urls')),
    path('advertising/', include('apps.advertising.urls')),
    path('analytics/', include('apps.analytics.urls')),
    path('profile/', include('apps.profile.urls')),
    path('management/', include('apps.management.urls')),
]
