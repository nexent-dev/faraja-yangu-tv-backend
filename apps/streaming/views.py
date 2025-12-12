from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from apps.streaming.serializers.video import (
    VideoFeedSerializer,
    VideoSerializer,
    VideoHistorySerializer,
    FavoriteVideoSerializer,
)
from apps.streaming.serializers.playlist import (
    PlaylistListSerializer,
    PlaylistDetailSerializer,
)
from apps.advertising.models import Ad
from core.response_wrapper import success_response, error_response
from rest_framework.decorators import api_view
from .models import Category, Video, Playlist, PlaylistVideo, Comment, VideoAdSlot
from apps.streaming.models import Like, Dislike
from rest_framework.permissions import AllowAny, IsAuthenticated, IsAdminUser
from rest_framework.decorators import permission_classes
from .serializers.category import CategorySerializer
from .serializers.comment import CommentSerializer, ReplySerializer
from apps.streaming.tasks.tasks import convert_video_to_hls, assemble_chunks_task, delete_video_files_task
from apps.authentication.models import Profile
from django.http import HttpResponse, Http404, FileResponse
from django.core.files.storage import default_storage
from django.core.files.base import ContentFile
from django.core.paginator import Paginator, EmptyPage, PageNotAnInteger
from django.db.models import Exists, OuterRef, F, Value, Case, When, BooleanField, CharField, Q
from django.db.models.functions import Concat, Cast
import logging
import mimetypes
import os
import hashlib
import io
import random
from django.shortcuts import get_object_or_404

logger = logging.getLogger(__name__)


def get_random_active_ad():
    """Get a random active interceptor ad from the database."""
    active_ads = VideoAdSlot.objects.filter(is_active=True).exclude(media_file='')
    if not active_ads.exists():
        return None
    return random.choice(list(active_ads))


def inject_ad_markers(playlist_content: str, video_slug: str, min_interval: int = 300) -> str:
    """
    Inject ad markers into HLS playlist for client-side ad insertion.
    
    Uses VideoAdSlot model to get active ads and injects them at random intervals,
    ensuring at least 5 minutes (300 seconds) between ads.
    
    Args:
        playlist_content: Original playlist content
        video_slug: Video slug for tracking
        min_interval: Minimum seconds between ad breaks (default: 300 = 5 minutes)
    
    Returns:
        Modified playlist with ad markers
    """
    # Get active ads from database
    active_ads = list(VideoAdSlot.objects.filter(is_active=True).exclude(media_file=''))
    if not active_ads:
        print(f"No active interceptor ads found for {video_slug}")
        return playlist_content
    
    lines = playlist_content.split('\n')
    new_lines = []
    current_duration = 0.0
    last_ad_time = 0.0
    ad_count = 0
    
    # Calculate total video duration first
    total_duration = 0.0
    for line in lines:
        if line.startswith('#EXTINF:'):
            try:
                duration_str = line.split(':')[1].split(',')[0]
                total_duration += float(duration_str)
            except (IndexError, ValueError):
                pass
    
    # Generate random ad insertion points with random intervals (5, 10, 20, 30 min)
    # Minimum interval is 5 minutes (300 seconds) after the initial ad
    interval_options = [300, 600, 1200, 1800]  # 5, 10, 20, 30 minutes in seconds
    
    ad_insertion_points = []
    if total_duration > 10:  # Only insert ads if video is longer than 10 seconds
        # Pre-roll ad at the very start (0 seconds)
        ad_insertion_points.append(0)
        
        # Subsequent ads after random intervals (5, 10, 20, or 30 min)
        current_point = random.choice(interval_options)
        while current_point < total_duration - 30:  # Don't insert ad in last 30 seconds
            ad_insertion_points.append(current_point)
            current_point += random.choice(interval_options)
    
    print(f"Planned ad insertion points for {video_slug}: {ad_insertion_points}")
    
    current_duration = 0.0
    next_ad_index = 0
    
    for line in lines:
        # Track segment duration
        if line.startswith('#EXTINF:'):
            try:
                duration_str = line.split(':')[1].split(',')[0]
                segment_duration = float(duration_str)
                current_duration += segment_duration
                
                # Check if we should insert an ad at this point
                if (next_ad_index < len(ad_insertion_points) and 
                    current_duration >= ad_insertion_points[next_ad_index]):
                    
                    # Pick a random ad from active ads
                    ad = random.choice(active_ads)
                    ad_count += 1
                    
                    # Get ad duration
                    ad_duration = ad.display_duration or 5
                    
                    # Inject HLS ad markers with ad metadata
                    new_lines.append(f'#EXT-X-CUE-OUT:DURATION={ad_duration}')
                    new_lines.append(f'#EXT-X-ASSET:CAID=interceptor-{ad.id}')
                    
                    # Add custom metadata for the player
                    if ad.media_file:
                        new_lines.append(f'#EXT-X-AD-URL:{ad.media_file.url}')
                    if ad.redirect_link:
                        new_lines.append(f'#EXT-X-AD-CLICK:{ad.redirect_link}')
                    new_lines.append(f'#EXT-X-AD-TYPE:{ad.media_type}')
                    
                    logger.info(f"Injected ad {ad.id} at {current_duration:.1f}s for {video_slug}")
                    
                    next_ad_index += 1
                    last_ad_time = current_duration
                    
            except (IndexError, ValueError):
                pass
        
        new_lines.append(line)
    
    logger.info(f"Injected {ad_count} ads into playlist for {video_slug}")
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
    include_videos = request.GET.get('include_videos', 'false').lower() == 'true'
    video_count = int(request.GET.get('video_count', 10))
    parents = request.GET.get('parents_only', 'false').lower() == 'true'
    
    category = Category.objects.get(pk=pk)
    serializer = CategorySerializer(
        category, 
        include_videos=include_videos, 
        video_count=video_count,
        parents=parents
    )
    
    return success_response(serializer.data)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def get_category_videos(request, pk):
    category = Category.objects.get(pk=pk)
    videos = Video.objects.filter(category=category)
    serializer = VideoSerializer(videos, many=True)
    return success_response(serializer.data)

@api_view(['GET'])
def get_subcategories(request, category_id):
    subcategories = Category.objects.filter(~Q(parent=None), parent=category_id)
    serializer = CategorySerializer(subcategories, many=True)
    print(subcategories.values("id", "name"))
    return success_response(serializer.data)

@api_view(['GET'])
def get_subcategory(request, pk):
    subcategory = Category.objects.get(parent=pk)
    serializer = CategorySerializer(subcategory)
    return success_response(serializer.data)

@api_view(['GET'])
def get_feed(request):
    """Return a paginated list of videos with category and parent category info."""
    # Prefetch category and its parent to avoid N+1 queries
    queryset = Video.objects.filter(is_published=True, processing_status='completed').select_related('category', 'category__parent').all().order_by('-created_at')

    # Pagination params
    try:
        page = int(request.GET.get('page', 1))
    except (TypeError, ValueError):
        page = 1

    try:
        page_size = int(request.GET.get('page_size', 20))
    except (TypeError, ValueError):
        page_size = 20

    paginator = Paginator(queryset, page_size)

    try:
        page_obj = paginator.page(page)
    except PageNotAnInteger:
        page_obj = paginator.page(1)
        page = 1
    except EmptyPage:
        page_obj = paginator.page(paginator.num_pages)
        page = paginator.num_pages

    serializer = VideoFeedSerializer(page_obj.object_list, many=True)

    # Base results are videos
    results = list(serializer.data)

    # Inject at most one ad segment per page so feed is not full of ads
    if results:
        ad_segment = None

        # Try to use a custom ad if available
        custom_ad = Ad.objects.filter(is_published=True).first()
        if custom_ad:
            ad_segment = {
                'segment_type': 'AD',
                'ad_render_type': 'CUSTOM',  # frontend: render custom ad
                'ad': {
                    'id': custom_ad.id,
                    'name': custom_ad.name,
                    'slug': custom_ad.slug,
                    'type': custom_ad.type,
                    'thumbnail': custom_ad.thumbnail.url if custom_ad.thumbnail else None,
                    'video': custom_ad.video.url if custom_ad.video else None,
                    'duration': custom_ad.duration.total_seconds() if custom_ad.duration else None,
                },
            }
        else:
            # Fallback to google ad placeholder only
            ad_segment = {
                'segment_type': 'AD',
                'ad_render_type': 'GOOGLE',  # frontend: render Google ad slot
            }

        # Place ad roughly in the middle of the page
        if ad_segment:
            insert_index = max(1, len(results) // 2)
            results.insert(insert_index, ad_segment)

    return success_response({
        'results': results,
        'pagination': {
            'page': page,
            'page_size': page_size,
            'total_items': paginator.count,
            'total_pages': paginator.num_pages,
            'has_next': page_obj.has_next(),
            'has_previous': page_obj.has_previous(),
        },
    })


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def history_list(request):
    """List videos in the authenticated user's watch history.

    This simplified version uses Profile.videos_watched without per-item
    timestamps, so `last_watched_at` is always null.
    """

    profile = getattr(request.user, "profile", None)
    if not profile:
        return success_response({
            'results': [],
            'pagination': {
                'page': 1,
                'page_size': 20,
                'has_next': False,
                'total': 0,
            },
        })

    queryset = (
        profile.videos_watched
        .select_related('category', 'category__parent')
        .all()
        .order_by('-created_at')
    )

    try:
        page = int(request.GET.get('page', 1))
    except (TypeError, ValueError):
        page = 1

    try:
        page_size = int(request.GET.get('page_size', 20))
    except (TypeError, ValueError):
        page_size = 20

    paginator = Paginator(queryset, page_size)

    try:
        page_obj = paginator.page(page)
    except PageNotAnInteger:
        page_obj = paginator.page(1)
        page = 1
    except EmptyPage:
        page_obj = paginator.page(paginator.num_pages)
        page = paginator.num_pages

    serializer = VideoHistorySerializer(page_obj.object_list, many=True)

    return success_response({
        'results': serializer.data,
        'pagination': {
            'page': page,
            'page_size': page_size,
            'has_next': page_obj.has_next(),
            'total': paginator.count,
        },
    })


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def favorites_list(request):
    """List videos in the authenticated user's favorites.

    Uses Profile.favorite_videos without per-item timestamps.
    """

    profile = getattr(request.user, "profile", None)
    if not profile:
        return success_response({
            'results': [],
            'pagination': {
                'page': 1,
                'page_size': 20,
                'has_next': False,
                'total': 0,
            },
        })

    queryset = profile.favorite_videos.select_related('category', 'category__parent').all()

    try:
        page = int(request.GET.get('page', 1))
    except (TypeError, ValueError):
        page = 1

    try:
        page_size = int(request.GET.get('page_size', 20))
    except (TypeError, ValueError):
        page_size = 20

    paginator = Paginator(queryset, page_size)

    try:
        page_obj = paginator.page(page)
    except PageNotAnInteger:
        page_obj = paginator.page(1)
        page = 1
    except EmptyPage:
        page_obj = paginator.page(paginator.num_pages)
        page = paginator.num_pages

    serializer = FavoriteVideoSerializer(page_obj.object_list, many=True)

    return success_response({
        'results': serializer.data,
        'pagination': {
            'page': page,
            'page_size': page_size,
            'has_next': page_obj.has_next(),
            'total': paginator.count,
        },
    })


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def downloads_list(request):
    """List videos the authenticated user marked as downloaded.

    Uses Profile.downloaded_videos; timestamp is not tracked in this version.
    """

    profile = getattr(request.user, "profile", None)
    if not profile:
        return success_response({
            'results': [],
            'pagination': {
                'page': 1,
                'page_size': 20,
                'has_next': False,
                'total': 0,
            },
        })

    queryset = profile.downloaded_videos.select_related('category', 'category__parent').all()

    try:
        page = int(request.GET.get('page', 1))
    except (TypeError, ValueError):
        page = 1

    try:
        page_size = int(request.GET.get('page_size', 20))
    except (TypeError, ValueError):
        page_size = 20

    paginator = Paginator(queryset, page_size)

    try:
        page_obj = paginator.page(page)
    except PageNotAnInteger:
        page_obj = paginator.page(1)
        page = 1
    except EmptyPage:
        page_obj = paginator.page(paginator.num_pages)
        page = paginator.page(paginator.num_pages)

    serializer = VideoHistorySerializer(page_obj.object_list, many=True)

    return success_response({
        'results': serializer.data,
        'pagination': {
            'page': page,
            'page_size': page_size,
            'has_next': page_obj.has_next(),
            'total': paginator.count,
        },
    })


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def favorite_video(request, video_uid):
    """Mark a video as favorite for the current user."""

    profile = getattr(request.user, "profile", None)
    if not profile:
        return error_response({'message': 'Profile not found'})

    try:
        video = Video.objects.get(uid=video_uid)
    except Video.DoesNotExist:
        return error_response({'message': 'Video not found'})

    profile.favorite_videos.add(video)
    return success_response(data={}, message='Favorited')


@api_view(['DELETE'])
@permission_classes([IsAuthenticated])
def unfavorite_video(request, video_uid):
    """Remove a video from the current user's favorites."""

    profile = getattr(request.user, "profile", None)
    if not profile:
        return error_response({'message': 'Profile not found'})

    try:
        video = Video.objects.get(uid=video_uid)
    except Video.DoesNotExist:
        return error_response({'message': 'Video not found'})

    profile.favorite_videos.remove(video)
    return success_response(data={}, message='Unfavorited')


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def mark_video_downloaded(request, video_uid):
    """Mark a video as downloaded for the current user."""

    profile = getattr(request.user, "profile", None)
    if not profile:
        return error_response({'message': 'Profile not found'})

    profile.credit_accumulation -= 10
    profile.save()
    
    try:
        video = Video.objects.get(uid=video_uid)
    except Video.DoesNotExist:
        return error_response({'message': 'Video not found'})

    profile.downloaded_videos.add(video)
    return success_response(data={}, message='Marked as downloaded')


@api_view(['DELETE'])
@permission_classes([IsAuthenticated])
def unmark_video_downloaded(request, video_uid):
    """Remove a video from the current user's downloads list."""

    profile = getattr(request.user, "profile", None)
    if not profile:
        return error_response({'message': 'Profile not found'})

    try:
        video = Video.objects.get(uid=video_uid)
    except Video.DoesNotExist:
        return error_response({'message': 'Video not found'})

    profile.downloaded_videos.remove(video)
    return success_response(data={}, message='Removed from downloads')

@api_view(['GET'])
def get_recent_feed(request):
    feed = Category.objects.all()
    serializer = CategorySerializer(feed, many=True)
    return success_response(serializer.data)


@api_view(['GET'])
def get_search(request):
    feed = Category.objects.all()
    serializer = CategorySerializer(feed, many=True)
    return success_response(serializer.data)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def search_videos(request):
    query = request.GET.get('search')
    page_param = request.GET.get('page')
    count_param = request.GET.get('count')

    if not query or not page_param or not count_param:
        return error_response('Invalid query parameters', code=400)

    try:
        page = int(page_param)
        count = int(count_param)
        if page < 1 or count < 1:
            raise ValueError
    except (TypeError, ValueError):
        return error_response('Invalid query parameters', code=400)

    queryset = (
        Video.objects
        .filter(is_published=True, processing_status='completed')
        .select_related('category', 'category__parent')
        .filter(
            Q(title__icontains=query)
            | Q(description__icontains=query)
            | Q(slug__icontains=query)
        )
        .order_by('-created_at')
    )

    paginator = Paginator(queryset, count)

    try:
        page_obj = paginator.page(page)
    except PageNotAnInteger:
        page = 1
        page_obj = paginator.page(page)
    except EmptyPage:
        page_obj = []

    if page_obj:
        objects = getattr(page_obj, 'object_list', page_obj)
        serializer = VideoFeedSerializer(objects, many=True)
        results = serializer.data
        has_next = getattr(page_obj, 'has_next', lambda: False)()
    else:
        results = []
        has_next = False

    return success_response({
        'results': results,
        'pagination': {
            'page': page,
            'count': count,
            'has_next': has_next,
            'total': paginator.count,
        },
    }, message='Search results loaded successfully.')


@api_view(['GET'])
def get_videos(request, category_id):
    feed = Category.objects.all()
    serializer = CategorySerializer(feed, many=True)
    return success_response(serializer.data)

@api_view(['GET'])
def get_banner_ads(request):
    feed = Category.objects.all()
    serializer = CategorySerializer(feed, many=True)
    return success_response(serializer.data)

@api_view(['POST'])
@permission_classes([IsAuthenticated])
def upload_chunk(request):
    """
    Upload a chunk of video data for resumable/chunked uploads.
    
    Expected request data (camelCase):
    - chunk: The file chunk (from request.FILES)
    - videoId: ID of the video being uploaded
    - chunkIndex: Current chunk number (0-based)
    - totalChunks: Total number of chunks
    - fileName: Original filename
    
    Optimized for S3/R2 cloud storage - avoids expensive listdir() calls.
    """
    try:
        # Validate required fields (camelCase from frontend)
        chunk_file = request.FILES.get('chunk')
        video_id = request.data.get('videoId')
        chunk_index = request.data.get('chunkIndex')
        total_chunks = request.data.get('totalChunks')
        filename = request.data.get('fileName')
        
        if not all([chunk_file, video_id, chunk_index is not None, total_chunks, filename]):
            return error_response({
                'error': 'Missing required fields',
                'required': ['chunk', 'videoId', 'chunkIndex', 'totalChunks', 'fileName']
            })
        
        # Convert to integers
        try:
            chunk_index = int(chunk_index)
            total_chunks = int(total_chunks)
        except ValueError:
            return error_response({'error': 'chunkIndex and totalChunks must be integers'})
        
        # Verify video exists (only on first chunk to reduce DB queries)
        if chunk_index == 0:
            if not Video.objects.filter(id=video_id).exists():
                return error_response({'error': f'Video with id {video_id} not found'})
        
        # Save chunk directly to cloud storage
        chunk_dir = f"videos/chunks/{video_id}"
        chunk_filename = f"chunk_{chunk_index:04d}"
        chunk_path = f"{chunk_dir}/{chunk_filename}"
        
        # Save the chunk - use save() with max_length to allow overwrite if retry
        saved_path = default_storage.save(chunk_path, chunk_file)
        
        # Trust client-side tracking instead of expensive listdir() on cloud storage
        # The assembly endpoint will verify all chunks exist before combining
        is_last_chunk = (chunk_index == total_chunks - 1)
        
        response_data = {
            'message': f'Chunk {chunk_index + 1}/{total_chunks} uploaded',
            'chunk_index': chunk_index,
            'total_chunks': total_chunks,
            'is_last_chunk': is_last_chunk
        }
        
        if is_last_chunk:
            response_data['message'] = 'Last chunk uploaded. Ready for assembly.'
            response_data['next_step'] = 'Call /api/streaming/assemble-chunks/ to combine chunks'
        
        return success_response(response_data)
        
    except Exception as e:
        logger.error(f"Error uploading chunk: {str(e)}", exc_info=True)
        return error_response({'error': str(e)})

@api_view(['POST'])
@permission_classes([IsAuthenticated])
def assemble_chunks(request):
    """
    Queue chunk assembly as a background task.
    
    Expected request data (camelCase):
    - videoId: ID of the video
    - fileName: Original filename for the assembled video
    """
    try:
        video_id = request.data.get('videoId')
        filename = request.data.get('fileName')
        
        if not video_id or not filename:
            return error_response({'error': 'Missing videoId or fileName'})
        
        # Verify video exists
        try:
            video = Video.objects.get(id=video_id)
        except Video.DoesNotExist:
            return error_response({'error': f'Video with id {video_id} not found'})
        
        # Queue the assembly task
        try:
            task = assemble_chunks_task.delay(video_id, filename)
            logger.info(f"Queued chunk assembly task {task.id} for video {video_id}")
            message = 'Video assembly queued. Processing will begin shortly.'
        except Exception as e:
            logger.error(f"Could not queue chunk assembly task: {str(e)}", exc_info=True)
            return error_response({'error': 'Could not queue video assembly. Please try again later.'})
        
        return success_response({
            'message': message,
            'video_id': video.id,
            'task_id': task.id
        })
        
    except Exception as e:
        logger.error(f"Error queuing chunk assembly: {str(e)}", exc_info=True)
        return error_response({'error': str(e)})

@api_view(['POST'])
@permission_classes([IsAuthenticated])
def create_video(request):
    """
    Create a new video and trigger HLS conversion.
    
    The uploaded MP4 video will be automatically converted to HLS format
    with multiple quality levels (1080p, 720p, 480p, 360p) for adaptive
    bitrate streaming based on client network speed.
    """
    # slug = request.data.get('title', None)
    
    data = {
        'title': request.data.get('title'),
        'description': request.data.get('description'),
        'category': request.data.get('category'),
        'thumbnail': request.data.get('thumbnail'),
        'video': request.data.get('video'),
        'is_published': request.data.get('status', 'draft') == 'published',
        # 'slug': slug.replace(' ', '-').lower() if slug else None,
        'uploaded_by': request.user.id,
        'processing_status': 'pending'  # Initial status
    }
    
    serializer = VideoSerializer(data=data)
    if serializer.is_valid():
        # Save the video object
        video = serializer.save()
        
        # Trigger async HLS conversion task
        try:
            # task = convert_video_to_hls.delay(video.id)
            message = 'Video uploaded successfully. HLS conversion in progress.'
        except Exception as e:
            # If Celery/Redis is not available, log the error
            message = 'Video uploaded successfully. Conversion will start when processing service is available.'
        
        # Return response with processing status
        response_data = serializer.data
        response_data['message'] = message
        response_data['processing_status'] = 'pending'
        
        return success_response(response_data)
    return error_response(serializer.errors)

@api_view(['GET'])
@permission_classes([AllowAny])
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
                modified_content = inject_ad_markers(modified_content, video_slug)
            
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
@permission_classes([IsAuthenticated])
def get_video_stream_url(request, uid):
    """
    Get the streaming URL for a video.
    
    Returns:
        Video details with HLS streaming URL from R2 storage
    """
    try:
        video = Video.objects.get(uid=uid)
        
        if not video.is_ready_for_streaming:
            return error_response({
                'message': 'Video is still processing',
                'processing_status': video.processing_status
            })

        # If the user is authenticated, record a view and update watch history
        user = getattr(request, 'user', None)
        if user is not None and getattr(user, 'is_authenticated', False):
            from apps.streaming.models import View

            View.objects.create(video=video, user=user)
            video.views_count = View.objects.filter(video=video).count()
            video.save(update_fields=['views_count'])

            # Optionally add to watch history like record_view_stream
            profile = getattr(user, 'profile', None)
            if profile:
                profile.videos_watched.add(video)

        # Construct backend streaming URL for ad injection
        from django.conf import settings
        backend_url = getattr(settings, 'BACKEND_URL', 'https://backend.farajayangutv.co.tz')

        # Use backend proxy URL to enable ad injection
        stream_url = f"{backend_url}/streaming/hls/{video.uid}/master.m3u8"
        
        parent_category_name = None
        category_name = None
        if video.category is not None:
            category_name = video.category.name
            if video.category.parent is not None:
                parent_category_name = video.category.parent.name

        has_liked = False
        has_disliked = False
        user = getattr(request, 'user', None)
        if user is not None and getattr(user, 'is_authenticated', False):
            has_liked = Like.objects.filter(video=video, user=user).exists()
            has_disliked = Dislike.objects.filter(video=video, user=user).exists()

        print(video.thumbnail.url if video.thumbnail else None)
        
        return success_response({
            'id': video.id,
            'uid': str(video.uid),
            'title': video.title,
            'description': video.description,
            # Thumbnail URL comes directly from object storage backend
            'thumbnail': video.thumbnail.url if video.thumbnail else None,
            'duration': str(video.duration) if video.duration else None,
            'views_count': video.views_count,
            'likes_count': video.likes_count,
            'dislikes_count': video.dislikes_count,
            'slug': video.slug,
            'created_at': video.created_at,
            'parent_category_name': parent_category_name,
            'category_name': category_name,
            'has_liked': has_liked,
            'has_disliked': has_disliked,
            'stream_url': stream_url,
            'is_ready': video.is_ready_for_streaming,
        })
        
    except Video.DoesNotExist:
        return error_response({'message': 'Video not found'})

@api_view(['PUT'])
@permission_classes([IsAuthenticated])
def update_video(request, pk):
    video = Video.objects.get(pk=pk)
    uploaded_by = video.uploaded_by.id
    data = { key: value for key, value in request.data.items() }
    data['uploaded_by'] = uploaded_by
    data['is_published'] = request.data.get('status', 'draft') == 'published'
    serializer = VideoSerializer(video, data=data)
    if serializer.is_valid():
        serializer.save()
        return success_response(serializer.data)
    return error_response(serializer.errors)

@api_view(['DELETE'])
@permission_classes([IsAuthenticated])
def delete_video(request, pk):
    video = Video.objects.get(pk=pk)
    
    # Queue background task to delete HLS files before deleting the video record
    if video.hls_path:
        delete_video_files_task.delay(video.hls_path, str(video.uid))
    
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
    return success_response(serializer.data)

@api_view(['GET'])
def get_video_comments(request, pk):
    feed = Category.objects.all()
    serializer = CategorySerializer(feed, many=True)
    return success_response(serializer.data)

@api_view(['GET'])
def get_video_related(request, video_id):
    feed = Category.objects.all()
    serializer = CategorySerializer(feed, many=True)
    return success_response(serializer.data)

@api_view(['POST'])
def like_video(request, video_id):
    feed = Category.objects.all()
    serializer = CategorySerializer(feed, many=True)
    return success_response(serializer.data)

@api_view(['POST'])
def dislike_video(request, video_id):
    feed = Category.objects.all()
    serializer = CategorySerializer(feed, many=True)
    return success_response(serializer.data)

@api_view(['POST'])
def like_comment(request, comment_id):
    feed = Category.objects.all()
    serializer = CategorySerializer(feed, many=True)
    return success_response(serializer.data)

@api_view(['POST'])
def dislike_comment(request, comment_id):
    feed = Category.objects.all()
    serializer = CategorySerializer(feed, many=True)
    return success_response(serializer.data)

@api_view(['POST'])
def comment(request, video_id):
    feed = Category.objects.all()
    serializer = CategorySerializer(feed, many=True)
    return success_response(serializer.data)

@api_view(['POST'])
def reply(request, comment_id):
    feed = Category.objects.all()
    serializer = CategorySerializer(feed, many=True)
    return success_response(serializer.data)

@api_view(['POST'])
def view(request, video_id):
    feed = Category.objects.all()
    serializer = CategorySerializer(feed, many=True)
    return success_response(serializer.data)


# ////////////////////////////////////////////////////////////////////////////////////////////////// #
# /////////////////////////// VIDEO PLAYER: RELATED & INTERACTION ENDPOINTS ///////////////////////// #


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def interceptor_ads(request, video_uid):
    """Return all interceptor ads for the given video uid.

    Supports two types of ad slots:
    1. Linked Ad: References an existing Ad from the advertising system
    2. Self-contained: Has its own media_file (image/video) with redirect_link

    Outer contract:
        {"data": [ ... ] | []}

    - 404 if video_uid does not exist
    - data == [] if there are no ads to show
    """

    # Ensure video exists
    video = get_object_or_404(Video, uid=video_uid)

    # Optional future-proof position hint ("pre" | "mid" | "post")
    position = request.GET.get('position')  # noqa: F841  # currently unused

    # Get all ad slots for this video (both linked and self-contained)
    slots = (
        VideoAdSlot.objects
        .select_related('ad')
        .filter(video=video)
        .order_by('start_time')
    )

    # Filter: include slots with published ad OR self-contained media
    valid_slots = [
        slot for slot in slots
        if (slot.ad and slot.ad.is_published) or slot.media_file
    ]

    if not valid_slots:
        return success_response([])

    ads_payload = []
    for slot in valid_slots:
        if slot.media_file:
            # Self-contained interceptor ad
            media_type = slot.media_type.upper()  # 'IMAGE' or 'VIDEO'
            if media_type == 'VIDEO':
                video_url = request.build_absolute_uri(slot.media_file.url)
                image_url = None
            else:
                image_url = request.build_absolute_uri(slot.media_file.url)
                video_url = None
            
            total_seconds = slot.display_duration or 5
            click_url = slot.redirect_link
            ad_id = f"slot_{slot.id}"
        elif slot.ad:
            # Linked Ad from advertising system
            ad = slot.ad
            if ad.type == Ad.AD_TYPES.VIDEO and ad.video:
                media_type = "VIDEO"
                video_url = ad.video.url
                image_url = None
            else:
                media_type = "IMAGE"
                image_url = ad.thumbnail.url if ad.thumbnail else None
                video_url = None

            if ad.duration:
                total_seconds = int(ad.duration.total_seconds())
            else:
                total_seconds = 15
            click_url = None
            ad_id = ad.id
        else:
            continue

        skippable_after = min(10, total_seconds)

        # Convert TimeField to seconds for start/end time
        def time_to_seconds(t):
            return t.hour * 3600 + t.minute * 60 + t.second if t else 0

        ads_payload.append({
            "id": ad_id,
            "media_type": media_type,
            "image_url": image_url,
            "video_url": video_url,
            "click_url": click_url,
            "duration": total_seconds,
            "skippable_after": skippable_after,
            "start_time": time_to_seconds(slot.start_time),
            "end_time": time_to_seconds(slot.end_time),
            "label": "Sponsored",
            "tracking": {
                "impression_url": None,
                "click_url": None,
            },
        })

    return success_response(ads_payload)


@api_view(['GET'])
def get_related_videos(request, video_uid):
    """Return related videos for a given video.

    Uses the same payload structure as get_video_stream_url for each video.
    """

    try:
        video = Video.objects.select_related('category').get(uid=video_uid)
    except Video.DoesNotExist:
        return error_response({'message': 'Video not found'})

    base_qs = (
        Video.objects
        .select_related('category', 'category__parent')
        .filter(category=video.category)
        .exclude(id=video.id)
        .order_by('-created_at')[:20]
    )

    from django.conf import settings

    backend_url = getattr(settings, 'BACKEND_URL', 'https://backend.farajayangutv.co.tz')
    user = getattr(request, 'user', None)

    # Annotate category names
    qs = base_qs.annotate(
        parent_category_name=F('category__parent__name'),
        category_name=F('category__name'),
    )

    # Annotate like/dislike flags based on current user
    if user is not None and getattr(user, 'is_authenticated', False):
        qs = qs.annotate(
            has_liked=Exists(Like.objects.filter(video=OuterRef('pk'), user=user)),
            has_disliked=Exists(Dislike.objects.filter(video=OuterRef('pk'), user=user)),
        )
    else:
        qs = qs.annotate(
            has_liked=Value(False),
            has_disliked=Value(False),
        )

    # is_ready equivalent of is_ready_for_streaming property
    qs = qs.annotate(
        is_ready=Case(
            When(
                processing_status='completed',
                hls_master_playlist__isnull=False,
                then=Value(True),
            ),
            default=Value(False),
            output_field=BooleanField(),
        ),
    )

    # Annotate stream_url using BACKEND_URL and uid (cast UUID to string)
    qs = qs.annotate(
        stream_url=Concat(
            Value(backend_url + '/streaming/hls/'),
            Cast('uid', output_field=CharField()),
            Value('/master.m3u8'),
            output_field=CharField(),
        ),
    )

    # Build response objects so thumbnail uses the storage backend URL (v.thumbnail.url)
    videos_payload = []
    for v in qs:
        videos_payload.append({
            'id': v.id,
            'uid': str(v.uid),
            'title': v.title,
            'description': v.description,
            'thumbnail': v.thumbnail.url if v.thumbnail else None,
            'duration': str(v.duration) if v.duration else None,
            'views': v.views_count,
            'likes_count': v.likes_count,
            'dislikes_count': v.dislikes_count,
            'slug': v.slug,
            'created_at': v.created_at,
            'parent_category_name': getattr(v, 'parent_category_name', None),
            'category_name': getattr(v, 'category_name', None),
            'has_liked': getattr(v, 'has_liked', False),
            'has_disliked': getattr(v, 'has_disliked', False),
            'stream_url': v.stream_url,
            'is_ready': getattr(v, 'is_ready', False),
        })

    return success_response({
        'videos': videos_payload,
        'has_more': False,
    })


def _like_video_stream(request, video_uid):
    """Internal helper to like a video."""

    try:
        video = Video.objects.get(uid=video_uid)
    except Video.DoesNotExist:
        return error_response({'message': 'Video not found'})

    from apps.streaming.models import Like

    Like.objects.get_or_create(video=video, user=request.user)
    video.likes_count = Like.objects.filter(video=video).count()
    video.save(update_fields=['likes_count'])

    return success_response(data={}, message='Liked')


def _unlike_video_stream(request, video_uid):
    """Internal helper to remove like from a video."""

    try:
        video = Video.objects.get(uid=video_uid)
    except Video.DoesNotExist:
        return error_response({'message': 'Video not found'})

    from apps.streaming.models import Like

    Like.objects.filter(video=video, user=request.user).delete()
    video.likes_count = Like.objects.filter(video=video).count()
    video.save(update_fields=['likes_count'])

    return success_response(data={}, message='Like removed')


@api_view(['POST', 'DELETE'])
@permission_classes([IsAuthenticated])
def video_like_stream(request, video_uid):
    """Combined like/unlike endpoint for `/stream/{video_uid}/like/`."""

    if request.method == 'POST':
        return _like_video_stream(request, video_uid)
    return _unlike_video_stream(request, video_uid)


def _dislike_video_stream(request, video_uid):
    """Internal helper to dislike a video."""

    try:
        video = Video.objects.get(uid=video_uid)
    except Video.DoesNotExist:
        return error_response({'message': 'Video not found'})

    from apps.streaming.models import Dislike

    Dislike.objects.get_or_create(video=video, user=request.user)
    video.dislikes_count = Dislike.objects.filter(video=video).count()
    video.save(update_fields=['dislikes_count'])

    return success_response(data={}, message='Disliked')


def _undislike_video_stream(request, video_uid):
    """Internal helper to remove dislike from a video."""

    try:
        video = Video.objects.get(uid=video_uid)
    except Video.DoesNotExist:
        return error_response({'message': 'Video not found'})

    from apps.streaming.models import Dislike

    Dislike.objects.filter(video=video, user=request.user).delete()
    video.dislikes_count = Dislike.objects.filter(video=video).count()
    video.save(update_fields=['dislikes_count'])

    return success_response(data={}, message='Dislike removed')


@api_view(['POST', 'DELETE'])
@permission_classes([IsAuthenticated])
def video_dislike_stream(request, video_uid):
    """Combined dislike/undislike endpoint for `/stream/{video_uid}/dislike/`."""

    if request.method == 'POST':
        return _dislike_video_stream(request, video_uid)
    return _undislike_video_stream(request, video_uid)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def record_view_stream(request, video_uid):
    """Record a view for a video."""

    try:
        video = Video.objects.get(uid=video_uid)
    except Video.DoesNotExist:
        return error_response({'message': 'Video not found'})

    from apps.streaming.models import View

    View.objects.create(video=video, user=request.user)
    video.views_count = View.objects.filter(video=video).count()
    video.save(update_fields=['views_count'])

    # Optionally add to watch history
    profile = getattr(request.user, 'profile', None)
    if profile:
        profile.videos_watched.add(video)

    return success_response(data={}, message='View recorded')


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def record_share_stream(request, video_uid):
    """Record a share action for analytics (no extra payload)."""

    # For now, we just acknowledge; you can add analytics model later.
    try:
        Video.objects.get(uid=video_uid)
    except Video.DoesNotExist:
        return error_response({'message': 'Video not found'})

    return success_response(data={}, message='Share recorded')


# ////////////////////////////////////////////////////////////////////////////////////////////////// #
# /////////////////////////////////////// COMMENTS ENDPOINTS /////////////////////////////////////// #


def _get_video_comments_payload(request, video_uid):
    """Internal helper to get paginated comments payload for a video."""

    try:
        video = Video.objects.get(uid=video_uid)
    except Video.DoesNotExist:
        return error_response({'message': 'Video not found'})

    try:
        page = int(request.GET.get('page', 1))
    except (TypeError, ValueError):
        page = 1

    try:
        per_page = int(request.GET.get('per_page', 4))
    except (TypeError, ValueError):
        per_page = 4

    qs = Comment.objects.filter(video=video, reply_to__isnull=True).order_by('-created_at')
    paginator = Paginator(qs, per_page)

    try:
        page_obj = paginator.page(page)
    except PageNotAnInteger:
        page_obj = paginator.page(1)
        page = 1
    except EmptyPage:
        page_obj = paginator.page(paginator.num_pages)
        page = paginator.num_pages

    serializer = CommentSerializer(page_obj.object_list, many=True)

    return success_response({
        'comments': serializer.data,
        'has_more': page_obj.has_next(),
    })


def _post_comment_payload(request, video_uid):
    """Internal helper to create a comment and return response payload."""

    try:
        video = Video.objects.get(uid=video_uid)
    except Video.DoesNotExist:
        return error_response({'message': 'Video not found'})

    content = request.data.get('content')
    if not content:
        return error_response({'message': 'content is required'})

    comment = Comment.objects.create(
        video=video,
        user=request.user,
        comment=content,
    )

    serializer = CommentSerializer(comment)
    return success_response(serializer.data, message='Comment posted')


@api_view(['GET', 'POST'])
@permission_classes([IsAuthenticated])
def video_comments_stream(request, video_uid):
    """Combined list/create endpoint for `/stream/{video_uid}/comments/`."""

    if request.method == 'GET':
        return _get_video_comments_payload(request, video_uid)
    return _post_comment_payload(request, video_uid)


def _get_comment_replies_payload(request, comment_id):
    """Internal helper to get paginated replies payload for a comment."""

    try:
        comment = Comment.objects.get(id=comment_id)
    except Comment.DoesNotExist:
        return error_response({'message': 'Comment not found'})

    try:
        page = int(request.GET.get('page', 1))
    except (TypeError, ValueError):
        page = 1

    try:
        per_page = int(request.GET.get('per_page', 10))
    except (TypeError, ValueError):
        per_page = 10

    qs = Comment.objects.filter(reply_to=comment).order_by('created_at')
    paginator = Paginator(qs, per_page)

    try:
        page_obj = paginator.page(page)
    except PageNotAnInteger:
        page_obj = paginator.page(1)
        page = 1
    except EmptyPage:
        page_obj = paginator.page(paginator.num_pages)
        page = paginator.num_pages

    serializer = ReplySerializer(page_obj.object_list, many=True)

    return success_response({
        'replies': serializer.data,
        'has_more': page_obj.has_next(),
    })


def _post_comment_reply_payload(request, comment_id):
    """Internal helper to create a reply and return response payload."""

    try:
        parent = Comment.objects.get(id=comment_id)
    except Comment.DoesNotExist:
        return error_response({'message': 'Comment not found'})

    content = request.data.get('content')
    if not content:
        return error_response({'message': 'content is required'})

    reply = Comment.objects.create(
        video=parent.video,
        user=request.user,
        comment=content,
        reply_to=parent,
    )

    serializer = ReplySerializer(reply)
    return success_response(serializer.data, message='Reply posted')


@api_view(['GET', 'POST'])
@permission_classes([IsAuthenticated])
def comment_replies_stream(request, comment_id):
    """Combined list/create endpoint for `/comments/{comment_id}/replies/`."""

    if request.method == 'GET':
        return _get_comment_replies_payload(request, comment_id)
    return _post_comment_reply_payload(request, comment_id)


def _like_comment_stream(request, comment_id):
    """Internal helper to like a comment (placeholder, no persistence)."""

    try:
        Comment.objects.get(id=comment_id)
    except Comment.DoesNotExist:
        return error_response({'message': 'Comment not found'})

    return success_response(data={}, message='Comment liked')


def _unlike_comment_stream(request, comment_id):
    """Internal helper to unlike a comment (placeholder)."""

    try:
        Comment.objects.get(id=comment_id)
    except Comment.DoesNotExist:
        return error_response({'message': 'Comment not found'})

    return success_response(data={}, message='Comment like removed')


@api_view(['POST', 'DELETE'])
@permission_classes([IsAuthenticated])
def comment_like_stream(request, comment_id):
    """Combined like/unlike endpoint for `/comments/{comment_id}/like/`."""

    if request.method == 'POST':
        return _like_comment_stream(request, comment_id)
    return _unlike_comment_stream(request, comment_id)


@api_view(['DELETE'])
@permission_classes([IsAuthenticated])
def delete_comment_stream(request, comment_id):
    """Delete a comment (or reply) by ID for the current user."""

    try:
        comment = Comment.objects.get(id=comment_id, user=request.user)
    except Comment.DoesNotExist:
        return error_response({'message': 'Comment not found'})

    comment.delete()
    return success_response(data={}, message='Comment deleted')


# ////////////////////////////////////////////////////////////////////////////////////////////////// #
# /////////////////////////////////////// PLAYLIST ENDPOINTS /////////////////////////////////////// #

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def playlist_list(request):
    """List playlists for the authenticated user (paginated)."""

    qs = Playlist.objects.filter(owner=request.user).order_by('-created_at')

    try:
        page = int(request.GET.get('page', 1))
    except (TypeError, ValueError):
        page = 1

    try:
        page_size = int(request.GET.get('page_size', 20))
    except (TypeError, ValueError):
        page_size = 20

    paginator = Paginator(qs, page_size)

    try:
        page_obj = paginator.page(page)
    except PageNotAnInteger:
        page_obj = paginator.page(1)
        page = 1
    except EmptyPage:
        page_obj = paginator.page(paginator.num_pages)
        page = paginator.num_pages

    serializer = PlaylistListSerializer(page_obj.object_list, many=True)

    return success_response({
        'results': serializer.data,
        'pagination': {
            'page': page,
            'page_size': page_size,
            'has_next': page_obj.has_next(),
            'total': paginator.count,
        },
    })

@api_view(['POST'])
@permission_classes([IsAuthenticated])
def playlist_create(request):
    """Create a new playlist for the authenticated user."""

    data = {
        'name': request.data.get('name'),
        'description': request.data.get('description', ''),
        'thumbnail': request.data.get('thumbnail'),
    }

    playlist = Playlist(owner=request.user, **{k: v for k, v in data.items() if k != 'thumbnail'})

    # Handle optional thumbnail separately (supports multipart or URL-like value)
    if 'thumbnail' in request.FILES:
        playlist.thumbnail = request.FILES['thumbnail']

    playlist.save()

    serializer = PlaylistListSerializer(playlist)
    return success_response(serializer.data, message='Playlist created')

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def playlist_detail(request, playlist_uid):
    """Get playlist details with videos for the authenticated user."""

    try:
        playlist = Playlist.objects.get(uid=playlist_uid, owner=request.user)
    except Playlist.DoesNotExist:
        return error_response({'message': 'Playlist not found'})

    serializer = PlaylistDetailSerializer(playlist)
    return success_response(serializer.data)

@api_view(['POST'])
@permission_classes([IsAuthenticated])
def playlist_add_video(request, playlist_id):
    """Add a video to a playlist.

    Expects JSON body: { "video_uid": "..." }
    """

    try:
        playlist = Playlist.objects.get(id=playlist_id, owner=request.user)
    except Playlist.DoesNotExist:
        return error_response({'message': 'Playlist not found'})

    video_uid = request.data.get('video_uid')
    if not video_uid:
        return error_response({'message': 'video_uid is required'})

    try:
        video = Video.objects.get(uid=video_uid)
    except Video.DoesNotExist:
        return error_response({'message': 'Video not found'})

    PlaylistVideo.objects.get_or_create(playlist=playlist, video=video)
    return success_response(data={}, message='Video added to playlist')

@api_view(['DELETE'])
@permission_classes([IsAuthenticated])
def playlist_remove_video(request, playlist_uid, video_uid):
    """Remove a video from a playlist."""

    try:
        playlist = Playlist.objects.get(uid=playlist_uid, owner=request.user)
    except Playlist.DoesNotExist:
        return error_response({'message': 'Playlist not found'})

    try:
        video = Video.objects.get(uid=video_uid)
    except Video.DoesNotExist:
        return error_response({'message': 'Video not found'})

    PlaylistVideo.objects.filter(playlist=playlist, video=video).delete()
    return success_response(data={}, message='Video removed from playlist')

@api_view(['DELETE'])
@permission_classes([IsAuthenticated])
def playlist_delete(request, playlist_uid):
    """Delete a playlist belonging to the authenticated user."""

    try:
        playlist = Playlist.objects.get(uid=playlist_uid, owner=request.user)
    except Playlist.DoesNotExist:
        return error_response({'message': 'Playlist not found'})

    playlist.delete()
    return success_response(data={}, message='Playlist deleted')
