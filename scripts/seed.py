"""灌入示例题库。用法：python -m scripts.seed（在 ocs-qa-server 目录下）"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.store import repository as repo
from app.store.db import init_db
from app.store.models import AnswerSource, AnswerStatus

SEED = [
    # 单选
    {
        "question": "1+1 等于多少？",
        "type": "single",
        "options": ["1", "2", "3", "4"],
        "answer": "2",
    },
    # 单选（选项文字型）
    {
        "question": "计算机网络的主要功能是什么？",
        "type": "single",
        "options": ["资源共享", "数据通信", "分布式处理", "提高可靠性"],
        "answer": "资源共享",
    },
    # 多选（答案用 # 连接）
    {
        "question": "以下哪些属于面向对象的特征？",
        "type": "multiple",
        "options": ["封装", "继承", "多态", "编译"],
        "answer": "封装#继承#多态",
    },
    # 判断
    {
        "question": "地球是太阳系中距离太阳最近的行星。",
        "type": "judgement",
        "options": ["正确", "错误"],
        "answer": "错误",
    },
    # 填空
    {
        "question": "水的化学式是____。",
        "type": "completion",
        "options": [],
        "answer": "H2O",
    },
]


def main() -> None:
    init_db()
    for item in SEED:
        opts = item["options"]
        qkey = repo.compute_qkey(item["question"], opts, item["type"])
        repo.upsert_question(qkey, item["question"], repo.normalize(item["question"]), item["type"], opts)
        repo.upsert_answer(qkey, item["answer"], AnswerSource.STORE, AnswerStatus.TRUSTED, confidence=1.0)
        print(f"seeded [{item['type']}] {item['question']}  qkey={qkey[:12]}…")
    print(f"完成，题库题目数：{repo.count_questions()}")


if __name__ == "__main__":
    main()
