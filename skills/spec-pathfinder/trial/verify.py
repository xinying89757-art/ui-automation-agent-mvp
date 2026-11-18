#!/usr/bin/env python3
"""磁盘行为验收；只在 trial 输出索引，在临时目录测试修改/删除/动态表达式。"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import runpy
import shutil
import subprocess
import tempfile
from zipfile import ZipFile


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--code-root', required=True, type=Path)
    parser.add_argument('--history-root', required=True, type=Path)
    parser.add_argument('--xlsx', required=True, type=Path)
    args = parser.parse_args()
    trial = Path(__file__).resolve().parent
    script = trial.parent / 'scripts/build-index.mjs'
    events = []

    def run(*cmd, ok=True):
        p = subprocess.run(list(map(str, cmd)), text=True, capture_output=True)
        events.append({'command': list(map(str, cmd)), 'exit': p.returncode, 'stdout': p.stdout.strip(), 'stderr': p.stderr.strip()})
        assert (p.returncode == 0) == ok, events[-1]
        return p.stdout

    def build(root, output, *extra):
        return json.loads(run('node', script, root, '--out', output, *extra))

    def table(output, name):
        p = output / (name + '.json')
        assert p.is_file() and p.stat().st_size > 0, p
        return json.loads(p.read_text())

    run('node', '--check', script)
    fixtures = trial / 'fixtures'
    fixture_out = fixtures / 'index'
    real_out = trial / 'real/index'
    cold_fixture = build(fixtures, fixture_out, '--force')
    assert [cold_fixture[k] for k in ['routes', 'elements', 'actions', 'parsed']] == [6, 6, 4, 3]
    fx_routes = table(fixture_out, 'routes')['entries']
    assert {(x['url'], tuple(x['httpMethods'])) for x in fx_routes} == {
        ('/settings/llms', ('GET',)), ('/prefs/llms', ('GET',)),
        ('/settings/llms/save', ('POST',)), ('/prefs/llms/save', ('POST',)),
        ('/files/remove', ('POST',)), ('/files/delete', ('POST',))}
    assert all('/fake' != x['url'] for x in fx_routes)
    assert next(x for x in fx_routes if x['url'] == '/settings/llms')['views'][0]['name'] == 'settings/llms'
    assert next(x for x in fx_routes if x['url'] == '/settings/llms')['line'] == 10
    fx_elements = table(fixture_out, 'template-elements')['entries']
    assert next(x for x in fx_elements if x['attributes'].get('data-testid') == 'save-llms')['locatorCandidate']['strategy'] == 'data-testid'
    fx_actions = table(fixture_out, 'actions')['entries']
    assert next(x for x in fx_actions if x['url'] == '/settings/llms/save')['successSignals'][0]['kind'] == 'status'
    warm_fixture = build(fixtures, fixture_out)
    assert warm_fixture['parsed'] == 0 and warm_fixture['reused'] == 3

    cold_real = build(args.code_root, real_out, '--force')
    assert [cold_real[k] for k in ['routes', 'elements', 'actions', 'parsed']] == [8, 74, 8, 4]
    real_routes = table(real_out, 'routes')['entries']
    config = next(x for x in real_routes if x['url'] == '/phoenix/customizeFile/llms/config')
    assert {v['name'] for v in config['views']} == {'phoenix_jsp/customizeFile/llms_tab', 'phoenix_jsp/customizeFile/llms_config'}
    save = next(x for x in table(real_out, 'actions')['entries'] if x['kind'] == 'backend-write-candidate' and x['url'] == '/phoenix/customizeFile/llms/save')
    assert save['httpMethods'] == ['POST'] and save['returnType'] == 'void'
    assert any(s['kind'] == 'status' and s['line'] == 477 for s in save['successSignals'])
    assert any(s['kind'] == 'status-check' and s['line'] == 216 for e in save['frontendEvidence'] for s in e['successSignals'])
    assert any('已关闭 llms.txt' in s['excerpt'] for e in save['frontendEvidence'] for s in e['successSignals'])
    real_elements = table(real_out, 'template-elements')['entries']
    assert any(x['file'].endswith('/llms_tab.jsp') and x['line'] == 13 and 'llms-switch' in x['classes'] for x in real_elements)
    assert any(x['file'].endswith('/llms_config.jsp') and x['line'] == 14 and x['id'] == 'llmsEnabled' for x in real_elements)
    warm_real = build(args.code_root, real_out)
    assert warm_real['parsed'] == 0 and warm_real['reused'] == 4

    with tempfile.TemporaryDirectory(prefix='spec-pathfinder-') as temp:
        temp = Path(temp)
        root = temp / 'root'
        shutil.copytree(fixtures / 'demo', root / 'demo')
        output = temp / 'index'
        build(root, output)
        java = root / 'demo/src/main/java/demo/SettingsController.java'
        original = java.read_text()
        stat = java.stat()
        os.utime(java, ns=(stat.st_atime_ns, stat.st_mtime_ns + 5_000_000_000))
        touched = build(root, output)
        assert touched['parsed'] == 1 and touched['reused'] == 2
        java.write_text(original.rsplit('}', 1)[0] + '@GetMapping("/extra") public String extra() { return "extra"; }\n}\n')
        changed = build(root, output)
        assert changed['parsed'] == 1 and changed['reused'] == 2 and changed['routes'] == 8
        added = root / 'AddedController.java'
        added.write_text('@Controller @RequestMapping("/added") public class AddedController { @GetMapping public String p() {return "added";} }')
        assert build(root, output)['routes'] == 9
        added.unlink()
        deleted = build(root, output)
        assert deleted['removed'] == 1 and deleted['routes'] == 8
        (output / 'routes.json').unlink()
        regenerated = build(root, output)
        assert regenerated['reused'] == 3 and table(output, 'routes')['entries']
        other_root = temp / 'other-root'
        shutil.copytree(root, other_root)
        assert build(other_root, output)['parsed'] == 3
        (output / '.cache.json').write_text('bad json')
        assert build(other_root, output)['parsed'] == 3
        dynamic = root / 'DynamicController.java'
        dynamic.write_text('''@Controller @RequestMapping("/base") public class DynamicController {
@GetMapping("/prefix" + SUFFIX) public String a() {return "v";}
@RequestMapping(method=RequestMethod.GET, value=DYNAMIC_PATH) public String b() {return "v";}
@GetMapping({"/literal", DYNAMIC_PATH}) public String c() {return "v";}
}''')
        (root / 'dynamic.js').write_text("const API={save:'/literal'+suffix}; $.ajax({url:API.save,type:'post'}); $.ajax({url:'/prefix'+suffix,type:'post'});")
        build(root, output)
        assert all(x['url'] is None for x in table(output, 'routes')['entries'] if x['controller'] == 'DynamicController')
        assert all(x['url'] is None for x in table(output, 'actions')['entries'] if x['kind'] == 'frontend-request-candidate')
        assert len(table(output, 'routes')['warnings']) >= 5
        run('node', script, temp / 'missing', '--out', output, ok=False)
        run('node', script, ok=False)
        run('node', script, root, '--out', ok=False)

    reader = runpy.run_path(str(trial.parent / 'scripts/read-cases.py'))['read_workbook']
    sheets = reader(args.xlsx)
    wanted = {'TC-0008', 'TC-0009', 'TC-0010', 'TC-0011'}
    def cases(sheet):
        return {r['cells']['A' + r['number']]['value']: r for r in sheet['rows'] if r['cells'].get('A' + r['number'], {}).get('value') in wanted}
    primary = cases(next(s for s in sheets if s['name'] == '测试用例'))
    secondary = cases(next(s for s in sheets if s['name'] == '测试用例-研发自测'))
    assert primary.keys() == secondary.keys() == wanted
    for key in wanted:
        assert primary[key]['number'] == secondary[key]['number']
        row = primary[key]['number']
        for col in 'ABCDEFGHI':
            assert primary[key]['cells'][col + row]['value'] == secondary[key]['cells'][col + row]['value']
        assert primary[key]['cells']['A' + row]['type'] == 'inlineStr'
    with tempfile.TemporaryDirectory(prefix='spec-pathfinder-xlsx-') as temp:
        sample = Path(temp) / 'sample.xlsx'
        with ZipFile(sample, 'w') as z:
            z.writestr('xl/workbook.xml', '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets><sheet name="样本" sheetId="1" r:id="r1"/></sheets></workbook>')
            z.writestr('xl/_rels/workbook.xml.rels', '<Relationships><Relationship Id="r1" Target="worksheets/sheet1.xml"/></Relationships>')
            z.writestr('xl/sharedStrings.xml', '<sst xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><si><t>共享中文</t></si></sst>')
            z.writestr('xl/worksheets/sheet1.xml', '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData><row r="1"><c r="A1" t="s"><v>0</v></c><c r="B1" t="inlineStr"><is><r><t>内联</t></r><r><t>中文</t></r></is></c><c r="C1" t="str"><v>普通字符串</v></c><c r="D1"><f>1+1</f><v>2</v></c></row></sheetData></worksheet>')
        cells = reader(sample)[0]['rows'][0]['cells']
        assert [cells[c]['value'] for c in ['A1', 'B1', 'C1', 'D1']] == ['共享中文', '内联中文', '普通字符串', '2']
        assert cells['D1']['formula'] == '1+1'

    source_files = list(args.code_root.rglob('*'))
    source_files = [p for p in source_files if p.is_file()]
    source_files += [args.history_root / p for p in ['src/txt-manager-page.mjs', 'src/live-fixtures.mjs', 'test/live-p0.test.mjs', 'test/live-extended.test.mjs']]
    by_name = {p.name: p for p in source_files}
    citations = re.findall(r'`([\w.-]+\.(?:java|jsp|js|mjs)):(\d+)`', (trial / 'real/SPEC.md').read_text())
    assert citations
    for name, line in citations:
        assert name in by_name and 1 <= int(line) <= len(by_name[name].read_text().splitlines()), (name, line)
    manifest = [{'path': str(p.resolve()), 'sha256': hashlib.sha256(p.read_bytes()).hexdigest(),
                 'lines': len(p.read_text().splitlines())} for p in sorted(source_files)]
    (trial / 'real/sources-manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + '\n')
    result = {'time': datetime.now(timezone.utc).isoformat(), 'status': '通过',
              'node': run('node', '--version').strip(), 'checks': [
                  'fixtures 路由组合/HTTP 方法/视图常量/注释排除/行号/元素/成功信号',
                  '真实正常与错误视图分支、开关定位、保存端点、helper 状态、JS success/toast 关联',
                  '两目录冷建、暖缓存与三表真实磁盘 JSON 读取',
                  'mtime-only、内容修改、新增删除、缺表重建、根路径切换、坏缓存回退',
                  '动态 Java/JS 路径不伪造及参数错误退出码',
                  '真实 inlineStr 四用例及两工作表 A:I 一致性',
                  '自造 XLSX sharedStrings/inlineStr 富文本/普通字符串/公式缓存',
                  '规格显式文件引用行号范围校验（不代替语义复核）'],
              'citedExplicitLocations': len(citations), 'commands': events}
    (trial / 'acceptance-results.json').write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps({k: v for k, v in result.items() if k != 'commands'}, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
