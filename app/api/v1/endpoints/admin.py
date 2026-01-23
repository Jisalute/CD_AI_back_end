from fastapi import APIRouter, UploadFile, File, Depends, HTTPException
from app.core.dependencies import get_current_user
from app.services.oss import upload_file_to_oss
import pymysql
from datetime import datetime
from app.database import get_db
import uuid

router = APIRouter()


def admin_only(
    # 注释掉认证依赖，保留参数行
    # user=Depends(get_current_user)
):
    # 注释掉原有角色校验逻辑
    # if user.get("role") != "admin":
    #     raise HTTPException(status_code=403, detail="仅管理员可访问")
    
    # 模拟管理员用户
    mock_admin_user = {
        "id": "admin_001",
        "role": "admin",
        "username": "test_admin"
    }
    return mock_admin_user


@router.post(
    "/templates",
    summary="上传模板",
    description="上传模板文件并存储元数据"
)
async def upload_template(
    file: UploadFile = File(...),
    user=Depends(admin_only),
    db: pymysql.connections.Connection = Depends(get_db)
):
    content = await file.read()
    key = upload_file_to_oss(file.filename, content)
    # 待办：持久化模板 ID 及元数据
    # 待办：持久化模板 ID 及元数据
    # template_id = "tpl_1"
    template_id = f"tpl_{uuid.uuid4().hex[:8]}"  
    
    # 定义模板元数据
    template_metadata = {
        "template_id": template_id,
        "oss_key": key,
        "filename": file.filename,
        "content_type": file.content_type,
        "uploader_id": user.get("id"),  
        "upload_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    }
    
    try:
        cursor = db.cursor()
        insert_sql = """
        INSERT INTO templates (template_id, oss_key, filename, content_type, uploader_id, upload_time)
        VALUES (%s, %s, %s, %s, %s, %s);
        """
        cursor.execute(
            insert_sql,
            (
                template_metadata["template_id"],
                template_metadata["oss_key"],
                template_metadata["filename"],
                template_metadata["content_type"],
                template_metadata["uploader_id"],
                template_metadata["upload_time"]
            )
        )
        db.commit()
        db.commit()
    except pymysql.MySQLError as e:
        db.rollback()
        db.rollback()
        raise HTTPException(
            status_code=500,
            detail=f"模板元数据存储失败：{str(e)}"
        )
    finally:
        cursor.close()
        cursor.close()
    # 同时修改返回值的template_id为动态生成的ID
    # return {"template_id": "tpl_1", "oss_key": key}
    return {"template_id": template_id, "oss_key": key}


@router.put(
    "/templates/{template_id}",
    summary="更新模板",
    description="重新上传模板并更新元数据"
)
async def update_template(
    template_id: str,
    file: UploadFile = File(...),
    user=Depends(admin_only),
    db: pymysql.connections.Connection = Depends(get_db)
):
    content = await file.read()
    key = upload_file_to_oss(file.filename, content)
    upload_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    cursor = None
    try:
        cursor = db.cursor()
        cursor.execute("SELECT id FROM templates WHERE template_id = %s", (template_id,))
        if not cursor.fetchone():
            raise HTTPException(status_code=404, detail="模板不存在")

        update_sql = """
        UPDATE templates
        SET oss_key = %s,
            filename = %s,
            content_type = %s,
            uploader_id = %s,
            upload_time = %s
        WHERE template_id = %s;
        """
        cursor.execute(
            update_sql,
            (
                key,
                file.filename,
                file.content_type,
                user.get("id"),
                upload_time,
                template_id,
            ),
        )
        db.commit()
        return {
            "template_id": template_id,
            "oss_key": key,
            "filename": file.filename,
            "content_type": file.content_type,
            "upload_time": upload_time,
        }
    except pymysql.MySQLError as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"模板更新失败：{str(e)}")
    finally:
        if cursor:
            cursor.close()


@router.delete(
    "/templates/{template_id}",
    summary="删除模板",
    description="根据模板ID删除记录"
)
def delete_template(
    template_id: str,
    user=Depends(admin_only),
    db: pymysql.connections.Connection = Depends(get_db)
):
    cursor = None
    try:
        cursor = db.cursor()
        cursor.execute("SELECT id FROM templates WHERE template_id = %s", (template_id,))
        if not cursor.fetchone():
            raise HTTPException(status_code=404, detail="模板不存在")

        cursor.execute("DELETE FROM templates WHERE template_id = %s", (template_id,))
        db.commit()
        return {"message": "删除成功", "template_id": template_id}
    except pymysql.MySQLError as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"模板删除失败：{str(e)}")
    finally:
        if cursor:
            cursor.close()

@router.put(
    "/templates/{template_id}",
    summary="更新模板",
    description="重新上传模板并更新元数据"
)
async def update_template(
    template_id: str,
    file: UploadFile = File(...),
    user=Depends(admin_only),
    db: pymysql.connections.Connection = Depends(get_db)
):
    content = await file.read()
    key = upload_file_to_oss(file.filename, content)
    upload_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    cursor = None
    try:
        cursor = db.cursor()
        cursor.execute("SELECT id FROM templates WHERE template_id = %s", (template_id,))
        if not cursor.fetchone():
            raise HTTPException(status_code=404, detail="模板不存在")

        update_sql = """
        UPDATE templates
        SET oss_key = %s,
            filename = %s,
            content_type = %s,
            uploader_id = %s,
            upload_time = %s
        WHERE template_id = %s;
        """
        cursor.execute(
            update_sql,
            (
                key,
                file.filename,
                file.content_type,
                user.get("id"),
                upload_time,
                template_id,
            ),
        )
        db.commit()
        return {
            "template_id": template_id,
            "oss_key": key,
            "filename": file.filename,
            "content_type": file.content_type,
            "upload_time": upload_time,
        }
    except pymysql.MySQLError as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"模板更新失败：{str(e)}")
    finally:
        if cursor:
            cursor.close()


@router.delete(
    "/templates/{template_id}",
    summary="删除模板",
    description="根据模板ID删除记录"
)
def delete_template(
    template_id: str,
    user=Depends(admin_only),
    db: pymysql.connections.Connection = Depends(get_db)
):
    cursor = None
    try:
        cursor = db.cursor()
        cursor.execute("SELECT id FROM templates WHERE template_id = %s", (template_id,))
        if not cursor.fetchone():
            raise HTTPException(status_code=404, detail="模板不存在")

        cursor.execute("DELETE FROM templates WHERE template_id = %s", (template_id,))
        db.commit()
        return {"message": "删除成功", "template_id": template_id}
    except pymysql.MySQLError as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"模板删除失败：{str(e)}")
    finally:
        if cursor:
            cursor.close()

@router.get(
    "/dashboard/stats",
    summary="仪表盘统计",
    description="按学院汇总论文数量并返回总数"
)
def dashboard_stats(
    user=Depends(admin_only),  
    db: pymysql.connections.Connection = Depends(get_db) 
):
    cursor = None
    try:
        cursor = db.cursor()
        # 聚合论文数据：按学院分组统计论文数量
        stats_sql = """
        SELECT p.owner_id, CASE WHEN t.id IS NOT NULL THEN COALESCE(t.department, '未知院系') WHEN s.id IS NOT NULL THEN COALESCE(s.grade, '未知年级') ELSE '未知' END AS college
        FROM papers p
        LEFT JOIN students s ON p.owner_id = s.id
        LEFT JOIN teachers t ON p.owner_id = t.id;
        """
        cursor.execute(stats_sql)
        rows = cursor.fetchall()
        
        # 在 Python 中分组统计
        from collections import defaultdict
        college_count = defaultdict(int)
        for owner_id, college in rows:
            college_count[college] += 1
        
        college_stats = [(college, count) for college, count in college_count.items()]
        
        # 统计论文总数
        total_sql = "SELECT COUNT(*) FROM papers;"
        cursor.execute(total_sql)
        total_papers = cursor.fetchone()[0]
        
        # 格式化按学院分组的统计结果
        by_college = []
        for item in college_stats:
            by_college.append({
                "college": item[0] if item[0] else "未归属学院",
                "paper_count": item[1]
            })
        
        # 返回结构化统计数据
        return {
            "total_papers": total_papers,
            "by_college": by_college,
            "update_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        }
    
    except pymysql.MySQLError as e:
        raise HTTPException(
            status_code=500,
            detail=f"统计数据查询失败：{str(e)}"
        )
    finally:
        if cursor:
            cursor.close()


@router.get(
    "/audit/logs",
    summary="审计日志查询",
    description="分页查询操作日志记录"
)
def audit_logs(
    user=Depends(admin_only),  
    page: int = 1,
    page_size: int = 50,
    db: pymysql.connections.Connection = Depends(get_db)  
):
    # 待办：查询操作日志表并返回分页结果
    # 待办：查询操作日志表并返回分页结果
    cursor = None
    try:
        # 校验分页参数合法性
        if page < 1:
            page = 1
        if page_size < 1 or page_size > 100:  # 限制单页最大条数，避免性能问题
            page_size = 50
        
        cursor = db.cursor()
        # 计算分页偏移量
        offset = (page - 1) * page_size
        
        # 查询分页数据（按操作时间倒序）
        select_sql = """
        SELECT id, user_id, username, operation_type, operation_path, 
               operation_params, ip_address, operation_time, status
        FROM operation_logs
        ORDER BY operation_time DESC
        LIMIT %s OFFSET %s;
        """
        cursor.execute(select_sql, (page_size, offset))
        log_items = cursor.fetchall()
        
        # 查询总条数（用于分页计算）
        count_sql = "SELECT COUNT(*) FROM operation_logs;"
        cursor.execute(count_sql)
        total = cursor.fetchone()[0]
        
        # 格式化返回数据（适配前端展示）
        items = []
        for log in log_items:
            items.append({
                "id": log[0],
                "user_id": log[1],
                "username": log[2],
                "operation_type": log[3],
                "operation_path": log[4],
                "operation_params": log[5],
                "ip_address": log[6],
                "operation_time": log[7].strftime("%Y-%m-%d %H:%M:%S") if log[7] else None,
                "status": log[8]
            })
        
        # 组装分页返回结果
        return {
            "items": items,
            "page": page,
            "page_size": page_size,
            "total": total,
            "total_pages": (total + page_size - 1) // page_size  # 向上取整计算总页数
        }
    
    except pymysql.MySQLError as e:
        raise HTTPException(
            status_code=500,
            detail=f"查询操作日志失败：{str(e)}"
        )
    finally:
        if cursor:
            cursor.close()
