"""
HTML 頁面模組

提供各頁面的 HTML 內容
"""

from .arbitrage import get_arbitrage_page
from .marketmaker import get_marketmaker_page
from .grvt_marketmaker import get_grvt_marketmaker_page
from .settings import get_settings_page
from .comparison import get_comparison_page


def get_all_pages() -> str:
    """返回所有頁面的 HTML"""
    return "\n".join([
        get_arbitrage_page(),
        get_marketmaker_page(),
        get_grvt_marketmaker_page(),
        get_settings_page(),
        get_comparison_page(),
    ])


__all__ = [
    'get_arbitrage_page',
    'get_marketmaker_page',
    'get_grvt_marketmaker_page',
    'get_settings_page',
    'get_comparison_page',
    'get_all_pages',
]
