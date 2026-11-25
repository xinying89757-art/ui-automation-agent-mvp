# Knowledge catalog

The catalog is split into `pages/`, `components/`, `flows/`, and `patterns/`, with a compact `index.yaml`. The index stores one-line metadata (`id`, page, route, frame, tags, version, status, verification date, summary, path and counters); payload details stay in per-record YAML files. `entries.yaml` and `page-map.yaml` remain the compatibility source during migration.

## Query and pipeline

Every `uia go` run queries knowledge before generating specs, asking questions, or exploring. Retrieval uses one replaceable `retrieval.select(case, budget)` seam: hard filters for page/frame/version/status, followed by keyword/BM25 ranking. No embeddings are used. It opens only ranked matching files; `needs_review`, `stale`, and `deprecated` items are excluded. Specs and exploration generators receive the per-case selected records and referenced interaction patterns, never the complete catalog.

```bash
python3 scripts/uia.py kb query --case TC-0004 [--run GO-id] [--max-tokens N]
```

The token limit is opt-in. With no `--max-tokens`, matching context is not truncated. If a limit is supplied, selection stops before exceeding the cumulative estimated tokens and records omitted IDs in `knowledge-match.json`. The run report records p50/p95 injected tokens. The estimate is tokenizer-independent and intended for comparative monitoring.

## Migration and verification

```bash
python3 scripts/uia.py knowledge merge --from /path/to/assets/playwright-runner/knowledge --run-id GO-source
python3 scripts/uia.py kb validate
```

Merge preserves legacy-readable catalogs, writes normalized split records, deduplicates identical locators and records `source_run` plus `verified_by` or `unverified`. It does not store transient snapshot references. Validation checks schemas/required fields, duplicate IDs and locators, alias targets, referenced files, per-file/index size limits, and secret-like or personal information patterns. CI runs the same validator and unit tests.

## Lifecycle

Reports, exploration, hints and human answers do not publish long-term knowledge. The run-local `state/entries-overlay.yaml` and `state/page-map-overlay.yaml` contain provisional routes and controls, including updates to shared entries. They are available only in that run; human answers remain unconfirmed until verified in the UI. Batches freeze the shared catalogs and both overlays, record their SHA-256 hashes and execute using those snapshots. Exported packages load their run-local overlay automatically; set `UIA_BATCH_KNOWLEDGE_ID` to load a particular included batch's frozen knowledge.

Agent-curated, successful-execution-backed discoveries may be added with `uia.py kb propose --run ID --file candidate.json` (use `--replace` for a revised same-ID candidate). A candidate specifies `kind` (`entry`, `target`, or `experience`), stable `id`, `scope`, `after`, and run-relative `evidence`. Include verification date and source run in the proposed entry; never put temporary snapshot references, test data, or case-specific expected results in shared knowledge. The report shows candidate before/after values and exports per-item approve/defer/reject decisions. Publish only those selected with `uia.py kb writeback --run ID --review review.json`; the `knowledge writeback` alias uses the same gate. Candidate content, evidence hashes and shared before-values are checked against the reviewed version, and conflicts leave shared files unchanged and write `reports/asset-review-conflicts.json` for renewed review. Re-importing the same decision is idempotent. Only approved catalog entries, their split resources, index rows and needed runner mirrors are updated; source run, evidence and scope remain traceable. Writeback does not change assertions or business semantics.

`uia.py kb prune` marks records not verified for 90 days as stale. Records with no hits for 180 days are listed as deletion candidates; the command never deletes them. Review and removal happen through a human-reviewed PR.

The fixed pipeline reports `re_explored_known_pages`; any positive count is surfaced as a process issue in report and status/next output. This makes a repeated exploration of a known page visible rather than silently normalizing it.
