"""Utility functions and helpers."""

import logging
import sys
from pathlib import Path
from datetime import datetime


def setup_logger(name: str, log_file: str = None, level: str = 'INFO') -> logging.Logger:
    """
    Setup logger with console and file handlers.
    
    Args:
        name: Logger name
        log_file: Optional log file path
        level: Logging level
        
    Returns:
        Configured logger
    """
    logger = logging.getLogger(name)
    logger.setLevel(getattr(logging, level.upper()))
    
    # Console handler
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.DEBUG)
    console_format = logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    console_handler.setFormatter(console_format)
    logger.addHandler(console_handler)
    
    # File handler
    if log_file:
        # Create logs directory if needed
        log_path = Path(log_file)
        log_path.parent.mkdir(parents=True, exist_ok=True)
        
        file_handler = logging.FileHandler(log_file)
        file_handler.setLevel(logging.DEBUG)
        file_format = logging.Formatter(
            '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
        )
        file_handler.setFormatter(file_format)
        logger.addHandler(file_handler)
    
    return logger


def format_timestamp(timestamp_ms: int) -> str:
    """
    Format timestamp to readable string.
    
    Args:
        timestamp_ms: Timestamp in milliseconds
        
    Returns:
        Formatted datetime string
    """
    dt = datetime.fromtimestamp(timestamp_ms / 1000)
    return dt.strftime('%Y-%m-%d %H:%M:%S')


def round_to_precision(value: float, precision: int) -> float:
    """
    Round value to specific decimal precision.
    
    Args:
        value: Value to round
        precision: Number of decimal places
        
    Returns:
        Rounded value
    """
    multiplier = 10 ** precision
    return round(value * multiplier) / multiplier


def calculate_pnl_percentage(entry_price: float, current_price: float, is_long: bool) -> float:
    """
    Calculate P&L percentage.
    
    Args:
        entry_price: Entry price
        current_price: Current price
        is_long: True if long position
        
    Returns:
        P&L percentage
    """
    if is_long:
        return ((current_price - entry_price) / entry_price) * 100
    else:
        return ((entry_price - current_price) / entry_price) * 100


def format_number(value: float, decimals: int = 2) -> str:
    """
    Format number with commas and decimal places.
    
    Args:
        value: Number to format
        decimals: Decimal places
        
    Returns:
        Formatted string
    """
    return f"{value:,.{decimals}f}"
