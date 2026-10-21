#!/usr/bin/env python3
"""Lightweight structural validator for automation-intent.yaml v1.0."""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

try:
    import yaml
except ImportError as exc:  # pragma: no cover - environment guidance
    raise SystemExit("PyYAML is required: python3 -m pip install pyyaml") from exc


SOURCE_TYPES = {
    "TEST_CASE",
    "PRD",
    "PROTOTYPE",
    "UI_PROFILE",
    "UI_PROFILE_RUNTIME_REQUIRED",
    "HUMAN",
    "RUNTIME_OBSERVATION",
}
STAGES = {"PRE_RUNTIME", "RUNTIME_ENRICHED", "FINALIZED"}
STATUSES = {"DRAFT", "REVIEWED", "READY_FOR_MATCHING", "BLOCKED", "FINALIZED"}
ELIGIBILITY = {"ELIGIBLE", "PARTIALLY_ELIGIBLE", "NOT_ELIGIBLE"}
RESOLUTION = {"RESOLVED", "PARTIALLY_RESOLVED", "UNRESOLVED"}
KNOWLEDGE_LEVELS = {
    "CONFIRMED",
    "INFERRED",
    "RUNTIME_UNKNOWN",
    "HUMAN_CONFIRMED",
    "RUNTIME_VERIFIED",
}
CAPABILITY_CATEGORIES = {
    "AUTH",
    "NAVIGATION",
    "STATE_SETUP",
    "TEST_DATA",
    "UI_TARGET",
    "UI_INTERACTION",
    "BUSINESS_ACTION",
    "BUSINESS_FLOW",
    "WAIT",
    "ASSERTION",
    "UPLOAD",
    "DOWNLOAD",
    "ENVIRONMENT",
}
ASSERTION_TYPES = {
    "FIELD_VALUE",
    "TEXT",
    "VISIBILITY",
    "PAGE_STATE",
    "DIALOG_STATE",
    "ROW_STATE",
    "URL",
    "COUNT",
    "ENABLED_STATE",
    "SELECTED_STATE",
    "SUCCESS_FEEDBACK",
    "BUSINESS_RESULT",
}
UNKNOWN_CATEGORIES = {
    "PAGE_RESOLUTION",
    "TARGET_RESOLUTION",
    "INTERACTION_BEHAVIOR",
    "DATA_BEHAVIOR",
    "PERMISSION_BEHAVIOR",
    "LOADING_BEHAVIOR",
    "POST_ACTION_BEHAVIOR",
    "IFRAME_BEHAVIOR",
    "OVERLAY_BEHAVIOR",
    "RESPONSIVE_BEHAVIOR",
    "UNKNOWN",
}
PREFERRED_RESOLUTIONS = {
    "UI_EXPLORATION",
    "HUMAN_HINT",
    "HUMAN_DEMO",
    "REQUIREMENT_CONFIRMATION",
    "TEST_DATA_PREPARATION",
}
PREFERRED_ASSET_TYPES = {
    "auth",
    "business_action",
    "assertion",
    "wait_strategy",
    "ui_component",
    "locator_strategy",
    "fixture",
    "test_data",
    "environment_helper",
    "business_flow",
    "page_object",
    "runtime_helper",
    "state_manager",
}
LEGACY_ASSET_TYPE_ALIASES = {
    "environment_setup": "environment_helper",
    "assertion_helper": "assertion",
}
UI_KNOWLEDGE_FILES = (
    "ui-match-index.yaml",
    "runtime-required.yaml",
    "pages.yaml",
    "components.yaml",
    "interaction-rules.yaml",
    "permissions.yaml",
)
UI_ID_KEYS = {
    "id",
    "knowledge_id",
    "page_id",
    "region_id",
    "component_id",
    "interaction_rule_id",
    "rule_id",
    "permission_id",
    "runtime_id",
}
FORBIDDEN_INTENT_KEYS = {
    "matched_asset",
    "selected_asset",
    "reuse_readiness",
    "effective_reuse_readiness",
    "dependency_closure",
    "reuse-plan",
}
LOCATOR_PATTERN = re.compile(
    r"(?i)(?:\bcss\b|\bxpath\b|\bnth\b|locator\s*\(|dom[_ -]?depth)"
)
BUSINESS_ASSERTION_QUESTION_PATTERN = re.compile(
    r"(?i)(?:是否|有无|有没有|does|whether|is)\s*.{0,40}"
    r"(?:出现|显示|展示|选中|保存成功|隐藏|可见|appear|visible|selected|saved|hidden)"
)
SNAKE_CASE = re.compile(r"^[a-z][a-z0-9]*(?:_[a-z0-9]+)*$")


class Validator:
    def __init__(
        self,
        document: object,
        intent_path: Path | None = None,
        ui_knowledge_root: Path | None = None,
    ):
        self.document = document
        self.intent_path = intent_path
        self.ui_knowledge_root = ui_knowledge_root
        self.errors: list[str] = []
        self.warnings: list[str] = []
        self.ui_knowledge_available = False
        self.ui_knowledge_ids: set[str] = set()
        self.ui_runtime_ids: set[str] = set()
        self.ui_match_terms: set[str] = set()
        self.ui_metadata: dict[str, dict] = {}
        self.ui_refs_resolved = 0
        self.ui_refs_unresolved = 0
        self.pseudo_reference_count = 0
        self.runtime_unknown_business_assertion_conflicts = 0
        self.reference_quality = {
            "exact_refs": 0,
            "related_refs": 0,
            "unresolved_refs": 0,
            "suspected_overmatches": 0,
        }

    def error(self, message: str) -> None:
        self.errors.append(message)

    def check(self) -> None:
        if not isinstance(self.document, dict):
            self.error("document must be a mapping")
            return
        if self.document.get("schema_version") != "1.0":
            self.error('schema_version must be "1.0"')
        intent = self.document.get("intent")
        if not isinstance(intent, dict):
            self.error("intent must be a mapping")
            return

        required = {
            "id",
            "lifecycle",
            "case",
            "eligibility",
            "goal",
            "test_data",
            "preconditions",
            "ui_context",
            "steps",
            "required_capabilities",
            "assertions",
            "knowledge",
            "runtime_unknowns",
            "automation_constraints",
            "validation",
        }
        missing = sorted(required - set(intent))
        if missing:
            self.error(f"intent missing required keys: {', '.join(missing)}")
        self.check_forbidden_content(intent)

        self.check_lifecycle(intent.get("lifecycle"))
        self.check_case_eligibility_goal(intent)
        self.check_test_data(intent.get("test_data"))
        self.check_preconditions(intent.get("preconditions"))
        self.check_ui_context(intent.get("ui_context"))
        self.check_steps_capabilities(intent)
        self.check_assertions(intent.get("assertions"))
        self.check_knowledge(intent.get("knowledge"))
        self.check_unknowns(intent.get("runtime_unknowns"))
        self.check_sources(intent)
        self.check_step_locators(intent.get("steps"))
        self.check_ui_knowledge_references(intent)
        self.check_runtime_enrichment(intent)
        self.check_runtime_unknown_business_conflicts(intent)
        self.check_reference_quality(intent)
        self.check_readiness(intent)

    def warning(self, message: str) -> None:
        if message not in self.warnings:
            self.warnings.append(message)

    def check_forbidden_content(self, intent: dict) -> None:
        """Reject Asset Matcher fields and historical asset evidence anywhere in intent."""

        def walk(node: object, path: str) -> None:
            if isinstance(node, dict):
                for key, value in node.items():
                    if key in FORBIDDEN_INTENT_KEYS:
                        self.error(f"Asset Matcher field is forbidden at {path}.{key}")
                    walk(value, f"{path}.{key}")
            elif isinstance(node, list):
                for index, value in enumerate(node):
                    walk(value, f"{path}[{index}]")
            elif isinstance(node, str):
                normalized = node.replace("\\", "/")
                if "automation-assets/" in normalized or normalized == "automation-assets":
                    self.error(f"automation-assets reference is forbidden at {path}")

        walk(intent, "intent")

    def _find_ui_knowledge_root(self) -> Path | None:
        candidates: list[Path] = []
        if self.ui_knowledge_root:
            candidates.append(self.ui_knowledge_root)
        if self.intent_path:
            candidates.append(self.intent_path.parent / "ui-knowledge")
        candidates.append(Path.cwd() / "ui-knowledge")
        for candidate in candidates:
            if candidate.is_dir():
                return candidate
        return None

    def _collect_ui_ids(self, node: object, ids: set[str]) -> None:
        if isinstance(node, dict):
            for key, value in node.items():
                if key in UI_ID_KEYS or key.endswith("_id"):
                    if isinstance(value, str) and value:
                        ids.add(value)
                self._collect_ui_ids(value, ids)
        elif isinstance(node, list):
            for value in node:
                self._collect_ui_ids(value, ids)

    def _collect_match_terms(self, node: object, active: bool = False) -> None:
        if isinstance(node, dict):
            for key, value in node.items():
                self._collect_match_terms(value, active or key == "business_terms")
        elif isinstance(node, list):
            for value in node:
                self._collect_match_terms(value, active)
        elif active and isinstance(node, str) and len(node.strip()) >= 2:
            self.ui_match_terms.add(node.strip())

    def _collect_ui_metadata(self, node: object, source_file: str) -> None:
        if isinstance(node, dict):
            identifier = None
            for key in UI_ID_KEYS:
                if isinstance(node.get(key), str) and node[key]:
                    identifier = node[key]
                    break
            if identifier:
                metadata = dict(node)
                metadata["_source_file"] = source_file
                existing = self.ui_metadata.get(identifier, {})
                existing.update(metadata)
                self.ui_metadata[identifier] = existing
            for value in node.values():
                self._collect_ui_metadata(value, source_file)
        elif isinstance(node, list):
            for value in node:
                self._collect_ui_metadata(value, source_file)

    def _load_ui_knowledge_ids(self) -> None:
        root = self._find_ui_knowledge_root()
        if root is None:
            self.warning("UI_KNOWLEDGE_NOT_AVAILABLE")
            return
        self.ui_knowledge_available = True
        for filename in UI_KNOWLEDGE_FILES:
            path = root / filename
            if not path.is_file():
                continue
            try:
                loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
            except yaml.YAMLError as exc:
                self.error(f"invalid ui-knowledge YAML at {path}: {exc}")
                continue
            file_ids: set[str] = set()
            self._collect_ui_ids(loaded, file_ids)
            self._collect_ui_metadata(loaded, filename)
            self.ui_knowledge_ids.update(file_ids)
            if filename == "runtime-required.yaml":
                self.ui_runtime_ids.update(file_ids)
            if filename == "ui-match-index.yaml":
                self._collect_match_terms(loaded)

    def _intent_ui_refs(self, intent: dict) -> list[tuple[str, str, str]]:
        refs: list[tuple[str, str, str]] = []

        def walk(node: object, path: str) -> None:
            if isinstance(node, dict):
                for key, value in node.items():
                    if key in {"knowledge_ref", "ui_runtime_ref"} and isinstance(value, str):
                        refs.append((value, f"{path}.{key}", key))
                    walk(value, f"{path}.{key}")
            elif isinstance(node, list):
                for index, value in enumerate(node):
                    walk(value, f"{path}[{index}]")

        walk(intent, "intent")
        profile_refs = intent.get("knowledge", {}).get("ui_profile_refs", {})
        if isinstance(profile_refs, dict):
            for kind, values in profile_refs.items():
                if isinstance(values, list):
                    for index, value in enumerate(values):
                        if isinstance(value, str):
                            refs.append((value, f"intent.knowledge.ui_profile_refs.{kind}[{index}]", kind))
        return refs

    def _reference_quality_counts(self, intent: dict) -> tuple[list[tuple[str, str, object]], list[tuple[str, str]], int]:
        exact: list[tuple[str, str, object]] = []
        related: list[tuple[str, str]] = []
        unresolved = 0

        def walk(node: object, path: str) -> None:
            nonlocal unresolved
            if isinstance(node, dict):
                for key, value in node.items():
                    current = f"{path}.{key}"
                    if key in {"knowledge_ref", "ui_runtime_ref"}:
                        if isinstance(value, str):
                            exact.append((value, current, node))
                        elif value is None:
                            unresolved += 1
                    elif key == "knowledge_refs" and path == "intent.ui_context.entry":
                        if isinstance(value, list):
                            for index, item in enumerate(value):
                                if isinstance(item, str):
                                    exact.append((item, f"{current}[{index}]", node))
                    walk(value, current)
            elif isinstance(node, list):
                for index, value in enumerate(node):
                    walk(value, f"{path}[{index}]")

        walk(intent, "intent")
        capabilities = intent.get("required_capabilities", [])
        for index, capability in enumerate(capabilities if isinstance(capabilities, list) else []):
            if not isinstance(capability, dict):
                continue
            values = capability.get("ui_knowledge_refs", [])
            if isinstance(values, list):
                related.extend(
                    (value, f"intent.required_capabilities[{index}].ui_knowledge_refs[{item_index}]")
                    for item_index, value in enumerate(values)
                    if isinstance(value, str)
                )
        profile_refs = intent.get("knowledge", {}).get("ui_profile_refs", {})
        if isinstance(profile_refs, dict):
            for kind, values in profile_refs.items():
                if isinstance(values, list):
                    related.extend(
                        (value, f"intent.knowledge.ui_profile_refs.{kind}[{index}]")
                        for index, value in enumerate(values)
                        if isinstance(value, str)
                    )
        return exact, related, unresolved

    def _semantic_overmatch_count(self, exact_refs: list[tuple[str, str, object]], intent: dict) -> int:
        suspected = 0
        for ref, path, owner in exact_refs:
            metadata = self.ui_metadata.get(ref, {})
            semantic_name = owner.get("semantic_name", "") if isinstance(owner, dict) else ""
            semantic_name = str(semantic_name)
            kind = metadata.get("kind")
            if metadata.get("exact_target_allowed") is False:
                suspected += 1
                self.error(f"EXACT UI reference is not targetable at {path}: {ref}")
            if kind == "page" and (".region." in path or "target_region" in path):
                suspected += 1
                self.error(f"Page Knowledge cannot be used as an exact Region reference at {path}: {ref}")
            if kind == "component" and (".region." in path or "target_region" in path):
                suspected += 1
                self.error(f"Component Knowledge cannot represent an exact Region at {path}: {ref}")
            scope = str(metadata.get("scope", ""))
            if scope == "BACKOFFICE_PRODUCT_MANAGEMENT" and re.search(r"前台|产品详情", semantic_name):
                suspected += 1
                self.error(f"Backend Page Knowledge is over-broad for frontend/detail target at {path}: {ref}")
            terms = metadata.get("terms", [])
            if kind == "region" and isinstance(terms, list) and semantic_name:
                if not any(isinstance(term, str) and term in semantic_name for term in terms):
                    suspected += 1
                    self.error(f"Region Knowledge does not match the named Region at {path}: {ref}")
        return suspected

    def check_ui_knowledge_references(self, intent: dict) -> None:
        self._load_ui_knowledge_ids()
        refs = self._intent_ui_refs(intent)
        exact_refs, related_refs, unresolved_refs = self._reference_quality_counts(intent)
        self.reference_quality["exact_refs"] = len(exact_refs)
        self.reference_quality["related_refs"] = len(related_refs)
        self.reference_quality["unresolved_refs"] = unresolved_refs
        if not self.ui_knowledge_available:
            self.ui_refs_unresolved = len(refs)
            if refs:
                self.pseudo_reference_count = len(refs)
                self.error(
                    "non-null UI references cannot be verified because ui-knowledge is unavailable"
                )
            warnings = intent.get("validation", {}).get("warnings", [])
            warning_text = " ".join(str(item) for item in warnings) if isinstance(warnings, list) else str(warnings)
            if "UI_KNOWLEDGE_NOT_AVAILABLE" not in warning_text:
                self.error("validation.warnings must include UI_KNOWLEDGE_NOT_AVAILABLE when ui-knowledge is absent")
            for unknown in intent.get("runtime_unknowns", []) or []:
                if not isinstance(unknown, dict):
                    continue
                source = unknown.get("source")
                if isinstance(source, dict) and source.get("type") == "UI_PROFILE_RUNTIME_REQUIRED":
                    self.error(
                        f"Runtime Unknown {unknown.get('id')} cannot use UI_PROFILE_RUNTIME_REQUIRED without ui-knowledge"
                    )
            return

        self.reference_quality["suspected_overmatches"] = self._semantic_overmatch_count(exact_refs, intent)

        if not refs and self._has_clear_ui_match(intent):
            self.error(
                "ui-knowledge clearly matches the business semantics but all UI references are null"
            )

        for ref, path, kind in refs:
            if ref in self.ui_knowledge_ids:
                if kind in {"ui_runtime_ref", "runtime_refs"} and ref not in self.ui_runtime_ids:
                    self.ui_refs_unresolved += 1
                    self.error(f"{path} must resolve to runtime-required.yaml ID: {ref}")
                else:
                    self.ui_refs_resolved += 1
            else:
                self.ui_refs_unresolved += 1
                self.pseudo_reference_count += 1
                self.error(f"unresolved UI Knowledge reference at {path}: {ref}")

        for unknown in intent.get("runtime_unknowns", []) or []:
            if not isinstance(unknown, dict):
                continue
            source = unknown.get("source")
            runtime_ref = unknown.get("ui_runtime_ref")
            if runtime_ref is not None and (
                not isinstance(source, dict) or source.get("type") != "UI_PROFILE_RUNTIME_REQUIRED"
            ):
                self.error(
                    f"Runtime Unknown {unknown.get('id')} ui_runtime_ref requires UI_PROFILE_RUNTIME_REQUIRED source"
                )
            if not isinstance(source, dict) or source.get("type") != "UI_PROFILE_RUNTIME_REQUIRED":
                continue
            source_ref = source.get("ref")
            if source_ref not in self.ui_runtime_ids:
                self.error(f"Runtime Unknown {unknown.get('id')} source.ref is not a runtime-required ID: {source_ref}")
            if runtime_ref not in self.ui_runtime_ids:
                self.error(f"Runtime Unknown {unknown.get('id')} ui_runtime_ref is not a runtime-required ID: {runtime_ref}")
            runtime_metadata = self.ui_metadata.get(runtime_ref, {})
            for required_key in ("reason", "verification_method", "resolves"):
                if not runtime_metadata.get(required_key):
                    self.reference_quality["suspected_overmatches"] += 1
                    self.error(
                        f"Runtime Required {runtime_ref} is missing semantic field {required_key}"
                    )
            if runtime_ref and source.get("type") != "UI_PROFILE_RUNTIME_REQUIRED":
                self.error(f"Runtime Unknown {unknown.get('id')} ui_runtime_ref requires UI_PROFILE_RUNTIME_REQUIRED source")
            if runtime_ref and isinstance(unknown.get("question"), str):
                resolves = str(runtime_metadata.get("resolves", ""))
                if resolves and not self._shares_semantic_phrase(unknown["question"], resolves):
                    self.reference_quality["suspected_overmatches"] += 1
                    self.error(
                        f"Runtime Required {runtime_ref} does not directly resolve Runtime Unknown {unknown.get('id')}"
                    )

        if self.reference_quality["suspected_overmatches"]:
            self.error("reference_quality.suspected_overmatches must be 0")

    def _shares_semantic_phrase(self, left: str, right: str) -> bool:
        left_tokens = re.findall(r"[\u4e00-\u9fff]{3,}|[A-Za-z][A-Za-z0-9_ -]{3,}", left)
        right_tokens = re.findall(r"[\u4e00-\u9fff]{3,}|[A-Za-z][A-Za-z0-9_ -]{3,}", right)
        if any(a in right or b in left for a in left_tokens for b in right_tokens):
            return True
        left_han = "".join(re.findall(r"[\u4e00-\u9fff]", left))
        right_han = "".join(re.findall(r"[\u4e00-\u9fff]", right))
        for text_value, other_value in ((left_han, right_han), (right_han, left_han)):
            for index in range(max(0, len(text_value) - 3)):
                if text_value[index : index + 4] in other_value:
                    return True
        return False

    def _has_clear_ui_match(self, intent: dict) -> bool:
        if not self.ui_match_terms:
            return False
        semantic_text: list[str] = []
        case = intent.get("case", {})
        if isinstance(case, dict):
            semantic_text.extend(str(case.get(key, "")) for key in ("name", "module"))
        goal = intent.get("goal", {})
        if isinstance(goal, dict):
            for key in ("actor", "action", "object"):
                item = goal.get(key)
                if isinstance(item, dict):
                    semantic_text.append(str(item.get("semantic_name", "")))
            results = goal.get("expected_business_result", [])
            if isinstance(results, list):
                semantic_text.extend(str(item) for item in results)
        for step in intent.get("steps", []) or []:
            if not isinstance(step, dict):
                continue
            semantic_text.append(str(step.get("intent", "")))
            for section in ("context", "anchor", "target"):
                value = step.get(section)
                if isinstance(value, dict):
                    for item in value.values():
                        if isinstance(item, dict):
                            semantic_text.append(str(item.get("semantic_name", "")))
        joined = " ".join(semantic_text)
        return any(term in joined for term in self.ui_match_terms if len(term) >= 2)

    def check_runtime_enrichment(self, intent: dict) -> None:
        enrichment = intent.get("runtime_enrichment")
        stage = intent.get("lifecycle", {}).get("stage") if isinstance(intent.get("lifecycle"), dict) else None
        if enrichment is not None and stage == "PRE_RUNTIME":
            self.error("PRE_RUNTIME Intent must omit runtime_enrichment")
        if enrichment:
            if stage != "RUNTIME_ENRICHED":
                self.error("runtime_enrichment requires lifecycle.stage RUNTIME_ENRICHED")
            source_types = self._source_types(intent)
            if "RUNTIME_OBSERVATION" not in source_types:
                self.error("runtime_enrichment requires an explicit RUNTIME_OBSERVATION source")

    def _source_types(self, node: object) -> set[str]:
        result: set[str] = set()
        if isinstance(node, dict):
            for key, value in node.items():
                if key in {"source", "source_refs", "basis"}:
                    values = value if isinstance(value, list) else [value]
                    for item in values:
                        if isinstance(item, dict) and isinstance(item.get("type"), str):
                            result.add(item["type"])
                result.update(self._source_types(value))
        elif isinstance(node, list):
            for value in node:
                result.update(self._source_types(value))
        return result

    def check_runtime_unknown_business_conflicts(self, intent: dict) -> None:
        business_texts: list[str] = []
        goal = intent.get("goal", {})
        if isinstance(goal, dict):
            expected = goal.get("expected_business_result", [])
            if isinstance(expected, list):
                business_texts.extend(str(item) for item in expected)
        for assertion in intent.get("assertions", []) or []:
            if not isinstance(assertion, dict):
                continue
            target = assertion.get("target", {})
            expected = assertion.get("expected", {})
            if isinstance(target, dict):
                business_texts.append(str(target.get("semantic_name", "")))
            if isinstance(expected, dict):
                for key in ("semantic_name", "text", "value"):
                    if isinstance(expected.get(key), str):
                        business_texts.append(expected[key])
        tokens: set[str] = set()
        for text_value in business_texts:
            tokens.update(re.findall(r"[\u4e00-\u9fff]{3,}|[A-Za-z][A-Za-z0-9_ -]{3,}", text_value))
        for unknown in intent.get("runtime_unknowns", []) or []:
            if not isinstance(unknown, dict) or not isinstance(unknown.get("question"), str):
                continue
            question = unknown["question"]
            conflicts = [token for token in tokens if token and token in question]
            if BUSINESS_ASSERTION_QUESTION_PATTERN.search(question):
                conflicts.append("business-result question form")
            if conflicts:
                self.runtime_unknown_business_assertion_conflicts += 1
                self.error(
                    f"Runtime Unknown {unknown.get('id')} restates business assertion text: {', '.join(sorted(conflicts))}"
                )

    def check_reference_quality(self, intent: dict) -> None:
        validation = intent.get("validation")
        if not isinstance(validation, dict):
            return
        quality = validation.get("reference_quality")
        if not isinstance(quality, dict):
            self.error("validation.reference_quality must be a mapping")
            return
        expected = self.reference_quality
        for key in ("exact_refs", "related_refs", "unresolved_refs", "suspected_overmatches"):
            value = quality.get(key)
            if not isinstance(value, dict) or not isinstance(value.get("count"), int):
                self.error(f"validation.reference_quality.{key}.count must be an integer")
                continue
            if value["count"] != expected[key]:
                self.error(
                    f"validation.reference_quality.{key}.count={value['count']} does not match computed {expected[key]}"
                )
        if expected["suspected_overmatches"] != 0:
            self.error("validation.reference_quality.suspected_overmatches must be 0")

    def check_lifecycle(self, lifecycle: object) -> None:
        if not isinstance(lifecycle, dict):
            self.error("intent.lifecycle must be a mapping")
            return
        if lifecycle.get("stage") not in STAGES:
            self.error("intent.lifecycle.stage is invalid")
        if lifecycle.get("status") not in STATUSES:
            self.error("intent.lifecycle.status is invalid")

    def check_case_eligibility_goal(self, intent: dict) -> None:
        case = intent.get("case")
        if not isinstance(case, dict):
            self.error("intent.case must be a mapping")
        else:
            for key in ("id", "name", "module", "source_refs"):
                if key not in case:
                    self.error(f"intent.case missing {key}")
        eligibility = intent.get("eligibility")
        if not isinstance(eligibility, dict) or eligibility.get("status") not in ELIGIBILITY:
            self.error("intent.eligibility.status is invalid")
        goal = intent.get("goal")
        if not isinstance(goal, dict) or any(
            not isinstance(goal.get(part), dict) for part in ("actor", "action", "object")
        ) or not goal.get("expected_business_result"):
            self.error("goal must contain actor, action, object, and expected_business_result")

    def check_test_data(self, test_data: object) -> None:
        if not isinstance(test_data, dict):
            self.error("intent.test_data must be a mapping")
            return
        variables = test_data.get("variables", [])
        if not isinstance(variables, list):
            self.error("test_data.variables must be a list")
            return
        for variable in variables:
            if not isinstance(variable, dict):
                self.error("each test-data variable must be a mapping")
                continue
            for key in ("id", "semantic_name", "type", "required", "value", "source", "sensitivity"):
                if key not in variable:
                    self.error(f"test-data variable missing {key}")
            if variable.get("sensitivity") not in {"NORMAL", "SENSITIVE", "SECRET"}:
                self.error(f"invalid sensitivity for variable {variable.get('id')}")
            if variable.get("sensitivity") == "SECRET":
                value = variable.get("value")
                if value is not None and not (isinstance(value, str) and value.startswith("${")):
                    self.error(f"SECRET variable {variable.get('id')} contains a literal value")

    def check_preconditions(self, preconditions: object) -> None:
        if not isinstance(preconditions, list):
            self.error("intent.preconditions must be a list")
            return
        for item in preconditions:
            if not isinstance(item, dict):
                self.error("each precondition must be a mapping")
                continue
            for key in ("id", "statement", "knowledge_level", "source_refs"):
                if key not in item:
                    self.error(f"precondition missing {key}")
            if item.get("knowledge_level") not in KNOWLEDGE_LEVELS:
                self.error(f"invalid precondition knowledge_level: {item.get('id')}")

    def check_ui_context(self, context: object) -> None:
        if not isinstance(context, dict):
            self.error("intent.ui_context must be a mapping")
            return
        for key in ("entry", "target_page", "target_region", "related_components"):
            if key not in context:
                self.error(f"ui_context missing {key}")
        for key in ("target_page", "target_region"):
            value = context.get(key)
            if not isinstance(value, dict) or value.get("resolution_status") not in RESOLUTION:
                self.error(f"ui_context.{key}.resolution_status is invalid")

    def check_steps_capabilities(self, intent: dict) -> None:
        steps = intent.get("steps")
        capabilities = intent.get("required_capabilities")
        if not isinstance(steps, list) or not isinstance(capabilities, list):
            self.error("steps and required_capabilities must be lists")
            return
        step_ids = {item.get("id") for item in steps if isinstance(item, dict)}
        cap_ids = {item.get("id") for item in capabilities if isinstance(item, dict)}
        for step in steps:
            if not isinstance(step, dict):
                self.error("each Step must be a mapping")
                continue
            for key in ("id", "intent", "context", "target", "action", "required_capability_refs", "source_refs"):
                if key not in step:
                    self.error(f"Step {step.get('id')} missing {key}")
            refs = step.get("required_capability_refs", [])
            if not refs:
                self.error(f"Step {step.get('id')} has no Required Capability reference")
            for ref in refs:
                if ref not in cap_ids:
                    self.error(f"Step {step.get('id')} references unknown Capability {ref}")
            for ref in step.get("runtime_unknown_refs", []) or []:
                # checked against unknown IDs after the unknown list is available
                if not isinstance(ref, str):
                    self.error(f"Step {step.get('id')} has invalid runtime unknown reference")
        for cap in capabilities:
            if not isinstance(cap, dict):
                self.error("each Required Capability must be a mapping")
                continue
            for key in ("id", "capability", "semantic_name", "category", "required", "step_refs", "preferred_asset_types", "ui_knowledge_refs"):
                if key not in cap:
                    self.error(f"Capability {cap.get('id')} missing {key}")
            if cap.get("category") not in CAPABILITY_CATEGORIES:
                self.error(f"invalid Capability category: {cap.get('id')}")
            if not isinstance(cap.get("capability"), str) or not SNAKE_CASE.match(cap.get("capability", "")):
                self.error(f"Capability must be semantic snake_case: {cap.get('id')}")
            asset_types = cap.get("preferred_asset_types")
            if not isinstance(asset_types, list):
                self.error(f"Capability {cap.get('id')} preferred_asset_types must be a list")
            else:
                for asset_type in asset_types:
                    if asset_type not in PREFERRED_ASSET_TYPES:
                        alias = LEGACY_ASSET_TYPE_ALIASES.get(asset_type)
                        if alias:
                            self.error(
                                f"Capability {cap.get('id')} uses legacy asset type {asset_type}; use {alias}"
                            )
                        else:
                            self.error(
                                f"Capability {cap.get('id')} uses non-canonical asset type: {asset_type}"
                            )
            for ref in cap.get("step_refs", []) or []:
                if ref not in step_ids:
                    self.error(f"Capability {cap.get('id')} references unknown Step {ref}")

    def check_assertions(self, assertions: object) -> None:
        if not isinstance(assertions, list):
            self.error("intent.assertions must be a list")
            return
        for assertion in assertions:
            if not isinstance(assertion, dict):
                self.error("each Assertion must be a mapping")
                continue
            for key in ("id", "type", "target", "expected", "required", "source_refs"):
                if key not in assertion:
                    self.error(f"Assertion {assertion.get('id')} missing {key}")
            if assertion.get("type") not in ASSERTION_TYPES:
                self.error(f"invalid Assertion type: {assertion.get('id')}")

    def check_knowledge(self, knowledge: object) -> None:
        if not isinstance(knowledge, dict):
            self.error("intent.knowledge must be a mapping")
            return
        for key in ("confirmed", "inferred", "ui_profile_refs"):
            if key not in knowledge:
                self.error(f"knowledge missing {key}")
        for fact in knowledge.get("inferred", []) or []:
            if not isinstance(fact, dict):
                self.error("each inferred fact must be a mapping")
                continue
            for key in ("id", "fact", "confidence", "basis", "must_not_be_treated_as_confirmed"):
                if key not in fact:
                    self.error(f"inferred fact {fact.get('id')} missing {key}")
            if fact.get("must_not_be_treated_as_confirmed") is not True:
                self.error(f"inferred fact {fact.get('id')} must explicitly remain unconfirmed")

    def check_unknowns(self, unknowns: object) -> None:
        if not isinstance(unknowns, list):
            self.error("intent.runtime_unknowns must be a list")
            return
        ids = {item.get("id") for item in unknowns if isinstance(item, dict)}
        for unknown in unknowns:
            if not isinstance(unknown, dict):
                self.error("each Runtime Unknown must be a mapping")
                continue
            for key in ("id", "question", "category", "blocking", "priority", "applies_to", "source", "ui_runtime_ref", "preferred_resolution", "status"):
                if key not in unknown:
                    self.error(f"Runtime Unknown {unknown.get('id')} missing {key}")
            if unknown.get("category") not in UNKNOWN_CATEGORIES:
                self.error(f"invalid Runtime Unknown category: {unknown.get('id')}")
            if unknown.get("preferred_resolution") not in PREFERRED_RESOLUTIONS:
                self.error(f"invalid Runtime Unknown resolution: {unknown.get('id')}")
            if unknown.get("status") not in {"OPEN", "RESOLVED"}:
                self.error(f"invalid Runtime Unknown status: {unknown.get('id')}")
        steps = self.document.get("intent", {}).get("steps", [])
        for step in steps:
            for ref in step.get("runtime_unknown_refs", []) or []:
                if ref not in ids:
                    self.error(f"Step {step.get('id')} references unknown Runtime Unknown {ref}")

    def check_sources(self, node: object, path: str = "intent") -> None:
        if isinstance(node, dict):
            for key, value in node.items():
                if key in {"source", "source_refs", "basis"}:
                    self.check_source_value(value, f"{path}.{key}")
                else:
                    self.check_sources(value, f"{path}.{key}")
        elif isinstance(node, list):
            for index, value in enumerate(node):
                self.check_sources(value, f"{path}[{index}]")

    def check_source_value(self, value: object, path: str) -> None:
        items = value if isinstance(value, list) else [value]
        for item in items:
            if not isinstance(item, dict) or "type" not in item:
                continue
            if item.get("type") not in SOURCE_TYPES:
                self.error(f"invalid source type at {path}: {item.get('type')}")

    def check_step_locators(self, steps: object) -> None:
        def walk(node: object, path: str) -> None:
            if isinstance(node, dict):
                for key, value in node.items():
                    walk(value, f"{path}.{key}")
            elif isinstance(node, list):
                for index, value in enumerate(node):
                    walk(value, f"{path}[{index}]")
            elif isinstance(node, str) and LOCATOR_PATTERN.search(node):
                self.error(f"forbidden Locator syntax in Step at {path}")

        walk(steps, "intent.steps")

    def check_readiness(self, intent: dict) -> None:
        validation = intent.get("validation")
        if not isinstance(validation, dict):
            self.error("intent.validation must be a mapping")
            return
        if validation.get("ready_for_asset_matching") is not True:
            return
        if not intent.get("steps"):
            self.error("ready_for_asset_matching=true requires at least one Step")
        if not intent.get("required_capabilities"):
            self.error("ready_for_asset_matching=true requires Required Capabilities")
        if not intent.get("assertions"):
            self.error("ready_for_asset_matching=true requires a core Assertion")
        if validation.get("blocking_issues"):
            self.error("ready_for_asset_matching=true cannot have blocking_issues")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("path", type=Path)
    parser.add_argument(
        "--ui-knowledge-root",
        type=Path,
        help="optional ui-knowledge directory; otherwise resolve beside the Intent or current directory",
    )
    args = parser.parse_args()
    try:
        document = yaml.safe_load(args.path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        print(f"ERROR: file not found: {args.path}", file=sys.stderr)
        return 2
    except yaml.YAMLError as exc:
        print(f"ERROR: invalid YAML: {exc}", file=sys.stderr)
        return 2
    validator = Validator(document, intent_path=args.path, ui_knowledge_root=args.ui_knowledge_root)
    validator.check()
    for warning in validator.warnings:
        print(f"WARNING: {warning}")
    print(
        "SUMMARY: "
        f"ui_knowledge_available={str(validator.ui_knowledge_available).lower()} "
        f"ui_knowledge_refs_resolved={validator.ui_refs_resolved} "
        f"ui_knowledge_refs_unresolved={validator.ui_refs_unresolved} "
        f"pseudo_reference_count={validator.pseudo_reference_count} "
        f"runtime_unknown_business_assertion_conflicts={validator.runtime_unknown_business_assertion_conflicts} "
        "automation_asset_reads=0 "
        f"lifecycle_stage={document.get('intent', {}).get('lifecycle', {}).get('stage') if isinstance(document, dict) and isinstance(document.get('intent'), dict) else 'UNKNOWN'} "
        f"reference_quality_exact_refs={validator.reference_quality['exact_refs']} "
        f"reference_quality_related_refs={validator.reference_quality['related_refs']} "
        f"reference_quality_unresolved_refs={validator.reference_quality['unresolved_refs']} "
        f"reference_quality_suspected_overmatches={validator.reference_quality['suspected_overmatches']}"
    )
    if validator.errors:
        for error in validator.errors:
            print(f"ERROR: {error}")
        return 1
    print(f"OK: {args.path} is a valid automation-intent.yaml v1.0 document")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
