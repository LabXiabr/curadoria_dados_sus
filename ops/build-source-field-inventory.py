#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import subprocess
from collections import defaultdict
from pathlib import Path

SQL = r'''
SELECT
  table_schema,
  column_name,
  count(DISTINCT table_name)::bigint AS table_count,
  array_to_string(array_agg(DISTINCT ordinal_position ORDER BY ordinal_position), ' ') AS positions,
  string_agg(DISTINCT (data_type || '|' || udt_name), ' ' ORDER BY (data_type || '|' || udt_name)) AS types
FROM information_schema.columns
WHERE table_schema NOT IN ('information_schema','pg_catalog')
  AND table_schema !~ '^pg_toast'
GROUP BY 1,2
ORDER BY 1,2;
'''

def query(service: str) -> list[tuple[str, str, str, str, str]]:
    p = subprocess.run(
        ['psql', f'service={service}', '-X', '-At', '-F', '\t', '-P', 'pager=off', '-c', SQL],
        text=True, capture_output=True,
    )
    if p.returncode:
        raise SystemExit(f'psql {service} falhou: {p.stderr.strip()}')
    out=[]
    for line in p.stdout.splitlines():
        parts=line.split('\t')
        if len(parts) != 5:
            continue
        out.append(tuple(parts))
    return out

def main() -> int:
    ap=argparse.ArgumentParser()
    ap.add_argument('--service', action='append', dest='services')
    ap.add_argument('--output', default='/dados/abertos/suslabx/state/metadata/source_fields_observed_current.tsv')
    ap.add_argument('--schemas-output', default='/dados/abertos/suslabx/state/metadata/source_schemas_observed_current.tsv')
    args=ap.parse_args()
    services=args.services or ['bureta','pipeta']

    data: dict[tuple[str,str], dict[str,tuple[str,str,str]]] = defaultdict(dict)
    schemas: dict[str, dict[str,int]] = defaultdict(dict)

    for svc in services:
        for schema, field, count, pos, types in query(svc):
            data[(schema,field)][svc]=(count,pos,types)
            schemas[schema][svc]=schemas[schema].get(svc,0)+1

    out=Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    cols=['source_schema','source_field']
    for svc in services:
        cols += [f'{svc}_present', f'{svc}_table_count', f'{svc}_positions', f'{svc}_types']
    with out.open('w',encoding='utf-8',newline='') as f:
        w=csv.writer(f,delimiter='\t',lineterminator='\n')
        w.writerow(cols)
        for schema,field in sorted(data, key=lambda x:(x[0],x[1].lower(),x[1])):
            row=[schema,field]
            for svc in services:
                v=data[(schema,field)].get(svc)
                row += ['1' if v else '0', v[0] if v else '', v[1] if v else '', v[2] if v else '']
            w.writerow(row)

    sout=Path(args.schemas_output)
    sout.parent.mkdir(parents=True, exist_ok=True)
    with sout.open('w',encoding='utf-8',newline='') as f:
        w=csv.writer(f,delimiter='\t',lineterminator='\n')
        w.writerow(['source_schema']+[f'{s}_present' for s in services]+['observed_field_count'])
        for schema in sorted(schemas):
            present=[1 if schema in schemas and svc in schemas[schema] else 0 for svc in services]
            field_count=sum(1 for (s,_) in data if s==schema)
            w.writerow([schema,*present,field_count])

    print(f'SOURCE_FIELD_INVENTORY_OK fields={len(data)} schemas={len(schemas)} output={out}')
    return 0

if __name__ == '__main__':
    raise SystemExit(main())
