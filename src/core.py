"""NextSync Guide 코어 — 데이터 로딩 · Profiler · Recommender · Task Generator · Mock API.

모듈별 책임:
  - load_*         : data/ CSV·JSON 로더
  - profile_user   : user_id → user_type 매핑 (신규면 fallback 유형 반환)
  - recommend      : 유형별 우선 기능 랭킹 (usage_logs 집계 + cold-start fallback)
  - generate_tasks : Gemini 호출, few-shot 프롬프트로 JSON 산출물 생성
  - post_mock      : 실제 HTTP 대신 콘솔 로깅
"""

from __future__ import annotations

import csv
import json
import os
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

load_dotenv()

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data"
LOGS_DIR = PROJECT_ROOT / "logs"
EVENTS_LOG = LOGS_DIR / "events.jsonl"

USER_TYPES = ["대학생", "직장인", "프리랜서", "팀 사용자"]

COLD_START_PRIORITY = {
    "대학생":     ["task_create", "team_invite", "note_create"],
    "직장인":     ["task_create", "note_create", "notification_rule"],
    "프리랜서":   ["task_create", "notification_rule", "note_create"],
    "팀 사용자":  ["team_invite", "note_create", "notification_rule"],
}

FEATURE_LABEL = {
    "task_create":       "일정·Task 생성",
    "note_create":       "협업 메모 작성",
    "team_invite":       "팀원 초대",
    "notification_rule": "알림 자동화 설정",
}


def load_user_segment() -> dict[int, str]:
    path = DATA_DIR / "user_segment.csv"
    with path.open(encoding="utf-8") as f:
        return {int(row["user_id"]): row["user_type"] for row in csv.DictReader(f)}


def load_feature_usage_logs() -> list[dict[str, Any]]:
    path = DATA_DIR / "feature_usage_logs.csv"
    with path.open(encoding="utf-8") as f:
        return [
            {"user_id": int(r["user_id"]), "feature": r["feature"], "usage_count": int(r["usage_count"])}
            for r in csv.DictReader(f)
        ]


def load_api_examples() -> dict[str, Any]:
    path = DATA_DIR / "api_examples.json"
    with path.open(encoding="utf-8") as f:
        return json.load(f)


def profile_user(user_id: int, segment: dict[int, str], fallback: str = "직장인") -> str:
    return segment.get(user_id, fallback)


def recommend(user_type: str, logs: list[dict[str, Any]], segment: dict[int, str], top_k: int = 3) -> list[str]:
    """유형별 누적 usage_count가 높은 기능을 상위 순으로 반환.

    데이터가 부족하면 COLD_START_PRIORITY로 채움.
    """
    scores: dict[str, int] = defaultdict(int)
    for row in logs:
        if segment.get(row["user_id"]) == user_type:
            scores[row["feature"]] += row["usage_count"]

    ranked = [f for f, _ in sorted(scores.items(), key=lambda kv: kv[1], reverse=True) if _ > 0]

    for fallback in COLD_START_PRIORITY.get(user_type, []):
        if fallback not in ranked:
            ranked.append(fallback)

    return ranked[:top_k]


def user_recent_activity(user_id: int, logs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [{"feature": r["feature"], "usage_count": r["usage_count"]} for r in logs if r["user_id"] == user_id]


SYSTEM_INSTRUCTION = """당신은 NextWave 생산성 SaaS의 온보딩 어시스턴트 "NextSync Guide"입니다.

역할:
- 신규 사용자의 자연어 목표를 읽고, 즉시 등록 가능한 Task·팀 초대·알림을 생성합니다.
- 사용자 유형과 우선 기능에 맞춰 개인화된 출력을 만듭니다.

출력 규칙:
- 반드시 주어진 JSON 스키마만 사용합니다.
- tasks: 2~4개, 명사구가 아닌 실행 가능한 문장으로 작성.
- team_invites: "팀 사용자"·"대학생" 유형이거나 목표에 협업이 명시된 경우에만 포함. 이메일은 샘플 도메인(example.com)을 사용.
- notifications: 마감·반복 알림이 실제로 의미 있을 때만 포함.
- 사용자 유형의 우선 기능과 실제 사용 이력을 근거로 항목을 선택합니다."""

FEW_SHOTS = [
    {
        "input": {
            "user_type": "대학생",
            "priority_features": ["task_create", "team_invite", "note_create"],
            "recent_activity": [{"feature": "task_create", "usage_count": 6}],
            "goal": "다음 주까지 팀플 발표 준비",
        },
        "output": {
            "tasks": [
                {"title": "자료 조사 범위 정리"},
                {"title": "슬라이드 초안 작성"},
                {"title": "발표 리허설 일정 잡기"},
            ],
            "team_invites": [
                {"email": "teammate1@example.com"},
                {"email": "teammate2@example.com"},
            ],
            "notifications": [],
        },
    },
    {
        "input": {
            "user_type": "프리랜서",
            "priority_features": ["task_create", "notification_rule", "note_create"],
            "recent_activity": [{"feature": "task_create", "usage_count": 12}],
            "goal": "다음 달 클라이언트 납품 3건 관리",
        },
        "output": {
            "tasks": [
                {"title": "클라이언트 A 중간 검수"},
                {"title": "클라이언트 B 초안 전달"},
                {"title": "클라이언트 C 최종 납품"},
            ],
            "team_invites": [],
            "notifications": [
                {"message": "각 납품 마감 D-2 자동 알림 설정"},
            ],
        },
    },
]


def _build_user_turn(user_type: str, priority_features: list[str], recent_activity: list[dict[str, Any]], goal: str) -> str:
    return json.dumps({
        "user_type": user_type,
        "priority_features": priority_features,
        "recent_activity": recent_activity,
        "goal": goal,
    }, ensure_ascii=False, indent=2)


def _build_prompt(user_type: str, priority_features: list[str], recent_activity: list[dict[str, Any]], goal: str) -> str:
    parts = [SYSTEM_INSTRUCTION, "\n--- 예시 ---"]
    for ex in FEW_SHOTS:
        parts.append("입력:\n" + json.dumps(ex["input"], ensure_ascii=False, indent=2))
        parts.append("출력:\n" + json.dumps(ex["output"], ensure_ascii=False, indent=2))
    parts.append("--- 실제 요청 ---")
    parts.append("입력:\n" + _build_user_turn(user_type, priority_features, recent_activity, goal))
    parts.append("출력:")
    return "\n".join(parts)


def generate_tasks(
    user_type: str,
    priority_features: list[str],
    recent_activity: list[dict[str, Any]],
    goal: str,
    model: str = "gemini-2.5-flash-lite",
    dry_run: bool = False,
) -> dict[str, Any]:
    if dry_run:
        return {
            "tasks": [{"title": f"[DRY] {goal} 관련 Task 1"}, {"title": f"[DRY] {goal} 관련 Task 2"}],
            "team_invites": [],
            "notifications": [{"message": f"[DRY] {goal} 관련 알림"}],
        }

    from google import genai
    from google.genai import types

    client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
    prompt = _build_prompt(user_type, priority_features, recent_activity, goal)
    resp = client.models.generate_content(
        model=model,
        contents=prompt,
        config=types.GenerateContentConfig(response_mime_type="application/json", temperature=0.4),
    )
    return json.loads(resp.text)


def post_mock(endpoint: str, payload: dict[str, Any]) -> None:
    print(f"  [MOCK POST] {endpoint}  {json.dumps(payload, ensure_ascii=False)}")


def log_event(user_id: int, user_type: str, endpoint: str, payload: dict[str, Any]) -> None:
    LOGS_DIR.mkdir(exist_ok=True)
    event = {
        "ts": datetime.now().isoformat(timespec="seconds"),
        "user_id": user_id,
        "user_type": user_type,
        "endpoint": endpoint,
        "payload": payload,
    }
    with EVENTS_LOG.open("a", encoding="utf-8") as f:
        f.write(json.dumps(event, ensure_ascii=False) + "\n")


def register(user_id: int, user_type: str, out: dict[str, Any], team_id: int = 12) -> None:
    for t in out.get("tasks", []):
        payload = {"user_id": user_id, "title": t["title"]}
        post_mock("/api/tasks", payload)
        log_event(user_id, user_type, "/api/tasks", payload)
    for inv in out.get("team_invites", []):
        payload = {"team_id": team_id, "email": inv["email"]}
        post_mock("/api/team/invite", payload)
        log_event(user_id, user_type, "/api/team/invite", payload)
    for n in out.get("notifications", []):
        payload = {"user_id": user_id, "message": n["message"]}
        post_mock("/api/notifications", payload)
        log_event(user_id, user_type, "/api/notifications", payload)


def feedback_summary() -> dict[str, Any]:
    """events.jsonl 집계 — Recommender 재학습 시그널 미리보기."""
    if not EVENTS_LOG.exists():
        return {"total_events": 0, "by_endpoint": {}, "by_user_type": {}}
    endpoint_counts: dict[str, int] = defaultdict(int)
    user_type_counts: dict[str, int] = defaultdict(int)
    total = 0
    with EVENTS_LOG.open(encoding="utf-8") as f:
        for line in f:
            e = json.loads(line)
            endpoint_counts[e["endpoint"]] += 1
            user_type_counts[e["user_type"]] += 1
            total += 1
    return {
        "total_events": total,
        "by_endpoint": dict(endpoint_counts),
        "by_user_type": dict(user_type_counts),
    }
