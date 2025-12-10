"""
Celery tasks for video processing and HLS conversion.
"""
import os
import logging
from datetime import timedelta
from celery import shared_task
from django.conf import settings
from django.core.files.storage import default_storage
from apps.analytics.models import Notification
from apps.streaming.models import Video
from apps.streaming.services.video_processor import VideoProcessor
from farajayangu_be.celery import app as celery_app
from apps.authentication.models import Devices, User
from apps.authentication.models import Role
logger = logging.getLogger(__name__)

class UserGroupTypes:
    ALL = "all"
    CLIENTS = "clients"
    ADMINS = "admins"
    

class NotificationTypes:
    NEW_VIDEO = "new_video"
    COMMENT_REPLY = "comment_reply"    


def _get_users(target: UserGroupTypes):
    if target == UserGroupTypes.ALL:
        return User.objects.all()
    elif target == UserGroupTypes.CLIENTS:
        return User.objects.filter(roles__name=Role.ROLES.USER)
    elif target == UserGroupTypes.ADMINS:
        return User.objects.filter(roles__name=Role.ROLES.ADMIN)
    else:
        return User.objects.none()

def _send_notification(fcm_token: str, title: str, body: str, data: dict = None):
    """
    Send push notification to a device via FCM.
    
    Args:
        fcm_token: The device's FCM registration token
        title: Notification title
        body: Notification body
        data: Optional data payload
    """
    import firebase_admin
    from firebase_admin import messaging, credentials
    
    # Initialize Firebase app if not already initialized
    if not firebase_admin._apps:
        cred = credentials.Certificate({
            "type": "service_account",
            "project_id": settings.FIREBASE_PROJECT_ID,
            "private_key_id": settings.FIREBASE_PRIVATE_KEY_ID,
            "private_key": settings.FIREBASE_PRIVATE_KEY,
            "client_email": settings.FIREBASE_CLIENT_EMAIL,
            "client_id": settings.FIREBASE_CLIENT_ID,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "auth_provider_x509_cert_url": "https://www.googleapis.com/oauth2/v1/certs",
            "client_x509_cert_url": f"https://www.googleapis.com/robot/v1/metadata/x509/{settings.FIREBASE_CLIENT_EMAIL.replace('@', '%40')}",
        })
        firebase_admin.initialize_app(cred)
    
    # FCM requires all data values to be strings
    string_data = {k: str(v) for k, v in (data or {}).items()}
    
    message = messaging.Message(
        notification=messaging.Notification(
            title=title,
            body=body,
        ),
        data=string_data,
        token=fcm_token,
    )
    
    try:
        response = messaging.send(message)
        logger.info(f"Successfully sent notification: {response}")
        return response
    except Exception as e:
        logger.error(f"Failed to send notification: {e}")
        return None

    
@celery_app.task(bind=True)
def send_push_notification(self, target: UserGroupTypes, notification_type: NotificationTypes, title: str, message: str, metadata: dict = None):
    
    get_users = _get_users(target)
    sent_count = 0
    failed_count = 0
    
    if not title:
        if notification_type == NotificationTypes.NEW_VIDEO:
            title = "New Video Uploaded"
        elif notification_type == NotificationTypes.COMMENT_REPLY:
            title = "You have a new comment reply"
        
    for user in get_users:
        devices: list[Devices] = user.devices.filter(is_active=True)
        message = message.replace("--username--", user.username)
        for device in devices:
            if device.fcm_token:
                result = _send_notification(device.fcm_token, title, message, data=metadata)
                if result:
                    sent_count += 1
                else:
                    failed_count += 1
            print(f"Push notifications sent: {user.username} | {device.fcm_token}")
        user.notifications.create(
            user = user,
            title = title,
            message = message,
            type = Notification.NOTIFICATION_TYPES.VIDEO if notification_type == NotificationTypes.NEW_VIDEO else Notification.NOTIFICATION_TYPES.PROMO,
            is_read = False,
            target_video_slug = None,
            target_url = None
        )
    
    print(f"Push notifications sent: {sent_count}, failed: {failed_count}")

@celery_app.task(bind=True)
def convert_video_to_hls(self, video_id: int):
    """
    Convert uploaded video to HLS format with multiple quality levels.
    
    Args:
        video_id: ID of the Video object to process
        
    Returns:
        Dictionary with conversion results
    """
    
    try:
        # Get video object
        video = Video.objects.get(id=video_id)
        video.processing_status = 'processing'
        video.save(update_fields=['processing_status'])
        
        logger.info(f"Starting HLS conversion for video {video_id}: {video.title}")
        
        # Get the original video file path
        if not video.video:
            raise ValueError("No video file uploaded")
        
        # Download video from remote storage (R2/S3) to local temp file
        import tempfile
        temp_dir = tempfile.gettempdir()
        video_file_path = os.path.join(temp_dir, f"video_{video_id}_original.mp4")
        
        logger.info(f"Downloading video from storage: {video.video.name}")
        with default_storage.open(video.video.name, 'rb') as source:
            with open(video_file_path, 'wb') as dest:
                dest.write(source.read())
        logger.info(f"Video downloaded to: {video_file_path}")
        
        # Define output directory for HLS files (use temp directory, NOT server storage)
        hls_output_dir = f"videos/hls/{video.uid}"  # Remote path in R2
        import tempfile
        local_hls_dir = os.path.join(tempfile.gettempdir(), f"hls_{video_id}")  # Local temp only
        
        # Initialize video processor
        processor = VideoProcessor(
            input_path=video_file_path,
            output_dir=local_hls_dir
        )
        
        # Convert to HLS
        result = processor.convert_to_hls()
        
        if not result['success']:
            raise Exception(result.get('error', 'Unknown conversion error'))
        
        # Upload HLS files from temp directory to R2 storage
        uploaded_paths = upload_hls_files_to_storage(local_hls_dir, hls_output_dir)
        logger.info(f"Uploaded {len(uploaded_paths)} files to R2 storage")
        
        # Update video object with HLS information
        video.hls_path = hls_output_dir
        video.hls_master_playlist = f"{hls_output_dir}/master.m3u8"
        video.duration = timedelta(seconds=result['duration'])
        video.processing_status = 'completed'
        video.processing_error = None
        video.save(update_fields=[
            'hls_path', 
            'hls_master_playlist', 
            'duration', 
            'processing_status',
            'processing_error'
        ])
        
        # Clean up: Delete original video file from R2 to save storage costs
        if video.video:
            try:
                video.video.delete(save=False)
                logger.info(f"Deleted original MP4 from R2 for video {video_id}")
            except Exception as e:
                logger.warning(f"Could not delete original video from R2: {str(e)}")
        
        # Clean up: Delete ALL local temp files (video + HLS directory)
        cleanup_local_files(video_file_path, local_hls_dir)
        logger.info(f"Cleaned up local temp files for video {video_id}")
        
        logger.info(f"Successfully converted video {video_id} to HLS")
        
        send_push_notification(UserGroupTypes.CLIENTS, NotificationTypes.NEW_VIDEO, title=f"{video.category.name} | {video.title}", message=f"-Hi, -username--! we have a new {video.category.name} video uploaded", metadata={"video_id": video_id})
        
        return {
            'success': True,
            'video_id': video_id,
            'hls_path': hls_output_dir,
            'duration': result['duration']
        }
        
    except Video.DoesNotExist:
        logger.error(f"Video {video_id} not found")
        return {'success': False, 'error': 'Video not found'}
        
    except Exception as e:
        logger.error(f"Error converting video {video_id} to HLS: {str(e)}")
        
        # Update video status to failed
        try:
            video = Video.objects.get(id=video_id)
            video.processing_status = 'failed'
            video.processing_error = str(e)
            video.save(update_fields=['processing_status', 'processing_error'])
        except:
            pass
        
        # Retry the task
        raise 


def upload_hls_files_to_storage(local_dir: str, remote_dir: str) -> list:
    """
    Upload HLS files from local directory to remote storage.
    
    Args:
        local_dir: Local directory containing HLS files
        remote_dir: Remote directory path in storage
        
    Returns:
        List of uploaded file paths
    """
    uploaded_files = []
    
    try:
        for root, dirs, files in os.walk(local_dir):
            for file in files:
                local_file_path = os.path.join(root, file)
                
                # Calculate relative path
                rel_path = os.path.relpath(local_file_path, local_dir)
                remote_file_path = os.path.join(remote_dir, rel_path).replace('\\', '/')
                
                # Upload to storage
                with open(local_file_path, 'rb') as f:
                    default_storage.save(remote_file_path, f)
                
                uploaded_files.append(remote_file_path)
                logger.debug(f"Uploaded {remote_file_path}")
        
        logger.info(f"Uploaded {len(uploaded_files)} HLS files to storage")
        return uploaded_files
        
    except Exception as e:
        logger.error(f"Error uploading HLS files: {str(e)}")
        raise


def cleanup_local_files(video_file_path: str, hls_dir: str):
    """
    Clean up local temporary files after processing.
    
    Args:
        video_file_path: Path to original video file
        hls_dir: Path to HLS output directory
    """
    try:
        import tempfile
        temp_dir = tempfile.gettempdir()
        
        # Remove original video if it's a temp file
        if video_file_path and os.path.exists(video_file_path):
            # Check if file is in temp directory
            if os.path.dirname(video_file_path).startswith(temp_dir):
                os.remove(video_file_path)
                logger.debug(f"Removed temp video file: {video_file_path}")
        
        # Remove HLS directory if it's a temp location
        if hls_dir and os.path.exists(hls_dir):
            # Check if directory is in temp directory
            if hls_dir.startswith(temp_dir):
                import shutil
                shutil.rmtree(hls_dir)
                logger.debug(f"Removed temp HLS directory: {hls_dir}")
            
    except Exception as e:
        logger.warning(f"Error during cleanup: {str(e)}")