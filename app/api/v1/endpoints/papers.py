from fastapi import APIRouter, UploadFile, File, HTTPException, Depends, BackgroundTasks, Query
from typing import List, Optional
import os
from app.core.dependencies import get_current_user
from app.schemas.document import (
    PaperCreate,
    PaperOut,
    PaperStatusCreate,
    PaperStatusOut,
    PaperStatusUpdate,
    VersionOut,
)
from app.services.oss import upload_file_to_oss, upload_paper_to_storage
from datetime import datetime
from app.database import get_db
import pymysql
import json

router = APIRouter()


def _parse_current_user(current_user: Optional[str]) -> dict:
    try:
        if not current_user:
            return {"sub": 0, "username": "", "roles": []}
        import urllib.parse
        raw = urllib.parse.unquote(current_user)
        if not raw.strip():
            return {"sub": 0, "username": "", "roles": []}
        if raw.isdigit():
            return {"sub": int(raw), "username": f"user{raw}", "roles": ["student"]}
        data = json.loads(raw)
        if isinstance(data, dict):
            return data
    except Exception:
        pass
    return {"sub": 0, "username": "", "roles": []}

def _parse_version(version_str: str) -> tuple:
    try:
        version_clean = version_str.strip().lower().lstrip('v')
        major_str, minor_str = version_clean.split('.')
        major = int(major_str)
        minor = int(minor_str)
        if major < 0 or minor < 0:
            raise ValueError("版本号数字不能为负数")
        return (major, minor)
    except ValueError as e:
        raise HTTPException(
            status_code=400,
            detail=f"版本号格式错误（示例：v2.0），要求为 v+数字.数字 格式，且数字为正整数：{str(e)}"
        )
    except Exception:
        raise HTTPException(
            status_code=400,
            detail="版本号格式错误，必须符合 v+数字.数字 格式（如 v1.0、v2.1）"
        )


@router.post(
    "/upload",
    response_model=PaperOut,
    summary="上传论文",
    description="上传 docx 生成论文记录与首个版本，并记录提交者信息"
)
async def upload_paper(
    file: UploadFile = File(...),
    owner_id: int = Query(..., description="论文归属者ID，必须传入且为有效整数"),
    teacher_id: int = Query(..., description="关联的老师ID，必须传入且为有效正整数"),
    db: pymysql.connections.Connection = Depends(get_db),
    current_user: Optional[str] = Query(None, description="提交者信息(JSON字符串，包含 sub/username/roles)"),
):
    current_user = _parse_current_user(current_user)
    submitter_id = current_user.get("sub", 0)  
    if not isinstance(owner_id, int) or owner_id <= 0:
        raise HTTPException(status_code=400, detail="owner_id必须是正整数")
    if not isinstance(teacher_id, int) or teacher_id <= 0:
        raise HTTPException(status_code=400, detail="teacher_id必须是正整数")
    if owner_id != submitter_id:
        raise HTTPException(
            status_code=403,
            detail="无权限上传：论文归属者ID必须与当前登录用户ID一致"
        )
    # 验证文件扩展名
    if not file.filename.lower().endswith(".docx"):
        raise HTTPException(status_code=400, detail="仅支持 .docx 格式")
    contents = await file.read()
    size = len(contents)
    if size > 100 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="文件大小超过 100MB")

    # 本地存储论文到 doc/essay（返回路径作为 oss_key）
    oss_key = upload_paper_to_storage(file.filename, contents)

    # 持久化到数据库：创建paper记录和初始版本v1.0
    cursor = None 
    try:
        cursor = db.cursor()
        submitter_name = current_user.get("username") or ""
        roles = current_user.get("roles") or []
        submitter_role = ",".join([str(r) for r in roles]) if isinstance(roles, list) else str(roles)
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        version = "v1.0"
        paper_sql = """
        INSERT INTO papers (owner_id, teacher_id, latest_version, oss_key, created_at, updated_at)
        VALUES (%s, %s, %s, %s, %s, %s)
        """
        cursor.execute(paper_sql, (owner_id, teacher_id, version, oss_key, now, now))
        paper_id = cursor.lastrowid 
        version_sql = """
        INSERT INTO paper_versions (paper_id, teacher_id, version, size, created_at, status, submitted_by_id, submitted_by_name, submitted_by_role)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
        """
        cursor.execute(version_sql, (paper_id, teacher_id, version, size, now, "已上传", submitter_id, submitter_name, submitter_role))
        db.commit()
    except pymysql.MySQLError as e:
        db.rollback() 
        raise HTTPException(status_code=500, detail=f"数据库操作失败: {str(e)}")
    finally:
        if cursor: 
            cursor.close()

    return PaperOut(id=paper_id, owner_id=owner_id, teacher_id=teacher_id, latest_version=version, oss_key=oss_key)


@router.put(
    "/{paper_id}",
    response_model=PaperOut,
    summary="更新论文",
    description="上传新版本并更新论文的最新版本信息"
)
async def update_paper(
    paper_id: int,
    file: UploadFile = File(...),
    version: str = Query(..., description="新版本号（必填，格式如v2.0，必须大于当前最新版本）"),
    db: pymysql.connections.Connection = Depends(get_db),
    current_user: Optional[str] = Query(None, description="提交者信息(JSON字符串，包含 sub/username/roles)"),
):
    current_user = _parse_current_user(current_user)
    submitter_id = current_user.get("sub", 0)
    if not file.filename.lower().endswith(".docx"):
        raise HTTPException(status_code=400, detail="仅支持 .docx 格式")
    contents = await file.read()
    size = len(contents)
    if size == 0:
        raise HTTPException(status_code=400, detail="文件为空")
    if size > 100 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="文件大小超过 100MB")

    cursor = None
    try:
        cursor = db.cursor()
        cursor.execute("SELECT owner_id, latest_version, teacher_id FROM papers WHERE id = %s", (paper_id,))
        row = cursor.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="论文不存在")
        paper_owner_id, current_version_str, teacher_id = row
        if paper_owner_id != submitter_id:
            raise HTTPException(status_code=403, detail="无权限更新该论文")
        current_version = _parse_version(current_version_str)
        new_version = _parse_version(version)
        if new_version <= current_version:
            raise HTTPException(
                status_code=400,
                detail=f"新版本号必须大于当前最新版本号 {current_version_str}，当前提交的版本号 {version} 不符合要求"
            )
        oss_key = upload_paper_to_storage(file.filename, contents)
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        submitter_name = current_user.get("username") or ""
        roles = current_user.get("roles") or []
        submitter_role = ",".join([str(r) for r in roles]) if isinstance(roles, list) else str(roles)

        cursor.execute(
            """
            UPDATE papers
            SET latest_version = %s, oss_key = %s, updated_at = %s
            WHERE id = %s
            """,
            (version, oss_key, now, paper_id),
        )
        cursor.execute(
            """
            INSERT INTO paper_versions (paper_id, teacher_id, version, size, created_at, updated_at, status, submitted_by_id, submitted_by_name, submitted_by_role)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (paper_id, teacher_id, version, size, now, now, "已更新", submitter_id, submitter_name, submitter_role),
        )
        db.commit()
        return PaperOut(id=paper_id, owner_id=paper_owner_id, teacher_id=teacher_id, latest_version=version, oss_key=oss_key)
    except pymysql.MySQLError as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"数据库操作失败: {str(e)}")
    finally:
        if cursor:
            cursor.close()
        # db.close()


@router.delete(
    "/{paper_id}",
    summary="删除论文",
    description="删除论文记录及其版本信息"
)
def delete_paper(
    paper_id: int,
    db: pymysql.connections.Connection = Depends(get_db),
    current_user: Optional[str] = Query(None, description="提交者信息(JSON字符串，包含 sub/username/roles)"),
):
    current_user = _parse_current_user(current_user)
    current_id = current_user.get("sub", 0) 
    current_roles = current_user.get("roles", []) 
    if current_id == 0:
        raise HTTPException(status_code=401, detail="请先登录后再操作")

    cursor = None
    try:
        cursor = db.cursor()
        cursor.execute("SELECT owner_id, teacher_id FROM papers WHERE id = %s", (paper_id,))
        row = cursor.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="论文不存在")
        paper_owner_id, teacher_id = row
        is_owner = (paper_owner_id == current_id)
        is_admin = ("admin" in current_roles) or ("管理员" in current_roles)
        if not is_owner and not is_admin:
            raise HTTPException(
                status_code=403,
                detail=f"无权限删除该论文：仅论文归属者（ID={paper_owner_id}）或管理员可删除，当前登录用户ID={current_id}，角色={current_roles}"
            )
        cursor.execute("DELETE FROM paper_versions WHERE paper_id = %s", (paper_id,))
        cursor.execute("DELETE FROM papers WHERE id = %s", (paper_id,))
        db.commit()
        delete_type = "归属者" if is_owner else "管理员"
        return {
            "message": f"论文及其所有版本信息删除成功（{delete_type}权限）",
            "paper_id": paper_id,
            "deleted_by": current_id,
            "deleted_by_role": current_roles,
            "paper_owner_id": paper_owner_id,
            "teacher_id": teacher_id
        }
    except pymysql.MySQLError as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"数据库操作失败: {str(e)}")
    finally:
        if cursor:
            cursor.close()
        # db.close()


@router.post(
    "/{paper_id}/status",
    response_model=PaperStatusOut,
    summary="创建论文状态",
    description="为指定论文版本创建状态记录",
)
def create_paper_status(
    paper_id: int,
    status: str = Query(
        "待审阅",
        description="论文状态（仅支持待审阅，不可修改）",
        enum=["待审阅"],
        include_in_schema=False
    ),
    db: pymysql.connections.Connection = Depends(get_db),
    current_user: Optional[str] = Query(None, description="登录用户信息(JSON字符串，包含 sub/username/roles)"),
):
    """Insert a status row for a paper if it does not exist."""
    current_user = _parse_current_user(current_user)
    login_user_id = current_user.get("sub", 0)
    if login_user_id <= 0:
        raise HTTPException(status_code=401, detail="请先登录后再操作")
    status = "待审阅"
    cursor = None
    try:
        cursor = db.cursor()
        cursor.execute("SELECT owner_id, teacher_id, latest_version FROM papers WHERE id = %s", (paper_id,))
        paper_info = cursor.fetchone()
        if not paper_info:
            raise HTTPException(status_code=404, detail="论文不存在")
        student_id, teacher_id, version = paper_info 
        cursor.execute(
            "SELECT status FROM paper_versions WHERE paper_id = %s AND version = %s ORDER BY updated_at DESC LIMIT 1",
            (paper_id, version),
        )
        current_status_row = cursor.fetchone()
        has_valid_history = False
        if current_status_row:
            current_status = current_status_row[0]
            if current_status != "已上传":
                raise HTTPException(status_code=400, detail=f"当前论文版本状态为【{current_status}】，仅状态为【已上传】时可创建待审阅状态")
            cursor.execute(
                """
                SELECT status FROM paper_versions 
                WHERE paper_id = %s AND version = %s AND status NOT IN ('已上传')
                ORDER BY updated_at DESC LIMIT 1
                """,
                (paper_id, version),
            )
            valid_history = cursor.fetchone()
            if valid_history:
                has_valid_history = True
        
        if has_valid_history:
            raise HTTPException(status_code=409, detail="该论文版本已存在有效状态记录，不可重复创建，可使用更新接口")
        is_student = (login_user_id == student_id)
        if not is_student:
            raise HTTPException(
                status_code=403,
                detail=f"仅该论文的学生（ID={student_id}）可创建待审阅状态，当前登录用户ID={login_user_id}"
            )
        now = datetime.now()
        size = 0  
        cursor.execute(
            """
            INSERT INTO paper_versions (
                paper_id, teacher_id, version, size, created_at, status, submitted_by_id
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            """,
            (paper_id, teacher_id, version, size, now.strftime("%Y-%m-%d %H:%M:%S"), status, login_user_id),
        )
        db.commit()
        return PaperStatusOut(
            paper_id=paper_id,
            version=version,  
            status=status,
            size=size,
            updated_at=now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        )
    except HTTPException:
        raise
    except pymysql.MySQLError as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"数据库操作失败: {str(e)}")
    finally:
        if cursor:
            cursor.close()
        db.close()


@router.put(
    "/{paper_id}/status",
    response_model=PaperStatusOut,
    summary="更新论文状态",
    description="更新指定论文版本的状态信息",
)
def update_paper_status(
    paper_id: int,
    status: str = Query(
        ...,
        description="论文状态（仅可选择：待审阅/已审阅/已更新/待更新/已定稿）",
        enum=["待审阅", "已审阅", "已更新", "待更新", "已定稿"]  
    ),
    db: pymysql.connections.Connection = Depends(get_db),
    current_user: Optional[str] = Query(None, description="登录用户信息(JSON字符串，包含 sub/username/roles)"),
):
    """Update status for the latest version of an existing paper."""
    current_user = _parse_current_user(current_user)
    login_user_id = current_user.get("sub", 0)
    if login_user_id <= 0:
        raise HTTPException(status_code=401, detail="请先登录后再操作")

    cursor = None
    try:
        cursor = db.cursor()
        cursor.execute(
            "SELECT owner_id, teacher_id, latest_version FROM papers WHERE id = %s", 
            (paper_id,)
        )
        paper_info = cursor.fetchone()
        if not paper_info:
            raise HTTPException(status_code=404, detail="论文不存在")
        student_id, teacher_id, version = paper_info 
        cursor.execute(
            """
            SELECT size, status, updated_at FROM paper_versions 
            WHERE paper_id = %s AND version = %s 
            ORDER BY updated_at DESC
            """,
            (paper_id, version),
        )
        all_status_records = cursor.fetchall()
        current_status = None
        original_size = None
        for record in all_status_records:
            rec_size, rec_status, rec_time = record
            if rec_status not in ('已上传'):
                current_status = rec_status
                original_size = rec_size
                break
        if not current_status:
            raise HTTPException(status_code=404, detail="该论文版本无有效状态记录，请先创建状态")
        
        is_student = (login_user_id == student_id)
        is_teacher = (login_user_id == teacher_id)
        status_rules = {
            "待审阅": {
                "student": ["待审阅"],     
                "teacher": ["已审阅", "已定稿"]  
            },
            "已审阅": {
                "student": ["已更新"],    
                "teacher": ["已审阅", "已定稿"]  
            },
            "已更新": {
                "student": ["已更新"],      
                "teacher": ["待更新", "已定稿"] 
            },
            "待更新": {
                "student": ["已更新"],
                "teacher": ["待更新", "已定稿"]
            },
            "已定稿": {
                "student": [],          
                "teacher": []            
            }
        }
        if not is_student and not is_teacher:
            raise HTTPException(
                status_code=403,
                detail=f"无权限更新状态：仅该论文的学生（ID={student_id}）或老师（ID={teacher_id}）可操作，当前登录用户ID={login_user_id}"
            )
        
        role_key = "student" if is_student else "teacher"
        allowed_target_status = status_rules.get(current_status, {}).get(role_key, [])
        if current_status == "已定稿":
            raise HTTPException(
                status_code=403,
                detail=f"论文最近有效状态为【已定稿】，不允许修改任何状态"
            )
        if status not in allowed_target_status:
            role_name = "学生" if is_student else "老师"
            raise HTTPException(
                status_code=400,
                detail=f"论文最近有效状态为【{current_status}】，{role_name}仅可选择状态：{allowed_target_status}，当前选择：{status}"
            )
        now = datetime.now()
        cursor.execute(
            """
            INSERT INTO paper_versions (
                paper_id, teacher_id, version, size, created_at, updated_at, status, submitted_by_id
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                paper_id,
                teacher_id,
                version,
                original_size,
                now.strftime("%Y-%m-%d %H:%M:%S"),
                now.strftime("%Y-%m-%d %H:%M:%S"),
                status,
                login_user_id,
            ),
        )
        
        db.commit()
        return PaperStatusOut(
            paper_id=paper_id,
            version=version, 
            status=status,
            size=original_size, 
            updated_at=now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        )
    except HTTPException:
        raise
    except pymysql.MySQLError as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"数据库操作失败: {str(e)}")
    finally:
        if cursor:
            cursor.close()
        db.close()


@router.get(
    "/{paper_id}/versions",
    response_model=List[VersionOut],
    summary="查询论文版本列表",
    description="按时间倒序返回指定论文的版本信息"
)
def list_versions(
    paper_id: int,
    # current_user=Depends(get_current_user),  # 保留验证代码，注释掉
    db: pymysql.connections.Connection = Depends(get_db),
    current_user: Optional[str] = Query(None, description="提交者信息(JSON字符串，包含 sub/username/roles)"),
):
    current_user = _parse_current_user(current_user)
    submitter_id = current_user.get("sub", 0)
    current_roles = current_user.get("roles", [])
    if submitter_id <= 0:
        raise HTTPException(status_code=401, detail="请先登录后再查看论文版本")
    
    # 实际业务逻辑：查询该paper_id对应的版本列表
    cursor = None
    try:
        cursor = db.cursor()
        check_owner_sql = "SELECT owner_id, teacher_id FROM papers WHERE id = %s"
        cursor.execute(check_owner_sql, (paper_id,))
        paper_info = cursor.fetchone()
        if not paper_info:
            raise HTTPException(status_code=404, detail="论文不存在")
        paper_owner_id, paper_teacher_id = paper_info
        
        is_owner = (paper_owner_id == submitter_id)
        is_teacher = (paper_teacher_id == submitter_id)
        is_admin = ("admin" in current_roles) or ("管理员" in current_roles)
        if not is_owner and not is_teacher and not is_admin:
            raise HTTPException(
                status_code=403,
                detail=f"无权限查看该论文版本：仅论文归属者（ID={paper_owner_id}）、关联老师（ID={paper_teacher_id}）或管理员可查看，当前登录用户ID={submitter_id}，角色={current_roles}"
            )
        
        # 查询版本表
        version_sql = """
        SELECT version, size, created_at, status, teacher_id 
        FROM paper_versions 
        WHERE paper_id = %s 
        ORDER BY created_at DESC
        """
        cursor.execute(version_sql, (paper_id,))
        versions = cursor.fetchall()
        # 组装返回数据
        result = []
        for version in versions:
            result.append(VersionOut(
                version=version[0],
                size=version[1],
                created_at=version[2].strftime("%Y-%m-%dT%H:%M:%SZ"),  # 格式化时间
                status=version[3],
                teacher_id=version[4]
            ))
        return result
    except pymysql.MySQLError as e:
        raise HTTPException(status_code=500, detail=f"数据库查询失败: {str(e)}")
    finally:
        if cursor:
            cursor.close()
        db.close()
    return [VersionOut(version="v1.0", size=12345, created_at="2025-01-01T00:00:00Z", status="正常", teacher_id=0)]


@router.get(
    "/list",
    response_model=List[PaperOut],
    summary="查询当前用户所有论文",
    description="输入学生ID，仅当与登录用户ID一致时返回该学生的所有论文基础信息"
)
async def list_student_papers(
    owner_id: int = Query(..., description="要查询的学生ID（论文所有者ID），必须传入且为有效整数"),
    db: pymysql.connections.Connection = Depends(get_db),
    current_user: Optional[str] = Query(None, description="登录用户信息(JSON字符串，包含 sub/username/roles)"),
):
    current_user = _parse_current_user(current_user)
    login_user_id = current_user.get("sub", 0)  
    current_roles = current_user.get("roles", [])
    if not isinstance(owner_id, int) or owner_id <= 0:
        raise HTTPException(status_code=400, detail="owner_id必须是正整数")
    
    cursor_check = None
    try:
        cursor_check = db.cursor()
        cursor_check.execute("SELECT teacher_id FROM papers WHERE owner_id = %s LIMIT 1", (owner_id,))
        paper_teacher_id = cursor_check.fetchone()
        paper_teacher_id = paper_teacher_id[0] if paper_teacher_id else 0
        
        is_owner = (owner_id == login_user_id)
        is_teacher = (paper_teacher_id == login_user_id)
        is_admin = ("admin" in current_roles) or ("管理员" in current_roles)
        
        if not is_owner and not is_teacher and not is_admin:
            raise HTTPException(
                status_code=403,
                detail=f"无权限查询：仅可查询本人论文、本人指导的学生论文或管理员查询，传入的owner_id({owner_id})与登录用户ID({login_user_id})不一致，且非该学生的指导老师/管理员"
            )
    finally:
        if cursor_check:
            cursor_check.close()
    
    cursor = None
    try:
        cursor = db.cursor(pymysql.cursors.DictCursor) 
        query_sql = """
        SELECT id, owner_id, teacher_id, latest_version, oss_key, created_at, updated_at
        FROM papers 
        WHERE owner_id = %s 
        ORDER BY created_at DESC
        """
        cursor.execute(query_sql, (owner_id,))
        paper_records = cursor.fetchall()
        
        result = []
        for record in paper_records:
            result.append(
                PaperOut(
                    id=record["id"],
                    owner_id=record["owner_id"],
                    teacher_id=record["teacher_id"],
                    latest_version=record["latest_version"],
                    oss_key=record["oss_key"]
                )
            )
        return result
    
    except pymysql.MySQLError as e:
        raise HTTPException(status_code=500, detail=f"数据库查询失败: {str(e)}")
    finally:
        if cursor:
            cursor.close()
