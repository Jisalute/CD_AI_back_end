from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Query
import csv
import io
import pymysql
from typing import List, Optional 
from pydantic import BaseModel
from app.schemas.user import (
    StudentCreate,
    TeacherCreate,
    AdminCreate,
    UserUpdate,
    UserOut,
    UserBindPhone,
    UserBindEmail,
)
from app.database import get_db
from app.core.security import get_password_hash
from loguru import logger

class UserBindGroup(BaseModel):
    group_id: int
    is_bind: bool = True  

class UserBindSchool(BaseModel):
    school_id: int
    school_name: Optional[str] = None 

class UserBindDepartment(BaseModel):
    department_id: int
    department_name: Optional[str] = None 

router = APIRouter()
SUPPORTED_IMPORT_EXTS = (".csv", ".tsv")

USER_TABLES = {
    "admin": {"table": "admins", "id_col": "admin_id", "role_col": "role"},
    "student": {"table": "students", "id_col": "student_id", "role": "student"},
    "teacher": {"table": "teachers", "id_col": "teacher_id", "role": "teacher"},
}


def _normalize_user_type(user_type: str | None) -> str:
    value = (user_type or "admin").strip().lower()
    if value not in USER_TABLES:
        raise HTTPException(status_code=400, detail="user_type 必须为 student/teacher/admin")
    return value


def _fetch_user(cursor: pymysql.cursors.Cursor, user_id: int, user_type: str) -> dict | None:
    user_type = _normalize_user_type(user_type)
    info = USER_TABLES[user_type]
    table = info["table"]
    id_col = info["id_col"]
    if user_type == "admin":
        cursor.execute(
            f"""
            SELECT id, {id_col} as username, name as full_name, phone, email, role, created_at, updated_at
            FROM {table} WHERE id = %s
            """,
            (user_id,),
        )
    else:
        cursor.execute(
            f"""
            SELECT id, {id_col} as username, name as full_name, phone, email, created_at, updated_at
            FROM {table} WHERE id = %s
            """,
            (user_id,),
        )
    row = cursor.fetchone()
    if not row:
        return None
    if isinstance(row, dict):
        data = {
            "id": row["id"],
            "username": row["username"],
            "phone": row.get("phone"),
            "email": row.get("email"),
            "full_name": row.get("full_name"),
            "role": row.get("role") if user_type == "admin" else info["role"],
            "created_at": row["created_at"] if isinstance(row["created_at"], str) else row["created_at"].strftime("%Y-%m-%d %H:%M:%S"),
            "updated_at": row["updated_at"] if isinstance(row["updated_at"], str) else row["updated_at"].strftime("%Y-%m-%d %H:%M:%S"),
        }
        return data
    # fallback for tuple cursor
    if user_type == "admin":
        return {
            "id": row[0],
            "username": row[1],
            "phone": row[3],
            "email": row[4],
            "full_name": row[2],
            "role": row[5],
            "created_at": row[6] if isinstance(row[6], str) else row[6].strftime("%Y-%m-%d %H:%M:%S"),
            "updated_at": row[7] if isinstance(row[7], str) else row[7].strftime("%Y-%m-%d %H:%M:%S"),
        }
    return {
        "id": row[0],
        "username": row[1],
        "phone": row[3],
        "email": row[4],
        "full_name": row[2],
        "role": info["role"],
        "created_at": row[5] if isinstance(row[5], str) else row[5].strftime("%Y-%m-%d %H:%M:%S"),
        "updated_at": row[6] if isinstance(row[6], str) else row[6].strftime("%Y-%m-%d %H:%M:%S"),
    }


@router.post(
    "/students",
    response_model=UserOut,
    summary="创建学生",
    description="创建学生并返回用户信息"
)
def create_student(payload: StudentCreate, db: pymysql.connections.Connection = Depends(get_db)):
    cursor = None
    try:
        cursor = db.cursor(pymysql.cursors.DictCursor)
        username = payload.username.strip()
        if not username:
            raise HTTPException(status_code=400, detail="username 不能为空")
        full_name = payload.full_name or username
        raw_password = payload.password or "123456"
        password_hash = get_password_hash(raw_password)
        cursor.execute(
            """
            INSERT INTO students (student_id, name, phone, email, password)
            VALUES (%s, %s, %s, %s, %s)
            """,
            (username, full_name, payload.phone, payload.email, password_hash),
        )
        db.commit()
        user_id = cursor.lastrowid
        cursor.execute(
            """
            SELECT id, student_id as username, name as full_name, phone, email,
                   DATE_FORMAT(created_at, '%%Y-%%m-%%d %%H:%%i:%%s') as created_at,
                   DATE_FORMAT(updated_at, '%%Y-%%m-%%d %%H:%%i:%%s') as updated_at
            FROM students WHERE id = %s
            """,
            (user_id,),
        )
        row = cursor.fetchone()
        if not row:
            raise HTTPException(status_code=500, detail="用户创建成功但查询失败")
        row["role"] = "student" if isinstance(row, dict) else "student"
        return UserOut(**row)
    except pymysql.err.IntegrityError:
        db.rollback()
        raise HTTPException(status_code=400, detail="用户名已存在")
    except pymysql.MySQLError as e:
        db.rollback()
        logger.error(f"用户创建数据库错误: {str(e)}")
        raise HTTPException(status_code=500, detail="用户创建失败")
    finally:
        if cursor:
            cursor.close()


@router.post(
    "/teachers",
    response_model=UserOut,
    summary="创建教师",
    description="创建教师并返回用户信息"
)
def create_teacher(payload: TeacherCreate, db: pymysql.connections.Connection = Depends(get_db)):
    cursor = None
    try:
        cursor = db.cursor(pymysql.cursors.DictCursor)
        username = payload.username.strip()
        if not username:
            raise HTTPException(status_code=400, detail="username 不能为空")

        full_name = payload.full_name or username
        raw_password = payload.password or "123456"
        password_hash = get_password_hash(raw_password)

        cursor.execute(
            """
            INSERT INTO teachers (teacher_id, name, phone, email, password)
            VALUES (%s, %s, %s, %s, %s)
            """,
            (username, full_name, payload.phone, payload.email, password_hash),
        )
        db.commit()
        user_id = cursor.lastrowid
        cursor.execute(
            """
            SELECT id, teacher_id as username, name as full_name, phone, email,
                   DATE_FORMAT(created_at, '%%Y-%%m-%%d %%H:%%i:%%s') as created_at,
                   DATE_FORMAT(updated_at, '%%Y-%%m-%%d %%H:%%i:%%s') as updated_at
            FROM teachers WHERE id = %s
            """,
            (user_id,),
        )
        row = cursor.fetchone()
        if not row:
            raise HTTPException(status_code=500, detail="用户创建成功但查询失败")
        row["role"] = "teacher" if isinstance(row, dict) else "teacher"
        return UserOut(**row)
    except pymysql.err.IntegrityError:
        db.rollback()
        raise HTTPException(status_code=400, detail="用户名已存在")
    except pymysql.MySQLError as e:
        db.rollback()
        logger.error(f"用户创建数据库错误: {str(e)}")
        raise HTTPException(status_code=500, detail="用户创建失败")
    finally:
        if cursor:
            cursor.close()


@router.post(
    "/admins",
    response_model=UserOut,
    summary="创建管理员",
    description="创建管理员并返回用户信息"
)
def create_admin(payload: AdminCreate, db: pymysql.connections.Connection = Depends(get_db)):
    cursor = None
    try:
        cursor = db.cursor(pymysql.cursors.DictCursor)
        username = payload.username.strip()
        if not username:
            raise HTTPException(status_code=400, detail="username 不能为空")

        full_name = payload.full_name or username
        raw_password = payload.password or "123456"
        password_hash = get_password_hash(raw_password)

        cursor.execute(
            """
            INSERT INTO admins (admin_id, name, phone, email, role, password)
            VALUES (%s, %s, %s, %s, %s, %s)
            """,
            (
                username,
                full_name,
                payload.phone,
                payload.email,
                payload.role or "admin",
                password_hash,
            ),
        )
        db.commit()
        user_id = cursor.lastrowid
        cursor.execute(
            """
            SELECT id, admin_id as username, name as full_name, phone, email, role,
                   DATE_FORMAT(created_at, '%%Y-%%m-%%d %%H:%%i:%%s') as created_at,
                   DATE_FORMAT(updated_at, '%%Y-%%m-%%d %%H:%%i:%%s') as updated_at
            FROM admins WHERE id = %s
            """,
            (user_id,),
        )
        row = cursor.fetchone()
        if not row:
            raise HTTPException(status_code=500, detail="用户创建成功但查询失败")
        return UserOut(**row)
    except pymysql.err.IntegrityError:
        db.rollback()
        raise HTTPException(status_code=400, detail="用户名已存在")
    except pymysql.MySQLError as e:
        db.rollback()
        logger.error(f"用户创建数据库错误: {str(e)}")
        raise HTTPException(status_code=500, detail="用户创建失败")
    finally:
        if cursor:
            cursor.close()


@router.put(
    "/{user_id}",
    response_model=UserOut,
    summary="更新用户信息",
    description="按需更新邮箱、姓名、角色或密码"
)
def update_user(user_id: int, payload: UserUpdate, db: pymysql.connections.Connection = Depends(get_db)):
    cursor = None
    try:
        cursor = db.cursor(pymysql.cursors.DictCursor)
        user_type = _normalize_user_type(payload.user_type)
        info = USER_TABLES[user_type]
        table = info["table"]
        cursor.execute(f"SELECT id FROM {table} WHERE id = %s", (user_id,))
        if not cursor.fetchone():
            raise HTTPException(status_code=404, detail="用户不存在")

        fields = []
        params: List[str] = []
        if payload.phone is not None:
            fields.append("phone = %s")
            params.append(payload.phone)
        if payload.email is not None:
            fields.append("email = %s")
            params.append(payload.email)
        if payload.full_name is not None:
            fields.append("name = %s")
            params.append(payload.full_name)
        if payload.role is not None and user_type == "admin":
            fields.append("role = %s")
            params.append(payload.role)
        if payload.password is not None:
            fields.append("password = %s")
            params.append(get_password_hash(payload.password))

        if not fields:
            existing = _fetch_user(cursor, user_id, user_type)
            if not existing:
                raise HTTPException(status_code=404, detail="用户不存在")
            return UserOut(**existing)

        fields.append("updated_at = NOW()")
        sql = f"UPDATE {table} SET {', '.join(fields)} WHERE id = %s"
        params.append(user_id)
        cursor.execute(sql, tuple(params))
        db.commit()
        updated = _fetch_user(cursor, user_id, user_type)
        if not updated:
            raise HTTPException(status_code=500, detail="用户更新后查询失败")
        return UserOut(**updated)
    except HTTPException:
        raise
    except pymysql.MySQLError as e:
        db.rollback()
        logger.error(f"用户更新数据库错误: {str(e)}")
        raise HTTPException(status_code=500, detail="用户更新失败")
    finally:
        if cursor:
            cursor.close()


@router.delete(
    "/{user_id}",
    summary="删除用户",
    description="根据用户ID删除用户"
)
def delete_user(
    user_id: int,
    db: pymysql.connections.Connection = Depends(get_db),
    user_type: str = Query("admin"),
):
    cursor = None
    try:
        cursor = db.cursor()
        user_type = _normalize_user_type(user_type)
        info = USER_TABLES[user_type]
        table = info["table"]
        cursor.execute(f"SELECT 1 FROM {table} WHERE id = %s", (user_id,))
        if not cursor.fetchone():
            raise HTTPException(status_code=404, detail="用户不存在")
        cursor.execute(f"DELETE FROM {table} WHERE id = %s", (user_id,))
        db.commit()
        return {"message": "删除成功", "user_id": user_id}
    except HTTPException:
        raise
    except pymysql.MySQLError as e:
        db.rollback()
        logger.error(f"用户删除数据库错误: {str(e)}")
        raise HTTPException(status_code=500, detail="用户删除失败")
    finally:
        if cursor:
            cursor.close()


@router.post(
    "/import",
    summary="一键导入用户",
    description="上传 CSV/TSV 文件批量导入用户（列：username,user_type,email,full_name,role,password 可选）"
)
async def import_users(file: UploadFile = File(...), db: pymysql.connections.Connection = Depends(get_db)):
    filename = file.filename or ""
    lower_name = filename.lower()
    if not lower_name.endswith(SUPPORTED_IMPORT_EXTS):
        raise HTTPException(status_code=400, detail="仅支持 .csv 或 .tsv 文件")

    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="上传文件为空")

    delimiter = "\t" if lower_name.endswith(".tsv") else ","
    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError:
        try:
            text = content.decode("gbk")
        except UnicodeDecodeError:
            raise HTTPException(status_code=400, detail="文件编码仅支持 UTF-8 或 GBK")

    reader = csv.DictReader(io.StringIO(text), delimiter=delimiter)
    required_col = "username"
    if required_col not in reader.fieldnames:
        raise HTTPException(status_code=400, detail="文件缺少 username 列")

    created, updated = 0, 0
    default_role = "admin"
    default_password = "123456"
    cursor = None
    created_items = []
    updated_items = []
    try:
        cursor = db.cursor()
        for row in reader:
            username = (row.get("username") or "").strip()
            if not username:
                continue
            user_type = _normalize_user_type(row.get("user_type") or "admin")
            info = USER_TABLES[user_type]
            table = info["table"]
            phone = (row.get("phone") or None) and row.get("phone").strip()
            email = (row.get("email") or None) and row.get("email").strip()
            full_name = (row.get("full_name") or None) and row.get("full_name").strip()
            role = (row.get("role") or default_role).strip() or default_role
            password = (row.get("password") or default_password).strip() or default_password
            password_hash = get_password_hash(password)
            if not full_name:
                full_name = username  # 默认使用username作为full_name
            if user_type == "admin":
                cursor.execute(
                    """
                    INSERT INTO admins (admin_id, name, phone, email, role, password)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    ON DUPLICATE KEY UPDATE
                        name = VALUES(name),
                        phone = VALUES(phone),
                        email = VALUES(email),
                        role = VALUES(role),
                        password = VALUES(password),
                        updated_at = NOW()
                    """,
                    (username, full_name, phone, email, role, password_hash),
                )
            elif user_type == "student":
                cursor.execute(
                    """
                    INSERT INTO students (student_id, name, phone, email, password)
                    VALUES (%s, %s, %s, %s, %s)
                    ON DUPLICATE KEY UPDATE
                        name = VALUES(name),
                        phone = VALUES(phone),
                        email = VALUES(email),
                        password = VALUES(password),
                        updated_at = NOW()
                    """,
                    (username, full_name, phone, email, password_hash),
                )
            else:
                cursor.execute(
                    """
                    INSERT INTO teachers (teacher_id, name, phone, email, password)
                    VALUES (%s, %s, %s, %s, %s)
                    ON DUPLICATE KEY UPDATE
                        name = VALUES(name),
                        phone = VALUES(phone),
                        email = VALUES(email),
                        password = VALUES(password),
                        updated_at = NOW()
                    """,
                    (username, full_name, phone, email, password_hash),
                )
            if cursor.rowcount == 1:
                created += 1
                # fetch id
                cursor.execute(f"SELECT id FROM {table} WHERE {info['id_col']} = %s", (username,))
                rid = cursor.fetchone()
                if rid:
                    if isinstance(rid, dict):
                        rec_id = rid.get('id')
                    else:
                        rec_id = rid[0]
                else:
                    rec_id = None
                created_items.append({"user_type": user_type, "username": username, "id": rec_id})
            else:
                updated += 1
                cursor.execute(f"SELECT id FROM {table} WHERE {info['id_col']} = %s", (username,))
                rid = cursor.fetchone()
                if rid:
                    if isinstance(rid, dict):
                        rec_id = rid.get('id')
                    else:
                        rec_id = rid[0]
                else:
                    rec_id = None
                updated_items.append({"user_type": user_type, "username": username, "id": rec_id})
        db.commit()
        return {
            "message": "导入完成",
            "created": created,
            "updated": updated,
            "created_items": created_items,
            "updated_items": updated_items,
        }
    except pymysql.MySQLError as e:
        db.rollback()
        logger.error(f"用户导入数据库错误: {str(e)}")
        raise HTTPException(status_code=500, detail="用户导入失败")
    finally:
        if cursor:
            cursor.close()


@router.put(
    "/{user_id}/bind-phone",
    response_model=UserOut,
    summary="绑定手机号",
    description="为指定用户绑定/更新手机号"
)
def bind_phone(
    user_id: int,
    payload: UserBindPhone,
    db: pymysql.connections.Connection = Depends(get_db),
    user_type: str = Query("admin"),
):
    cursor = None
    try:
        cursor = db.cursor(pymysql.cursors.DictCursor)
        user_type = _normalize_user_type(user_type)
        table = USER_TABLES[user_type]["table"]
        cursor.execute(f"SELECT id FROM {table} WHERE id = %s", (user_id,))
        if not cursor.fetchone():
            raise HTTPException(status_code=404, detail="用户不存在")

        cursor.execute(
            f"UPDATE {table} SET phone = %s, updated_at = NOW() WHERE id = %s",
            (payload.phone.strip(), user_id),
        )
        db.commit()
        updated = _fetch_user(cursor, user_id, user_type)
        if not updated:
            raise HTTPException(status_code=500, detail="手机号绑定后查询失败")
        return UserOut(**updated)
    except HTTPException:
        raise
    except pymysql.MySQLError as e:
        db.rollback()
        logger.error(f"绑定手机号数据库错误: {str(e)}")
        raise HTTPException(status_code=500, detail="绑定手机号失败")
    finally:
        if cursor:
            cursor.close()


@router.put(
    "/{user_id}/bind-email",
    response_model=UserOut,
    summary="绑定邮箱",
    description="为指定用户绑定/更新邮箱"
)
def bind_email(
    user_id: int,
    payload: UserBindEmail,
    db: pymysql.connections.Connection = Depends(get_db),
    user_type: str = Query("admin"),
):
    cursor = None
    try:
        cursor = db.cursor(pymysql.cursors.DictCursor)
        user_type = _normalize_user_type(user_type)
        table = USER_TABLES[user_type]["table"]
        cursor.execute(f"SELECT id FROM {table} WHERE id = %s", (user_id,))
        if not cursor.fetchone():
            raise HTTPException(status_code=404, detail="用户不存在")

        cursor.execute(
            f"UPDATE {table} SET email = %s, updated_at = NOW() WHERE id = %s",
            (payload.email, user_id),
        )
        db.commit()
        updated = _fetch_user(cursor, user_id, user_type)
        if not updated:
            raise HTTPException(status_code=500, detail="邮箱绑定后查询失败")
        return UserOut(**updated)
    except HTTPException:
        raise
    except pymysql.MySQLError as e:
        db.rollback()
        logger.error(f"绑定邮箱数据库错误: {str(e)}")
        raise HTTPException(status_code=500, detail="绑定邮箱失败")
    finally:
        if cursor:
            cursor.close()


@router.post(
    "/{user_id}/bind-group",
    summary="绑定群组",
    description="将用户绑定到指定群组（写入 group_members）"
)
def bind_group(user_id: int, payload: UserBindGroup, db: pymysql.connections.Connection = Depends(get_db)):
    if payload.role not in ["member", "admin"]:
        raise HTTPException(status_code=400, detail="角色必须是member或admin")

    cursor = None
    try:
        cursor = db.cursor()
        cursor.execute("SELECT 1 FROM admins WHERE id = %s", (user_id,))
        if not cursor.fetchone():
            raise HTTPException(status_code=404, detail="用户不存在")

        cursor.execute("SELECT 1 FROM `groups` WHERE `group_id` = %s", (payload.group_id,))
        if not cursor.fetchone():
            raise HTTPException(status_code=404, detail="群组不存在")

        cursor.execute(
            """
            INSERT INTO `group_members` (`group_id`, `member_id`, `member_type`, `role`)
            VALUES (%s, %s, 'admin', %s)
            ON DUPLICATE KEY UPDATE `is_active` = 1, `role` = VALUES(`role`)
            """,
            (payload.group_id, user_id, payload.role),
        )
        db.commit()
        return {
            "user_id": user_id,
            "group_id": payload.group_id,
            "member_type": "admin",
            "role": payload.role,
            "message": "绑定成功",
        }
    except HTTPException:
        raise
    except pymysql.MySQLError as e:
        db.rollback()
        logger.error(f"绑定群组数据库错误: {str(e)}")
        raise HTTPException(status_code=500, detail="绑定群组失败")
    finally:
        if cursor:
            cursor.close()


@router.put(
    "/{user_id}/bind-school",
    response_model=UserOut,
    summary="绑定用户学校",
    description="为指定用户绑定/更新所属学校信息"
)
def bind_school(
    user_id: int,
    payload: UserBindSchool,
    db: pymysql.connections.Connection = Depends(get_db),
    user_type: str = Query("admin"),
):
    cursor = None
    try:
        cursor = db.cursor(pymysql.cursors.DictCursor)
        user_type = _normalize_user_type(user_type)
        table = USER_TABLES[user_type]["table"]
        cursor.execute(f"SELECT id FROM {table} WHERE id = %s", (user_id,))
        if not cursor.fetchone():
            raise HTTPException(status_code=404, detail="用户不存在")
        cursor.execute("SELECT 1 FROM schools WHERE school_id = %s", (payload.school_id,))
        if not cursor.fetchone():
            raise HTTPException(status_code=404, detail="学校不存在")
        update_fields = ["school_id = %s", "updated_at = NOW()"]
        update_params = [payload.school_id]
        if payload.school_name:
            update_fields.append("school_name = %s")
            update_params.append(payload.school_name.strip())
        
        update_params.append(user_id)
        cursor.execute(
            f"UPDATE {table} SET {', '.join(update_fields)} WHERE id = %s",
            tuple(update_params)
        )
        db.commit()
        updated = _fetch_user(cursor, user_id, user_type)
        if not updated:
            raise HTTPException(status_code=500, detail="绑定学校后查询用户信息失败")
        return UserOut(**updated)
    
    except HTTPException:
        raise
    except pymysql.MySQLError as e:
        db.rollback()
        logger.error(f"绑定学校数据库错误: {str(e)}")
        raise HTTPException(status_code=500, detail="绑定学校失败")
    finally:
        if cursor:
            cursor.close()

@router.put(
    "/{user_id}/bind-department",
    response_model=UserOut,
    summary="绑定用户院系",
    description="为指定用户绑定/更新所属院系信息"
)
def bind_department(
    user_id: int,
    payload: UserBindDepartment,
    db: pymysql.connections.Connection = Depends(get_db),
    user_type: str = Query("admin"),
):
    cursor = None
    try:
        cursor = db.cursor(pymysql.cursors.DictCursor)
        user_type = _normalize_user_type(user_type)
        table = USER_TABLES[user_type]["table"]
        cursor.execute(f"SELECT id FROM {table} WHERE id = %s", (user_id,))
        if not cursor.fetchone():
            raise HTTPException(status_code=404, detail="用户不存在")
        cursor.execute("SELECT 1 FROM departments WHERE department_id = %s", (payload.department_id,))
        if not cursor.fetchone():
            raise HTTPException(status_code=404, detail="院系不存在")
        update_fields = ["department_id = %s", "updated_at = NOW()"]
        update_params = [payload.department_id]
        if payload.department_name:
            update_fields.append("department_name = %s")
            update_params.append(payload.department_name.strip())
        
        update_params.append(user_id)
        cursor.execute(
            f"UPDATE {table} SET {', '.join(update_fields)} WHERE id = %s",
            tuple(update_params)
        )
        db.commit()
        updated = _fetch_user(cursor, user_id, user_type)
        if not updated:
            raise HTTPException(status_code=500, detail="绑定院系后查询用户信息失败")
        return UserOut(**updated)
    
    except HTTPException:
        raise
    except pymysql.MySQLError as e:
        db.rollback()
        logger.error(f"绑定院系数据库错误: {str(e)}")
        raise HTTPException(status_code=500, detail="绑定院系失败")
    finally:
        if cursor:
            cursor.close()
