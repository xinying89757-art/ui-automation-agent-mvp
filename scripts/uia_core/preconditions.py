"""One consolidated human-precondition checklist. Unmet items wait; they are not marked unsuitable."""
from __future__ import annotations

from .common import digest, now, read_json

def vocabulary():
    from .common import ROOT, read_yaml
    path = ROOT / "preconditions.yaml"
    if not path.is_file():
        from pathlib import Path
        path = Path(__file__).resolve().parents[2] / "preconditions.yaml"
    return read_yaml(path)["preconditions"]


def local_env(spec):
    verbs = {step.get('verb') for step in spec.get('steps', [])}
    supplied = ({'public_frontend'} if 'defer_public' in verbs else set()) | ({'delayed_save'} if 'network_delay' in verbs else set())
    return [item for item in spec.get('required_env', []) if item not in supplied]


def labels():
    return {key: value["label"] for key, value in vocabulary().items()}


QUESTION_KEY = digest(["preconditions", "run-preconditions"])[:16]


def derive_items(text):
    blob = text or ""
    found = [item_id for item_id, entry in vocabulary().items() if any(needle in blob for needle in entry.get("match", []))]
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
        unanswered_business = any(cid in row["case_ids"] and not (answer.get("business") or {}).get(row["question"])
                                  for row in question.get("business_questions", []))
        if unanswered_business or any(item in unavailable for item in items) or any(item not in available for item in items):
            case.update(result=None, work_status="waiting_human", stability="not_run",
                        classification={"reason": "等待人工前置：" + "、".join(labels().get(item, item) for item in items),
                                        "at": now()})
        elif case["work_status"] != "finished":
            case["work_status"] = "runnable" if case.get("registration") and case.get("stage") == "execution" else "pending"
            case["classification"] = {"reason": "前置条件已确认可用", "at": now()}


def sync_preconditions(base, m):
    if m.get("interaction_mode") == "once":
        from .experience import sync_checklist
        return sync_checklist(base, m)
    from .workflow import question
    grouped = {}
    affected = []
    for cid, case in m["cases"].items():
        items = derive_items(case_text(base, case))
        spec_path = base / case.get("case_spec", "__missing__")
        if spec_path.is_file():
            from .common import read_yaml
            items = local_env(read_yaml(spec_path))
        case["precondition_items"] = items
        if not items or _protected(case):
            continue
        grouped[cid] = items
        affected.append(cid)
        label_text = "、".join(labels().get(item, item) for item in items)
        case.update(result=None, stability="not_run", work_status="pending",
                    stage=case["stage"] if case.get("stage") not in {None, "finished"} else "discovery",
                    classification={"reason": "等待人工前置：" + label_text, "at": now()})
    if not affected:
        return {"question_id": None, "cases": [], "items": []}
    lines = []
    present = []
    for item_id, entry in vocabulary().items():
        label = entry["label"]
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
