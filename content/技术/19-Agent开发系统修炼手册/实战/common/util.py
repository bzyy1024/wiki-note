"""
common/util.py — 各 lab 共用的小工具
"""


def print_step(record):
    """run_loop 的 on_step 回调：把每一步的轨迹打印成可读日志。"""
    s = record.get("step", "?")
    if record.get("tool_calls"):
        for name, args in record["tool_calls"]:
            print(f"  [{s}] think 模型要求调用: {name}({args})")
    elif record.get("tool_result"):
        print(f"  [{s}] act   工具结果: {record['tool_result']}")
    elif record.get("content"):
        print(f"  [{s}] think 模型说: {record['content']}")


def banner(title: str):
    print(f"\n{'='*60}\n  {title}\n{'='*60}")
