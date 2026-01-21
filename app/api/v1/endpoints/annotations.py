from fastapi import APIRouter, Depends, HTTPException
from app.core.dependencies import get_current_user
from app.schemas.annotation import AnnotationCreate, AnnotationOut
import pymysql
import json
from app.database import get_db
from loguru import logger
from datetime import datetime

router = APIRouter()


@router.post(
    "/",
    response_model=AnnotationOut,
    summary="创建论文标注",
    description="为指定论文创建标注并校验坐标后入库"
)
def create_annotation(
    # TODO: 权限与坐标校验，持久化到数据库
    payload: AnnotationCreate,
    # current_user=Depends(get_current_user),
    current_user = {"sub": 1, "username": "test_user", "roles": ["admin"]},
    db: pymysql.connections.Connection = Depends(get_db)
):

    try:
        if isinstance(current_user, str):
            # 解码URL编码的字符串
            import urllib.parse
            current_user = urllib.parse.unquote(current_user)
            # 解析为字典
            current_user = json.loads(current_user)
        if not isinstance(current_user, dict):
            current_user = {"sub": 0, "username": "", "roles": []}
    except (json.JSONDecodeError, Exception) as e:
        logger.error(f"解析current_user失败: {str(e)}")
        current_user = {"sub": 0, "username": "", "roles": []}

    # 表结构已由 database_setup.py 统一维护

    # 权限校验：验证当前用户是否有权限操作该论文
    try:
        cursor = db.cursor()
        cursor.execute(
            """
            SELECT 1 FROM papers 
            WHERE id = %s AND owner_id = %s
            """,
            (payload.paper_id, current_user.get("sub", 0)) 
        )
        has_permission = cursor.fetchone()
        if not has_permission:
            logger.warning(
                f"用户{current_user.get('sub')}无权限为论文{payload.paper_id}创建标注"
            )
            raise HTTPException(
                status_code=403,
                detail="无权限为该论文创建标注，请确认论文归属"
            )
    except pymysql.MySQLError as e:
        logger.error(f"权限校验数据库异常: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail="权限校验失败，请稍后重试"
        )
    finally:
        cursor.close()

    # 坐标校验：如果传入coordinates则验证格式合法性
    if payload.coordinates:
        try:
            required_coord_fields = ("x", "y")
            alternative_fields = ("top", "left", "width", "height")
            has_basic_coords = (
                all(k in payload.coordinates for k in required_coord_fields) or
                all(k in payload.coordinates for k in alternative_fields)
            )
            if not has_basic_coords:
                raise ValueError(f"坐标需包含{required_coord_fields}或{alternative_fields}字段")
            
            for k, v in payload.coordinates.items():
                if k in list(required_coord_fields) + list(alternative_fields):
                    if not isinstance(v, (int, float)):
                        raise ValueError(f"坐标{k}必须为数字类型")
        except ValueError as e:
            logger.warning(f"标注坐标格式错误: {str(e)}")
            raise HTTPException(
                status_code=400,
                detail=f"坐标格式不合法: {str(e)}"
            )

    # 持久化到数据库
    try:
        cursor = db.cursor()
        # 插入标注数据
        insert_sql = """
        INSERT INTO annotations (
            paper_id, author_id, paragraph_id, coordinates, content, created_at
        ) VALUES (%s, %s, %s, %s, %s, %s)
        """
        # 处理coordinates：转为JSON字符串
        coord_json = json.dumps(payload.coordinates) if payload.coordinates else None
        cursor.execute(
            insert_sql,
            (
                payload.paper_id,
                current_user.get("sub", 0),
                payload.paragraph_id,
                coord_json,
                payload.content,
                datetime.now()
            )
        )
        db.commit()
        
        annotation_id = cursor.lastrowid
        logger.info(
            f"用户{current_user.get('sub')}为论文{payload.paper_id}创建标注成功，ID: {annotation_id}"
        )
        
        return AnnotationOut(
            id=annotation_id,
            paper_id=payload.paper_id,
            author_id=current_user.get("sub", 0),
            content=payload.content
        )
    except pymysql.MySQLError as e:
        db.rollback()
        logger.error(f"标注存储数据库异常: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail="标注创建失败，请稍后重试"
        )
    finally:
        cursor.close()