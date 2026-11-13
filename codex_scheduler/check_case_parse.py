#!/usr/bin/env python3
"""检查 deviceCheck 项目能否完整解析指定 xlsx 测试用例。

判定标准：case_workbook.read() 不抛异常，且 case_runner.preview() 返回
selected > 0 且 pending == 0（所有筛选出的用例都 ready）。

输出：解析报告 JSON（stdout + 落盘 parse_report.json）
退出码：0 = 全部解析成功；1 = 存在失败/异常
"""
import json
import os
import sys

PROJECT_DIR = "/Users/apple/Documents/deviceCheck"
XLSX_PATH = "/Users/apple/Downloads/App与H5全功能多语言测试用例.xlsx"
OUT_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "parse_report.json")

sys.path.insert(0, PROJECT_DIR)

import case_runner  # noqa: E402
import case_workbook  # noqa: E402


def main():
    report = {"ok": False, "xlsx": XLSX_PATH}
    try:
        book = case_workbook.read(XLSX_PATH)
        report["summary"] = case_workbook.summary(book)
        preview = case_runner.preview(book, {})
        report["selected"] = preview.get("selected", 0)
        report["ready"] = preview.get("ready", 0)
        report["pending"] = preview.get("pending", 0)
        report["excluded"] = preview.get("excluded", [])
        failures = []
        for case in preview.get("cases", []):
            if not case.get("ready"):
                failures.append({
                    "id": case.get("id"),
                    "title": case.get("title"),
                    "reason": case.get("reason") or case.get("partial_reason") or "未知原因",
                })
        report["failures"] = failures
        report["failures"] = failures[:200]
        report["ok"] = report["pending"] == 0 and report["selected"] > 0
    except Exception as exc:  # noqa: BLE001
        report["error"] = "{}: {}".format(type(exc).__name__, exc)

    with open(OUT_PATH, "w", encoding="utf-8") as fh:
        json.dump(report, fh, ensure_ascii=False, indent=2)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    sys.exit(0 if report["ok"] else 1)


if __name__ == "__main__":
    main()
