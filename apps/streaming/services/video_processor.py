"""
Video processing service for HLS conversion with adaptive bitrate streaming.
Converts uploaded MP4 videos to HLS format with multiple quality levels.
"""
import os
import subprocess
import logging
import shutil
from pathlib import Path
from typing import Dict, List, Tuple
from django.conf import settings

logger = logging.getLogger(__name__)


def check_ffmpeg_installed():
    """Check if FFmpeg is installed and accessible."""
    ffmpeg_path = shutil.which('ffmpeg')
    
    # If not in PATH, try common Windows Chocolatey location
    if not ffmpeg_path:
        choco_ffmpeg = r"C:\ProgramData\chocolatey\lib\ffmpeg\tools\ffmpeg\bin\ffmpeg.exe"
        if os.path.exists(choco_ffmpeg):
            ffmpeg_path = choco_ffmpeg
        else:
            raise RuntimeError(
                "FFmpeg is not installed or not in PATH. "
                "Please install FFmpeg:\n"
                "Windows: choco install ffmpeg OR download from https://ffmpeg.org/download.html\n"
                "Linux: sudo apt-get install ffmpeg\n"
                "macOS: brew install ffmpeg"
            )
    
    logger.info(f"FFmpeg found at: {ffmpeg_path}")
    return ffmpeg_path


class VideoProcessor:
    """
    Handles video conversion to HLS format with multiple quality levels.
    """
    
    # Quality presets for adaptive bitrate streaming
    QUALITY_PRESETS = [
        {
            'name': '1080p',
            'resolution': '1920x1080',
            'video_bitrate': '5000k',
            'audio_bitrate': '192k',
            'maxrate': '5350k',
            'bufsize': '7500k'
        },
        {
            'name': '720p',
            'resolution': '1280x720',
            'video_bitrate': '2800k',
            'audio_bitrate': '128k',
            'maxrate': '2996k',
            'bufsize': '4200k'
        },
        {
            'name': '480p',
            'resolution': '854x480',
            'video_bitrate': '1400k',
            'audio_bitrate': '128k',
            'maxrate': '1498k',
            'bufsize': '2100k'
        },
        {
            'name': '360p',
            'resolution': '640x360',
            'video_bitrate': '800k',
            'audio_bitrate': '96k',
            'maxrate': '856k',
            'bufsize': '1200k'
        },
    ]
    
    def __init__(self, input_path: str, output_dir: str):
        """
        Initialize the video processor.
        
        Args:
            input_path: Path to the input MP4 file
            output_dir: Directory where HLS files will be saved
        """
        self.input_path = input_path
        self.output_dir = output_dir
        self.segment_duration = getattr(settings, 'HLS_SEGMENT_DURATION', 6)
        
        # Check FFmpeg availability
        self.ffmpeg_path = check_ffmpeg_installed()
        
    def convert_to_hls(self) -> Dict[str, any]:
        """
        Convert video to HLS format with multiple quality levels.
        
        Returns:
            Dictionary containing conversion results and file paths
        """
        try:
            # Create output directory if it doesn't exist
            Path(self.output_dir).mkdir(parents=True, exist_ok=True)
            
            # Get video metadata
            duration = self._get_video_duration()
            
            # Generate HLS variants for each quality
            variants = []
            for preset in self.QUALITY_PRESETS:
                variant_info = self._create_hls_variant(preset)
                if variant_info:
                    variants.append(variant_info)
            
            # Create master playlist
            master_playlist_path = self._create_master_playlist(variants)
            
            return {
                'success': True,
                'master_playlist': master_playlist_path,
                'variants': variants,
                'duration': duration,
                'output_dir': self.output_dir
            }
            
        except Exception as e:
            logger.error(f"Error converting video to HLS: {str(e)}")
            return {
                'success': False,
                'error': str(e)
            }
    
    def _create_hls_variant(self, preset: Dict) -> Dict:
        """
        Create HLS variant for a specific quality preset.
        
        Args:
            preset: Quality preset configuration
            
        Returns:
            Dictionary with variant information
        """
        try:
            variant_name = preset['name']
            variant_dir = os.path.join(self.output_dir, variant_name)
            Path(variant_dir).mkdir(parents=True, exist_ok=True)
            
            playlist_filename = f"{variant_name}.m3u8"
            playlist_path = os.path.join(variant_dir, playlist_filename)
            segment_pattern = os.path.join(variant_dir, f"{variant_name}_%03d.ts")
            
            # FFmpeg command for HLS conversion
            cmd = [
                self.ffmpeg_path,
                '-i', self.input_path,
                '-c:v', 'libx264',
                '-c:a', 'aac',
                '-b:v', preset['video_bitrate'],
                '-b:a', preset['audio_bitrate'],
                '-maxrate', preset['maxrate'],
                '-bufsize', preset['bufsize'],
                '-s', preset['resolution'],
                '-profile:v', 'main',
                '-level', '4.0',
                '-start_number', '0',
                '-hls_time', str(self.segment_duration),
                '-hls_list_size', '0',
                '-hls_segment_filename', segment_pattern,
                '-f', 'hls',
                playlist_path
            ]
            
            # Execute FFmpeg command
            result = subprocess.run(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True
            )
            
            if result.returncode != 0:
                logger.error(f"FFmpeg error for {variant_name}: {result.stderr}")
                return None
            
            # Get relative path for playlist
            relative_playlist = os.path.join(variant_name, playlist_filename)
            
            return {
                'name': variant_name,
                'resolution': preset['resolution'],
                'bandwidth': self._calculate_bandwidth(preset),
                'playlist': relative_playlist,
                'playlist_path': playlist_path
            }
            
        except Exception as e:
            logger.error(f"Error creating HLS variant {preset['name']}: {str(e)}")
            return None
    
    def _create_master_playlist(self, variants: List[Dict]) -> str:
        """
        Create HLS master playlist that references all quality variants.
        
        Args:
            variants: List of variant information dictionaries
            
        Returns:
            Path to the master playlist file
        """
        master_playlist_path = os.path.join(self.output_dir, 'master.m3u8')
        
        with open(master_playlist_path, 'w') as f:
            f.write('#EXTM3U\n')
            f.write('#EXT-X-VERSION:3\n\n')
            
            for variant in variants:
                # Write stream info
                f.write(f'#EXT-X-STREAM-INF:BANDWIDTH={variant["bandwidth"]},'
                       f'RESOLUTION={variant["resolution"]}\n')
                f.write(f'{variant["playlist"]}\n\n')
        
        return master_playlist_path
    
    def _get_video_duration(self) -> float:
        """
        Get video duration using ffprobe.
        
        Returns:
            Duration in seconds
        """
        try:
            # Use ffprobe from the same directory as ffmpeg
            if self.ffmpeg_path.endswith('.exe'):
                ffprobe_path = self.ffmpeg_path.replace('ffmpeg.exe', 'ffprobe.exe')
            else:
                ffprobe_path = self.ffmpeg_path.replace('ffmpeg', 'ffprobe')
            
            if not os.path.exists(ffprobe_path):
                ffprobe_path = shutil.which('ffprobe')
                if not ffprobe_path:
                    # Try Chocolatey location
                    choco_ffprobe = r"C:\ProgramData\chocolatey\lib\ffmpeg\tools\ffmpeg\bin\ffprobe.exe"
                    if os.path.exists(choco_ffprobe):
                        ffprobe_path = choco_ffprobe
                    else:
                        ffprobe_path = 'ffprobe'
            
            cmd = [
                ffprobe_path,
                '-v', 'error',
                '-show_entries', 'format=duration',
                '-of', 'default=noprint_wrappers=1:nokey=1',
                self.input_path
            ]
            
            result = subprocess.run(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True
            )
            
            if result.returncode == 0:
                return float(result.stdout.strip())
            return 0.0
            
        except Exception as e:
            logger.error(f"Error getting video duration: {str(e)}")
            return 0.0
    
    def _calculate_bandwidth(self, preset: Dict) -> int:
        """
        Calculate bandwidth for a quality preset.
        
        Args:
            preset: Quality preset configuration
            
        Returns:
            Bandwidth in bits per second
        """
        # Convert bitrates to bps and sum video + audio
        video_bps = int(preset['video_bitrate'].replace('k', '')) * 1000
        audio_bps = int(preset['audio_bitrate'].replace('k', '')) * 1000
        return video_bps + audio_bps
    
    @staticmethod
    def cleanup_original_file(file_path: str) -> bool:
        """
        Delete the original uploaded video file after successful conversion.
        
        Args:
            file_path: Path to the file to delete
            
        Returns:
            True if deletion was successful, False otherwise
        """
        try:
            if os.path.exists(file_path):
                os.remove(file_path)
                logger.info(f"Deleted original file: {file_path}")
                return True
            return False
        except Exception as e:
            logger.error(f"Error deleting original file: {str(e)}")
            return False
