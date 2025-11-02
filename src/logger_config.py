# src/logger_config.py
import logging
from pythonjsonlogger import jsonlogger

def setup_logger():
    """Configure logging for the application"""
    
    # Create logger
    logger = logging.getLogger("chat_service")
    logger.setLevel(logging.INFO)
    
    # Create console handler
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)
    
    # Create JSON formatter
    json_formatter = jsonlogger.JsonFormatter(
        fmt='%(asctime)s %(name)s %(levelname)s %(message)s'
    )
    
    # Add formatter to handler
    console_handler.setFormatter(json_formatter)
    
    # Add handler to logger
    if not logger.handlers:
        logger.addHandler(console_handler)
    
    return logger

logger = setup_logger()