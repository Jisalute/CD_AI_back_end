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
        data = json.loads(raw)
        if isinstance(data, dict):
            return data
    except Exception:
        pass
    return {"sub": 0, "username": "", "roles": []}

@router.post(
    "/upload",
    response_model=PaperOut,
    summary="上传论文",
    description="上传 docx 生成论文记录与首个版本，并记录提交者信息"
)
async def upload_paper(
    file: UploadFile = File(...),
    db: pymysql.connections.Connection = Depends(get_db),
    current_user: Optional[str] = Query(None, description="提交者信息(JSON字符串，包含 sub/username/roles)"),
    # current_user=Depends(get_current_user),
):
    current_user = _parse_current_user(current_user)
    # 验证文件扩展名
    if not file.filename.lower().endswith(".docx"):
        raise HTTPException(status_code=400, detail="仅支持 .docx 格式")
    contents = await file.read()
    size = len(contents)
    if size > 100 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="文件大小超过 100MB")

    # 本地存储论文到 doc/essay（返回路径作为 oss_key）
    oss_key = upload_paper_to_storage(file.filename, contents)

    # TODO: persist to DB, create paper record and initial version v1.0
    # 持久化到数据库：创建paper记录和初始版本v1.0
    cursor = None 
    try:
        cursor = db.cursor()
        user_id = current_user.get("sub", 0)
        submitter_name = current_user.get("username") or ""
        roles = current_user.get("roles") or []
        submitter_role = ",".join([str(r) for r in roles]) if isinstance(roles, list) else str(roles)
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        version = "v1.0"
        # 插入papers主表
        paper_sql = """
        INSERT INTO papers (owner_id, latest_version, oss_key, created_at, updated_at)
        VALUES (%s, %s, %s, %s, %s)
        """
        cursor.execute(paper_sql, (user_id, version, oss_key, now, now))
        paper_id = cursor.lastrowid 
        version_sql = """
        INSERT INTO paper_versions (paper_id, version, size, created_at, status, submitted_by_id, submitted_by_name, submitted_by_role)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        """
        cursor.execute(version_sql, (paper_id, version, size, now, "ok", user_id, submitter_name, submitter_role))
        db.commit()
    except pymysql.MySQLError as e:
        db.rollback() 
        raise HTTPException(status_code=500, detail=f"数据库操作失败: {str(e)}")
    finally:
        if cursor: 
            cursor.close()
        db.close()

    return PaperOut(id=paper_id, owner_id=current_user.get("sub", 0), latest_version=version, oss_key=oss_key)


@router.put(
    "/{paper_id}",
    response_model=PaperOut,
    summary="更新论文",
    description="上传新版本并更新论文的最新版本信息"
)
async def update_paper(
    paper_id: int,
    file: UploadFile = File(...),
    version: str = "v2.0",
    db: pymysql.connections.Connection = Depends(get_db),
    current_user: Optional[str] = Query(None, description="提交者信息(JSON字符串，包含 sub/username/roles)"),
):
    current_user = _parse_current_user(current_user)
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
        cursor.execute("SELECT owner_id FROM papers WHERE id = %s", (paper_id,))
        row = cursor.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="论文不存在")
        if row[0] != current_user.get("sub"):
            raise HTTPException(status_code=403, detail="无权限更新该论文")

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
            INSERT INTO paper_versions (paper_id, version, size, created_at, updated_at, status, submitted_by_id, submitted_by_name, submitted_by_role)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (paper_id, version, size, now, now, "ok", current_user.get("sub", 0), submitter_name, submitter_role),
        )
        db.commit()
        return PaperOut(id=paper_id, owner_id=current_user.get("sub", 0), latest_version=version, oss_key=oss_key)
    except pymysql.MySQLError as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"数据库操作失败: {str(e)}")
    finally:
        if cursor:
            cursor.close()
        db.close()


@router.delete(
    "/{paper_id}",
    summary="删除论文",
    description="删除论文记录及其版本信息"
)
def delete_paper(
    paper_id: int,
    db: pymysql.connections.Connection = Depends(get_db),
):
    current_user = {"sub": 1}
    cursor = None
    try:
        cursor = db.cursor()
        cursor.execute("SELECT owner_id FROM papers WHERE id = %s", (paper_id,))
        row = cursor.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="论文不存在")
        if row[0] != current_user.get("sub"):
            raise HTTPException(status_code=403, detail="无权限删除该论文")

        cursor.execute("DELETE FROM papers WHERE id = %s", (paper_id,))
        db.commit()
        return {"message": "删除成功", "paper_id": paper_id}
    except pymysql.MySQLError as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"数据库操作失败: {str(e)}")
    finally:
        if cursor:
            cursor.close()
        db.close()


@router.post(
    "/{paper_id}/versions/{version}/status",
    response_model=PaperStatusOut,
    summary="创建论文状态",
    description="为指定论文版本创建状态记录",
)
def create_paper_status(
    paper_id: int,
    version: str,
    payload: PaperStatusCreate,
    db: pymysql.connections.Connection = Depends(get_db),
):
    """Insert a status row for a paper version if it does not exist."""
    cursor = None
    try:
        cursor = db.cursor()
        cursor.execute("SELECT 1 FROM papers WHERE id = %s", (paper_id,))
        if not cursor.fetchone():
            raise HTTPException(status_code=404, detail="论文不存在")

        cursor.execute(
            "SELECT id FROM paper_versions WHERE paper_id = %s AND version = %s",
            (paper_id, version),
        )
        if cursor.fetchone():
            raise HTTPException(status_code=409, detail="该版本状态已存在，可使用更新接口")

        size = payload.size if payload.size is not None else 0
        now = datetime.now()
        cursor.execute(
            """
            INSERT INTO paper_versions (paper_id, version, size, created_at, status)
            VALUES (%s, %s, %s, %s, %s)
            """,
            (paper_id, version, size, now.strftime("%Y-%m-%d %H:%M:%S"), payload.status),
        )
        db.commit()
        return PaperStatusOut(
            paper_id=paper_id,
            version=version,
            status=payload.status,
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
    "/{paper_id}/versions/{version}/status",
    response_model=PaperStatusOut,
    summary="更新论文状态",
    description="更新指定论文版本的状态信息",
)
def update_paper_status(
    paper_id: int,
    version: str,
    payload: PaperStatusUpdate,
    db: pymysql.connections.Connection = Depends(get_db),
):
    """Update status for an existing paper version."""
    cursor = None
    try:
        cursor = db.cursor()
        cursor.execute(
            "SELECT size FROM paper_versions WHERE paper_id = %s AND version = %s",
            (paper_id, version),
        )
        row = cursor.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="该版本不存在")

        new_size = payload.size if payload.size is not None else row[0]
        now = datetime.now()
        cursor.execute(
            """
            UPDATE paper_versions
            SET status = %s, size = %s, updated_at = %s
            WHERE paper_id = %s AND version = %s
            """,
            (
                payload.status,
                new_size,
                now.strftime("%Y-%m-%d %H:%M:%S"),
                paper_id,
                version,
            ),
        )
        db.commit()
        return PaperStatusOut(
            paper_id=paper_id,
            version=version,
            status=payload.status,
            size=new_size,
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
    db: pymysql.connections.Connection = Depends(get_db) 
):
    # 模拟“已登录”，和第一个接口的模拟逻辑保持一致
    current_user = {"sub": 1}
    # 实际业务逻辑：查询该paper_id对应的版本列表
    cursor = None
    try:
        cursor = db.cursor()
        # 验证paper归属
        check_owner_sql = "SELECT owner_id FROM papers WHERE id = %s"
        cursor.execute(check_owner_sql, (paper_id,))
        paper_info = cursor.fetchone()
        if not paper_info:
            raise HTTPException(status_code=404, detail="论文不存在")
        if paper_info[0] != current_user.get("sub"):
            raise HTTPException(status_code=403, detail="无权限查看该论文版本")
        # 查询版本表
        version_sql = """
        SELECT version, size, created_at, status 
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
                status=version[3]
            ))
        return result
    except pymysql.MySQLError as e:
        raise HTTPException(status_code=500, detail=f"数据库查询失败: {str(e)}")
    finally:
        if cursor:
            cursor.close()
        db.close()
    return [VersionOut(version="v1.0", size=12345, created_at="2025-01-01T00:00:00Z", status="正常")]
