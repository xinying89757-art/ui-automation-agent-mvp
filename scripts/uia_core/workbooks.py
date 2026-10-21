from __future__ import annotations

import collections
import datetime as dt
import re
from pathlib import Path

from openpyxl import load_workbook
from openpyxl.utils import column_index_from_string

from .common import digest, require, safe_id

ALIASES = {
    "id": ["用例编号", "用例ID", "测试用例编号", "caseid", "编号"],
    "title": ["用例名称", "用例标题", "用例描述", "测试用例", "测试点", "标题", "title", "name"],
    "module": ["所属模块", "功能模块", "模块", "module"],
    "priority": ["优先级", "用例级别", "用例等级", "等级", "priority"],
    "preconditions": ["前置条件", "前提条件", "预置条件", "preconditions"],
    "steps": ["操作步骤", "测试步骤", "执行步骤", "步骤", "steps"],
    "expected": ["预期结果", "期望结果", "预期", "expected", "expectedresult"],
    "data": ["测试数据", "输入数据", "data"],
    "cleanup": ["清理步骤", "后置条件", "数据清理", "cleanup"],
}
SUPPLEMENTAL = {"需求覆盖", "待产品确认", "覆盖矩阵", "说明", "填写说明"}


def text(value):
    if value is None:
        return ""
    if isinstance(value, (dt.date, dt.datetime)):
        return value.isoformat()
    return str(value)


def header_token(value):
    return re.sub(r"[\s_\-:：()（）]+", "", text(value)).casefold()


def find_header(ws, override=None):
    override = override or {}
    if override.get("ignore"):
        return None, {}, []
    if override.get("columns"):
        row = int(override.get("header_row", 1))
        columns = {k: column_index_from_string(v) if isinstance(v, str) else int(v)
                   for k, v in override["columns"].items()}
        require(all(k in ALIASES for k in columns), "Unknown column mapping field")
        require(all(v > 0 for v in columns.values()) and row > 0, "Columns/rows start at one")
        require(len(set(columns.values())) == len(columns), "One column cannot serve two fields")
        missing = [k for k in ("title", "steps", "expected") if k not in columns]
        return row, columns, ["Missing mapped fields: " + ", ".join(missing)] if missing else []
    best = (0, None, {}, [])
    for row in ws.iter_rows(min_row=1, max_row=min(ws.max_row, 40)):
        matches = collections.defaultdict(list)
        for cell in row:
            token = header_token(cell.value)
            for field, aliases in ALIASES.items():
                if token and token in {header_token(a) for a in aliases}:
                    matches[field].append(cell.column)
        score = len(matches)
        if score > best[0]:
            errors = ["Ambiguous columns for " + k for k, v in matches.items() if len(v) > 1]
            cols = {k: v[0] for k, v in matches.items() if len(v) == 1}
            best = (score, row[0].row, cols, errors)
    _, row, columns, errors = best
    missing = [k for k in ("title", "steps", "expected") if k not in columns]
    if missing:
        errors = errors + ["Cannot identify " + ", ".join(missing)]
    return row, columns, errors


def extract(path, mappings=None):
    """Read all source cases; never evaluate formulas or modify the workbook."""
    path = Path(path)
    require(path.suffix.lower() in {".xlsx", ".xlsm"}, "Use XLSX/XLSM; convert legacy XLS first")
    wb = load_workbook(path, data_only=False, read_only=False, keep_links=False)
    cases, sheets, gaps = [], [], []
    try:
        for ws in wb.worksheets:
            override = (mappings or {}).get(ws.title, {})
            if override.get("ignore") or (ws.title in SUPPLEMENTAL and not override):
                sheets.append({"sheet": ws.title, "ignored": True, "reason": "supplemental_or_explicit"})
                continue
            if not any(c.value is not None for row in ws for c in row):
                sheets.append({"sheet": ws.title, "ignored": True, "reason": "empty"})
                continue
            header, columns, errors = find_header(ws, override)
            sheets.append({"sheet": ws.title, "header_row": header, "columns": columns,
                           "errors": errors})
            if errors:
                gaps.append({"sheet": ws.title, "kind": "column_mapping", "errors": errors,
                             "prompt": "Confirm header_row and columns, or explicitly ignore this sheet."})
                continue
            merged = {}
            for area in ws.merged_cells.ranges:
                # Do not propagate action/expectation/data blanks into negative test inputs.
                for field in ("id", "title", "module", "priority", "preconditions"):
                    col = columns.get(field)
                    if col and area.min_col <= col <= area.max_col:
                        for row in range(area.min_row, area.max_row + 1):
                            merged[(row, col)] = ws.cell(area.min_row, area.min_col).value
            current = None
            for row in range(header + 1, ws.max_row + 1):
                values = {k: text(merged.get((row, col), ws.cell(row, col).value))
                          for k, col in columns.items()}
                if not any(v.strip() for v in values.values()):
                    current = None
                    continue
                # Repeated headers in printed workbooks are not source cases.
                if header_token(values.get("title")) in {header_token(a) for a in ALIASES["title"]} and \
                        header_token(values.get("steps")) in {header_token(a) for a in ALIASES["steps"]}:
                    current = None
                    continue
                cid, title = values.get("id", "").strip(), values.get("title", "").strip()
                continuation = current is not None and (
                    (not title and (not cid or cid == current["original_id"])) or
                    (cid and cid == current["original_id"] and title == current["title"]))
                if not continuation:
                    current = {"original_id": cid, "title": title, "sheet": ws.title,
                               "module": values.get("module", ""), "priority": values.get("priority", "") or "P2",
                               "preconditions": values.get("preconditions", ""), "rows": [], "records": []}
                    cases.append(current)
                current["rows"].append(row)
                current["records"].append({"row": row, "values": values,
                                           "cells": {k: ws.cell(row, c).coordinate for k, c in columns.items()}})
                for field in ("steps", "expected", "data", "cleanup"):
                    if field in values:
                        current.setdefault(field, []).append(values[field])
            # Blank business fields stay explicit; the preparation skill resolves intent.
        duplicates = collections.Counter(c["original_id"] for c in cases if c["original_id"])
        occurrences = collections.Counter()
        for c in cases:
            identity = {"sheet": c["sheet"], "original_id": c["original_id"]}
            if not c["original_id"]:
                identity.update(title=c["title"], steps=c.get("steps"), expected=c.get("expected"))
            key = digest(identity)
            occurrences[key] += 1
            c["identity_key"] = key + ":" + str(occurrences[key])
            c["suggested_id"] = ((safe_id(c["original_id"]) + ("--" + key[:8] if duplicates[c["original_id"]] > 1 else ""))
                                 if c["original_id"] else "AUTO-" + key[:12])
            if occurrences[key] > 1:
                c["suggested_id"] += "-" + str(occurrences[key])
            business = {k: c.get(k) for k in ("title", "module", "priority", "preconditions", "steps", "expected", "data", "cleanup")}
            c["content_hash"] = digest(business)
        return {"cases": cases, "sheets": sheets, "gaps": gaps}
    finally:
        wb.close()
