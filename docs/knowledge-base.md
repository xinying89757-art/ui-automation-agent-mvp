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

Successful execution-backed write-back happens at report/close-out or through `uia.py kb writeback --run ID`. Stable entry/locator records require reuse by at least two cases or two successful executions. Reusable repair patterns require multiple cases with a classified failure followed by a successful repair. Provenance and freshness counters are idempotent per run; write-back never changes case assertions or business meaning. Two independent failures for a record in the same version make it `needs_review`, which is excluded from retrieval by default.

`uia.py kb prune` marks records not verified for 90 days as stale. Records with no hits for 180 days are listed as deletion candidates; the command never deletes them. Review and removal happen through a human-reviewed PR.

The fixed pipeline reports `re_explored_known_pages`; any positive count is surfaced as a process issue in report and status/next output. This makes a repeated exploration of a known page visible rather than silently normalizing it.
