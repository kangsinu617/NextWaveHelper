"""NextSync Guide 웹 데모 — FastAPI 단일 페이지.

  GET  /           가입 폼 (user_id + goal)
  POST /onboard    4단계 파이프라인 실행 후 결과 렌더링

실행:
  uvicorn prototype.app:app --reload --port 8000
"""

from __future__ import annotations

import io
from contextlib import redirect_stdout
from pathlib import Path

from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

from src.core import (
    USER_TYPES,
    generate_tasks,
    load_feature_usage_logs,
    load_user_segment,
    profile_user,
    recommend,
    register,
    user_recent_activity,
    FEATURE_LABEL,
)

BASE_DIR = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

app = FastAPI(title="NextSync Guide Demo")


class ChatRequest(BaseModel):
    session_id: str
    user_id: str
    user_type: str
    goal: str


@app.get("/", response_class=HTMLResponse)
async def index(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(request, "onboarding.html", {
        "user_types": USER_TYPES,
        "result": None,
    })


@app.post("/onboard", response_class=HTMLResponse)
async def onboard(
    request: Request,
    user_id: int = Form(...),
    user_type_override: str = Form(""),
    goal: str = Form(...),
) -> HTMLResponse:
    segment = load_user_segment()
    logs = load_feature_usage_logs()

    user_type = user_type_override or profile_user(user_id, segment)
    features = recommend(user_type, logs, segment)
    recent = user_recent_activity(user_id, logs)
    features_labeled = [{"code": f, "label": FEATURE_LABEL.get(f, f)} for f in features]

    out = generate_tasks(user_type, features, recent, goal)

    mock_log = io.StringIO()
    with redirect_stdout(mock_log):
        register(user_id, user_type, out)

    result = {
        "user_id": user_id,
        "user_type": user_type,
        "features": features_labeled,
        "recent": recent,
        "goal": goal,
        "tasks": out.get("tasks", []),
        "team_invites": out.get("team_invites", []),
        "notifications": out.get("notifications", []),
        "mock_log": mock_log.getvalue().strip(),
    }

    return templates.TemplateResponse(request, "onboarding.html", {
        "user_types": USER_TYPES,
        "result": result,
        "submitted": {"user_id": user_id, "user_type_override": user_type_override, "goal": goal},
    })


@app.get("/chat", response_class=HTMLResponse)
async def chat_page(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(request, "chat.html", {})


@app.post("/api/chat/generate")
async def chat_generate(req: ChatRequest) -> JSONResponse:
    segment = load_user_segment()
    logs = load_feature_usage_logs()

    user_type = req.user_type
    features = recommend(user_type, logs, segment)
    recent = user_recent_activity(req.user_id, logs)
    features_labeled = [{"code": f, "label": FEATURE_LABEL.get(f, f)} for f in features]

    out = generate_tasks(user_type, features, recent, req.goal)

    mock_log = io.StringIO()
    with redirect_stdout(mock_log):
        register(req.user_id, user_type, out)

    return JSONResponse({
        "user_id": req.user_id,
        "user_type": user_type,
        "features": features_labeled,
        "tasks": out.get("tasks", []),
        "team_invites": out.get("team_invites", []),
        "notifications": out.get("notifications", []),
    })
