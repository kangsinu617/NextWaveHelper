"""4개 사용자 유형 end-to-end 시연 (공모서 시나리오 자동 재현).

공모서 3.2 (유형별 end-to-end 시나리오)에 대응:
  A. 대학생     - user_id=101 - "다음 주까지 팀플 발표 준비"
  B. 직장인     - user_id=102 - "이번 주 업무 정리 & 회의 준비"
  C. 프리랜서   - user_id=107 - "다음 달 클라이언트 납품 3건 관리"
  D. 팀 사용자  - user_id=105 - "신규 프로젝트 킥오프 준비"

실행:
  python3 -m prototype.tests          # 실제 Gemini 호출
  python3 -m prototype.tests --dry-run
"""

from __future__ import annotations

import argparse
import json
import sys
import time

from src.core import (
    generate_tasks,
    load_feature_usage_logs,
    load_user_segment,
    profile_user,
    recommend,
    register,
    user_recent_activity,
)

SCENARIOS = [
    ("A. 대학생",    101, "다음 주까지 팀플 발표 준비"),
    ("B. 직장인",    102, "이번 주 업무 정리 & 회의 준비"),
    ("C. 프리랜서",  107, "다음 달 클라이언트 납품 3건 관리"),
    ("D. 팀 사용자", 105, "신규 프로젝트 킥오프 준비"),
]


def run_one(label: str, user_id: int, goal: str, dry_run: bool) -> dict:
    segment = load_user_segment()
    logs = load_feature_usage_logs()
    user_type = profile_user(user_id, segment)
    features = recommend(user_type, logs, segment)
    recent = user_recent_activity(user_id, logs)

    print(f"\n{'=' * 72}")
    print(f"{label}  user_id={user_id}  user_type={user_type}")
    print(f"  priority_features={features}")
    print(f"  recent_activity={recent}")
    print(f"  goal=\"{goal}\"")
    print(f"{'-' * 72}")

    start = time.time()
    out = generate_tasks(user_type, features, recent, goal, dry_run=dry_run)
    elapsed = time.time() - start

    print(f"LLM 출력 (경과 {elapsed:.2f}s):")
    print(json.dumps(out, ensure_ascii=False, indent=2))
    print(f"\nMock API 호출:")
    register(user_id, user_type, out)

    return {
        "label": label,
        "user_id": user_id,
        "user_type": user_type,
        "tasks": len(out.get("tasks", [])),
        "team_invites": len(out.get("team_invites", [])),
        "notifications": len(out.get("notifications", [])),
        "elapsed_s": round(elapsed, 2),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    summary = [run_one(label, uid, goal, args.dry_run) for label, uid, goal in SCENARIOS]

    print(f"\n\n{'=' * 72}")
    print("요약 (4개 유형 × 1회 시연)")
    print(f"{'=' * 72}")
    print(f"{'label':<15} {'user_id':>8} {'type':<10} {'tasks':>6} {'invites':>8} {'notifs':>7} {'time':>7}")
    for r in summary:
        print(f"{r['label']:<15} {r['user_id']:>8} {r['user_type']:<10} "
              f"{r['tasks']:>6} {r['team_invites']:>8} {r['notifications']:>7} {r['elapsed_s']:>6.2f}s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
