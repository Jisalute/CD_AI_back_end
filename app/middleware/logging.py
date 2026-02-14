"""
日志中间件
"""
import time
from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from loguru import logger


class LoggingMiddleware(BaseHTTPMiddleware):
    """请求日志中间件"""
    
    async def dispatch(self, request: Request, call_next):
        start_time = time.time()
        
        # 记录请求信息
        logger.info(
            f"请求: {request.method} {request.url.path} - "
            f"客户端: {request.client.host if request.client else 'Unknown'}"
        )
        
        # 处理请求
        try:
            response = await call_next(request)
        except Exception:
            logger.exception(
                f"请求处理异常: {request.method} {request.url.path} - "
                f"客户端: {request.client.host if request.client else 'Unknown'}"
            )
            raise
        
        # 计算处理时间
        process_time = time.time() - start_time
        
        # 记录响应信息
        logger.info(
            f"响应: {request.method} {request.url.path} - "
            f"状态码: {response.status_code} - "
            f"耗时: {process_time:.3f}s"
        )
        
        response.headers["X-Process-Time"] = str(process_time)
        return response

