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
        cursor = db.cursor()
        # 组装 operation_params
        op_params = {
            "title": payload.title,
            "content": payload.content,
            "target_user_id": payload.target_user_id,
            "target_username": payload.target_username,
        }
        now = datetime.now()
        # 示例：如果无真实登录，这里使用空用户标识
        user_id = payload.target_user_id or "system"
        username = payload.target_username or "system"
        insert_sql = (
            "INSERT INTO operation_logs (user_id, username, operation_type, operation_path, "
            "operation_params, ip_address, operation_time, status) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s)"
        )
        cursor.execute(
            insert_sql,
            (
                user_id,
                username,
                "notify",
                "/api/v1/notifications/push",
                json.dumps(op_params, ensure_ascii=False),
                None,
                now.strftime("%Y-%m-%d %H:%M:%S"),
                "success",
            ),
        )
        db.commit()
        return {"message": "推送成功", "id": cursor.lastrowid}
    except pymysql.MySQLError as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"日志写入失败：{str(e)}")
    finally:
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
    if page < 1:
        page = 1
    if page_size < 1 or page_size > 100:
        page_size = 20

    cursor = None
    try:
        cursor = db.cursor()
        base_where = "operation_type = 'notify'"
        params = []
        if target_user_id:
            base_where += " AND user_id = %s"
            params.append(target_user_id)

        count_sql = f"SELECT COUNT(*) FROM operation_logs WHERE {base_where}"
        cursor.execute(count_sql, params)
        total = cursor.fetchone()[0]

        offset = (page - 1) * page_size
        select_sql = (
            "SELECT id, user_id, username, operation_params, operation_time, status "
            "FROM operation_logs WHERE " + base_where + " ORDER BY operation_time DESC LIMIT %s OFFSET %s"
        )
        cursor.execute(select_sql, params + [page_size, offset])
        rows = cursor.fetchall()

        items = []
        for row in rows:
            # row: (id, user_id, username, operation_params, operation_time, status)
            try:
                op_params = json.loads(row[3]) if row[3] else {}
            except Exception:
                op_params = {}
            items.append(
                NotificationItem(
                    id=row[0],
                    user_id=row[1],
                    username=row[2],
                    title=op_params.get("title", ""),
                    content=op_params.get("content", ""),
                    target_user_id=op_params.get("target_user_id"),
                    target_username=op_params.get("target_username"),
                    operation_time=row[4].strftime("%Y-%m-%d %H:%M:%S") if row[4] else None,
                    status=row[5],
                )
            )

        return NotificationQueryResponse(
            items=items,
            page=page,
            page_size=page_size,
            total=total,
            total_pages=(total + page_size - 1) // page_size,
        )
    except pymysql.MySQLError as e:
        raise HTTPException(status_code=500, detail=f"查询失败：{str(e)}")
    finally:
        if cursor:
            cursor.close()
