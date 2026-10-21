from __future__ import annotations

import re
from pathlib import Path

from .common import ROOT, atomic_write, digest, file_hash, read_json, read_yaml


def terms(value):
    raw = str(value).lower()
    words = set(re.findall(r"[a-z0-9]+", raw))
    for chinese in re.findall(r"[\u4e00-\u9fff]+", raw):
        words.add(chinese)
        words.update(chinese[i:i + 2] for i in range(len(chinese) - 1))
    return words


def catalog():
    assets = {}
    for file in (ROOT / "automation-assets").glob("*.yaml"):
        for asset in read_yaml(file).get("assets", []):
            assets[asset.get("id", asset.get("asset_id"))] = asset
    index = read_yaml(ROOT / "automation-assets/match-index.yaml").get("entries", [])
    return assets, index


def source_file(asset, cfg):
    name = asset.get("source_file", "")
    if not name:
        return None
    for root in [str(ROOT)] + cfg.get("source_roots", []):
        p = (Path(root) / name).resolve()
        if p.is_file():
            return p
    return None


def bounds_known(asset):
    for field in ("dependencies", "requires", "preconditions"):
        bound = asset.get(field, {})
        if bound.get("status") not in {"KNOWN", "NONE"}:
            return False
        if bound.get("completeness") in {"PARTIAL", "UNKNOWN"}:
            return False
    return True


def verified_direct(asset, cfg, proof, base=None):
    src = source_file(asset, cfg)
    if not src or not bounds_known(asset) or asset.get("blocking_risks"):
        return False
    if asset.get("reuse_readiness") in {"DO_NOT_REUSE", "REFERENCE_ONLY"}:
        return False
    return bool(proof and proof.get("exported") is True and proof.get("signature") and
                proof.get("source_sha256") == file_hash(src) and
                proof.get("target_fingerprint") == digest(cfg.get("targets", {})) and
                proof.get("evidence") and (Path(base or ROOT) / proof["evidence"]).is_file())


def make_plan(intent_path, cfg, proofs=None):
    intent = read_yaml(intent_path)["intent"]
    assets, index = catalog()
    proofs = proofs or {}
    capabilities = []
    for cap in intent.get("required_capabilities", []):
        query = terms([cap.get("capability"), cap.get("semantic_name"), cap.get("description"), cap.get("name")])
        ranked = []
        for entry in index:
            asset = assets.get(entry.get("asset_id"))
            if not asset or entry.get("reuse_readiness") == "DO_NOT_REUSE":
                continue
            words = terms([entry.get(k) for k in ("name", "business_terms", "capability", "match_keys", "semantic_tags", "aliases")])
            score = len(words & query) / max(1, len(query))
            if score >= 0.2:
                src = source_file(asset, cfg)
                ranked.append({"asset_id": entry["asset_id"], "score": round(score, 3),
                               "source_available": bool(src), "bounds_known": bounds_known(asset),
                               "symbol": asset.get("symbol"),
                               "reuse_readiness": asset.get("reuse_readiness"),
                               "blocking_risks": asset.get("blocking_risks", [])})
        ranked.sort(key=lambda item: (-item["score"], item["asset_id"]))
        unknowns = list(dict.fromkeys(cap.get("runtime_unknown_refs", []) +
                        [ru["id"] for ru in intent.get("runtime_unknowns", [])
                         if cap["id"] in ru.get("applies_to", {}).get("capabilities", [])]))
        # Lexical similarity suggests candidates, never a semantic or runtime verification.
        item = {"ref": cap["id"], "capability": cap.get("capability", cap.get("name", cap["id"])),
                "decision": "DISCOVERY_REQUIRED" if unknowns else "MISSING",
                "runtime_unknowns": unknowns, "next_action": "DISCOVER" if unknowns else "IMPLEMENT_NEW",
                "candidates": ranked[:5], "selection_confirmed": False}
        capabilities.append(item)
    return {"schema_version": "1.0", "reuse_plan": {
        "id": "RP-" + intent["case"]["id"], "source": {"case_id": intent["case"]["id"]},
        "status": "REVIEW_REQUIRED", "capabilities": capabilities, "composite_assets": []}}


def dependency_issues(asset_id, assets, cfg, chain=None):
    chain = (chain or []) + [asset_id]
    asset = assets.get(asset_id)
    if not asset:
        return ["Missing asset: " + asset_id]
    issues = []
    if not source_file(asset, cfg):
        issues.append("Source missing: " + asset_id)
    if not bounds_known(asset):
        issues.append("Unresolved prerequisites/dependencies: " + asset_id)
    for edge in asset.get("dependencies", {}).get("items", []):
        dep = edge.get("asset_id")
        if not dep:
            issues.append("Dependency without asset_id: " + asset_id)
        elif dep in chain:
            issues.append("Dependency cycle: " + " -> ".join(chain + [dep]))
        else:
            issues.extend(dependency_issues(dep, assets, cfg, chain))
    return issues
