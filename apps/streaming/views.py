from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from apps.streaming.serializers.video import VideoSerializer
from core.response_wrapper import success_response, error_response
from rest_framework.decorators import api_view
from .models import Category, Video
from rest_framework.permissions import IsAuthenticated, IsAdminUser
from rest_framework.decorators import permission_classes
from .serializers.category import CategorySerializer
from .tasks import convert_video_to_hls
import logging

logger = logging.getLogger(__name__)
# Create your views here.

@api_view(['POST'])
@permission_classes([IsAuthenticated])
def create_category(request):
    
    serializer = CategorySerializer(data=request.data)
    if serializer.is_valid():
        serializer.save()
        return success_response(serializer.data)
    return error_response(serializer.errors)

@api_view(['PUT'])
@permission_classes([IsAuthenticated])
def update_category(request, pk):
    category = Category.objects.get(pk=pk)
    serializer = CategorySerializer(category, data=request.data)
    if serializer.is_valid():
        serializer.save()
        return success_response(serializer.data)
    return error_response(serializer.errors)

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def get_categories(request):
    types: ('all', 'parent', 'child') = request.GET.get('type', 'all')
    
    if types == 'parent':
        categories = Category.objects.filter(parent_id=None)
    elif types == 'child':
        categories = Category.objects.filter(parent_id__isnull=False)
    else:
        categories = Category.objects.all()
    
    serializer = CategorySerializer(categories, many=True)
    return success_response(serializer.data)

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def get_category(request, pk):
    category = Category.objects.get(pk=pk)
    serializer = CategorySerializer(category)
    return success_response(serializer.data)

@api_view(['GET'])
def get_subcategories(request, category_id):
    subcategories = Category.objects.filter(parent_id=category_id)
    return success_response(subcategories)

@api_view(['GET'])
def get_subcategory(request, pk):
    subcategory = Category.objects.get(pk=pk)
    return success_response(subcategory)

@api_view(['GET'])
def get_feed(request):
    feed = Category.objects.all()
    return success_response(feed)

@api_view(['GET'])
def get_recent_feed(request):
    feed = Category.objects.all()
    return success_response(feed)

@api_view(['GET'])
def get_search(request):
    feed = Category.objects.all()
    return success_response(feed)

@api_view(['GET'])
def get_videos(request, category_id):
    feed = Category.objects.all()
    return success_response(feed)

@api_view(['GET'])
def get_banner_ads(request):
    feed = Category.objects.all()
    return success_response(feed)

@api_view(['POST'])
@permission_classes([IsAuthenticated])
def create_video(request):
    """
    Create a new video and trigger HLS conversion.
    
    The uploaded MP4 video will be automatically converted to HLS format
    with multiple quality levels (1080p, 720p, 480p, 360p) for adaptive
    bitrate streaming based on client network speed.
    """
    slug = request.data.get('title', None)
    
    data = {
        'title': request.data.get('title'),
        'description': request.data.get('description'),
        'category': request.data.get('category'),
        'thumbnail': request.data.get('thumbnail'),
        'video': request.data.get('video'),
        'slug': slug.replace(' ', '-').lower() if slug else None,
        'uploaded_by': request.user.id,
        'processing_status': 'pending'  # Initial status
    }
    
    serializer = VideoSerializer(data=data)
    if serializer.is_valid():
        # Save the video object
        video = serializer.save()
        
        # Trigger async HLS conversion task
        try:
            task = convert_video_to_hls.delay(video.id)
            logger.info(f"Queued HLS conversion task {task.id} for video {video.id}")
            message = 'Video uploaded successfully. HLS conversion in progress.'
        except Exception as e:
            # If Celery/Redis is not available, log the error
            logger.error(f"Could not queue video conversion task for video {video.id}: {str(e)}", exc_info=True)
            message = 'Video uploaded successfully. Conversion will start when processing service is available.'
        
        # Return response with processing status
        response_data = serializer.data
        response_data['message'] = message
        response_data['processing_status'] = 'pending'
        
        return success_response(response_data)
    return error_response(serializer.errors)

@api_view(['PUT'])
@permission_classes([IsAuthenticated])
def update_video(request, pk):
    video = Video.objects.get(pk=pk)
    serializer = VideoSerializer(video, data=request.data)
    if serializer.is_valid():
        serializer.save()
        return success_response(serializer.data)
    return error_response(serializer.errors)

@api_view(['DELETE'])
@permission_classes([IsAuthenticated])
def delete_video(request, pk):
    video = Video.objects.get(pk=pk)
    video.delete()
    return success_response()

@api_view(['GET'])
def get_all_videos(request):
    feed = Video.objects.all()
    serializer = VideoSerializer(feed, many=True)
    return success_response(serializer.data)

@api_view(['GET'])
def get_video(request, pk):
    feed = Video.objects.get(pk=pk)
    serializer = VideoSerializer(feed)
    return success_response(feed)

@api_view(['GET'])
def get_video_comments(request, pk):
    feed = Category.objects.all()
    return success_response(feed)

@api_view(['GET'])
def get_video_related(request, video_id):
    feed = Category.objects.all()
    return success_response(feed)

@api_view(['POST'])
def like_video(request, video_id):
    feed = Category.objects.all()
    return success_response(feed)

@api_view(['POST'])
def dislike_video(request, video_id):
    feed = Category.objects.all()
    return success_response(feed)

@api_view(['POST'])
def like_comment(request, comment_id):
    feed = Category.objects.all()
    return success_response(feed)

@api_view(['POST'])
def dislike_comment(request, comment_id):
    feed = Category.objects.all()
    return success_response(feed)

@api_view(['POST'])
def comment(request, video_id):
    feed = Category.objects.all()
    return success_response(feed)

@api_view(['POST'])
def reply(request, comment_id):
    feed = Category.objects.all()
    return success_response(feed)

@api_view(['POST'])
def view(request, video_id):
    feed = Category.objects.all()
    return success_response(feed)
