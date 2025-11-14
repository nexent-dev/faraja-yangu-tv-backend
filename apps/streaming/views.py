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
from django.http import HttpResponse, Http404, FileResponse
from django.core.files.storage import default_storage
import logging
import mimetypes

logger = logging.getLogger(__name__)


def inject_ad_markers(playlist_content: str, video_slug: str, ad_interval: int = 120) -> str:
    """
    Inject ad markers into HLS playlist for client-side ad insertion.
    
    Args:
        playlist_content: Original playlist content
        video_slug: Video slug for tracking
        ad_interval: Seconds between ad breaks (default: 120 = 2 minutes)
    
    Returns:
        Modified playlist with ad markers
    """
    lines = playlist_content.split('\n')
    new_lines = []
    current_duration = 0.0
    last_ad_time = 0.0
    ad_count = 0
    
    for line in lines:
        # Track segment duration
        if line.startswith('#EXTINF:'):
            try:
                # Extract duration from #EXTINF:10.0,
                duration_str = line.split(':')[1].split(',')[0]
                segment_duration = float(duration_str)
                current_duration += segment_duration
                
                # Check if it's time for an ad break
                if current_duration - last_ad_time >= ad_interval:
                    ad_count += 1
                    # Insert ad markers before this segment
                    new_lines.append(f'#EXT-X-CUE-OUT:DURATION=30')
                    new_lines.append(f'#EXT-X-ASSET:CAID=ad-{ad_count}')
                    logger.info(f"Injected ad marker {ad_count} at {current_duration}s for {video_slug}")
                    last_ad_time = current_duration
            except (IndexError, ValueError):
                pass
        
        new_lines.append(line)
    
    return '\n'.join(new_lines)

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

@api_view(['GET'])
def stream_hls(request, video_slug, file_path):
    """
    Stream HLS files with ad injection support.
    
    This endpoint proxies HLS files from R2 storage and modifies playlists
    to inject ad markers for client-side ad insertion.
    
    Args:
        video_slug: The video slug
        file_path: Path to the HLS file (e.g., 'master.m3u8', '1080p/1080p.m3u8', '1080p/1080p_001.ts')
    
    Returns:
        HLS file with appropriate content type and ad markers
    """
    try:
        # Construct the full path in R2 storage
        storage_path = f"videos/hls/{video_slug}/{file_path}"
        
        # Check if file exists in storage
        if not default_storage.exists(storage_path):
            logger.warning(f"HLS file not found: {storage_path}")
            raise Http404("Video file not found")
        
        # Determine content type based on file extension
        content_type, _ = mimetypes.guess_type(file_path)
        if file_path.endswith('.m3u8'):
            content_type = 'application/vnd.apple.mpegurl'
        elif file_path.endswith('.ts'):
            content_type = 'video/mp2t'
        else:
            content_type = content_type or 'application/octet-stream'
        
        # For playlist files, modify content to inject ad markers
        if file_path.endswith('.m3u8'):
            # Read playlist content
            file_obj = default_storage.open(storage_path, 'rb')
            content = file_obj.read().decode('utf-8')
            file_obj.close()
            
            # Modify playlist URLs to point to backend proxy
            from django.conf import settings
            backend_url = getattr(settings, 'BACKEND_URL', 'https://backend.farajayangutv.co.tz')
            
            # Replace relative paths with backend URLs
            modified_content = content
            lines = content.split('\n')
            new_lines = []
            
            for line in lines:
                # Skip comments and empty lines
                if line.startswith('#') or not line.strip():
                    new_lines.append(line)
                    continue
                
                # If it's a file reference (not a URL), convert to backend URL
                if line.strip() and not line.startswith('http'):
                    # Construct backend URL for the file
                    if '/' in line:
                        # Variant playlist reference (e.g., "1080p/1080p.m3u8")
                        new_line = f"{backend_url}/streaming/hls/{video_slug}/{line.strip()}"
                    else:
                        # Segment reference (e.g., "1080p_001.ts")
                        # Get directory from current file_path
                        import os
                        current_dir = os.path.dirname(file_path)
                        if current_dir:
                            new_line = f"{backend_url}/streaming/hls/{video_slug}/{current_dir}/{line.strip()}"
                        else:
                            new_line = f"{backend_url}/streaming/hls/{video_slug}/{line.strip()}"
                    new_lines.append(new_line)
                else:
                    new_lines.append(line)
            
            modified_content = '\n'.join(new_lines)
            
            # Inject ad markers for variant playlists (not master playlist)
            if '/' in file_path:  # This is a variant playlist like "1080p/1080p.m3u8"
                modified_content = inject_ad_markers(modified_content, video_slug, ad_interval=120)
            
            # Return modified playlist
            response = HttpResponse(modified_content, content_type=content_type)
        else:
            # For video segments (.ts files), stream directly
            file_obj = default_storage.open(storage_path, 'rb')
            response = FileResponse(file_obj, content_type=content_type)
        
        # Add CORS headers for cross-origin streaming
        response['Access-Control-Allow-Origin'] = '*'
        response['Access-Control-Allow-Methods'] = 'GET, OPTIONS'
        response['Access-Control-Allow-Headers'] = 'Range'
        
        # Add caching headers for better performance
        if file_path.endswith('.ts'):
            # Cache segments for longer (they don't change)
            response['Cache-Control'] = 'public, max-age=31536000'
        else:
            # Cache playlists for shorter time (to allow ad updates)
            response['Cache-Control'] = 'public, max-age=10'
        
        logger.info(f"Streaming HLS file: {storage_path}")
        return response
        
    except Exception as e:
        logger.error(f"Error streaming HLS file {video_slug}/{file_path}: {str(e)}")
        raise Http404("Error loading video file")

@api_view(['GET'])
def get_video_stream_url(request, pk):
    """
    Get the streaming URL for a video.
    
    Returns:
        Video details with HLS streaming URL from R2 storage
    """
    try:
        video = Video.objects.get(pk=pk)
        
        if not video.is_ready_for_streaming:
            return error_response({
                'message': 'Video is still processing',
                'processing_status': video.processing_status
            })
        
        # Construct backend streaming URL for ad injection
        from django.conf import settings
        backend_url = getattr(settings, 'BACKEND_URL', 'https://backend.farajayangutv.co.tz')
        
        # Use backend proxy URL to enable ad injection
        stream_url = f"{backend_url}/streaming/hls/{video.slug}/master.m3u8"
        
        return success_response({
            'id': video.id,
            'title': video.title,
            'slug': video.slug,
            'stream_url': stream_url,
            'is_ready': video.is_ready_for_streaming,
            'duration': str(video.duration) if video.duration else None,
            'thumbnail': video.thumbnail.url if video.thumbnail else None,
        })
        
    except Video.DoesNotExist:
        return error_response({'message': 'Video not found'})

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
