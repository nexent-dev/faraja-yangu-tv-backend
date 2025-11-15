"""
Celery tasks for video processing and HLS conversion.
"""
import os
import logging
from datetime import timedelta
from celery import shared_task
from django.conf import settings
from django.core.files.storage import default_storage
from apps.authentication.models import User
from apps.common.services.templates import EmailTemplates, EmailTemplateType
from apps.streaming.models import Video
from apps.streaming.services.video_processor import VideoProcessor
from core.services.azure.email.main import AzureEmailService
from farajayangu_be.celery import app as celery_app
from apps.common.services.otp import OTPService
from apps.authentication.models import OTP
from django.utils.timezone import datetime
logger = logging.getLogger(__name__)

@celery_app.task(bind=True)
def send_welcome_email():
    pass

@celery_app.task(bind=True)
def send_verification_email(self, id):
    
    user: User = User.objects.get(id=id)
    
    otp: OTPService = OTPService()
    otp_code = otp.send_otp_email(user)
    
    if otp_code:
        OTP.objects.create(
            user = user,
            expires_at = datetime.now() + timedelta(minutes=otp.otp_expiry_minutes),
            otp = otp_code,
        )
    
    return

@celery_app.task(bind=True)
def send_password_reset_email(self, id):
    
    user: User = User.objects.get(id=id)
    
    otp: OTPService = OTPService()
    otp_code = otp._generate_otp()
    email_templates: EmailTemplates = EmailTemplates()
    html_content = email_templates.get_template(
        EmailTemplateType.PASSWORD_RESET,
        first_name=getattr(user, "first_name", ""),
        otp_code=otp_code,
        otp_expiry_minutes=otp.otp_expiry_minutes,
    )
    
    OTP.objects.create(
        user = user,
        expires_at = datetime.now() + timedelta(minutes=otp.otp_expiry_minutes),
        otp = otp_code,
    )

    azure = AzureEmailService(is_no_reply=True)
    azure.send_email(
        recipient_email=user.email,
        subject="Reset your Faraja Yangu TV password",
        content=html_content,
    )