"""材料相关接口"""
from fastapi import APIRouter, UploadFile, File, Depends, HTTPException, Query
import pymysql
from app.database import get_db
from app.schemas.document import MaterialResponse
import os

router = APIRouter()


@router.post(
    "/upload",
    response_model=MaterialResponse,
    summary="上传材料",
    description="上传材料并存储到数据库"
)
async def upload_material(file: UploadFile = File(...), db: pymysql.connections.Connection = Depends(get_db)):
    """上传材料并写入数据库。"""
    if not file.filename:
        raise HTTPException(status_code=400, detail="上传的文件必须包含文件名")
    if not file.content_type:
        raise HTTPException(status_code=400, detail="上传的文件必须包含内容类型")
    try:
        content = await file.read()
        if not content:
            raise HTTPException(status_code=400, detail="上传的文件为空")
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"读取上传文件失败：{str(e)}")

    cursor = None
    try:
        cursor = db.cursor(pymysql.cursors.DictCursor)
        insert_sql = """
            INSERT INTO documents (filename, content, content_type, created_at, updated_at)
            VALUES (%s, %s, %s, NOW(), NOW())
        """
        cursor.execute(insert_sql, (file.filename, content, file.content_type))
        material_id = cursor.lastrowid
        db.commit()

        cursor.execute(
            "SELECT id, filename, content_type, created_at, updated_at FROM documents WHERE id = %s",
            (material_id,),
        )
        row = cursor.fetchone()
        return MaterialResponse(**row)
    except pymysql.MySQLError as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"数据库错误：{str(e)}")
    finally:
        if cursor:
            cursor.close()


@router.put(
    "/{material_id}",
    response_model=MaterialResponse,
    summary="更新材料",
    description="替换已有材料文件并更新记录"
)
async def update_material(material_id: int, file: UploadFile = File(...), db: pymysql.connections.Connection = Depends(get_db)):
    if not file.filename:
        raise HTTPException(status_code=400, detail="上传的文件必须包含文件名")
    if not file.content_type:
        raise HTTPException(status_code=400, detail="上传的文件必须包含内容类型")
    try:
        content = await file.read()
        if not content:
            raise HTTPException(status_code=400, detail="上传的文件为空")
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"读取上传文件失败：{str(e)}")

    cursor = None
    try:
        cursor = db.cursor(pymysql.cursors.DictCursor)
        cursor.execute("SELECT id FROM documents WHERE id = %s", (material_id,))
        if not cursor.fetchone():
            raise HTTPException(status_code=404, detail="材料不存在")

        update_sql = """
            UPDATE documents
            SET filename = %s, content = %s, content_type = %s, updated_at = NOW()
            WHERE id = %s
        """
        cursor.execute(update_sql, (file.filename, content, file.content_type, material_id))
        db.commit()

        cursor.execute(
            "SELECT id, filename, content_type, created_at, updated_at FROM documents WHERE id = %s",
            (material_id,),
        )
        row = cursor.fetchone()
        return MaterialResponse(**row)
    except pymysql.MySQLError as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"数据库错误：{str(e)}")
    finally:
        if cursor:
            cursor.close()


@router.delete(
    "/{material_id}",
    summary="删除材料",
    description="根据材料ID删除记录"
)
def delete_material(material_id: int, db: pymysql.connections.Connection = Depends(get_db)):
    cursor = None
    try:
        cursor = db.cursor()
        cursor.execute("SELECT id FROM documents WHERE id = %s", (material_id,))
        if not cursor.fetchone():
            raise HTTPException(status_code=404, detail="材料不存在")
        cursor.execute("DELETE FROM documents WHERE id = %s", (material_id,))
        db.commit()
        return {"message": "删除成功", "material_id": material_id}
    except pymysql.MySQLError as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"数据库错误：{str(e)}")
    finally:
        if cursor:
            cursor.close()


@router.get(
    "/names",
    summary="获取材料名称列表",
    description="列出指定存储路径下的材料文件名（非递归）"
)
def list_material_names(path: str = Query(..., description="材料所在目录的绝对或相对路径")):
    """Return filenames under the given directory."""
    try:
        target = os.path.abspath(path)
        if not os.path.exists(target):
            raise HTTPException(status_code=404, detail="路径不存在")
        if not os.path.isdir(target):
            raise HTTPException(status_code=400, detail="提供的路径不是目录")
        names = [f for f in os.listdir(target) if os.path.isfile(os.path.join(target, f))]
        return {"path": target, "files": names}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"读取目录失败：{str(e)}")
