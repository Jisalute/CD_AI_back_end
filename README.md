# CD AI Backend

Class Design AI 后端 API 服务

## 技术栈

- Web 框架: FastAPI ≥0.123.9（生成 OpenAPI 文档）
- Python 版本: 3.9+
- 数据库: MySQL 8.0+（InnoDB，事务支持）
- 数据验证: Pydantic ≥2.12.5
- 认证: PyJWT ≥2.9.0（HS256）
- 密码加密: bcrypt ≥4.2.0
- HTTP 客户端: requests ≥2.32.0
- 配置管理: pydantic-settings（`.env`）
- ASGI 服务器: uvicorn ≥0.38.0
- 文件上传: python-multipart ≥0.0.20
- 图像处理: Pillow ≥12.0.0（可选）

## 项目结构

```
CD_AI_back_end/
├── alembic.ini
├── database_setup.py        # 初始化/同步数据库表结构
├── main.py                  # 应用入口 (FastAPI app)
├── pyproject.toml
├── README.md
├── docs/
├── logs/
└── app/
		├── __init__.py
		├── config.py            # 配置项（BaseSettings）
		├── database.py          # 运行期数据库连接（需要 DATABASE_URL）
		├── api/
		│   └── v1/
		│       ├── routes.py    # 路由汇总（前缀 /api/v1）
		│       └── endpoints/   # 具体接口
		├── core/
		│   ├── dependencies.py
		│   └── security.py
		├── middleware/
		│   └── logging.py
		├── models/
		├── schemas/
		├── services/
		└── utils/
```

## 快速开始

### 1) 安装 uv 并创建虚拟环境

```bash
# Windows
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"

# Linux/macOS
curl -LsSf https://astral.sh/uv/install.sh | sh

# 创建虚拟环境
uv venv
```

### 2) 安装依赖

```bash
uv sync
```

### 3) 配置环境变量（必需）

本项目运行期需配置 `DATABASE_URL`，否则会报错。可在系统环境或 `.env` 中设置。

示例（MySQL 连接串）：

```
DATABASE_URL=mysql+pymysql://user:password@127.0.0.1:3306/cd_ai_db?charset=utf8mb4
```

### 4) 初始化/同步数据库表结构

```bash
# 一次性创建基础表（或补齐缺失索引/列）
python database_setup.py
```

### 5) 运行应用

```bash
# 快速运行（开发环境）
uv run main.py

# 热重载
uvicorn main:app --reload --host 0.0.0.0 --port 8000

# 生产模式
uvicorn main:app --host 0.0.0.0 --port 8000
```

### 6) 访问 API 文档

- Swagger UI: <http://localhost:8000/docs>
- ReDoc: <http://localhost:8000/redoc>

说明：所有业务接口均挂载在前缀 `/api/v1` 下（见 [app/api/v1/routes.py](app/api/v1/routes.py)）。

## 主要接口概览（/api/v1）

- 健康检查
	- GET `/health/`
	- GET `/health/detailed`

- 材料 Materials（存储与路径读取）
	- POST `/materials/upload`
	- PUT `/materials/{material_id}`
	- DELETE `/materials/{material_id}`
	- GET `/materials/names?path=...`（列出指定目录下文件名，非递归）

- 论文 Papers（上传与版本）
	- POST `/papers/upload`
	- PUT `/papers/{paper_id}`（上传新版本并更新最新版本）
	- DELETE `/papers/{paper_id}`
	- GET `/papers/{paper_id}/versions`
	- POST `/papers/{paper_id}/versions/{version}/status`（创建论文版本状态）
	- PUT  `/papers/{paper_id}/versions/{version}/status`（更新论文版本状态）

- AI 评审
	- POST `/papers/{paper_id}/ai-review`（触发评审任务）
	- GET  `/papers/{paper_id}/ai-report`（查询评审报告）

- 群组 Groups（导入与成员管理）
	- POST `/groups/import`（批量导入 TSV/CSV）
	- POST `/groups/create`
	- DELETE `/groups/{group_id}`
	- POST `/groups/{group_id}/members`
	- DELETE `/groups/{group_id}/members`

- 标注 Annotations
	- POST `/annotations/`（为论文创建标注）

- 管理 Admin
	- POST `/admin/templates`（上传模板并存储元数据）
	- PUT  `/admin/templates/{template_id}`
	- DELETE `/admin/templates/{template_id}`
	- GET  `/admin/dashboard/stats`
	- GET  `/admin/audit/logs`

- 通知 Notifications
	- POST `/notifications/push`（信息推送，记录到操作日志）
	- GET  `/notifications/query`（信息查询，支持按用户与分页）

## 注意事项

- 认证与权限：当前部分接口使用模拟用户，实际接入请启用 [app/core/dependencies.py](app/core/dependencies.py) 与 [app/core/security.py](app/core/security.py)。
- 数据库：运行前必须正确配置 `DATABASE_URL`，并执行一次 `python database_setup.py` 创建/同步表结构。
- 代理/网络：如通过反向代理访问，请确保 `/docs`、`/openapi.json` 可正常透传。

## 故障排查

- `/docs` 打不开或为空：直接访问 <http://localhost:8000/openapi.json> 检查是否能返回 OpenAPI JSON；若报错，优先核验数据库配置和应用启动日志。
- 接口 404：确认是否使用了 `/api/v1` 前缀（例如材料上传应为 `/api/v1/materials/upload`）。

