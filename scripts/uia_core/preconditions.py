"""One consolidated human-precondition checklist. Unmet items wait; they are not marked unsuitable."""
from __future__ import annotations

from .common import digest, now, read_json

ITEMS = (
    ("no_settings_permission", "无网站设置权限的账号", ("不具备当前站点的网站设置", "无网站设置权限", "没有网站设置")),
    ("editor_4_0", "4.0 编辑器", ("4.0编辑器", "4.0 编辑器")),
    ("fresh_unconfigured_site", "从未配置过的新站点", ("尚未修改过", "新站点首次", "从未配置")),
    ("simplified_chinese_site", "简体中文站点", ("简体中文站点",)),
    ("multi_language_site", "多语言或小语种站点", ("小语种", "简站", "专站")),
    ("existing_root_llms", "根目录已有 llms.txt", ("根目录已有", "根目录有客户上传", "根目录已存在")),
    ("unmigrated_site", "未迁移的存量站点", ("上线前", "存量迁移")),
)
LABELS = {item_id: label for item_id, label, _needles in ITEMS}
QUESTION_KEY = digest(["preconditions", "run-preconditions"])[:16]


def derive_items(text):
    blob = text or ""
    found = [item_id for item_id, _label, needles in ITEMS if any(needle in blob for needle in needles)]
    return found


def case_text(base, case):
    source = case.get("source")
    if not source:
        return case.get("title") or ""
    try:
        raw = read_json(base / source)
    except (OSError, ValueError):
        return case.get("title") or ""
    return "\n".join([raw.get("title") or "", raw.get("preconditions") or ""])


def _protected(case):
    if case.get("result") in {"passed", "business_failure", "automation_failure", "interrupted"}:
        return True
    return any(attempt.get("result") == "passed" for attempt in case.get("attempts") or [])


def apply_precondition_answer(m, question):
    """Unavailable items stay waiting with a null result. Available items resume."""
    answer = question.get("answer") if isinstance(question.get("answer"), dict) else {}
    available = set(answer.get("available") or [])
    unavailable = set(answer.get("unavailable") or [])
    for cid in question.get("case_ids") or []:
        case = m["cases"].get(cid)
        if not case or _protected(case):
            continue
        items = case.get("precondition_items") or []
        if any(item in unavailable for item in items) or any(item not in available for item in items):
            case.update(result=None, work_status="waiting_human", stability="not_run",
                        classification={"reason": "等待人工前置：" + "、".join(LABELS.get(item, item) for item in items),
                                        "at": now()})
        elif case["work_status"] != "finished":
            case["work_status"] = "runnable" if case.get("registration") and case.get("stage") == "execution" else "pending"
            case["classification"] = {"reason": "前置条件已确认可用", "at": now()}


def sync_preconditions(base, m):
    from .workflow import question
    grouped = {}
    affected = []
    for cid, case in m["cases"].items():
        items = derive_items(case_text(base, case))
        case["precondition_items"] = items
        if not items or _protected(case):
            continue
        grouped[cid] = items
        affected.append(cid)
        labels = "、".join(LABELS.get(item, item) for item in items)
        case.update(result=None, stability="not_run", work_status="pending",
                    stage=case["stage"] if case.get("stage") not in {None, "finished"} else "discovery",
                    classification={"reason": "等待人工前置：" + labels, "at": now()})
    if not affected:
        return {"question_id": None, "cases": [], "items": []}
    lines = []
    present = []
    for item_id, label, _needles in ITEMS:
        owners = [cid for cid, items in grouped.items() if item_id in items]
        if not owners:
            continue
        present.append(item_id)
        lines.append("- {0} ({1}): {2}".format(item_id, label, ", ".join(owners)))
    prompt = (
        "执行前请一次确认这些人工前置。数据类前置（FAQ 条数、产品分类、导航、首页 Meta、网站简称、快速联系、社媒）由自动化自行准备，不要标成不适合。\n"
        "回答 JSON：{{\"available\":[\"item\"],\"unavailable\":[\"item\"]}}。unavailable 的用例继续等待，不会记为 not_suitable。\n"
        + "\n".join(lines)
    )
    existing = m["questions"].get(QUESTION_KEY)
    if existing and existing.get("status") == "answered":
        for cid in affected:
            if cid not in existing["case_ids"]:
                existing["case_ids"].append(cid)
        apply_precondition_answer(m, existing)
        return {"question_id": existing["id"], "status": "answered", "cases": affected, "items": present}
    queued = question(m, "preconditions", "run-preconditions", prompt, affected, key=QUESTION_KEY, attempted=present)
    queued["prompt"] = prompt
    queued["checklist"] = present
    return {"question_id": queued["id"], "status": queued["status"], "cases": affected, "items": present}
