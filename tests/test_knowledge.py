import json
import sys
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from uia_core import common, knowledge, retrieval, metrics, cli


class KnowledgeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name) / 'repo'; self.root.mkdir()
        self.old_root, self.old_common = knowledge.ROOT, common.ROOT
        knowledge.ROOT = self.root / 'knowledge'; common.ROOT = self.root
        knowledge.ROOT.mkdir()
        (self.root/'schemas').mkdir()
        import shutil
        shutil.copyfile(Path(__file__).resolve().parents[1]/'schemas/knowledge-index.schema.json', self.root/'schemas/knowledge-index.schema.json')
        shutil.copyfile(Path(__file__).resolve().parents[1]/'schemas/knowledge-patterns.schema.json', self.root/'schemas/knowledge-patterns.schema.json')
        self.addCleanup(self.restore_roots)
        common.atomic_write(knowledge.ROOT / 'entries.yaml', {'schema_version':'entry-hints.v1','entries':{}}, as_yaml=True)
        common.atomic_write(knowledge.ROOT / 'page-map.yaml', {'schema_version':'page-map.v1','pages':{},'targets':{}}, as_yaml=True)
        common.atomic_write(knowledge.ROOT / 'patterns.yaml', {'schema_version':'uia-patterns.v1','patterns':{
            'FRAME_JOIN': {'description':'Nested frame chain.', 'strategy':'frame_chain'},
            'RERENDER_RELOCATE': {'description':'Stable redraw locator.', 'strategy':'stable_relocate','retries':3},
            'OCCLUDED_SCROLL_OR_COLLAPSE': {'description':'Scroll then collapse overlay.', 'strategy':'scroll_collapse','retries':2}}}, as_yaml=True)
        common.atomic_write(knowledge.ROOT / 'experience.yaml', {'schema_version':'uia-experience.v1','entries':{}}, as_yaml=True)
        common.atomic_write(knowledge.ROOT / 'config.yaml', {'prompt_budget_chars':8000,'prune_after_days':365}, as_yaml=True)

    def restore_roots(self):
        knowledge.ROOT, common.ROOT = self.old_root, self.old_common

    def test_index_selects_relevant_file_and_explicit_token_budget(self):
        pages = {'schema_version':'page-map.v1','pages': {'faq': {'entry':'内容管理 FAQ'}}, 'targets': {
            'faq.answer': {'frame':'#faq','selector':'.answer','patterns':['FRAME_JOIN'], 'label':'FAQ 答案'},
            'faq.answer.large': {'selector':'.answer-large','label':'FAQ 答案','description':'x'*1200}}}
        knowledge.sync_layout(pages=pages)
        selected = retrieval.select({'page':'faq','title':'FAQ 答案'}, budget=300)
        ids = [x['id'] for x in selected['selected']]
        self.assertIn('target.faq.answer', ids)
        self.assertIn('pattern.FRAME_JOIN', ids)
        self.assertIn('target.faq.answer.large', selected['discarded'])
        self.assertLessEqual(selected['used_tokens'], 300)
        index = common.read_yaml(knowledge.ROOT/'index.yaml')
        self.assertTrue(all({'id','page','route','frame','tags','version','status','last_verified','summary','path'} <= set(row) for row in index['entries']))
        self.assertEqual(next(row for row in index['entries'] if row['id']=='target.faq.answer')['hit_count'], 0)  # query is read-only

    def test_hits_are_aggregated_once_per_run_by_writeback(self):
        pages={'schema_version':'page-map.v1','pages':{'faq':{}},'targets':{'faq.answer':{'selector':'.a','label':'FAQ'}}}
        common.atomic_write(knowledge.ROOT/'page-map.yaml', pages, as_yaml=True); knowledge.sync_layout(pages=pages)
        base = Path(tempfile.mkdtemp()); self.addCleanup(lambda: __import__('shutil').rmtree(base, True))
        common.atomic_write(base/'km.json', {'matched': {'C1': {'target.faq.answer': {}}, 'C2': {'target.faq.answer': {}}}})
        m = {'run_id': 'R1', 'cases': {}, 'knowledge_match': {'file': 'km.json'}}
        for _ in range(2):
            knowledge.writeback(base, m)
        row = next(r for r in common.read_yaml(knowledge.ROOT/'index.yaml')['entries'] if r['id']=='target.faq.answer')
        self.assertEqual(row['hit_count'], 2)
        self.assertTrue(row['last_hit'])

    def test_default_query_is_untruncated_and_hard_filters_page_version_and_status(self):
        pages={'schema_version':'page-map.v1','pages':{'faq':{},'editor':{}},'targets':{
            'faq.answer':{'label':'FAQ答案','selector':'.answer','version':'v1'},
            'faq.review':{'label':'FAQ复核','selector':'.review','status':'needs_review','version':'v1'},
            'editor.button':{'label':'FAQ答案编辑器按钮','selector':'.button','version':'v1'}}}
        knowledge.sync_layout(pages=pages)
        result=retrieval.select({'page':'faq','version':'v1','title':'FAQ答案'})
        ids=[row['id'] for row in result['selected']]
        self.assertIn('target.faq.answer',ids)
        self.assertNotIn('target.faq.review',ids)
        self.assertNotIn('target.editor.button',ids)
        self.assertIsNone(result['max_tokens'])
        self.assertFalse(result['truncated'])

    def test_flat_merge_deduplicates_locator_and_keeps_provenance(self):
        source = Path(self.tmp.name)/'src'; source_knowledge=source/'assets/playwright-runner/knowledge'; source_knowledge.mkdir(parents=True)
        run=source/'runs/R'; run.mkdir(parents=True)
        common.atomic_write(source_knowledge/'entries.yaml', {'schema_version':'entry-hints.v1','entries':{'FAQ编辑':{'label':'FAQ编辑','path_text':'内容管理 → FAQ'}}}, as_yaml=True)
        common.atomic_write(source_knowledge/'page-map.yaml', {'schema_version':'page-map.v1','pages':{'faq':{'entry':'FAQ编辑'}},'targets':{
            'faq.answer':{'frame':'#faq','selector':'.answer'}, 'faq.answer.copy':{'frame':'#faq','selector':'.answer'}}}, as_yaml=True)
        common.atomic_write(run/'run.json', {'run_id':'R','cases':{'C1':{'case_spec':'cases/C1/case-spec.yaml','attempts':[{'executed':True,'result':'passed'}]}}})
        spec=run/'cases/C1/case-spec.yaml'; spec.parent.mkdir(parents=True); common.atomic_write(spec, {'start_page':'faq','steps':[{'target':'faq.answer'}]}, as_yaml=True)
        (self.root/'assets/playwright-runner/knowledge').mkdir(parents=True)
        stats=knowledge.merge(source_knowledge,'R')
        catalog=common.read_yaml(knowledge.ROOT/'page-map.yaml')
        self.assertEqual(catalog['targets']['faq.answer.copy']['alias_of'],'faq.answer')
        self.assertEqual(catalog['targets']['faq.answer']['provenance']['verified_by'], ['C1'])
        self.assertEqual(stats['unverified'], 2)  # entry and locator alias absent from the exercised spec
        self.assertTrue((knowledge.ROOT/'index.yaml').is_file())
        self.assertTrue(list((knowledge.ROOT/'pages').glob('*.yaml')))

    def test_prune_marks_after_90_days_and_lists_180_day_candidates_without_deleting(self):
        pages={'schema_version':'page-map.v1','pages':{},'targets':{
            'old.unused':{'selector':'.old','last_verified':(date.today()-timedelta(days=200)).isoformat()},
            'recent.unused':{'selector':'.recent','last_verified':(date.today()-timedelta(days=20)).isoformat()}}}
        knowledge.sync_layout(pages=pages)
        result=knowledge.prune()
        old=next(x for x in result['stale_marked'] if x=='target.old.unused')
        self.assertEqual(old,'target.old.unused')
        self.assertIn('target.old.unused',result['deletion_candidates'])
        self.assertNotIn('target.recent.unused',result['deletion_candidates'])
        self.assertTrue((knowledge.ROOT/'components/target-old-unused.yaml').is_file())
        self.assertFalse(result['deleted'])
        self.assertNotIn('target.old.unused',[x['id'] for x in retrieval.select({'page':'old'})['selected']])

    def test_go_matching_persists_only_budgeted_items_and_truncated_ids(self):
        pages={'schema_version':'page-map.v1','pages':{'faq':{'entry':'FAQ 页面'}},'targets':{'faq.answer':{'label':'FAQ 答案','selector':'.answer'}}}
        knowledge.sync_layout(pages=pages)
        base=self.root/'runs/R'; base.mkdir(parents=True)
        common.atomic_write(base/'case.json', {'title':'FAQ 答案','expected':'检查 FAQ 页面答案'})
        m={'run_id':'R','cases':{'C1':{'source':'case.json','title':'FAQ 答案'}}}
        result=knowledge.match_run(base,m)
        self.assertIn('C1',result['matched'])
        self.assertTrue((base/'knowledge-match.json').is_file())
        self.assertIn('discarded',result)
        self.assertIsNone(result['budgets']['C1']['max_tokens'])
        measured=metrics.calculate(base,m)['knowledge_injected_tokens']
        self.assertEqual(measured['count'],1)
        self.assertGreater(measured['p95'],0)

    def test_match_run_filters_same_page_siblings_without_default_token_cap(self):
        pages={'schema_version':'page-map.v1','pages':{'content-admin':{'entry':'内容管理'}},'targets':{}}
        for i in range(12):
            pages['targets'][f'content-admin.unrelated{i}']={'label':f'unrelated widget {i}', 'selector':f'.unrelated-{i}', 'description':'details '*20}
        pages['targets']['content-admin.article-import']={'label':'Article Markdown import command menu', 'selector':'[role="menuitem"]'}
        pages['targets']['content-admin.product-title']={'label':'Product title editor field', 'selector':'input.product-title'}
        knowledge.sync_layout(pages=pages)
        base=self.root/'runs/R'; base.mkdir(parents=True)
        for cid,target,title in [('C1','content-admin.article-import','Article Markdown import'),('C2','content-admin.product-title','Product title editor')]:
            common.atomic_write(base/f'{cid}.json', {'title':title, 'expected':'verify the target'})
            common.atomic_write(base/f'{cid}.yaml', {'start_page':'content-admin','intent':f'operate {title}',
                'steps':[{'id':'S1','verb':'click','target':target}], 'assertions':[]}, as_yaml=True)
        m={'run_id':'R','cases':{
            'C1':{'source':'C1.json','case_spec':'C1.yaml','title':'Article Markdown import'},
            'C2':{'source':'C2.json','case_spec':'C2.yaml','title':'Product title editor'}}}
        result=knowledge.match_run(base,m)
        first=set(result['matched']['C1']); second=set(result['matched']['C2'])
        self.assertNotEqual(first,second)
        self.assertIn('target.content-admin.article-import',first)
        self.assertNotIn('target.content-admin.product-title',first)
        self.assertIn('target.content-admin.product-title',second)
        self.assertNotIn('target.content-admin.article-import',second)
        self.assertLess(len(first),13)
        self.assertLess(len(second),13)
        self.assertTrue(all(row['max_tokens'] is None for row in result['budgets'].values()))

    def test_partial_writeback_keeps_successful_steps_after_assertion_failure(self):
        pages={'schema_version':'page-map.v1','pages':{'faq':{}},'targets':{'faq.cancel':{'selector':'button.cancel'}}}
        common.atomic_write(knowledge.ROOT/'page-map.yaml',pages,as_yaml=True)
        knowledge.sync_layout(pages=pages)
        base=self.root/'runs/R'; base.mkdir(parents=True)
        common.atomic_write(base/'C1.yaml',{'start_page':'faq','steps':[{'id':'S1','verb':'click','target':'faq.cancel'}],
            'assertions':[{'id':'A1','after':'S1','checks':[{'target':'faq.cancel'}]}]},as_yaml=True)
        manifest={'run_id':'R','cases':{'C1':{'case_id':'C1','case_spec':'C1.yaml','attempts':[
            {'executed':True,'result':'business_failure','successful_steps':['S1'],'assertions':[{'id':'A1','passed':False}]}]}}}
        result=knowledge.writeback(base,manifest)
        self.assertEqual(result['partial_count'],1)
        page_map=common.read_yaml(knowledge.ROOT/'page-map.yaml')
        proof=page_map['targets']['faq.cancel']['provenance'][-1]
        self.assertEqual(proof['evidence'],'executed_successful_steps')
        self.assertEqual(proof['verified_by'],['C1'])

    def test_kb_query_has_no_default_token_limit(self):
        args=cli.parser().parse_args(['kb','query','--case','C1'])
        self.assertIsNone(args.max_tokens)

    def test_missing_control_exploration_is_not_counted_as_known_page_reexploration(self):
        pages={'schema_version':'page-map.v1','pages':{'content-admin':{'entry':'内容管理'}},
               'targets':{'content-admin.article-list':{'label':'文章列表'}}}
        entries={'schema_version':'entry-hints.v1','entries':{}}
        common.atomic_write(knowledge.ROOT/'page-map.yaml',pages,as_yaml=True)
        common.atomic_write(knowledge.ROOT/'entries.yaml',entries,as_yaml=True)
        knowledge.sync_layout(pages=pages,entries=entries)
        missing=knowledge.exploration_knowledge('markdown-slash-menu','content-admin')
        known=knowledge.exploration_knowledge('content-admin.article-list','content-admin')
        self.assertTrue(missing['exploration_for_missing_controls'])
        self.assertFalse(missing['re_explored'])
        self.assertFalse(known['exploration_for_missing_controls'])
        self.assertTrue(known['re_explored'])
        base=self.root/'runs/METRIC'; base.mkdir(parents=True)
        result=metrics.calculate(base,{'cases':{},'exploration':[missing,known]})
        self.assertEqual(result['re_explored_known_pages'],1)
        self.assertEqual(result['exploration_for_missing_controls'],1)

    def test_writeback_requires_repeated_verified_execution_and_records_freshness(self):
        pages={'schema_version':'page-map.v1','pages':{'faq':{'entry':'FAQ'}},'targets':{'faq.answer':{'selector':'.answer'}}}
        common.atomic_write(knowledge.ROOT/'page-map.yaml',pages,as_yaml=True)
        knowledge.sync_layout(pages=pages)
        base=self.root/'runs/R'; (base/'cases/C1').mkdir(parents=True); (base/'cases/C2').mkdir(parents=True)
        specs={}
        for cid in ('C1','C2'):
            rel=f'cases/{cid}/case-spec.yaml'; specs[cid]=rel
            common.atomic_write(base/rel, {'start_page':'faq','steps':[{'target':'faq.answer'}]}, as_yaml=True)
        m={'run_id':'R','cases':{cid:{'case_spec':rel,'attempts':[{'executed':True,'result':'passed'}]} for cid,rel in specs.items()}}
        result=knowledge.writeback(base,m)
        self.assertTrue(any(x['name']=='faq.answer' for x in result['added_or_updated']))
        row=common.read_yaml(knowledge.ROOT/'page-map.yaml')['targets']['faq.answer']
        self.assertEqual(row['provenance'][0]['verified_by'],['C1','C2'])
        index=common.read_yaml(knowledge.ROOT/'index.yaml')['entries']
        self.assertIsNotNone(next(x for x in index if x['id']=='target.faq.answer')['last_verified'])
        self.assertEqual(metrics.calculate(base,{'cases':{},'exploration':[{'known_page':True,'re_explored':True}]})['re_explored_known_pages'],1)

    def test_single_success_does_not_write_back_locator_as_verified(self):
        pages={'schema_version':'page-map.v1','pages':{'faq':{}},'targets':{'faq.answer':{'selector':'.answer'}}}
        common.atomic_write(knowledge.ROOT/'page-map.yaml',pages,as_yaml=True); knowledge.sync_layout(pages=pages)
        base=self.root/'runs/ONE'; (base/'cases/C1').mkdir(parents=True)
        rel='cases/C1/case-spec.yaml'; common.atomic_write(base/rel,{'start_page':'faq','steps':[{'target':'faq.answer'}]},as_yaml=True)
        knowledge.writeback(base,{'run_id':'ONE','cases':{'C1':{'case_spec':rel,'attempts':[{'executed':True,'result':'passed'}]}}})
        row=next(x for x in common.read_yaml(knowledge.ROOT/'index.yaml')['entries'] if x['id']=='target.faq.answer')
        target=common.read_yaml(knowledge.ROOT/'page-map.yaml')['targets']['faq.answer']
        self.assertIsNone(row['last_verified'])
        self.assertNotIn('provenance',target)

    def test_writeback_extracts_repeated_failure_to_successful_locator_repair_pattern(self):
        pages={'schema_version':'page-map.v1','pages':{},'targets':{}}
        common.atomic_write(knowledge.ROOT/'page-map.yaml',pages,as_yaml=True)
        base=self.root/'runs/REPAIR'; base.mkdir(parents=True)
        cases={}
        for cid in ('C1','C2'):
            before=f'cases/{cid}/before.spec.ts'; after=f'runner/tests/{cid}.spec.ts'
            (base/before).parent.mkdir(parents=True,exist_ok=True); (base/after).parent.mkdir(parents=True,exist_ok=True)
            (base/before).write_text("await page.locator('.old').click();\n",encoding='utf-8')
            (base/after).write_text("await page.getByRole('button', { name: 'Save' }).click();\n",encoding='utf-8')
            cases[cid]={'attempts':[
                {'executed':True,'result':'automation_failure','failure_stage':'locator'},
                {'executed':True,'result':'passed','repair_baseline_script':before,'repair_script':after}]}
        result=knowledge.writeback(base,{'run_id':'REPAIR','cases':cases})
        self.assertEqual(result['count'],1)
        experience=common.read_yaml(knowledge.ROOT/'experience.yaml')['entries']
        row=next(value for key,value in experience.items() if key.startswith('repair-locator-'))
        self.assertIn('更新并限定目标定位器',row['summary'])
        self.assertEqual(row['provenance']['verified_by'],['C1','C2'])

    def test_writeback_is_idempotent_and_sets_needs_review_after_two_run_failures(self):
        pages={'schema_version':'page-map.v1','pages':{'faq':{}},'targets':{'faq.answer':{'selector':'.answer'}}}
        common.atomic_write(knowledge.ROOT/'page-map.yaml',pages,as_yaml=True); knowledge.sync_layout(pages=pages)
        base=self.root/'runs/R'; (base/'cases/C1').mkdir(parents=True)
        rel='cases/C1/case-spec.yaml'; common.atomic_write(base/rel,{'start_page':'faq','steps':[{'target':'faq.answer'}]},as_yaml=True)
        for run_id in ('R1','R2'):
            manifest={'run_id':run_id,'cases':{'C1':{'case_spec':rel,'attempts':[{'executed':True,'result':'automation_failure','batch_id':run_id}]}}}
            knowledge.writeback(base,manifest)
        index=common.read_yaml(knowledge.ROOT/'index.yaml')['entries']
        self.assertEqual(next(x for x in index if x['id']=='target.faq.answer')['status'],'needs_review')
        self.assertNotIn('target.faq.answer',[x['id'] for x in retrieval.select({'page':'faq'})['selected']])

    def test_validator_rejects_duplicate_locator_and_unsafe_record(self):
        pages={'schema_version':'page-map.v1','pages':{'faq':{}},'targets':{
            'faq.a':{'selector':'.same'},'faq.b':{'selector':'.same'}}}
        knowledge.sync_layout(pages=pages)
        with self.assertRaises(common.UiaError): knowledge.validate()


if __name__ == '__main__': unittest.main()
