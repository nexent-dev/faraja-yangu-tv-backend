from django.db import models
from core.base_model import BaseModel

# Create your models here.

class Ad(BaseModel):
    
    class AD_TYPES(models.TextChoices):
        BANNER = 'BANNER'
        VIDEO = 'VIDEO'
    
    name = models.CharField(max_length=255)
    description = models.TextField()
    slug = models.SlugField(unique=True)
    type = models.CharField(max_length=255, choices=AD_TYPES.choices, default=AD_TYPES.BANNER)
    thumbnail = models.ImageField(upload_to='ads', null=True, blank=True)
    video = models.FileField(upload_to='ads', null=True, blank=True)
    duration = models.DurationField(null=True, blank=True)
    uploaded_by = models.ForeignKey('authentication.User', related_name='ads', on_delete=models.CASCADE)
    views_count = models.IntegerField(default=0)
    likes_count = models.IntegerField(default=0)
    dislikes_count = models.IntegerField(default=0)
    is_published = models.BooleanField(default=False)
    
    
    def __str__(self):
        return self.name