import json
import tempfile
import unittest
from pathlib import Path

from uia_core import common, knowledge, knowledge_review


class KnowledgeReviewTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name).resolve()
        self.old_common, self.old_knowledge = common.ROOT, knowledge.ROOT
        common.ROOT = self.root
        knowledge.ROOT = self.root / 'knowledge'
        knowledge.ROOT.mkdir()
        (self.root / 'assets/playwright-runner/knowledge').mkdir(parents=True)
        for name, data in [('entries.yaml', {'schema_version':'entry-hints.v1','entries':{}}),
                           ('page-map.yaml', {'schema_version':'page-map.v1','pages':{},'targets':{}}),
                           ('experience.yaml', {'schema_version':'uia-experience.v1','entries':{}})]:
            common.atomic_write(knowledge.ROOT / name, data, as_yaml=True)
        self.base = self.root / 'runs/R'
        self.base.mkdir(parents=True)
        (self.base / 'evidence.json').write_text('{}')
        self.m = {'run_id':'R','knowledge_review_candidates':[
            {'kind':'experience','id':ident,'scope':'test','after':{'summary':ident},'evidence':['evidence.json']}
            for ident in ['one','two']]}
        self.review = self.root / 'review.json'

    def tearDown(self):
        common.ROOT, knowledge.ROOT = self.old_common, self.old_knowledge
        self.tmp.cleanup()

    def make_review(self, decisions=('approve','defer')):
        rows = knowledge_review.candidates(self.base, self.m)
        body = {'schema_version':'uia-knowledge-review.v1','run_id':'R',
                'items':[{'id':row['id'],'version':row['version'],'decision':decision} for row, decision in zip(rows, decisions)]}
        self.review.write_text(json.dumps(body))
        return body

    def test_selective_and_idempotent(self):
        self.make_review()
        result = knowledge_review.writeback(self.base,self.m,self.review)
        self.assertEqual([x['id'] for x in result['applied']], ['one'])
        self.assertEqual(set(knowledge.catalog('experience.yaml')['entries']), {'one'})
        self.assertTrue(knowledge_review.writeback(self.base,self.m,self.review)['already_applied'])

    def test_approval_preserves_unrelated_resource_and_index_rows(self):
        from copy import deepcopy
        unrelated = {'schema_version':'uia-experience.v1','entries': {'unrelated': {'summary':'keep'}}}
        common.atomic_write(knowledge.ROOT / 'experience.yaml', unrelated, as_yaml=True)
        knowledge.sync_layout(experience=unrelated)
        index = knowledge.catalog('index.yaml')
        old_row = next(row for row in index['entries'] if row['id'] == 'experience.unrelated')
        old_file = (knowledge.ROOT / old_row['path']).read_bytes()
        old_index_row = deepcopy(old_row)
        self.make_review()
        knowledge_review.writeback(self.base, self.m, self.review)
        self.assertEqual((knowledge.ROOT / old_row['path']).read_bytes(), old_file)
        self.assertEqual(next(row for row in knowledge.catalog('index.yaml')['entries'] if row['id'] == 'experience.unrelated'), old_index_row)
        self.assertEqual(knowledge.catalog('experience.yaml')['entries']['unrelated'], {'summary':'keep'})

    def test_missing_review_and_changed_candidate_and_shared_conflict(self):
        with self.assertRaises(common.UiaError): knowledge_review.writeback(self.base,self.m,None)
        self.make_review()
        self.m['knowledge_review_candidates'][0]['after']['summary'] = 'changed'
        with self.assertRaises(common.UiaError): knowledge_review.writeback(self.base,self.m,self.review)
        self.assertFalse(knowledge.catalog('experience.yaml')['entries'])
        self.make_review()
        common.atomic_write(knowledge.ROOT / 'experience.yaml', {'entries':{'one':{'summary':'other'}}}, as_yaml=True)
        with self.assertRaises(common.UiaError): knowledge_review.writeback(self.base,self.m,self.review)
        self.assertEqual(knowledge.catalog('experience.yaml')['entries']['one']['summary'], 'other')
        refreshed = common.read_json(self.base / 'reports/asset-review-conflicts.json')
        self.assertEqual(refreshed['candidates'][0]['before']['summary'], 'other')

    def test_proposal_requires_provenance_and_successful_referenced_cases(self):
        common.atomic_write(self.base / 'batch/case-results.json', {'cases':[{'case_id':'C1','result':'passed'}]})
        ref = 'batch/case-results.json'
        item = {'kind':'entry','id':'route','scope':'test','evidence':[ref],
                'after':{'summary':'open','last_verified':'2026-11-25','arrival_signal':'ready',
                         'provenance':{'source_run':'R','verified_at':'2026-11-25','verified_by':['C1'],'evidence':[ref]}}}
        manifest = {'run_id':'R','config':{}}
        self.assertEqual(knowledge_review.propose(self.base, manifest, item)['candidate']['id'], 'route')
        invalid = dict(item, id='wrong')
        invalid['after'] = {**item['after'], 'provenance':{**item['after']['provenance'], 'verified_by':['C2']}}
        with self.assertRaises(common.UiaError): knowledge_review.propose(self.base, manifest, invalid)
        self.assertEqual(len(manifest['knowledge_review_candidates']), 1)

    def test_local_hints_are_resolved_only_in_run_and_do_not_modify_shared(self):
        from uia_core import entries
        shared = self.root / 'assets/playwright-runner/knowledge/entries.yaml'
        common.atomic_write(shared, {'schema_version':'entry-hints.v1','entries':{}}, as_yaml=True)
        before = shared.read_bytes()
        token = common.CURRENT_RUN_BASE.set(self.base)
        try:
            entries.add({'run_id':'R','config':{}}, '产品描述=内容管理 → 产品')
            self.assertEqual(entries.resolve('产品描述')['path_text'], '内容管理 → 产品')
            matches = knowledge.local_matches(self.base, {'start_page':'产品描述'}, '产品描述')
            self.assertEqual(matches[0]['status'], 'run_local')
        finally:
            common.CURRENT_RUN_BASE.reset(token)
        self.assertEqual(shared.read_bytes(), before)
        self.assertIsNone(entries.resolve('产品描述'))

    def test_reject_and_defer_do_not_write(self):
        self.make_review(('reject','defer'))
        self.assertEqual(knowledge_review.writeback(self.base,self.m,self.review)['applied'], [])
        self.assertFalse(knowledge.catalog('experience.yaml')['entries'])

if __name__ == '__main__': unittest.main()
