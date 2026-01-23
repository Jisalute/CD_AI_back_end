from fastapi import APIRouter, Depends, HTTPException, Query
from typing import Optional
from datetime import datetime
import json
import pymysql

from app.database import get_db
from app.schemas.notification import NotificationPush, NotificationQueryResponse, NotificationItem

router = APIRouter()


@router.post(
    "/push",
    summary="信息推送",
    description="推送一条通知信息，记录到操作日志表（operation_logs）"
)
def push_notification(
    payload: NotificationPush,
    db: pymysql.connections.Connection = Depends(get_db),
    # 可接入真实用户：current_user=Depends(get_current_user)
):
    cursor = None
    try:
        # 1. 核心参数校验
        if not payload.target_user_id:
            raise HTTPException(status_code=400, detail="目标用户ID（target_user_id）不能为空")
        if not payload.title:
            raise HTTPException(status_code=400, detail="消息标题（title）不能为空")
        if not payload.content:
            raise HTTPException(status_code=400, detail="消息内容（content）不能为空")
        
        cursor = db.cursor()
        now = datetime.now()
        now_str = now.strftime("%Y-%m-%d %H:%M:%S")
        
        # 2. 安全获取可选字段（兼容模型中有无这些字段的情况）
        # 使用 getattr 安全访问，避免 AttributeError
        metadata = getattr(payload, "metadata", None)
        source = getattr(payload, "source", None)
        target_username = getattr(payload, "target_username", None)
        
        # 处理JSON字段
        metadata_json = json.dumps(metadata, ensure_ascii=False) if metadata else None
        # 处理source默认值
        source_value = source or "system"
        # 处理用户名默认值
        username_value = target_username or ""
        
        # 3. 组装插入SQL（完全匹配 user_messages 表结构）
        insert_sql = """
        INSERT INTO user_messages (
            user_id, username, title, content, source, status, 
            received_time, metadata, created_at, updated_at
        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """
        
        # 4. 执行插入操作
        cursor.execute(
            insert_sql,
            (
                payload.target_user_id,  # user_id（接收用户ID）
                username_value,          # username（接收用户名，可为空）
                payload.title,           # title（消息标题）
                payload.content,         # content（消息内容）
                source_value,            # source（来源，默认system）
                "unread",                # status（默认未读）
                now_str,                 # received_time（接收时间）
                metadata_json,           # metadata（扩展元数据，可为空）
                now_str,                 # created_at（记录创建时间）
                now_str                  # updated_at（记录更新时间）
            ),
        )
        db.commit()
        
        # 5. 返回推送结果
        return {
            "message": "消息推送成功",
            "message_id": cursor.lastrowid,  # 返回消息ID
            "target_user_id": payload.target_user_id,
            "title": payload.title
        }
        
    except HTTPException:
        # 重新抛出已定义的业务异常
        raise
    except pymysql.MySQLError as e:
        # 数据库异常回滚
        db.rollback()
        raise HTTPException(status_code=500, detail=f"消息记录写入失败：{str(e)}")
    except Exception as e:
        # 捕获所有其他异常，给出友好提示
        raise HTTPException(status_code=500, detail=f"消息推送失败：{str(e)}")
    finally:
        # 仅关闭游标，数据库连接由依赖管理
        if cursor:
            cursor.close()


@router.get(
    "/query",
    response_model=NotificationQueryResponse,
    summary="信息查询",
    description="查询通知类操作日志（operation_type=notify），支持按用户筛选与分页"
)
def query_notifications(
    target_user_id: Optional[str] = Query(None, description="按用户ID筛选"),
    page: int = 1,
    page_size: int = 20,
    db: pymysql.connections.Connection = Depends(get_db),
):
    # 分页参数校验
    if page < 1:
        page = 1
    if page_size < 1 or page_size > 100:
        page_size = 20
    cursor = None
    try:
        cursor = db.cursor()
        # 构建查询条件（适配user_messages表）
        base_where = "1=1" 
        params = []
        # 按用户ID筛选
        if target_user_id:
            base_where += " AND user_id = %s"
            params.append(target_user_id)
        # 查询总记录数
        count_sql = f"SELECT COUNT(*) FROM user_messages WHERE {base_where}"
        cursor.execute(count_sql, params)
        total = cursor.fetchone()[0]
        # 分页查询数据
        offset = (page - 1) * page_size
        select_sql = f"""
        SELECT id, user_id, username, title, content, source, status, received_time, metadata 
        FROM user_messages 
        WHERE {base_where} 
        ORDER BY received_time DESC 
        LIMIT %s OFFSET %s
        """
        cursor.execute(select_sql, params + [page_size, offset])
        rows = cursor.fetchall()
        # 组装返回数据
        items = []
        for row in rows:
            # row结构：(id, user_id, username, title, content, source, status, received_time, metadata)
            try:
                metadata = json.loads(row[8]) if row[8] else {}
            except Exception:
                metadata = {}
            items.append(
                NotificationItem(
                    id=row[0],
                    user_id=row[1],
                    username=row[2] or "",
                    title=row[3],
                    content=row[4],
                    target_user_id=row[1],  # user_messages表中的user_id就是目标用户ID
                    target_username=row[2], # username就是目标用户名
                    operation_time=row[7].strftime("%Y-%m-%d %H:%M:%S") if row[7] else None,
                    status=row[6],  # unread/read
                )
            )
        # 计算总页数
        total_pages = (total + page_size - 1) // page_size
        return NotificationQueryResponse(
            items=items,
            page=page,
            page_size=page_size,
            total=total,
            total_pages=total_pages,
        )
    except pymysql.MySQLError as e:
        raise HTTPException(status_code=500, detail=f"查询失败：{str(e)}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"查询处理失败：{str(e)}")
    finally:
        if cursor:
            cursor.close()
