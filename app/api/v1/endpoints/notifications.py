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
    description="推送一条通知信息，记录到user_messages表"
)
def push_notification(
    payload: NotificationPush,
    db: pymysql.connections.Connection = Depends(get_db),
    # 可接入真实用户：current_user=Depends(get_current_user)
):
    cursor = None
    try:
        cursor = db.cursor()
        insert_sql = (
            "INSERT INTO user_messages (user_id, username, title, content, source, status, received_time) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s)"
        )
        cursor.execute(
            insert_sql,
            (
                payload.target_user_id,
                payload.target_username,
                payload.title,
                payload.content,
                "system",  # 假设来源为系统
                "unread",
                datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            ),
        )
        db.commit()
        return {"message": "推送成功", "id": cursor.lastrowid}
    except pymysql.MySQLError as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"推送失败：{str(e)}")
    finally:
        if cursor:
            cursor.close()


@router.get(
    "/query",
    response_model=NotificationQueryResponse,
    summary="信息查询",
    description="查询通知类消息（user_messages），支持按用户筛选与分页"
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
        base_where = ""
        params = []
        if target_user_id:
            base_where = "WHERE user_id = %s"
            params.append(target_user_id)

        count_sql = f"SELECT COUNT(*) FROM user_messages {base_where}"
        cursor.execute(count_sql, params)
        total = cursor.fetchone()[0]

        offset = (page - 1) * page_size
        select_sql = (
            "SELECT id, user_id, username, title, content, source, status, received_time "
            f"FROM user_messages {base_where} ORDER BY received_time DESC LIMIT %s OFFSET %s"
        )
        cursor.execute(select_sql, params + [page_size, offset])
        rows = cursor.fetchall()

        items = []
        for row in rows:
            # row: (id, user_id, username, title, content, source, status, received_time)
            items.append(
                NotificationItem(
                    id=row[0],
                    user_id=row[1],
                    username=row[2],
                    title=row[3],
                    content=row[4],
                    target_user_id=row[1],  # 假设目标用户就是接收用户
                    target_username=row[2],
                    operation_time=row[7].strftime("%Y-%m-%d %H:%M:%S") if row[7] else None,
                    status=row[6],
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
