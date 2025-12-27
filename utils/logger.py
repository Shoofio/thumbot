"""
Logging for ThumbBot
"""
import sys
import os
from loguru import logger


def setup_logger(log_level: str = "INFO"):
    """Configure loguru with colors for stdout only"""
    
    # Remove default handler
    logger.remove()
    
    # Console handler with colors (stdout only)
    logger.add(
        sys.stdout,
        format="<level>{level: <8}</level> | <level>{message}</level>",
        level=log_level.upper(),
        colorize=True,
        backtrace=True,
        diagnose=True
    )


def get_logger(name: str = None):
    """Get a logger instance with optional name"""
    if name:
        return logger.bind(name=name)
    return logger


# Initialize logger on import
setup_logger(os.getenv("LOG_LEVEL", "INFO"))

