from django.db import models
from apps.common.models import TimeStampedModel
from core.base_model import BaseModel

# Create your models here.

class Category(BaseModel):
    name = models.CharField(max_length=255)
    description = models.TextField()
    slug = models.SlugField(unique=True)
    thumbnail = models.ImageField(upload_to='categories', null=True, blank=True)
    cover = models.ImageField(upload_to='categories', null=True, blank=True)
    parent = models.ForeignKey('self', related_name='subcategories', on_delete=models.CASCADE, null=True, blank=True)

    def __str__(self):
        return self.name




class Video(BaseModel):
    PROCESSING_STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('processing', 'Processing'),
        ('completed', 'Completed'),
        ('failed', 'Failed'),
    ]
    
    title = models.CharField(max_length=255)
    description = models.TextField()
    slug = models.SlugField(unique=True, null=True, blank=True)
    thumbnail = models.ImageField(upload_to='videos', null=True, blank=True)
    category = models.ForeignKey(Category, related_name='videos', on_delete=models.CASCADE, null=True, blank=True )
    
    # Original uploaded video (will be deleted after HLS conversion)
    video = models.FileField(upload_to='videos/originals', null=True, blank=True)
    
    # HLS streaming fields
    hls_master_playlist = models.CharField(max_length=500, null=True, blank=True, 
                                          help_text='Path to HLS master playlist (master.m3u8)')
    hls_path = models.CharField(max_length=500, null=True, blank=True,
                               help_text='Base directory path for HLS files')
    processing_status = models.CharField(max_length=20, choices=PROCESSING_STATUS_CHOICES, 
                                        default='pending')
    processing_error = models.TextField(null=True, blank=True)
    
    duration = models.DurationField(null=True, blank=True)
    uploaded_by = models.ForeignKey('authentication.User', related_name='videos', on_delete=models.CASCADE)
    views_count = models.IntegerField(default=0)
    likes_count = models.IntegerField(default=0)
    dislikes_count = models.IntegerField(default=0)
    is_published = models.BooleanField(default=False)
    is_live = models.BooleanField(default=False)
    
    def __str__(self):
        return self.title
    
    @property
    def is_ready_for_streaming(self):
        """Check if video is ready for HLS streaming."""
        return self.processing_status == 'completed' and self.hls_master_playlist
    
    @property
    def streaming_url(self):
        """Get the streaming URL for the video."""
        if self.is_ready_for_streaming:
            return f"{self.hls_path}/master.m3u8"
        return None
    

class Comment(BaseModel):
    video = models.ForeignKey(Video, related_name='comments', on_delete=models.CASCADE)
    user = models.ForeignKey('authentication.User', related_name='comments', on_delete=models.CASCADE)
    comment = models.TextField()
    reply_to = models.ForeignKey('self', related_name='replies', on_delete=models.CASCADE, null=True, blank=True)
    interaction_time = models.DurationField(null=True, blank=True)
    
    def __str__(self):
        return self.comment
    

class Like(BaseModel):
    video = models.ForeignKey(Video, related_name='likes', on_delete=models.CASCADE)
    user = models.ForeignKey('authentication.User', related_name='likes', on_delete=models.CASCADE)
    interaction_time = models.DurationField(null=True, blank=True)
    
    def __str__(self):
        return f'{self.user} likes {self.video}'
    
class Dislike(BaseModel):
    video = models.ForeignKey(Video, related_name='dislikes', on_delete=models.CASCADE)
    user = models.ForeignKey('authentication.User', related_name='dislikes', on_delete=models.CASCADE)
    interaction_time = models.DurationField(null=True, blank=True)
    
    def __str__(self):
        return f'{self.user} dislikes {self.video}'


class View(BaseModel):
    video = models.ForeignKey(Video, related_name='views', on_delete=models.CASCADE)
    user = models.ForeignKey('authentication.User', related_name='views', on_delete=models.CASCADE)
    watch_time = models.DurationField(null=True, blank=True)
    
    def __str__(self):
        return f'{self.user} views {self.video}'

class VideoAdSlot(BaseModel):
    """Interceptor ad slot - defines when an ad break should occur during video playback."""
    
    class MediaType(models.TextChoices):
        IMAGE = 'image', 'Image'
        VIDEO = 'video', 'Video'
    
    video = models.ForeignKey(Video, related_name='ad_slots', on_delete=models.CASCADE, null=True, blank=True)
    
    # Optional link to existing Ad (for reusing ads from advertising system)
    ad = models.ForeignKey('advertising.Ad', related_name='ad_slots', on_delete=models.CASCADE, null=True, blank=True)
    
    is_active = models.BooleanField(default=True)
    
    # Self-contained interceptor ad fields
    title = models.CharField(max_length=255, null=True, blank=True)
    description = models.TextField(null=True, blank=True)
    media_type = models.CharField(max_length=10, choices=MediaType.choices, default=MediaType.IMAGE)
    media_file = models.FileField(upload_to='interceptor_ads/', null=True, blank=True,
                                  help_text='Image or video file for the interceptor ad')
    redirect_link = models.URLField(max_length=500, null=True, blank=True,
                                    help_text='URL to redirect when ad is clicked')
    display_duration = models.PositiveIntegerField(default=5,
                                                   help_text='Duration in seconds to display the ad (for images)')
    
    # Timing fields
    start_time = models.TimeField(help_text='When the ad should appear during video playback')
    end_time = models.TimeField(help_text='When the ad slot ends')
    
    class Meta:
        ordering = ['start_time']
    
    def __str__(self):
        return f'{self.video} ad slot ({self.start_time} - {self.end_time})'
    
    @property
    def is_self_contained(self):
        """Check if this ad slot uses its own media instead of linked Ad."""
        return self.media_file and not self.ad
    
    def clean(self):
        """Validate that either ad or media_file is provided."""
        from django.core.exceptions import ValidationError
        if not self.ad and not self.media_file:
            raise ValidationError('Either an Ad reference or a media_file must be provided.')


class Playlist(BaseModel):
    """User playlist model for grouping videos."""

    owner = models.ForeignKey('authentication.User', related_name='playlists', on_delete=models.CASCADE)
    name = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    thumbnail = models.ImageField(upload_to='playlists', null=True, blank=True)

    def __str__(self):
        return f'{self.owner} - {self.name}'


class PlaylistVideo(BaseModel):
    """Through model for videos inside a playlist."""

    playlist = models.ForeignKey(Playlist, related_name='playlist_videos', on_delete=models.CASCADE)
    video = models.ForeignKey(Video, related_name='in_playlists', on_delete=models.CASCADE)

    class Meta:
        unique_together = ('playlist', 'video')

    def __str__(self):
        return f'{self.playlist} -> {self.video}'