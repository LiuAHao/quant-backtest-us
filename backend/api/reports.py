from __future__ import annotations

import html
import json

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import Response

from backend.services.report_service import ReportService

router = APIRouter()
service = ReportService()


@router.get("")
def list_reports(
    type: str | None = Query(None, description="报告类型: backtest | event_analysis | factor_analysis"),
    keyword: str | None = Query(None, description="关键词搜索"),
    start_date: str | None = Query(None, description="开始日期 YYYY-MM-DD"),
    end_date: str | None = Query(None, description="结束日期 YYYY-MM-DD"),
    status: str | None = Query(None, description="状态筛选"),
    page: int = Query(1, ge=1, description="页码"),
    page_size: int = Query(20, ge=1, le=100, description="每页数量"),
):
    return service.list_reports(
        report_type=type,
        keyword=keyword,
        start_date=start_date,
        end_date=end_date,
        status=status,
        page=page,
        page_size=page_size,
    )


@router.get("/{task_id}")
def get_report(task_id: int, kind: str = "backtest"):
    report = service.get_report(task_id, kind=kind)
    if report is None:
        raise HTTPException(status_code=404, detail="报告不存在")
    return report


@router.get("/{task_id}/download")
def download_report(task_id: int, format: str = "html", kind: str = "backtest"):
    normalized = format.lower()
    if normalized not in {"html", "json"}:
        raise HTTPException(status_code=400, detail="format 只支持 html 或 json")
    if kind in {"event_analysis", "factor_analysis"} and normalized != "json":
        raise HTTPException(status_code=400, detail="分析结果只支持 json 下载")

    report = service.get_report(task_id, kind=kind)
    if report is None:
        raise HTTPException(status_code=404, detail="报告不存在")

    payload = report.get("payload", {})
    task = report.get("task", {})
    runtime_logs = payload.get("runtime", {}).get("logs", [])

    if normalized == "json":
        content = json.dumps(payload, ensure_ascii=False, indent=2)
        filename = f"report_{task_id}.json"
        return Response(
            content=content,
            media_type="application/json",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )

    path = service.get_report_file(task_id, normalized, kind=kind)
    if path is None:
        raise HTTPException(status_code=404, detail="报告文件不存在")

    html_content = path.read_text(encoding="utf-8")
    if runtime_logs:
        log_rows = "".join(
            "<tr>"
            f'<td>{html.escape(str(log.get("timestamp", "")))}</td>'
            f'<td>{html.escape(str(log.get("level", "")))}</td>'
            f'<td>{html.escape(str(log.get("source", "")))}</td>'
            f'<td>{html.escape(str(log.get("message", "")))}</td>'
            "</tr>"
            for log in runtime_logs
        )
        log_section = f"""
    <div style="margin-top:32px;padding:20px;background:var(--panel);border:1px solid var(--line);border-radius:var(--radius);">
      <h3 style="margin:0 0 12px;">运行日志</h3>
      <div style="max-height:400px;overflow:auto;border:1px solid var(--line);border-radius:10px;">
        <table style="width:100%;border-collapse:collapse;font-size:13px;">
          <thead><tr><th style="text-align:left;padding:8px;background:#f7f9fc;">时间</th><th style="text-align:left;padding:8px;background:#f7f9fc;">级别</th><th style="text-align:left;padding:8px;background:#f7f9fc;">来源</th><th style="text-align:left;padding:8px;background:#f7f9fc;">消息</th></tr></thead>
          <tbody>{log_rows}</tbody>
        </table>
      </div>
    </div>"""
        html_content = html_content.replace("</body>", f"{log_section}\n</body>")

    return Response(
        content=html_content,
        media_type="text/html",
        headers={"Content-Disposition": f'attachment; filename="report_{task_id}.html"'},
    )


@router.delete("/{task_id}")
def delete_report(task_id: int, kind: str = "backtest"):
    success = service.delete_report(task_id, kind=kind)
    if not success:
        raise HTTPException(status_code=404, detail="报告不存在")
    return {"ok": True, "message": "报告已删除"}
