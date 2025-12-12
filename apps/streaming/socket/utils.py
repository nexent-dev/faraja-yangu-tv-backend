"""
Utility functions for sending WebSocket progress updates from Celery tasks.
"""
from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
import logging

logger = logging.getLogger(__name__)


def send_video_progress(video_id: int, stage: str, progress: int, message: str, status: str = "processing"):
    """
    Send a progress update to all WebSocket clients listening for this video.
    
    Args:
        video_id: The video ID
        stage: Current processing stage (e.g., 'assembling', 'converting', 'uploading')
        progress: Progress percentage (0-100)
        message: Human-readable progress message
        status: Status string (processing, completed, failed)
    """
    try:
        channel_layer = get_channel_layer()
        group_name = f"video_progress_{video_id}"
        
        async_to_sync(channel_layer.group_send)(
            group_name,
            {
                "type": "video_progress",
                "video_id": video_id,
                "stage": stage,
                "progress": progress,
                "message": message,
                "status": status
            }
        )
        logger.debug(f"Sent progress update for video {video_id}: {stage} - {progress}%")
    except Exception as e:
        logger.warning(f"Could not send progress update for video {video_id}: {str(e)}")


def send_video_complete(video_id: int, message: str = "Video processing completed", hls_path: str = None):
    """
    Send a completion notification to all WebSocket clients listening for this video.
    
    Args:
        video_id: The video ID
        message: Completion message
        hls_path: Path to the HLS files
    """
    try:
        channel_layer = get_channel_layer()
        group_name = f"video_progress_{video_id}"
        
        async_to_sync(channel_layer.group_send)(
            group_name,
            {
                "type": "video_complete",
                "video_id": video_id,
                "message": message,
                "hls_path": hls_path
            }
        )
        logger.info(f"Sent completion notification for video {video_id}")
    except Exception as e:
        logger.warning(f"Could not send completion notification for video {video_id}: {str(e)}")


def send_video_error(video_id: int, message: str, error: str = None):
    """
    Send an error notification to all WebSocket clients listening for this video.
    
    Args:
        video_id: The video ID
        message: Error message
        error: Detailed error string
    """
    try:
        channel_layer = get_channel_layer()
        group_name = f"video_progress_{video_id}"
        
        async_to_sync(channel_layer.group_send)(
            group_name,
            {
                "type": "video_error",
                "video_id": video_id,
                "message": message,
                "error": error
            }
        )
        logger.info(f"Sent error notification for video {video_id}: {message}")
    except Exception as e:
        logger.warning(f"Could not send error notification for video {video_id}: {str(e)}")
