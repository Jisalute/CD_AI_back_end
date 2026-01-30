"""材料相关接口"""
from fastapi import APIRouter, UploadFile, File, Depends, HTTPException, Query
import pymysql
from app.database import get_db
from app.schemas.document import MaterialResponse
from app.services.oss import upload_attachment_to_storage
import os

router = APIRouter()


@router.post(
    "/upload",
    response_model=MaterialResponse,
    summary="上传材料",
    description="上传材料并存储到数据库"
)
async def upload_material(
    file: UploadFile = File(...),  
    name: str = Query(..., description="作者/上传者姓名（必填）"),
    file_type: str = Query(
        "document", 
        description="文件类型，可选值：document(文档)、essay(文章)",
        enum=["document", "essay"] 
    ),
    version: int = Query(1, description="版本号，默认1，最小值1", ge=1),
    remark: str = Query(None, description="备注信息"),
    db: pymysql.connections.Connection = Depends(get_db)
):
    # 基础参数校验
    if not file.filename:
        raise HTTPException(status_code=400, detail="文件名不能为空")
    if not name:
        raise HTTPException(status_code=400, detail="作者/上传者姓名不能为空")
    # 读取文件内容
    try:
        content = await file.read()
        if not content:
            raise HTTPException(status_code=400, detail="上传的文件内容不能为空")
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"读取文件失败：{str(e)}")
    # 数据库操作
    cursor = None
    try:
        # 创建游标
        cursor = db.cursor(pymysql.cursors.DictCursor)
        # 插入SQL
        insert_sql = """
            INSERT INTO file_records (
                name, filename, upload_time, storage_path, 
                file_type, version, remark, created_at, updated_at
            )
            VALUES (%s, %s, NOW(), %s, %s, %s, %s, NOW(), NOW())
        """
        storage_path = upload_attachment_to_storage(file.filename, content)
        # 执行插入
        cursor.execute(
            insert_sql,
            (
                name,            # 作者/上传者姓名
                file.filename,   # 文件名
                storage_path,    # 存储路径（标识值）
                file_type,       # 文件类型
                version,         # 版本号
                remark           # 备注
            )
        )
        # 获取新增记录ID
        material_id = cursor.lastrowid
        # 提交事务
        db.commit()
        # 查询新增记录并返回
        select_sql = """
            SELECT 
                id, name, filename, upload_time, storage_path, 
                file_type, version, remark, created_at, updated_at 
            FROM file_records 
            WHERE id = %s
        """
        cursor.execute(select_sql, (material_id,))
        new_record = cursor.fetchone()
        if not new_record:
            raise HTTPException(status_code=500, detail="文件上传成功，但查询不到新增记录")
        # 返回结果
        return new_record
    except pymysql.MySQLError as e:
        # 数据库异常回滚事务
        db.rollback()
        raise HTTPException(status_code=500, detail=f"数据库操作失败：{str(e)}")
    finally:
        # 确保游标关闭
        if cursor:
            cursor.close()


@router.put(
    "/{material_id}",
    response_model=MaterialResponse,
    summary="更新材料",
    description="替换已有材料文件并更新记录"
)
async def update_material(
    material_id: int,
    file: UploadFile = File(...),
    name: str = Query(None, description="作者/上传者姓名"),
    file_type: str = Query(None, description="文件类型：document(文档)或essay(文章)", enum=["document", "essay"]),
    version: int = Query(None, description="版本号", ge=1),
    remark: str = Query(None, description="备注"),
    db: pymysql.connections.Connection = Depends(get_db)
):
    # 基础文件参数校验
    if not file.filename:
        raise HTTPException(status_code=400, detail="上传的文件必须包含文件名")
    # 读取文件内容
    try:
        content = await file.read()
        if not content:
            raise HTTPException(status_code=400, detail="上传的文件内容不能为空")
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"读取上传文件失败：{str(e)}")
    cursor = None
    try:
        cursor = db.cursor(pymysql.cursors.DictCursor)
        # 检查指定ID的材料是否存在
        cursor.execute("SELECT id FROM file_records WHERE id = %s", (material_id,))
        if not cursor.fetchone():
            raise HTTPException(status_code=404, detail=f"ID为{material_id}的材料不存在")
        # 4. 构建动态更新SQL
        update_fields = []
        update_params = []
        # 必更新字段：文件名、上传时间、storage_path
        update_fields.append("filename = %s")
        update_params.append(file.filename)
        update_fields.append("upload_time = NOW()")
        update_fields.append("storage_path = %s")
        update_params.append(upload_attachment_to_storage(file.filename, content))
        # 可选更新字段
        if name is not None:
            update_fields.append("name = %s")
            update_params.append(name)
        if file_type is not None:
            update_fields.append("file_type = %s")
            update_params.append(file_type)
        if version is not None:
            update_fields.append("version = %s")
            update_params.append(version)
        if remark is not None:
            update_fields.append("remark = %s")
            update_params.append(remark)
        # 最后更新updated_at字段
        update_fields.append("updated_at = NOW()")
        # 拼接更新SQL
        update_sql = f"""
            UPDATE file_records
            SET {', '.join(update_fields)}
            WHERE id = %s
        """
        # 添加material_id到参数列表末尾
        update_params.append(material_id)
        # 执行更新
        cursor.execute(update_sql, tuple(update_params))
        db.commit()
        # 查询更新后的完整记录并返回
        cursor.execute(
            """
            SELECT 
                id, name, filename, upload_time, storage_path, 
                file_type, version, remark, created_at, updated_at 
            FROM file_records WHERE id = %s
            """,
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
def delete_material(
    material_id: int,
    db: pymysql.connections.Connection = Depends(get_db)
):
    cursor = None
    try:
        # 创建游标
        cursor = db.cursor()
        # 检查指定ID的材料是否存在
        check_sql = "SELECT id FROM file_records WHERE id = %s"
        cursor.execute(check_sql, (material_id,))
        if not cursor.fetchone():
            raise HTTPException(status_code=404, detail=f"ID为{material_id}的材料不存在")
        # 执行删除操作
        delete_sql = "DELETE FROM file_records WHERE id = %s"
        cursor.execute(delete_sql, (material_id,))
        # 3. 提交事务
        db.commit()
        # 返回友好的删除成功响应
        return {
            "code": 200,
            "message": "删除成功",
            "material_id": material_id,
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        }
    except pymysql.MySQLError as e:
        # 数据库异常时回滚事务
        db.rollback()
        raise HTTPException(status_code=500, detail=f"数据库错误：{str(e)}")
    finally:
        # 确保游标关闭，释放资源
        if cursor:
            cursor.close()


@router.get(
    "/names",
    summary="获取材料名称列表",
    description="列出指定存储路径下的材料文件名（非递归）"
)
def list_material_names(
    name: str = Query(None, description="按上传者姓名筛选"),
    file_type: str = Query(None, description="按文件类型筛选：document/essay", enum=["document", "essay"]),
    keyword: str = Query(None, description="按文件名关键词模糊筛选"),
    db: pymysql.connections.Connection = Depends(get_db)
):
    cursor = None
    try:
        cursor = db.cursor(pymysql.cursors.DictCursor)
        # 构建基础查询SQL
        query_sql = """
            SELECT id, name, filename, file_type, upload_time, version 
            FROM file_records 
            WHERE 1=1
        """
        query_params = []
        # 动态添加筛选条件
        if name:
            query_sql += " AND name LIKE %s"
            query_params.append(f"%{name}%")  # 姓名模糊匹配
        if file_type:
            query_sql += " AND file_type = %s"
            query_params.append(file_type)  # 文件类型精准匹配
        if keyword:
            query_sql += " AND filename LIKE %s"
            query_params.append(f"%{keyword}%")  # 文件名关键词模糊匹配
        # 按上传时间倒序排列
        query_sql += " ORDER BY upload_time DESC"
        # 执行查询
        cursor.execute(query_sql, tuple(query_params))
        records = cursor.fetchall()
        # 提取文件名列表
        file_list = [
            {
                "id": record["id"],
                "uploader_name": record["name"],
                "filename": record["filename"],
                "file_type": record["file_type"],
                "upload_time": record["upload_time"],
                "version": record["version"]
            }
            for record in records
        ]
        return {
            "total": len(file_list),
            "filter_conditions": {
                "uploader_name": name,
                "file_type": file_type,
                "filename_keyword": keyword
            },
            "files": file_list
        }
    except pymysql.MySQLError as e:
        raise HTTPException(status_code=500, detail=f"数据库查询错误：{str(e)}")
    finally:
        if cursor:
            cursor.close()
