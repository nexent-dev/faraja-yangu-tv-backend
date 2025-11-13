from django.db import models
from apps.common.models import TimeStampedModel
from core.base_model import BaseModel

# Create your models here.

class Analytics(BaseModel):
    
    class ANALYTICS_TYPES(models.TextChoices):
        VIDEO = 'VIDEO'
        AD = 'AD'
        
    type = models.CharField(max_length=255, choices=ANALYTICS_TYPES.choices, default=ANALYTICS_TYPES.VIDEO)
    
    def __str__(self):
        return self.type

class Report(BaseModel):
    
    class REPORT_STATUS(models.TextChoices):
        PENDING = 'PENDING'
        APPROVED = 'APPROVED'
        REJECTED = 'REJECTED'
    
    analytics = models.ForeignKey('analytics.Analytics', related_name='reports', on_delete=models.CASCADE)
    user = models.ForeignKey('authentication.User', related_name='reports', on_delete=models.CASCADE)
    video = models.ForeignKey('streaming.Video', related_name='reports', on_delete=models.CASCADE)
    reason = models.TextField()
    details = models.TextField()
    status = models.CharField(max_length=255, choices=REPORT_STATUS.choices, default=REPORT_STATUS.PENDING)
    
    def __str__(self):
        return f'{self.user} report {self.analytics}'

class Notification(BaseModel):
    user = models.ForeignKey('authentication.User', related_name='notifications', on_delete=models.CASCADE)
    title = models.CharField(max_length=255)
    message = models.TextField()
    is_read = models.BooleanField(default=False)
    
    def __str__(self):
        return f'{self.user} notification'