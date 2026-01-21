"""
FastAPI应用主入口
"""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from app.middleware import setup_middleware
from app.api.v1.routes import api_router
import uvicorn
from app.config import settings
from datetime import datetime  
from app.database import get_db  

# 创建FastAPI应用实例
app = FastAPI(
    title=settings.PROJECT_NAME,
    version=settings.VERSION,
    description=settings.DESCRIPTION,
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json"
)

# OpenAPI 标签本地化（用于 Swagger UI 展示中文分组）
openapi_tags = [
    {"name": "健康检查", "description": "服务健康状态与详细信息"},
    {"name": "材料", "description": "材料上传与管理"},
    {"name": "群组", "description": "群组与师生关系导入"},
    {"name": "论文", "description": "论文上传与版本管理"},
    {"name": "AI评审", "description": "AI 自动评审与报告"},
    {"name": "标注", "description": "论文标注创建与查询"},
    {"name": "管理", "description": "后台管理、模板与审计"},
]
app.openapi_tags = openapi_tags

# 配置CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 添加Gzip压缩
app.add_middleware(GZipMiddleware, minimum_size=1000)

# 设置自定义中间件
setup_middleware(app)

# 注册API路由
app.include_router(api_router, prefix="/api/v1")


@app.get("/")
async def root():
    """根路径"""
    return {
        "message": "欢迎使用 CD AI 后端 API",
        "version": settings.VERSION,
        "docs": "/docs"
    }


@app.get("/health")
async def health_check():
    """健康检查"""
    return {"status": "ok", "message": "服务正在运行"}


if __name__ == "__main__":
    # 以模块路径形式启动，才能在 reload 模式下正常工作
    uvicorn.run(
        "main:app",
        host=settings.HOST,
        port=settings.PORT,
        reload=settings.RELOAD,
        log_level="info",
    )