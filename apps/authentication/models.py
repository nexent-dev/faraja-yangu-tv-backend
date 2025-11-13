from django.db import models
from django.contrib.auth.models import AbstractUser
from core.base_model import BaseModel

# Create your models here.

class Role(BaseModel):
    
    class ROLES(models.TextChoices):
        ADMIN = 'ADMIN'
        USER = 'USER'
        EDITOR = 'EDITOR'
    
    name = models.CharField(max_length=255, choices=ROLES.choices, default=ROLES.USER)
    description = models.TextField()
    
class Profile(BaseModel):
    bio = models.TextField(null=True, blank=True)
    location = models.CharField(max_length=255, null=True, blank=True)
    is_phone_verified = models.BooleanField(default=False)
    phone_number = models.CharField(max_length=255, null=True, blank=True)
    phone_number_country_code = models.CharField(max_length=255, null=True, blank=True)
    country_short_code = models.CharField(max_length=255, null=True, blank=True)
    birth_date = models.DateField(null=True, blank=True)
    preferences = models.JSONField(null=True, blank=True)
    credit_accumulation = models.IntegerField(default=0)
    avatar = models.ImageField(upload_to='avatars', null=True, blank=True)    

class User(AbstractUser):
    
    profile = models.OneToOneField('authentication.Profile', related_name='user', on_delete=models.CASCADE, null=True, blank=True)
    is_verified = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)
    date_joined = models.DateTimeField(auto_now_add=True)
    last_login = models.DateTimeField(auto_now=True)
    auth_provider = models.CharField(max_length=255)
    roles = models.ManyToManyField('authentication.Role', related_name='users', default=Role.ROLES.USER)
    
class OTP(BaseModel):
    user = models.OneToOneField('authentication.User', related_name='otp', on_delete=models.CASCADE)
    otp = models.CharField(max_length=255)
    expires_at = models.DateTimeField(auto_now_add=True)