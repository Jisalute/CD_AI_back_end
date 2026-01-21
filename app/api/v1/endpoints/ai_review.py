from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from app.core.dependencies import get_current_user
from app.services.ai_adapter import submit_ai_review

router = APIRouter()


@router.post(
    "/{paper_id}/ai-review",
    summary="触发 AI 评审",
    description="提交评审任务到后台队列"
)
def trigger_ai_review(paper_id: int, background_tasks: BackgroundTasks, current_user=Depends(get_current_user)):
    # 权限检查由业务层负责（是否为论文作者或指导教师）
    # 这里将任务交给后台/任务队列
    try:
        background_tasks.add_task(submit_ai_review, paper_id, current_user)
    except Exception as e:
        raise HTTPException(status_code=503, detail="AI 服务暂时不可用")
    return {"status": "排队中", "message": "任务已加入队列"}


@router.get(
    "/{paper_id}/ai-report",
    summary="获取 AI 报告",
    description="查询并返回指定论文的 AI 评审报告"
)
def get_ai_report(paper_id: int, current_user=Depends(get_current_user)):
    # TODO: 从 ai_reports 表读取结构化报告
    return {"paper_id": paper_id, "report": {}}
