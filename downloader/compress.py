"""
Video compression using ffmpeg
"""
import os
import asyncio
import subprocess
from typing import Optional

from thumbot.utils.logger import get_logger

logger = get_logger("compress")


async def compress_video(
    input_path: str,
    target_size_mb: float,
    output_path: Optional[str] = None
) -> Optional[str]:
    """
    Compress a video to fit within target size using ffmpeg
    
    Args:
        input_path: Path to input video file
        target_size_mb: Target file size in MB
        output_path: Optional output path (default: input_compressed.ext)
    
    Returns:
        Path to compressed file, or None if compression failed
    """
    if not os.path.exists(input_path):
        logger.error(f"Input file not found: {input_path}")
        return None
    
    # Get input file info
    input_size = os.path.getsize(input_path)
    input_size_mb = input_size / (1024 * 1024)
    
    # Generate output path
    if not output_path:
        base, ext = os.path.splitext(input_path)
        output_path = f"{base}_compressed{ext}"
    
    # Get video duration
    duration = await _get_video_duration(input_path)
    if not duration or duration <= 0:
        logger.error("Could not determine video duration")
        return None
    
    # Calculate target bitrate
    # Target size in bits, minus 10% buffer for container overhead
    target_size_bits = target_size_mb * 8 * 1024 * 1024 * 0.9
    
    # Total bitrate (video + audio)
    target_bitrate = int(target_size_bits / duration)
    
    # Reserve ~128kbps for audio, rest for video
    audio_bitrate = min(128000, target_bitrate // 4)
    video_bitrate = target_bitrate - audio_bitrate
    
    # Minimum viable bitrate check
    if video_bitrate < 100000:  # 100kbps minimum
        logger.warning(f"Target bitrate too low ({video_bitrate}bps), video would be unwatchable")
        return None
    
    logger.info(f"Compressing {input_size_mb:.1f}MB -> {target_size_mb:.1f}MB target")
    logger.info(f"Duration: {duration:.1f}s, Video bitrate: {video_bitrate // 1000}kbps")
    
    # Build ffmpeg command
    cmd = [
        "ffmpeg",
        "-y",  # Overwrite output
        "-i", input_path,
        "-c:v", "libx264",  # H.264 codec
        "-preset", "fast",  # Balance speed/quality
        "-b:v", str(video_bitrate),
        "-maxrate", str(int(video_bitrate * 1.5)),  # Allow some headroom
        "-bufsize", str(int(video_bitrate * 2)),
        "-c:a", "aac",  # AAC audio
        "-b:a", str(audio_bitrate),
        "-movflags", "+faststart",  # Web optimization
        "-loglevel", "error",  # Only show errors
        output_path
    ]
    
    try:
        # Run ffmpeg asynchronously
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        
        stdout, stderr = await process.communicate()
        
        if process.returncode != 0:
            error_msg = stderr.decode() if stderr else "Unknown error"
            logger.error(f"ffmpeg failed: {error_msg}")
            return None
        
        # Verify output
        if not os.path.exists(output_path):
            logger.error("Compressed file not created")
            return None
        
        output_size = os.path.getsize(output_path)
        output_size_mb = output_size / (1024 * 1024)
        
        # Check if we hit the target (within 10% margin)
        if output_size_mb > target_size_mb * 1.1:
            logger.warning(f"Compressed file still too large: {output_size_mb:.1f}MB > {target_size_mb:.1f}MB")
            # Try a second pass with lower bitrate
            os.remove(output_path)
            return await _compress_second_pass(input_path, target_size_mb, duration, output_path)
        
        logger.success(f"Compressed: {input_size_mb:.1f}MB -> {output_size_mb:.1f}MB")
        return output_path
        
    except Exception as e:
        logger.error(f"Compression failed: {e}")
        if os.path.exists(output_path):
            os.remove(output_path)
        return None


async def _get_video_duration(file_path: str) -> Optional[float]:
    """Get video duration in seconds using ffprobe"""
    cmd = [
        "ffprobe",
        "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        file_path
    ]
    
    try:
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        
        stdout, _ = await process.communicate()
        
        if process.returncode == 0 and stdout:
            return float(stdout.decode().strip())
        return None
        
    except Exception as e:
        logger.debug(f"Could not get duration: {e}")
        return None


async def _compress_second_pass(
    input_path: str,
    target_size_mb: float,
    duration: float,
    output_path: str
) -> Optional[str]:
    """Second compression pass with more aggressive settings"""
    
    # More aggressive: 70% of target size
    target_size_bits = target_size_mb * 8 * 1024 * 1024 * 0.7
    target_bitrate = int(target_size_bits / duration)
    
    audio_bitrate = min(96000, target_bitrate // 4)  # Lower audio
    video_bitrate = target_bitrate - audio_bitrate
    
    if video_bitrate < 80000:
        logger.error("Cannot compress further without severe quality loss")
        return None
    
    logger.info(f"Second pass: Video bitrate: {video_bitrate // 1000}kbps")
    
    cmd = [
        "ffmpeg",
        "-y",
        "-i", input_path,
        "-c:v", "libx264",
        "-preset", "slow",  # Better compression
        "-crf", "28",  # Quality-based with target bitrate as cap
        "-b:v", str(video_bitrate),
        "-maxrate", str(video_bitrate),
        "-bufsize", str(video_bitrate),
        "-vf", "scale=-2:720",  # Max 720p
        "-c:a", "aac",
        "-b:a", str(audio_bitrate),
        "-movflags", "+faststart",
        "-loglevel", "error",
        output_path
    ]
    
    try:
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        
        stdout, stderr = await process.communicate()
        
        if process.returncode != 0:
            error_msg = stderr.decode() if stderr else "Unknown error"
            logger.error(f"Second pass failed: {error_msg}")
            return None
        
        if os.path.exists(output_path):
            output_size_mb = os.path.getsize(output_path) / (1024 * 1024)
            logger.success(f"Second pass: {output_size_mb:.1f}MB")
            return output_path
        
        return None
        
    except Exception as e:
        logger.error(f"Second pass failed: {e}")
        return None

