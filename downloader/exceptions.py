"""
Custom exceptions for ThumbBot downloader
"""


class ThumbBotError(Exception):
    """Base exception for ThumbBot"""
    pass


class FileTooLargeError(ThumbBotError):
    """Raised when the file size exceeds the allowed limit"""
    pass


class CobaltError(ThumbBotError):
    """Raised when there is a problem with Cobalt API"""
    pass


class DownloadError(ThumbBotError):
    """Raised when a download fails"""
    pass


class UploadError(ThumbBotError):
    """Raised when a Discord upload fails"""
    pass

