"""
Web 模板模組

提供 HTML/CSS/JS 模板組件：
- styles.py: CSS 樣式
- pages/: HTML 頁面模板
"""

from .styles import get_css_styles
from .pages import (
    get_arbitrage_page,
    get_marketmaker_page,
    get_settings_page,
    get_comparison_page,
    get_all_pages,
)

__all__ = [
    'get_css_styles',
    'get_arbitrage_page',
    'get_marketmaker_page',
    'get_settings_page',
    'get_comparison_page',
    'get_all_pages',
]
