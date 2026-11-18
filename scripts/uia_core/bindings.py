"""Runtime/delivery bindings are projections of run.json, never a second progress source."""
from .common import inside, read_yaml


def case_bindings(base, manifest):
    entries = {}
    catalog_path = base / "runner/knowledge/network.yaml"
    networks = read_yaml(catalog_path)["rules"] if catalog_path.is_file() else {}
    for cid, case in manifest['cases'].items():
        reg = case.get('registration')
        if not reg:
            continue
        spec = read_yaml(inside(base, case['case_spec'])) if reg.get('case_spec') else None
        entries[cid] = {'case_id': cid, 'hooks': reg['fixture']['hooks'],
                        'mutates': reg['fixture']['mutates'], 'isolated': case['isolated'],
                        'fixture_ids': case['fixture_ids'], 'flow_ids': case['flow_ids'],
                        'start_page': spec.get('start_page') if spec else None, 'spec': spec, 'network_catalog': networks}
    return entries
