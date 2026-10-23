"""Replaceable retrieval seam: hard metadata filters, BM25 ranking, then budgeted file reads."""
from __future__ import annotations

import json
import math
import re
from datetime import datetime, timezone

from .common import atomic_write, require
from . import knowledge


def _tokens(value):
    text = str(value or '').casefold()
    latin = re.findall(r'[a-z0-9_.-]+', text)
    cjk = re.findall(r'[\u4e00-\u9fff]+', text)
    grams = [part[i:i + 2] for part in cjk for i in range(max(1, len(part) - 1))]
    return latin + cjk + grams


def estimate_tokens(value):
    """Conservative tokenizer-free estimate: CJK chars cost 1.5, other chars 0.25."""
    text = str(value)
    cjk = sum('\u4e00' <= char <= '\u9fff' for char in text)
    return math.ceil(cjk * 1.5 + (len(text) - cjk) / 4)


def _bm25(query_tokens, document_tokens, avg_length, corpus_size, document_frequency):
    if not query_tokens or not document_tokens: return 0.0
    from collections import Counter
    query, frequencies = set(query_tokens), Counter(document_tokens)
    total = len(document_tokens); score = 0.0; k1, b = 1.2, .75
    for term in query:
        tf = frequencies[term]
        if not tf: continue
        df = document_frequency.get(term, 0)
        idf = math.log(1 + (corpus_size - df + .5) / (df + .5))
        score += idf * tf * (k1 + 1) / (tf + k1 * (1 - b + b * total / max(avg_length, 1)))
    return score


def _hard_filter(item, case):
    page, frame, version = case.get('page'), case.get('frame'), case.get('version')
    status = item.get('status')
    if status in {'needs_review', 'stale', 'deprecated'}: return False
    if page and str(item.get('page') or '').casefold() not in {str(page).casefold(), '*'}: return False
    if frame and item.get('frame') and item.get('frame') != frame: return False
    if version and item.get('version') not in {version, '*'}: return False
    return True


def resolve_page(query):
    """Resolve a case/feature phrase to one page using index metadata only."""
    index = knowledge.load_index()
    needle = str(query or '').casefold().strip()
    if not needle: return None
    exact = [row for row in index if str(row.get('page') or '').casefold() == needle]
    if exact: return exact[0].get('page')
    query_tokens = set(_tokens(needle))
    scores = {}
    for row in index:
        page = row.get('page')
        if not page or page == '*': continue
        search = ' '.join([str(row.get('id') or ''), str(page), str(row.get('route') or ''),
                           str(row.get('summary') or ''), ' '.join(row.get('tags') or [])]).casefold()
        terms = set(_tokens(search))
        overlap = len(query_tokens & terms)
        if overlap:
            scores[page] = scores.get(page, 0) + overlap + (3 if needle in search else 0)
    if not scores: return None
    ranked = sorted(scores.items(), key=lambda row: (-row[1], str(row[0])))
    if len(ranked) > 1 and ranked[0][1] == ranked[1][1]: return None
    return ranked[0][0]


def select(case, budget=None):
    """Return relevant records; apply a cumulative token cap only when explicitly requested.

    The index is the only corpus-wide input. Knowledge files are opened only after
    page/frame/version/status filtering and are loaded in BM25/freshness order.
    """
    case = {'text': case} if isinstance(case, str) else dict(case or {})
    query = ' '.join([*(str(case.get(k) or '') for k in ('title', 'module', 'intent', 'text', 'feature')),
                      ' '.join(str(x) for x in case.get('targets', []) if x)])
    if budget is None and case.get('max_tokens') is not None:
        budget = case['max_tokens']
    if budget is not None:
        budget = int(budget)
        require(budget > 0, 'max-tokens must be a positive integer')
    index = knowledge.load_index()
    eligible = [item for item in index if _hard_filter(item, case)]
    docs = [(_tokens(' '.join([str(item.get('page') or ''), str(item.get('route') or ''),
                               str(item.get('frame') or ''), ' '.join(item.get('tags') or []), str(item.get('summary') or '')])), item)
            for item in eligible]
    average = sum(len(doc) for doc, _ in docs) / len(docs) if docs else 1
    from collections import Counter
    document_frequency = Counter(term for tokens, _ in docs for term in set(tokens))
    qtokens = _tokens(query)
    ranked = []
    for tokens, item in docs:
        score = _bm25(qtokens, tokens, average, len(docs), document_frequency)
        direct = item.get('id') in set(case.get('direct_ids') or [])
        if score > 0 or direct: ranked.append((score, item))
    ranked.sort(key=lambda pair: pair[1]['id'])
    ranked.sort(key=lambda pair: (pair[0], pair[1].get('last_verified') or '', pair[1].get('pass_count', 0), -pair[1].get('fail_count', 0)), reverse=True)
    selected, discarded, read_files, used = [], [], [], 0
    selected_patterns = set()
    for position, (score, item) in enumerate(ranked):
        record = knowledge.load_item(item)
        read_files.append(item['id'])
        if not record or item['status'] in {'needs_review', 'stale', 'deprecated'}:
            discarded.append(item['id']); continue
        compact = {'id': item['id'], 'page': item['page'], 'status': item['status'], 'version': item['version'],
                   'last_verified': item.get('last_verified'), 'summary': item['summary'], 'path': item['path'],
                   'knowledge': record}
        proposed = [*selected, compact]
        cost = estimate_tokens(json.dumps(proposed, ensure_ascii=False, separators=(',', ':')))
        if budget is not None and cost > budget:
            discarded.extend(row['id'] for _, row in ranked[position:])
            break
        selected.append(compact); used = cost
        if record.get('kind') == 'component': selected_patterns.update(record.get('patterns', []))
    # Related patterns are loaded after selecting page/component files, not during corpus scan.
    for pattern_id in sorted(selected_patterns):
        ident = 'pattern.' + pattern_id
        if any(row['id'] == ident for row in selected): continue
        item = next((row for row in index if row['id'] == ident and _hard_filter(row, case)), None)
        if not item: continue
        record = knowledge.load_item(item); read_files.append(ident)
        if not record or item['status'] in {'needs_review', 'stale', 'deprecated'}:
            discarded.append(ident); continue
        compact = {'id': ident, 'page': item['page'], 'status': item['status'], 'version': item['version'],
                   'last_verified': item.get('last_verified'), 'summary': item['summary'], 'path': item['path'], 'knowledge': record}
        cost = estimate_tokens(json.dumps([*selected, compact], ensure_ascii=False, separators=(',', ':')))
        if budget is not None and cost > budget:
            discarded.append(ident)
            continue
        selected.append(compact); used = cost
    # Read-only: usage stats (hit_count/last_hit) are aggregated once per run by knowledge.writeback.
    return {'selected': selected, 'discarded': list(dict.fromkeys(discarded)), 'read_ids': read_files,
            'max_tokens': budget, 'used_tokens': used, 'truncated': bool(discarded) and budget is not None,
            'query_tokens': len(qtokens)}
