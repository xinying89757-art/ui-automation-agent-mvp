import contextlib
import sys
import unittest
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from openpyxl import Workbook, load_workbook

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from uia_core import cli, reports


class ReportTransactionTests(unittest.TestCase):
    def test_excel_rows_remove_controls_without_changing_source(self):
        source = '等待\x1b[2m定位\x1b[22m\x00失败\n下一行'
        workbook = Workbook()
        reports.append_excel(workbook.active, [source, 3, None])
        self.assertEqual(workbook.active.cell(1, 1).value, '等待定位失败\n下一行')
        self.assertEqual(source, '等待\x1b[2m定位\x1b[22m\x00失败\n下一行')
        data = BytesIO()
        workbook.save(data)
        data.seek(0)
        self.assertEqual(load_workbook(data).active.cell(1, 1).value, '等待定位失败\n下一行')

    def test_valid_receipt_is_saved_even_if_report_generation_fails(self):
        manifest = {'cases': {'C': {'result': 'remote_pending'}}, 'questions': {}, 'sources': [],
                    'config': {}, 'preflight': None, 'contaminated_fixtures': {}, 'active_batch': None,
                    'history': [], 'delivery': {}}
        @contextlib.contextmanager
        def locked(_):
            yield Path('/tmp/example-run/run.json'), manifest
        def ingest(_base, m, _file):
            m['cases']['C']['result'] = 'passed'
            return {'ingested': 1, 'cases': {'C': 'passed'}}
        args = SimpleNamespace(command='remote-checks', action='ingest', file='receipt.json', run='R')
        with patch.object(cli, 'locked_run', locked), patch.object(cli, 'save') as save, \
             patch('uia_core.remote_checks.ingest', side_effect=ingest), \
             patch.object(reports, 'make_report', side_effect=OSError('private details')) as report:
            result = cli.execute(args)
        self.assertEqual(result['cases']['C'], 'passed')
        self.assertEqual(result['report'], {'ok': False, 'error': 'OSError'})
        self.assertEqual(save.call_args.args[1]['cases']['C']['result'], 'passed')
        self.assertFalse(report.call_args.kwargs['writeback'])
        self.assertEqual(manifest['history'][-1]['kind'], 'report_generation_failed')


if __name__ == '__main__':
    unittest.main()
