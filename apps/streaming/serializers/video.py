from rest_framework import serializers
from apps.streaming.models import Video


class VideoSerializer(serializers.ModelSerializer):
    """
    Serializer for Video model with HLS streaming support.
    """
    streaming_url = serializers.ReadOnlyField()
    is_ready_for_streaming = serializers.ReadOnlyField()
    
    class Meta:
        model = Video
        fields = '__all__'
        read_only_fields = [
            'hls_master_playlist', 
            'hls_path', 
            'processing_status',
            'processing_error',
            'duration',
            'streaming_url',
            'is_ready_for_streaming'
        ]
