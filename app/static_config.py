from fastapi.staticfiles import StaticFiles

# 静态文件目录
ESSAY_STATIC_DIR = "/root/CD_AI_back_end/doc/essay"
ESSAY_MOUNT_PATH = "/essay"

def setup_static_files(app):
    """
    配置静态文件服务，将 /root/CD_AI_back_end/doc/essay/ 映射到 /essay 路径。
    """
    app.mount(ESSAY_MOUNT_PATH, StaticFiles(directory=ESSAY_STATIC_DIR), name="essay")
