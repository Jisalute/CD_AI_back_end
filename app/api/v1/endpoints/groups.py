from fastapi import APIRouter, UploadFile, File, Depends, HTTPException
from pydantic import BaseModel
from app.core.dependencies import get_current_user
from app.core.security import decode_access_token, create_access_token 
from app.models.document import DocumentRecord  
import io
import json
import pymysql
from datetime import datetime  
from loguru import logger  
from app.database import get_connection

router = APIRouter()


class GroupCreate(BaseModel):
    """创建群组请求体"""

    group_id: str
    group_name: str
    teacher_id: str | None = None
    description: str | None = None


class GroupMember(BaseModel):
    """群组成员增删请求体"""

    member_id: int
    member_type: str  # 学生 student / 教师 teacher / 管理员 admin
    role: str = "member"  # 成员 member / 管理员 admin


@router.post(
    "/import",
    summary="导入群组与师生关系",
    description="上传 TSV/CSV 文件批量导入群组及师生关系"
)
async def import_groups(
    file: UploadFile = File(...),
    #current_user=Depends(get_current_user),
    current_user = {"sub": 1, "username": "test_user", "roles": ["admin"]}
):
   # 这里只做接收并返回模拟结果；实际应解析 Excel 并写入 db
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

    # 权限校验
    required_roles = {"admin", "manager"}
    user_roles = set(current_user.get("roles", []))  
    if not required_roles & user_roles:
        logger.warning(f"用户{current_user['username']}无导入权限，当前角色: {user_roles}")
        raise HTTPException(status_code=403, detail="无批量导入师生群组权限，请联系管理员")

    # 基础文件格式校验
    supported_formats = ('.tsv', '.csv')
    if not file.filename.lower().endswith(supported_formats):
        logger.warning(f"用户{current_user['username']}上传非支持文件：{file.filename}，支持格式：{supported_formats}")
        raise HTTPException(
            status_code=400,
            detail=f"请上传文本表格文件（{', '.join(supported_formats)}）"
        )
    content = await file.read()
    if not content:
        logger.warning(f"用户{current_user['username']}上传空文件：{file.filename}")
        raise HTTPException(status_code=400, detail="上传文件为空，无有效数据")
    
    # 数据解析
    try:
        import_data = []
        required_cols = {"群组编号", "群组名称", "教师工号", "学生学号", "学生姓名"}
        delimiter = '\t' if file.filename.lower().endswith('.tsv') else ','  
        
        try:
            text_content = content.decode('utf-8', errors='ignore')
        except Exception as e:
            raise Exception(f"文件内容解码失败：{str(e)}")
        
        lines = [line.strip() for line in text_content.split('\n') if line.strip()]
        if not lines:
            raise Exception("文件无有效文本内容")
        
        headers = [h.strip() for h in lines[0].split(delimiter) if h.strip()]
        missing_cols = required_cols - set(headers)
        if missing_cols:
            logger.error(f"用户{current_user['username']}上传文件缺少必填列：{missing_cols}")
            raise HTTPException(status_code=400, detail=f"文件缺少必填列：{', '.join(missing_cols)}")
        
        for line_num, line in enumerate(lines[1:], start=2):
            row_values = [v.strip() for v in line.split(delimiter) if v.strip()]

            row_len = len(row_values)
            header_len = len(headers)
            if row_len != header_len:
                logger.warning(f"第{line_num}行列数异常（表头{header_len}列，当前行{row_len}列），跳过该行")
                continue
            row_dict = dict(zip(headers, row_values))

            if all([row_dict.get(col) for col in required_cols]):
                import_data.append({
                    "group_id": row_dict["群组编号"],
                    "group_name": row_dict["群组名称"],
                    "teacher_id": row_dict["教师工号"],
                    "student_id": row_dict["学生学号"],
                    "student_name": row_dict["学生姓名"]
                })
        
        # 数据清洗结果校验
        if not import_data:
            logger.warning(f"用户{current_user['username']}上传文件无有效师生关系数据")
            raise HTTPException(status_code=400, detail="文件中无有效师生关系数据")
        
        # 数据存储
        imported_count = len(import_data)
        group_ids = set(item["group_id"] for item in import_data)

        conn = get_connection()
        cursor = conn.cursor()
        try:
            # 创建文件存储表
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS uploaded_files (
                id INT PRIMARY KEY AUTO_INCREMENT,
                filename VARCHAR(255) NOT NULL,
                content_type VARCHAR(100) NOT NULL,
                content LONGBLOB NOT NULL,  # 存文件二进制内容
                operated_by VARCHAR(50) NOT NULL,
                operated_time DATETIME NOT NULL,
                created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
            )
            """)
            # 插入上传的文件
            cursor.execute("""
            INSERT INTO uploaded_files (filename, content_type, content, operated_by, operated_time)
            VALUES (%s, %s, %s, %s, %s)
            """, (file.filename, file.content_type, content, current_user["username"], datetime.now()))
            conn.commit()
            logger.info(f"文件{file.filename}已存入数据库")
        finally:
            cursor.close()
            conn.close()
        
        # 实例化 DocumentRecord
        document_record = DocumentRecord(
            id=hash(f"{file.filename}_{datetime.now()}_{current_user['username']}"),
            filename=file.filename,
            content=content,
            content_type=file.content_type,
            created_at=datetime.now()
        )
        
        # 日志记录文件存储信息
        logger.info(f"用户{current_user['username']}上传文件已生成记录：{document_record.filename}（ID：{document_record.id}）")
        
        # 师生关系数据日志记录
        for item in import_data:
            logger.info(f"待绑定师生关系：教师{item['teacher_id']}-学生{item['student_id']}（群组：{item['group_id']}）")
        
        # 6. 审计日志：操作留痕
        log_content = f"用户{current_user['username']}批量导入师生关系：成功识别{imported_count}条有效数据，涉及群组{','.join(group_ids)}，上传文件已存档"
        logger.success(log_content)
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"用户{current_user['username']}导入失败：{str(e)}")
        raise HTTPException(status_code=500, detail=f"数据导入失败：{str(e)}")
    
    # 返回导入结果
    return {
        "imported": imported_count,
        "message": f"成功识别{imported_count}条有效师生关系，上传文件已存档",
        "operated_by": current_user["username"],
        "operated_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "uploaded_file": file.filename,
        "file_format": file.filename.lower().split('.')[-1],
    }


@router.post(
    "/create",
    summary="创建群组",
    description="新增单个群组记录"
)
async def create_group(payload: GroupCreate, current_user: dict = {"roles": ["admin"], "username": "test_user"}):
    required_roles = {"admin", "manager"}
    if not required_roles & set(current_user.get("roles", [])):
        raise HTTPException(status_code=403, detail="无创建群组权限，请联系管理员")

    conn = get_connection()
    try:
        cursor = conn.cursor()
        insert_sql = (
            "INSERT INTO groups (group_id, group_name, teacher_id, description) "
            "VALUES (%s, %s, %s, %s)"
        )
        cursor.execute(
            insert_sql,
            (
                payload.group_id.strip(),
                payload.group_name.strip(),
                payload.teacher_id.strip() if payload.teacher_id else None,
                payload.description.strip() if payload.description else None,
            ),
        )
        conn.commit()
        return {
            "group_id": payload.group_id,
            "group_name": payload.group_name,
            "teacher_id": payload.teacher_id,
            "description": payload.description,
            "message": "群组创建成功",
        }
    except pymysql.err.IntegrityError:
        conn.rollback()
        raise HTTPException(status_code=400, detail="群组编号已存在")
    except pymysql.MySQLError as e:
        conn.rollback()
        raise HTTPException(status_code=500, detail=f"数据库错误：{str(e)}")
    finally:
        try:
            cursor.close()
        except Exception:
            pass
        conn.close()


@router.delete(
    "/{group_id}",
    summary="删除群组",
    description="根据群组编号删除群组"
)
async def delete_group(group_id: str, current_user: dict = {"roles": ["admin"], "username": "test_user"}):
    required_roles = {"admin", "manager"}
    if not required_roles & set(current_user.get("roles", [])):
        raise HTTPException(status_code=403, detail="无删除群组权限，请联系管理员")

    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT id FROM groups WHERE group_id = %s", (group_id,))
        row = cursor.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="群组不存在")

        cursor.execute("DELETE FROM groups WHERE group_id = %s", (group_id,))
        conn.commit()
        return {"group_id": group_id, "message": "群组已删除"}
    except HTTPException:
        raise
    except pymysql.MySQLError as e:
        conn.rollback()
        raise HTTPException(status_code=500, detail=f"数据库错误：{str(e)}")
    finally:
        try:
            cursor.close()
        except Exception:
            pass
        conn.close()


@router.post(
    "/{group_id}/members",
    summary="添加群组成员",
    description="为指定群组添加成员（学生/教师/管理员）"
)
async def add_group_member(group_id: str, payload: GroupMember, current_user: dict = {"roles": ["admin"], "username": "test_user"}):
    required_roles = {"admin", "manager"}
    if not required_roles & set(current_user.get("roles", [])):
        raise HTTPException(status_code=403, detail="无添加成员权限，请联系管理员")

    conn = get_connection()
    try:
        cursor = conn.cursor()

        cursor.execute("SELECT 1 FROM groups WHERE group_id = %s", (group_id,))
        if not cursor.fetchone():
            raise HTTPException(status_code=404, detail="群组不存在")

        cursor.execute(
            """
            INSERT INTO group_members (group_id, member_id, member_type, role)
            VALUES (%s, %s, %s, %s)
            ON DUPLICATE KEY UPDATE is_active = 1, role = VALUES(role)
            """,
            (group_id, payload.member_id, payload.member_type, payload.role),
        )
        conn.commit()
        return {
            "group_id": group_id,
            "member_id": payload.member_id,
            "member_type": payload.member_type,
            "role": payload.role,
            "message": "成员已添加/更新",
        }
    except HTTPException:
        raise
    except pymysql.MySQLError as e:
        conn.rollback()
        raise HTTPException(status_code=500, detail=f"数据库错误：{str(e)}")
    finally:
        try:
            cursor.close()
        except Exception:
            pass
        conn.close()


@router.delete(
    "/{group_id}/members",
    summary="删除群组成员",
    description="从指定群组移除成员（软删除，设置 is_active=0）"
)
async def remove_group_member(group_id: str, payload: GroupMember, current_user: dict = {"roles": ["admin"], "username": "test_user"}):
    required_roles = {"admin", "manager"}
    if not required_roles & set(current_user.get("roles", [])):
        raise HTTPException(status_code=403, detail="无删除成员权限，请联系管理员")

    conn = get_connection()
    try:
        cursor = conn.cursor()

        cursor.execute("SELECT 1 FROM groups WHERE group_id = %s", (group_id,))
        if not cursor.fetchone():
            raise HTTPException(status_code=404, detail="群组不存在")

        cursor.execute(
            """
            SELECT 1 FROM group_members 
            WHERE group_id = %s AND member_id = %s AND member_type = %s
            """,
            (group_id, payload.member_id, payload.member_type),
        )
        if not cursor.fetchone():
            raise HTTPException(status_code=404, detail="成员不在该群组")

        cursor.execute(
            """
            UPDATE group_members 
            SET is_active = 0 
            WHERE group_id = %s AND member_id = %s AND member_type = %s
            """,
            (group_id, payload.member_id, payload.member_type),
        )
        conn.commit()
        return {
            "group_id": group_id,
            "member_id": payload.member_id,
            "member_type": payload.member_type,
            "message": "成员已移除",
        }
    except HTTPException:
        raise
    except pymysql.MySQLError as e:
        conn.rollback()
        raise HTTPException(status_code=500, detail=f"数据库错误：{str(e)}")
    finally:
        try:
            cursor.close()
        except Exception:
            pass
        conn.close()