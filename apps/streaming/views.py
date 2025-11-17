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
from .models import Category, Video, Playlist, PlaylistVideo, Comment
from rest_framework.permissions import IsAuthenticated, IsAdminUser
from rest_framework.decorators import permission_classes
from .serializers.category import CategorySerializer
from .serializers.comment import CommentSerializer, ReplySerializer
from .tasks import convert_video_to_hls
from apps.authentication.models import Profile
from django.http import HttpResponse, Http404, FileResponse
from django.core.files.storage import default_storage
from django.core.files.base import ContentFile
from django.core.paginator import Paginator, EmptyPage, PageNotAnInteger
import logging
import mimetypes
import os
import hashlib
import io

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
    first_segment_ad_inserted = False
    
    for line in lines:
        # Track segment duration
        if line.startswith('#EXTINF:'):
            try:
                # Extract duration from #EXTINF:10.0,
                duration_str = line.split(':')[1].split(',')[0]
                segment_duration = float(duration_str)
                current_duration += segment_duration

                # Ensure a pre-roll ad before the very first media segment
                if not first_segment_ad_inserted:
                    ad_count += 1
                    new_lines.append('#EXT-X-CUE-OUT:DURATION=30')
                    new_lines.append(f'#EXT-X-ASSET:CAID=ad-{ad_count}')
                    logger.info(f"Injected pre-roll ad marker {ad_count} at start for {video_slug}")
                    first_segment_ad_inserted = True

                # Time-based ad breaks after every ad_interval seconds of content
                if current_duration - last_ad_time >= ad_interval:
                    ad_count += 1
                    new_lines.append('#EXT-X-CUE-OUT:DURATION=30')
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
def get_category_videos(request, pk):
    category = Category.objects.get(pk=pk)
    videos = Video.objects.filter(category=category)
    serializer = VideoSerializer(videos, many=True)
    return success_response(serializer.data)

@api_view(['GET'])
def get_subcategories(request, category_id):
    subcategories = Category.objects.filter(parent_id=category_id)
    serializer = CategorySerializer(subcategories, many=True)
    return success_response(serializer.data)

@api_view(['GET'])
def get_subcategory(request, pk):
    subcategory = Category.objects.get(pk=pk)
    serializer = CategorySerializer(subcategory)
    return success_response(serializer.data)

@api_view(['GET'])
def get_feed(request):
    """Return a paginated list of videos with category and parent category info."""
    # Prefetch category and its parent to avoid N+1 queries
    queryset = Video.objects.select_related('category', 'category__parent').all().order_by('-created_at')

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
        
        # Verify video exists
        try:
            video = Video.objects.get(id=video_id)
        except Video.DoesNotExist:
            return error_response({'error': f'Video with id {video_id} not found'})
        
        # Create chunk storage directory
        chunk_dir = f"videos/chunks/{video_id}"
        
        # Save chunk using Django storage system
        chunk_filename = f"chunk_{chunk_index:04d}"
        chunk_path = os.path.join(chunk_dir, chunk_filename)
        
        # Save the chunk
        saved_path = default_storage.save(chunk_path, chunk_file)
        logger.info(f"Saved chunk {chunk_index}/{total_chunks} for video {video_id} at {saved_path}")
        
        # Check if all chunks are uploaded
        uploaded_chunks = []
        for i in range(total_chunks):
            test_chunk_path = os.path.join(chunk_dir, f"chunk_{i:04d}")
            if default_storage.exists(test_chunk_path):
                uploaded_chunks.append(i)
        
        is_complete = len(uploaded_chunks) == total_chunks
        
        response_data = {
            'message': f'Chunk {chunk_index + 1}/{total_chunks} uploaded successfully',
            'chunk_index': chunk_index,
            'total_chunks': total_chunks,
            'uploaded_chunks': len(uploaded_chunks),
            'is_complete': is_complete
        }
        
        # If all chunks uploaded, trigger assembly
        if is_complete:
            response_data['message'] = 'All chunks uploaded. Ready for assembly.'
            response_data['next_step'] = 'Call /api/streaming/assemble-chunks/ to combine chunks'
        
        return success_response(response_data)
        
    except Exception as e:
        logger.error(f"Error uploading chunk: {str(e)}", exc_info=True)
        return error_response({'error': str(e)})

@api_view(['POST'])
@permission_classes([IsAuthenticated])
def assemble_chunks(request):
    """
    Assemble uploaded chunks into a complete video file.
    
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
        
        chunk_dir = f"videos/chunks/{video_id}"
        
        # Get all chunk files sorted by index
        chunk_files = []
        chunk_index = 0
        while True:
            chunk_path = os.path.join(chunk_dir, f"chunk_{chunk_index:04d}")
            if not default_storage.exists(chunk_path):
                break
            chunk_files.append(chunk_path)
            chunk_index += 1
        
        if not chunk_files:
            return error_response({'error': 'No chunks found for this video'})
        
        logger.info(f"Assembling {len(chunk_files)} chunks for video {video_id}")
        
        # Create final video path
        final_video_path = f"videos/originals/{video_id}_{filename}"
        
        # Assemble chunks into final file
        # Create a temporary buffer to hold assembled content
        assembled_content = io.BytesIO()
        
        for chunk_path in chunk_files:
            chunk_file = default_storage.open(chunk_path, 'rb')
            assembled_content.write(chunk_file.read())
            chunk_file.close()
        
        # Save assembled file
        assembled_content.seek(0)
        final_path = default_storage.save(final_video_path, ContentFile(assembled_content.read()))
        
        # Update video model with the assembled file path
        video.video = final_path
        video.save()
        
        # Clean up chunks
        for chunk_path in chunk_files:
            try:
                default_storage.delete(chunk_path)
            except Exception as e:
                logger.warning(f"Could not delete chunk {chunk_path}: {str(e)}")
        
        # Try to remove chunk directory
        try:
            # Note: Some storage backends may not support directory deletion
            if hasattr(default_storage, 'delete'):
                default_storage.delete(chunk_dir)
        except Exception as e:
            logger.warning(f"Could not delete chunk directory {chunk_dir}: {str(e)}")
        
        logger.info(f"Successfully assembled video {video_id} at {final_path}")
        
        # Trigger HLS conversion
        try:
            task = convert_video_to_hls.delay(video.id)
            logger.info(f"Queued HLS conversion task {task.id} for video {video.id}")
            message = 'Video assembled successfully. HLS conversion in progress.'
        except Exception as e:
            logger.error(f"Could not queue video conversion task: {str(e)}", exc_info=True)
            message = 'Video assembled successfully. Conversion will start when processing service is available.'
        
        return success_response({
            'message': message,
            'video_id': video.id,
            'video_path': final_path,
            'chunks_assembled': len(chunk_files)
        })
        
    except Exception as e:
        logger.error(f"Error assembling chunks: {str(e)}", exc_info=True)
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
@permission_classes([IsAuthenticated])
def get_video_stream_url(request, id):
    """
    Get the streaming URL for a video.
    
    Returns:
        Video details with HLS streaming URL from R2 storage
    """
    try:
        video = Video.objects.get(uid=id)
        
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
        stream_url = f"{backend_url}/streaming/hls/{video.slug}/master.m3u8"
        
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
            from apps.streaming.models import Like, Dislike
            has_liked = Like.objects.filter(video=video, user=user).exists()
            has_disliked = Dislike.objects.filter(video=video, user=user).exists()

        return success_response({
            'id': video.id,
            'uid': str(video.uid),
            'title': video.title,
            'description': video.description,
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
def get_related_videos(request, video_uid):
    """Return related videos for a given video.

    Initial simple implementation: videos from the same category, excluding
    the current one, ordered by -created_at.
    """

    try:
        video = Video.objects.select_related('category').get(uid=video_uid)
    except Video.DoesNotExist:
        return error_response({'message': 'Video not found'})

    queryset = (
        Video.objects
        .select_related('category', 'category__parent')
        .filter(category=video.category)
        .exclude(id=video.id)
        .order_by('-created_at')[:20]
    )

    serializer = VideoFeedSerializer(queryset, many=True)

    return success_response({
        'videos': serializer.data,
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
def playlist_add_video(request, playlist_uid):
    """Add a video to a playlist.

    Expects JSON body: { "video_uid": "..." }
    """

    try:
        playlist = Playlist.objects.get(uid=playlist_uid, owner=request.user)
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
