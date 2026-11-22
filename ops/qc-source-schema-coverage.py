#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import re
import subprocess
from datetime import datetime
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
CONTRACT=ROOT/'catalog'/'source_schema_contract.tsv'
IGNORE=ROOT/'catalog'/'source_schema_ignore.tsv'

def read_patterns(path: Path, field: str):
    with path.open(encoding='utf-8',newline='') as f:
        rows=list(csv.DictReader(f,delimiter='\t'))
    return [(r[field], re.compile(r[field]), r) for r in rows if r.get(field)]

def query_schemas(service: str) -> set[str]:
    sql="SELECT DISTINCT table_schema FROM information_schema.tables ORDER BY 1;"
    p=subprocess.run(['psql',f'service={service}','-X','-At','-P','pager=off','-c',sql],text=True,capture_output=True)
    if p.returncode:
        raise SystemExit(f'psql {service} falhou: {p.stderr.strip()}')
    return {x.strip() for x in p.stdout.splitlines() if x.strip()}

def main() -> int:
    ap=argparse.ArgumentParser()
    ap.add_argument('--service',action='append',dest='services')
    ap.add_argument('--state-root',default='/dados/abertos/suslabx/state/metadata')
    args=ap.parse_args()
    services=args.services or ['bureta','pipeta']

    contracts=read_patterns(CONTRACT,'schema_pattern')
    ignores=read_patterns(IGNORE,'schema_pattern')
    seen={svc:query_schemas(svc) for svc in services}
    all_schemas=sorted(set().union(*seen.values()))
    rows=[]; bad=0

    for schema in all_schemas:
        cm=[r for _,rx,r in contracts if rx.fullmatch(schema)]
        im=[r for _,rx,r in ignores if rx.fullmatch(schema)]
        if len(cm)==1 and not im:
            cls='source'; system=cm[0]['system']; status='ok'
        elif not cm and len(im)>=1:
            cls='ignored_local'; system=''; status='ok'
        elif not cm and not im:
            cls='unclassified'; system=''; status='fail'; bad+=1
        else:
            cls='ambiguous'; system='|'.join(sorted({r.get('system','') for r in cm})); status='fail'; bad+=1
        rows.append([schema,*(1 if schema in seen[s] else 0 for s in services),cls,system,status])

    state=Path(args.state_root); state.mkdir(parents=True,exist_ok=True)
    ts=datetime.now().strftime('%Y%m%d_%H%M%S')
    report=state/f'source_schema_coverage_{ts}.tsv'
    with report.open('w',encoding='utf-8',newline='') as f:
        w=csv.writer(f,delimiter='\t',lineterminator='\n')
        w.writerow(['source_schema']+[f'{s}_present' for s in services]+['classification','system','status'])
        w.writerows(rows)

    if bad:
        print(f'SOURCE_SCHEMA_COVERAGE_FAIL bad={bad} report={report}')
        return 20
    marker=state/'source_schema_coverage_current.ok'
    marker.write_text(f'timestamp={ts}\nschemas={len(rows)}\nreport={report}\nstatus=validated\n',encoding='utf-8')
    print(f'SOURCE_SCHEMA_COVERAGE_OK schemas={len(rows)} report={report}')
    return 0

if __name__ == '__main__':
    raise SystemExit(main())
