#!/usr/bin/env python3
"""只读抽取 XLSX 为中文 Markdown；Python 3 标准库，不依赖 openpyxl。"""
import argparse
import hashlib
from pathlib import Path, PurePosixPath
import posixpath
from xml.etree import ElementTree as ET
from zipfile import ZipFile

M = '{http://schemas.openxmlformats.org/spreadsheetml/2006/main}'
R = '{http://schemas.openxmlformats.org/officeDocument/2006/relationships}'


def read_workbook(filename):
    result = []
    with ZipFile(filename) as archive:
        strings = []
        if 'xl/sharedStrings.xml' in archive.namelist():
            strings = [''.join(x.itertext()) for x in ET.fromstring(archive.read('xl/sharedStrings.xml'))]
        relationships = {r.attrib['Id']: r.attrib['Target'] for r in
                         ET.fromstring(archive.read('xl/_rels/workbook.xml.rels'))}
        workbook = ET.fromstring(archive.read('xl/workbook.xml'))
        for sheet in workbook.find(M + 'sheets'):
            target = relationships[sheet.attrib[R + 'id']]
            member = str(PurePosixPath(target.lstrip('/'))) if target.startswith('/') else posixpath.normpath('xl/' + target)
            tree = ET.fromstring(archive.read(member))
            rows = []
            for row in tree.iter(M + 'row'):
                cells = {}
                for cell in row.findall(M + 'c'):
                    kind = cell.get('t', 'n')
                    if kind == 'inlineStr':
                        value = ''.join(t.text or '' for t in cell.iter(M + 't'))
                    else:
                        value = cell.findtext(M + 'v', '')
                        if kind == 's':
                            value = strings[int(value)]
                    formula = cell.findtext(M + 'f')
                    cells[cell.attrib['r']] = {'value': value, 'type': kind, 'formula': formula}
                rows.append({'number': row.attrib['r'], 'cells': cells})
            result.append({'name': sheet.attrib['name'], 'member': member, 'rows': rows,
                           'merges': [x.attrib['ref'] for x in tree.iter(M + 'mergeCell')]})
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('xlsx', type=Path)
    parser.add_argument('--sheet', required=True, help='明确工作表名，避免同编号多表混淆')
    parser.add_argument('--ids', required=True, nargs='+')
    parser.add_argument('--out', type=Path, help='省略时输出至 stdout')
    args = parser.parse_args()
    sheets = read_workbook(args.xlsx)
    sheet = next((s for s in sheets if s['name'] == args.sheet), None)
    if sheet is None:
        parser.error('工作表不存在；可选：' + '、'.join(s['name'] for s in sheets))
    matched = {key: [r for r in sheet['rows'] if any(c['value'] == key for c in r['cells'].values())] for key in args.ids}
    bad = [key for key, rows in matched.items() if len(rows) != 1]
    if bad:
        parser.error('编号缺失或不唯一：' + '、'.join(bad))
    headers = {''.join(c for c in addr if c.isalpha()): cell['value'] for addr, cell in sheet['rows'][0]['cells'].items()}
    lines = ['# Excel 原文快照', '', f'源文件：{args.xlsx.resolve()}', '',
             f'SHA-256：{hashlib.sha256(args.xlsx.read_bytes()).hexdigest()}', '',
             f'工作表：{sheet["name"]}（{sheet["member"]}）；工作簿共 {len(sheets)} 张工作表。', '',
             '合并单元格：' + ('、'.join(sheet['merges']) or '无') + '。', '',
             '原值保留；字面量 `\\n` 不在此快照中改写。公式不计算，只记录缓存值；空值不自动向下填充。', '']
    for key, rows in matched.items():
        row = rows[0]
        lines.extend([f'## {key}（第 {row["number"]} 行）', ''])
        for addr, cell in row['cells'].items():
            col = ''.join(c for c in addr if c.isalpha())
            lines.extend([f'### {headers.get(col, col)}（{addr}；{cell["type"]}）', '', '~~~~', cell['value'], '~~~~', ''])
            if cell['formula'] is not None:
                lines.extend(['公式（未计算）：' + cell['formula'], ''])
    output = '\n'.join(lines)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(output, encoding='utf-8')
        print(f'已写入 {args.out}；{len(matched)} 条用例。')
    else:
        print(output)


if __name__ == '__main__':
    main()
