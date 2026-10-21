from __future__ import annotations

import html
import json
import zipfile
from pathlib import Path
from urllib.parse import quote

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill

from .common import atomic_write, elapsed, file_hash, inside, now, read_json, summary


def waiting_seconds(m):
    entries = [q for q in m["questions"].values()]
    entries += [prior for q in m["questions"].values() for prior in q.get("previous_answers", []) if prior.get("created_at")]
    intervals = sorted((q["created_at"], q.get("answered_at") or now()) for q in entries)
    merged = []
    for start, end in intervals:
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(end, merged[-1][1]))
        else:
            merged.append((start, end))
    return sum(elapsed(start, end) for start, end in merged)


def make_report(base, m):
    out = base / "reports"
    out.mkdir(parents=True, exist_ok=True)
    records = []
    for c in m["cases"].values():
        records.append({k: c.get(k) for k in ("case_id", "original_id", "title", "module", "priority",
                       "sheet", "rows", "stage", "work_status", "result", "stability", "pass_streak",
                       "flow_ids", "fixture_ids", "repair_rounds", "attempts", "feedback", "classification")})
        records[-1]["script"] = (c.get("registration") or {}).get("script")
    s = summary(m)
    metrics = {"elapsed_seconds": elapsed(m["created_at"]), "human_wait_seconds": waiting_seconds(m),
               "first_result_seconds": elapsed(m["created_at"], m["first_result_at"]) if m.get("first_result_at") else None,
               "first_pass_seconds": elapsed(m["created_at"], m["first_pass_at"]) if m.get("first_pass_at") else None,
               "exploration_seconds": sum(a["seconds"] for a in m["exploration"]),
               "exploration_attempts": len(m["exploration"]),
               "human_questions": len(m["questions"]),
               "cases_with_asset_reuse": sum(bool((c.get("registration") or {}).get("reused_assets")) for c in m["cases"].values()),
               "repair_rounds": sum(c["repair_rounds"] for c in m["cases"].values())}
    questions = [{k: q.get(k) for k in ("id", "kind", "subject", "prompt", "case_ids", "status", "attempted")}
                 for q in m["questions"].values()]
    payload = {"schema_version": "uia-results.v1", "run_id": m["run_id"], "generated_at": now(),
               "summary": s, "metrics": metrics, "source": m["sources"], "cases": records,
               "questions": questions, "unresolved_sheets": [x for src in m["sources"] for x in src.get("unresolved_sheets", [])],
               "source_update_required": m.get("source_update_required", False), "delivery_complete": False}
    diff = {"schema_version": "uia-asset-review.v1", "writeback": "not_applied", "cases": []}
    for c in m["cases"].values():
        if c.get("feedback"):
            file = inside(base, c["feedback"])
            diff["cases"].append({"case_id": c["case_id"], "review": c["feedback"],
                                  "sha256": file_hash(file), "content": read_json(file)})
    atomic_write(out / "asset-review.json", diff)
    atomic_write(out / "results.json", payload)
    wb = Workbook()
    sheet = wb.active
    sheet.title = "逐条结果"
    sheet.append(["用例ID", "原始ID", "工作表", "源行号", "标题", "优先级", "进度", "结果", "稳定性", "连续成功", "脚本", "执行次数", "最近证据"])
    for r in records:
        sheet.append([r["case_id"], r["original_id"], r["sheet"], ",".join(map(str, r["rows"])),
                      r["title"], r["priority"], r["work_status"], r["result"], r["stability"], r["pass_streak"],
                      r["script"], len(r["attempts"]), r["attempts"][-1]["evidence"] if r["attempts"] else ""])
    stats = wb.create_sheet("汇总")
    stats.append(["指标", "值"])
    for key, value in {**s, **metrics}.items():
        stats.append([key, json.dumps(value, ensure_ascii=False) if isinstance(value, dict) else value])
    qs = wb.create_sheet("人工问题")
    qs.append(["问题ID", "类型", "问题", "影响用例", "状态", "已尝试"])
    for q in questions:
        qs.append([q["id"], q["kind"], q["prompt"], ", ".join(q["case_ids"]), q["status"], "\n".join(q["attempted"])])
    for ws in wb:
        ws.freeze_panes = "A2"
        ws.auto_filter.ref = ws.dimensions
        for cell in ws[1]:
            cell.font = Font(color="FFFFFF", bold=True)
            cell.fill = PatternFill("solid", fgColor="23415A")
        for row in ws.iter_rows():
            for cell in row:
                # Source text must never become an executable spreadsheet formula.
                if isinstance(cell.value, str):
                    cell.data_type = "s"
                cell.alignment = Alignment(vertical="top", wrap_text=True)
        for col in ws.columns:
            ws.column_dimensions[col[0].column_letter].width = min(64, max(14, max(len(str(c.value or "")) for c in col[:100]) + 2))
    wb.save(out / "results.xlsx")
    escape = lambda value: html.escape(str(value if value is not None else ""))
    def link(ref):
        if not ref:
            return ""
        return '<a href="../' + quote(str(ref), safe="/") + '">' + escape(ref) + '</a>'
    rows = []
    for r in records:
        source = escape(r["sheet"]) + ":" + escape(",".join(map(str, r["rows"])))
        rows.append("<tr>" + "".join("<td>" + x + "</td>" for x in [escape(r["case_id"]), source, escape(r["title"]),
                    escape(r["work_status"]), escape(r["result"]), escape(r["stability"]), str(r["pass_streak"]),
                    link(r["script"]), link(r["attempts"][-1]["evidence"] if r["attempts"] else None)]) + "</tr>")
    body = """<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width">
<title>UI 自动化结果</title><style>body{font:15px system-ui;margin:32px;color:#193348;background:#f5f8fb}
table{border-collapse:collapse;width:100%;background:white}th,td{padding:10px;text-align:left;border:1px solid #dbe4eb;vertical-align:top}
th{background:#23415a;color:white}a{color:#0069a3}pre{white-space:pre-wrap}section{overflow:auto}input{padding:10px;min-width:260px;margin:12px 0}</style>
<h1>UI 自动化结果</h1>"""
    body += "<p>运行：" + escape(m["run_id"]) + "；源用例总数：" + str(s["total"]) + "。稳定标准：同一版本独立运行两次成功。</p>"
    body += "<p>执行覆盖率：{:.1%}；已执行用例通过率：{:.1%}；全部用例稳定率：{:.1%}。</p>".format(s["execution_coverage"], s["pass_rate"], s["stability_rate"])
    body += '<p><a href="results.json">JSON</a> · <a href="results.xlsx">Excel</a> · <a href="scripts.zip">脚本工程</a> · <a href="asset-review.json">资产回写候选</a></p>'
    body += '<label>筛选 <input id="filter" placeholder="用例 ID、标题或状态"></label><section><table><thead><tr>'
    body += "".join("<th>" + h + "</th>" for h in ("用例ID", "来源", "标题", "进度", "结果", "稳定性", "连续成功", "脚本", "证据"))
    body += "</tr></thead><tbody>" + "".join(rows) + "</tbody></table></section><h2>耗时与人工问题</h2><pre>"
    body += escape(json.dumps({"metrics": metrics, "questions": questions}, ensure_ascii=False, indent=2)) + "</pre>"
    body += '<script>document.getElementById("filter").addEventListener("input",e=>document.querySelectorAll("tbody tr").forEach(r=>r.hidden=!r.textContent.toLowerCase().includes(e.target.value.toLowerCase())))</script></html>'
    (out / "index.html").write_text(body, encoding="utf-8")
    runner = base / "runner"
    script_package = None
    if runner.exists():
        with zipfile.ZipFile(out / "scripts.zip", "w", compression=zipfile.ZIP_DEFLATED) as archive:
            protected = {Path(m["config_path"]).resolve()}
            if m["config"].get("auth", {}).get("storage_state"):
                protected.add(Path(m["config"]["auth"]["storage_state"]).resolve())
            for file in runner.rglob("*"):
                rel = file.relative_to(runner)
                if not file.is_file() or file.is_symlink() or file.resolve() in protected or any(part in {"node_modules", "results", ".auth", "test-results", "playwright-report"} for part in rel.parts):
                    continue
                if file.name.startswith(".env") or file.name in {"auth.json", "storage-state.json"} or ".local." in file.name:
                    continue
                if file.suffix in {".ts", ".js", ".mjs", ".json", ".md"}:
                    archive.write(file, "runner/" + str(rel))
        script_package = str((out / "scripts.zip").relative_to(base))
    m["delivery"] = {"json": str((out / "results.json").relative_to(base)),
                     "html": str((out / "index.html").relative_to(base)),
                     "xlsx": str((out / "results.xlsx").relative_to(base)),
                     "asset_diff": str((out / "asset-review.json").relative_to(base)),
                     "scripts": script_package, "generated_at": now()}
    payload["delivery_complete"] = (bool(records) and all(c["work_status"] == "finished" for c in m["cases"].values())
                                    and not payload["unresolved_sheets"] and bool(script_package)
                                    and not payload["source_update_required"]
                                    and not any(q["status"] == "open" for q in m["questions"].values())
                                    and all(c.get("feedback") for c in m["cases"].values() if c.get("result") == "passed"))
    atomic_write(out / "results.json", payload)
    return {"artifacts": m["delivery"], "summary": s, "delivery_complete": payload["delivery_complete"]}
