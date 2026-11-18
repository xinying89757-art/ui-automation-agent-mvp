"""Representative smoke gate and the first-result stop rule for `uia go`."""
from __future__ import annotations

from .common import elapsed, event, now

_PRIORITY = {"P0": 0, "P1": 1, "P2": 2, "P3": 3}


def pick_smoke_cases(cases, size=3):
    """Pick up to `size` cases, preferring different modules and higher priority."""
    rows = []
    for cid, case in cases.items():
        priority = _PRIORITY.get(str(case.get("priority") or "P9").upper(), 9)
        module = str(case.get("module") or case.get("sheet") or "")
        rows.append((priority, module, str(cid), cid))
    rows.sort()
    picked, seen = [], set()
    for _priority, module, _sort_id, cid in rows:
        if module in seen:
            continue
        seen.add(module)
        picked.append(cid)
        if len(picked) >= size:
            return picked
    for _priority, _module, _sort_id, cid in rows:
        if cid not in picked:
            picked.append(cid)
        if len(picked) >= size:
            break
    return picked


def _scope_ids(m):
    selected = m.get("selected_cases")
    if selected:
        return [cid for cid in selected if cid in m.get("cases", {})]
    return list(m.get("cases", {}))


def plan_smoke(m, size, bar):
    """Attach a stable smoke plan. Batches no larger than the smoke stay a single run."""
    existing = m.get("smoke_plan") or {}
    if existing.get("status") == "passed" and existing.get("cases"):
        existing["bar"] = bar
        m["smoke_plan"] = existing
        return existing
    if existing.get("status") == "failed" and existing.get("cases"):
        return existing
    ids = _scope_ids(m)
    if existing.get("cases") and existing.get("size") == size and existing.get("bar") == bar and existing.get("status") == "pending":
        return existing
    if len(ids) <= size:
        plan = {"status": "skipped", "reason": "batch_not_larger_than_smoke", "cases": ids, "size": size, "bar": bar}
    else:
        subset = {cid: m["cases"][cid] for cid in ids}
        plan = {"status": "pending", "cases": pick_smoke_cases(subset, size), "size": size, "bar": bar}
    m["smoke_plan"] = plan
    return plan


def abort_reason(m):
    """Stop once case execution has run longer than the first-result budget without a timely result.

    The clock starts when execution starts, so an open checklist does not consume it.
    A first result that already arrived inside the budget does not abort the rest of the run.
    """
    current = m.get("abort")
    if current and current.get("reason") != "first_result_exceeded":
        return current
    limit = m.get("max_first_result_minutes")
    start = m.get("execution_started_at")
    if not limit or not start:
        return None

    def trip(elapsed_s):
        if (m.get("abort") or {}).get("reason") != "first_result_exceeded":
            event(m, "run_aborted", reason="first_result_exceeded", elapsed_seconds=elapsed_s)
        m["abort"] = {"reason": "first_result_exceeded", "limit_minutes": limit,
                      "elapsed_seconds": elapsed_s, "at": (m.get("abort") or {}).get("at") or now()}
        return m["abort"]

    limit_seconds = float(limit) * 60
    first = m.get("first_result_at")
    if first and first >= start:
        elapsed_s = elapsed(start, first)
        if elapsed_s > limit_seconds:
            return trip(elapsed_s)
        m.pop("abort", None)
        return None
    if first and first < start:
        m.pop("abort", None)
        return None
    elapsed_s = elapsed(start)
    if elapsed_s > limit_seconds:
        return trip(elapsed_s)
    m.pop("abort", None)
    return None


def update_smoke(m):
    """Close the smoke gate once every executable smoke case has a result."""
    plan = m.get("smoke_plan") or {}
    if plan.get("status") != "pending":
        if plan.get("status") == "failed" and (m.get("abort") or {}).get("reason") != "smoke_below_bar":
            m["abort"] = {"reason": "smoke_below_bar", "bar": plan.get("bar"),
                          "pass_rate": plan.get("pass_rate"), "cases": plan.get("cases"), "at": now()}
        return plan
    outcomes = []
    for cid in plan.get("cases") or []:
        result = (m.get("cases") or {}).get(cid, {}).get("result")
        if result is None:
            return plan
        if result == "not_suitable":
            continue
        outcomes.append(result == "passed")
    if not outcomes:
        plan["status"] = "skipped"
        plan["reason"] = "no_executable_smoke_cases"
        return plan
    rate = sum(outcomes) / len(outcomes)
    plan.update(pass_rate=rate, executed=len(outcomes), passed=sum(outcomes))
    if rate + 1e-9 >= float(plan.get("bar", 1)):
        plan["status"] = "passed"
        event(m, "smoke_passed", pass_rate=rate, cases=plan.get("cases"))
    else:
        plan["status"] = "failed"
        m["abort"] = {"reason": "smoke_below_bar", "bar": plan.get("bar"), "pass_rate": rate,
                      "cases": plan.get("cases"), "at": now()}
        event(m, "smoke_failed", pass_rate=rate, bar=plan.get("bar"), cases=plan.get("cases"))
    return plan


def allowed_cases(m, ready):
    """Smoke-pending runs may execute only the representative cases. An abort executes nothing."""
    if abort_reason(m):
        return []
    plan = m.get("smoke_plan") or {}
    status = plan.get("status")
    if status in {None, "skipped", "passed"}:
        return list(ready)
    if status == "failed":
        return []
    smoke = set(plan.get("cases") or [])
    return [cid for cid in ready if cid in smoke]
