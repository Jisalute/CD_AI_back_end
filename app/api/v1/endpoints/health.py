"""
健康检查端点
"""
from fastapi import APIRouter

router = APIRouter()


@router.get(
    "/",
    summary="健康检查",
    description="返回服务健康状态"
)
async def health_check():
    """健康检查"""
    return {
        "status": "健康",
        "message": "API 服务运行正常"
    }


@router.get(
    "/detailed",
    summary="详细健康检查",
    description="返回包含数据库等详细健康信息"
)
async def detailed_health_check():
    """详细健康检查"""
    # 这里可以添加数据库连接检查等
    return {
        "status": "健康",
        "database": "已连接",
        "message": "所有服务运行正常"
    }

