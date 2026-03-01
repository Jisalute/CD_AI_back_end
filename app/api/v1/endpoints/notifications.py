from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from typing import Optional
from datetime import datetime
import json
import pymysql

from app.database import get_db
from app.schemas.notification import NotificationQueryResponse, NotificationItem, NotificationUpdate

router = APIRouter()


class NotificationContent(BaseModel):
    title: str
    content: str


@router.post(
    "/push",
    summary="信息推送",
    description="推送通知信息，支持单个用户或多个用户批量推送，记录到 user_messages 表"
)
def push_notification(
    payload: NotificationContent,
    target_user_id: str | None = Query(None, description="单个目标用户ID"),
    target_user_ids: str | None = Query(None, description="批量目标用户ID列表，逗号分隔，例如: 1,2,3"),
    current_user: str = Query(..., description="当前用户信息(JSON字符串)，示例: {\"sub\":1,\"roles\":[\"teacher\"],\"username\":\"teacher1\"}"),
    db: pymysql.connections.Connection = Depends(get_db),
):
    cursor = None
    try:
        # 1. 核心参数校验
        if not (target_user_id or target_user_ids):
            raise HTTPException(status_code=400, detail="必须提供目标用户ID（target_user_id）或目标用户ID列表（target_user_ids）")
        if not payload.title:
            raise HTTPException(status_code=400, detail="消息标题（title）不能为空")
        if not payload.content:
            raise HTTPException(status_code=400, detail="消息内容（content）不能为空")
        
        # 2. 解析 current_user 获取发送者信息
        try:
            import urllib.parse
            current_user = urllib.parse.unquote(current_user)
            current_user_data = json.loads(current_user)
            sender_id = str(current_user_data.get("sub"))
            sender_roles = current_user_data.get("roles", [])
            sender_role = sender_roles[0] if sender_roles else "user"
        except Exception:
            sender_id = "unknown"
            sender_role = "user"
        
        cursor = db.cursor()
        now = datetime.now()
        now_str = now.strftime("%Y-%m-%d %H:%M:%S")
        
        # 3. 准备目标用户列表
        target_users = []
        if target_user_id:
            target_users.append({"user_id": target_user_id, "username": ""})
        if target_user_ids:
            user_id_list = [uid.strip() for uid in target_user_ids.split(",") if uid.strip()]
            for user_id in user_id_list:
                target_users.append({"user_id": user_id, "username": ""})
        
        # 4. 处理消息内容
        content_value = payload.content or ""
        metadata = {}
        # 如果 content 超过 TEXT 大小（防护），将超长部分保存到 metadata.long_content
        if len(content_value) > 60000:
            metadata["long_content"] = content_value[60000:]
            content_value = content_value[:60000]

        # 5. 保存 sender 信息到 metadata
        metadata["sender_id"] = sender_id
        metadata["sender_role"] = sender_role

        metadata_json = json.dumps(metadata, ensure_ascii=False) if metadata else None
        source_value = "system"  # 固定来源
        
        # 4. 组装插入SQL
        insert_sql = """
        INSERT INTO user_messages (
            user_id, username, title, content, source, status, 
            received_time, metadata, created_at, updated_at
        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """
        
        # 5. 批量执行插入操作
        inserted_ids = []
        for user in target_users:
            cursor.execute(
                insert_sql,
                (
                    user["user_id"],     # user_id（接收用户ID）
                    user["username"],    # username（接收用户名，可为空）
                    payload.title,        # title（消息标题）
                    content_value,        # content（消息内容，已按长度保护）
                    source_value,         # source（来源）
                    "unread",            # status（默认未读）
                    now_str,              # received_time（接收时间）
                    metadata_json,        # metadata（扩展元数据）
                    now_str,              # created_at（记录创建时间）
                    now_str               # updated_at（记录更新时间）
                ),
            )
            inserted_ids.append(cursor.lastrowid)
        
        db.commit()
        
        # 6. 返回推送结果
        return {
            "message": f"消息推送成功，共推送 {len(target_users)} 条消息",
            "message_ids": inserted_ids,
            "target_user_count": len(target_users),
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
    summary="查看已推送消息",
    description="管理员和教师查看已推送的消息，支持按发送者、目标用户和状态筛选与分页"
)
def query_notifications(
    user_type: str = Query(..., description="用户类型：admin(管理员) 或 teacher(教师)"),
    target_user_id: Optional[str] = Query(None, description="按目标用户ID筛选"),
    sender_id: Optional[str] = Query(None, description="按发送者ID筛选（仅管理员可用）"),
    status: Optional[str] = Query(None, description="按状态筛选：unread, read, retracted"),
    page: int = 1,
    page_size: int = 20,
    current_user: str = Query(..., description="当前用户信息(JSON字符串)，示例: {\"sub\":1,\"roles\":[\"teacher\"],\"username\":\"teacher1\"}"),
    db: pymysql.connections.Connection = Depends(get_db),
):
    # 1. 权限校验
    try:
        import urllib.parse
        current_user = urllib.parse.unquote(current_user)
        current_user_data = json.loads(current_user)
        user_roles = current_user_data.get("roles", [])
        
        # 验证用户类型选择是否与实际身份一致
        if user_type == "admin":
            if "admin" not in user_roles:
                raise HTTPException(status_code=403, detail="当前用户不是管理员，无法以管理员身份查看")
        elif user_type == "teacher":
            if "teacher" not in user_roles and "admin" not in user_roles:
                raise HTTPException(status_code=403, detail="当前用户不是教师，无法以教师身份查看")
        else:
            raise HTTPException(status_code=400, detail="用户类型必须是 admin 或 teacher")
            
    except json.JSONDecodeError:
        raise HTTPException(status_code=403, detail="无效的用户信息格式")
    except HTTPException:
        raise
    
    # 2. 分页参数校验
    if page < 1:
        page = 1
    if page_size < 1 or page_size > 100:
        page_size = 20
    
    cursor = None
    try:
        cursor = db.cursor()
        # 3. 构建查询条件
        base_where = "1=1" 
        params = []
        
        # 权限限制：根据选择的用户类型
        user_sub = str(current_user_data.get("sub"))
        
        if user_type == "teacher":
            # 老师只能查看自己发送的消息
            # 但如果消息没有 sender_id，也允许查看
            base_where += " AND (metadata LIKE %s OR metadata IS NULL OR metadata = '{}')"
            params.append(f'%\"sender_id\":\"{user_sub}\"%')
        
        # 按目标用户ID筛选
        if target_user_id:
            # 教师只能查看自己学生的消息
            if user_type == "teacher":
                # 检查学生是否是该教师的学生（通过群组关系）
                check_sql = """
                SELECT 1 FROM group_members gm1
                JOIN group_members gm2 ON gm1.group_id = gm2.group_id
                WHERE gm1.member_id = %s AND gm1.member_type = 'student' AND gm1.is_active = 1
                AND gm2.member_id = %s AND gm2.member_type = 'teacher' AND gm2.is_active = 1
                LIMIT 1
                """
                cursor.execute(check_sql, (target_user_id, user_sub))
                if not cursor.fetchone():
                    raise HTTPException(status_code=403, detail="无权查看该学生的消息，该学生不是您的学生")
            
            base_where += " AND user_id = %s"
            params.append(target_user_id)
        
        # 按发送者ID筛选（仅管理员可用）
        if sender_id and user_type == "admin":
            base_where += " AND metadata LIKE %s"
            params.append(f'%\"sender_id\":\"{sender_id}\"%')
        
        # 按状态筛选
        if status:
            base_where += " AND status = %s"
            params.append(status)
        
        # 4. 查询总记录数
        count_sql = f"SELECT COUNT(*) FROM user_messages WHERE {base_where}"
        cursor.execute(count_sql, params)
        total = cursor.fetchone()[0]
        
        # 5. 分页查询数据
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
        
        # 6. 组装返回数据
        items = []
        for row in rows:
            # row结构：(id, user_id, username, title, content, source, status, received_time, metadata)
            try:
                metadata = json.loads(row[8]) if row[8] else {}
            except Exception:
                metadata = {}
            sender_id = metadata.get("sender_id")
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
                    status=row[6],  # unread/read/retracted
                    sender_id=sender_id
                )
            )
        
        # 7. 计算总页数
        total_pages = (total + page_size - 1) // page_size
        return NotificationQueryResponse(
            items=items,
            page=page,
            page_size=page_size,
            total=total,
            total_pages=total_pages,
        )
    except HTTPException:
        raise
    except pymysql.MySQLError as e:
        raise HTTPException(status_code=500, detail=f"查询失败：{str(e)}")
    finally:
        if cursor:
            cursor.close()


@router.put(
    "/{notification_id}",
    summary="更新通知",
    description="更新已推送的通知内容，可修改标题和内容"
)
def update_notification(
    notification_id: int,
    payload: NotificationUpdate,
    db: pymysql.connections.Connection = Depends(get_db),
    # 可接入真实用户：current_user=Depends(get_current_user)
):
    cursor = None
    try:
        # 1. 核心参数校验
        if not (payload.title or payload.content):
            raise HTTPException(status_code=400, detail="至少需要提供标题或内容进行更新")
        
        cursor = db.cursor()
        now = datetime.now()
        now_str = now.strftime("%Y-%m-%d %H:%M:%S")
        
        # 2. 检查通知是否存在
        cursor.execute("SELECT id FROM user_messages WHERE id = %s", (notification_id,))
        if not cursor.fetchone():
            raise HTTPException(status_code=404, detail="通知不存在")
        
        # 3. 准备更新字段
        updates = []
        params = []
        
        if payload.title:
            updates.append("title = %s")
            params.append(payload.title)
        
        if payload.content:
            content_value = payload.content or ""
            # 处理长内容
            metadata = {}
            if len(content_value) > 60000:
                metadata["long_content"] = content_value[60000:]
                content_value = content_value[:60000]
            
            # 先获取现有metadata
            cursor.execute("SELECT metadata FROM user_messages WHERE id = %s", (notification_id,))
            existing_metadata = cursor.fetchone()[0]
            if existing_metadata:
                try:
                    existing_metadata = json.loads(existing_metadata)
                    # 合并现有metadata
                    existing_metadata.update(metadata)
                    metadata = existing_metadata
                except Exception:
                    pass
            
            updates.append("content = %s")
            params.append(content_value)
            updates.append("metadata = %s")
            params.append(json.dumps(metadata, ensure_ascii=False) if metadata else None)
        
        updates.append("updated_at = %s")
        params.append(now_str)
        params.append(notification_id)
        
        # 4. 执行更新
        update_sql = f"UPDATE user_messages SET {', '.join(updates)} WHERE id = %s"
        cursor.execute(update_sql, params)
        
        if cursor.rowcount == 0:
            raise HTTPException(status_code=404, detail="通知更新失败")
        
        db.commit()
        
        # 5. 返回更新结果
        return {
            "message": "通知更新成功",
            "notification_id": notification_id
        }
        
    except HTTPException:
        raise
    except pymysql.MySQLError as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"通知更新失败：{str(e)}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"更新处理失败：{str(e)}")
    finally:
        if cursor:
            cursor.close()


@router.put(
    "/{notification_id}/retract",
    summary="撤回通知",
    description="撤回已推送的通知，将状态标记为已撤回"
)
def retract_notification(
    notification_id: int,
    db: pymysql.connections.Connection = Depends(get_db),
    # 可接入真实用户：current_user=Depends(get_current_user)
):
    cursor = None
    try:
        cursor = db.cursor()
        now = datetime.now()
        now_str = now.strftime("%Y-%m-%d %H:%M:%S")
        
        # 1. 检查通知是否存在
        cursor.execute("SELECT id FROM user_messages WHERE id = %s", (notification_id,))
        if not cursor.fetchone():
            raise HTTPException(status_code=404, detail="通知不存在")
        
        # 2. 执行撤回操作（将状态改为已撤回）
        update_sql = """
        UPDATE user_messages 
        SET status = 'retracted', updated_at = %s 
        WHERE id = %s
        """
        cursor.execute(update_sql, (now_str, notification_id))
        
        if cursor.rowcount == 0:
            raise HTTPException(status_code=404, detail="通知撤回失败")
        
        db.commit()
        
        # 3. 返回撤回结果
        return {
            "message": "通知已成功撤回",
            "notification_id": notification_id
        }
        
    except HTTPException:
        raise
    except pymysql.MySQLError as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"通知撤回失败：{str(e)}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"撤回处理失败：{str(e)}")
    finally:
        if cursor:
            cursor.close()
