"""
配置 API 路由

包含:
- GET /api/config/list - 獲取所有配置
- POST /api/config/save - 保存配置
- POST /api/config/delete - 刪除配置
"""

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse


router = APIRouter(prefix="/api/config", tags=["config"])


def register_config_routes(app, dependencies):
    """
    註冊配置相關路由

    Args:
        app: FastAPI 應用實例
        dependencies: 依賴項字典
    """
    config_manager = dependencies['config_manager']
    add_exchange = dependencies['add_exchange']
    remove_exchange = dependencies['remove_exchange']

    @router.get("/list")
    async def list_configs():
        """獲取所有配置"""
        try:
            configs = config_manager.get_all_configs()
            return JSONResponse(configs)
        except Exception as e:
            return JSONResponse({'error': str(e)})

    @router.post("/save")
    async def save_config(request: Request):
        """保存配置並動態添加到監控"""
        try:
            data = await request.json()
            exchange_name = data['exchange_name']
            exchange_type = data['exchange_type']
            config = data['config']

            # 保存配置
            config_manager.save_config(exchange_name, exchange_type, config)

            # 動態添加到監控
            await add_exchange(exchange_name, exchange_type)

            return JSONResponse({'success': True})
        except Exception as e:
            return JSONResponse({'success': False, 'error': str(e)})

    @router.post("/delete")
    async def delete_config(request: Request):
        """刪除配置並從監控移除"""
        try:
            data = await request.json()
            exchange_name = data['exchange_name']
            exchange_type = data['exchange_type']

            # 從監控移除
            await remove_exchange(exchange_name)

            # 刪除配置
            config_manager.delete_config(exchange_name, exchange_type)

            return JSONResponse({'success': True})
        except Exception as e:
            return JSONResponse({'success': False, 'error': str(e)})

    app.include_router(router)
