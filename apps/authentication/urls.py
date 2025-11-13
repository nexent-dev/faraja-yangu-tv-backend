from django.urls import path
from . import views

app_name = 'authentication'

urlpatterns = [
    path('login/', views.login, name='login'),
    path('login-with-google/', views.login_with_google, name='login-with-google'),
    path('refresh/', views.refresh, name='refresh'),
    path('logout/', views.logout, name='logout'),
    path('register/', views.register, name='register'),
    path('complete-profile/', views.complete_profile, name='complete-profile'),
    path('profile/', views.profile, name='profile'),
    path('verify-user/<int:id>/', views.verify_user, name='verify-user'),
    path('verify-otp/', views.verify_otp, name='verify-otp'),
    path('send-otp/', views.send_otp, name='send-otp'),
    path('request-password-reset-with-email/', views.request_password_reset_with_email, name='request-password-reset-with-email'),
    path('request-password-reset-with-phone/', views.request_password_reset_with_phone, name='request-password-reset-with-phone'),
]
