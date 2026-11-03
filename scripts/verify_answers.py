"""候选答案验证/转正工具。

规则（可调）：
- 若某候选答案与题库中已有 trusted 答案文本一致 -> 合并/维持 trusted。
- 若同 qkey 下同一候选答案出现次数 >= 阈值（默认 2，可用 --min-hits）-> 转正 trusted。
- 其余保持 candidate，冲突项标记 conflict。

用法：python -m scripts.verify_answers [--min-hits 2] [--dry-run]
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.store import repository as repo
from app.store.db import get_conn, init_db


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--min-hits", type=int, default=2)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    init_db()
    conn = get_conn()
    qkeys = [r["qkey"] for r in conn.execute("SELECT DISTINCT qkey FROM answers").fetchall()]
    promoted = 0
    for qkey in qkeys:
        answers = repo.list_answers(qkey)
        trusted = [a for a in answers if a.status.value == "trusted"]
        for a in answers:
            if a.status.value != "candidate":
                continue
            # 与已有 trusted 文本一致 -> 合并
            if any(t.answer.strip() == a.answer.strip() for t in trusted):
                print(f"[merge] {qkey[:10]}… candidate 合并入 trusted: {a.answer[:30]}")
                if not args.dry_run:
                    repo.promote_answer(a.id)
                promoted += 1
                continue
            # 出现次数达阈值 -> 转正
            if a.hit_count + 1 >= args.min_hits:
                print(f"[promote] {qkey[:10]}… hits={a.hit_count} 转正: {a.answer[:30]}")
                if not args.dry_run:
                    repo.promote_answer(a.id)
                promoted += 1
            else:
                print(f"[keep] {qkey[:10]}… 保持候选(需更多验证): {a.answer[:30]}")
    print(f"\n处理完成，转正/合并 {promoted} 条{' (dry-run 未写入)' if args.dry_run else ''}")


if __name__ == "__main__":
    main()
