"""NextSync Guide CLI.

예:
  python3 -m prototype.cli --user-id 105 --goal "신규 프로젝트 킥오프 준비"
  python3 -m prototype.cli --user-id 107 --goal "클라이언트 납품 관리"
  python3 -m prototype.cli --user-id 999 --user-type 대학생 --goal "기말 과제 정리"  # 신규 사용자
  python3 -m prototype.cli --dry-run
"""

from __future__ import annotations

import argparse
import json
import sys

from src.core import (
    USER_TYPES,
    generate_tasks,
    load_feature_usage_logs,
    load_user_segment,
    profile_user,
    recommend,
    register,
    user_recent_activity,
)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--user-id", type=int, default=105)
    ap.add_argument("--user-type", choices=USER_TYPES, help="신규 사용자(미등록)일 때 유형 직접 지정")
    ap.add_argument("--goal", default="신규 프로젝트 킥오프 준비")
    ap.add_argument("--model", default="gemini-2.5-flash-lite")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    segment = load_user_segment()
    logs = load_feature_usage_logs()

    user_type = args.user_type or profile_user(args.user_id, segment)
    features = recommend(user_type, logs, segment)
    recent = user_recent_activity(args.user_id, logs)

    print(f"\n=== NextSync Guide ===")
    print(f"[Step 1] Profile    user_id={args.user_id}, user_type={user_type}")
    print(f"[Step 2] Recommend  priority_features={features}")
    print(f"         recent_activity={recent}")
    print(f"[Step 3] Act        goal=\"{args.goal}\"  (model={args.model})")

    out = generate_tasks(user_type, features, recent, args.goal, model=args.model, dry_run=args.dry_run)
    print(f"  LLM 출력:\n{json.dumps(out, ensure_ascii=False, indent=2)}")

    print(f"[Step 4] Register NextWave API 호출")
    register(args.user_id, user_type, out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
