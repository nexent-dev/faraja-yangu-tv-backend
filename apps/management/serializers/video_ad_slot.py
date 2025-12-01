from rest_framework import serializers
from apps.streaming.models import Video, VideoAdSlot


class VideoNestedSerializer(serializers.ModelSerializer):
    """Nested serializer for Video in interceptor ads."""
    
    class Meta:
        model = Video
        fields = ['id', 'title', 'thumbnail', 'duration']


class VideoAdSlotSerializer(serializers.ModelSerializer):
    """Serializer for VideoAdSlot model (list/detail response)."""
    
    video = VideoNestedSerializer(read_only=True)
    
    class Meta:
        model = VideoAdSlot
        fields = [
            'id',
            'video',
            'start_time',
            'end_time',
            'created_at',
        ]


class VideoAdSlotCreateSerializer(serializers.ModelSerializer):
    """Serializer for creating VideoAdSlot."""
    
    class Meta:
        model = VideoAdSlot
        fields = ['id', 'video', 'start_time', 'end_time', 'created_at']
        read_only_fields = ['id', 'created_at']
    
    def validate(self, data):
        """Validate time fields."""
        start_time = data.get('start_time')
        end_time = data.get('end_time')
        video = data.get('video')
        
        # Validate end_time > start_time
        if start_time and end_time and start_time >= end_time:
            raise serializers.ValidationError({
                'end_time': 'End time must be after start time.'
            })
        
        # Validate times are within video duration if video has duration
        if video and video.duration:
            video_duration_seconds = video.duration.total_seconds()
            
            def time_to_seconds(t):
                return t.hour * 3600 + t.minute * 60 + t.second
            
            if start_time:
                start_seconds = time_to_seconds(start_time)
                if start_seconds > video_duration_seconds:
                    raise serializers.ValidationError({
                        'start_time': 'Start time exceeds video duration.'
                    })
            
            if end_time:
                end_seconds = time_to_seconds(end_time)
                if end_seconds > video_duration_seconds:
                    raise serializers.ValidationError({
                        'end_time': 'End time exceeds video duration.'
                    })
        
        return data
    
    def validate_video(self, value):
        """Validate that video exists."""
        if not Video.objects.filter(pk=value.pk).exists():
            raise serializers.ValidationError('Video does not exist.')
        return value
