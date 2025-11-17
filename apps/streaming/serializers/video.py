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


class VideoLightSerializer(serializers.ModelSerializer):
    """
    Lightweight serializer for Video model with only essential fields.
    Used for listing videos in categories or feeds.
    """
    class Meta:
        model = Video
        fields = [
            'id',
            'uid',
            'created_at',
            'updated_at',
            'is_published',
            'title',
            'description',
            'slug',
            'thumbnail',
            'duration',
            'views_count',
            'likes_count',
            'dislikes_count'
        ]

class VideoFeedSerializer(serializers.ModelSerializer):
    """Serializer for video feed with category and parent category info."""

    category_id = serializers.IntegerField(source='category.id', read_only=True)
    category_name = serializers.CharField(source='category.name', read_only=True)
    parent_category_id = serializers.SerializerMethodField()
    parent_category_name = serializers.SerializerMethodField()

    class Meta:
        model = Video
        fields = [
            'id',
            'uid',
            'created_at',
            'updated_at',
            'is_published',
            'title',
            'description',
            'slug',
            'thumbnail',
            'duration',
            'views_count',
            'likes_count',
            'dislikes_count',
            'category_id',
            'category_name',
            'parent_category_id',
            'parent_category_name',
        ]

    def get_parent_category_id(self, obj):
        category = getattr(obj, 'category', None)
        parent = getattr(category, 'parent', None) if category else None
        return parent.id if parent else None

    def get_parent_category_name(self, obj):
        category = getattr(obj, 'category', None)
        parent = getattr(category, 'parent', None) if category else None
        return parent.name if parent else None


class VideoHistorySerializer(VideoFeedSerializer):
    """Simplified watch history serializer based on VideoFeedSerializer.

    The API spec mentions `last_watched_at`, but since we're using a plain
    ManyToMany relation on Profile without per-item timestamps, this field is
    provided as null for now.
    """

    last_watched_at = serializers.SerializerMethodField()

    class Meta(VideoFeedSerializer.Meta):
        fields = VideoFeedSerializer.Meta.fields + ['last_watched_at']

    def get_last_watched_at(self, obj):  # pragma: no cover - placeholder
        return None


class FavoriteVideoSerializer(VideoFeedSerializer):
    """Simplified favorites serializer based on VideoFeedSerializer.

    The API spec mentions `favorited_at`, but we don't persist timestamps yet,
    so it is always null in this first version.
    """

    favorited_at = serializers.SerializerMethodField()

    class Meta(VideoFeedSerializer.Meta):
        fields = VideoFeedSerializer.Meta.fields + ['favorited_at']

    def get_favorited_at(self, obj):  # pragma: no cover - placeholder
        return None