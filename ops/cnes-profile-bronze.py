#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import os
import re
import shutil
import subprocess
from pathlib import Path

CANDIDATES = {
    "cnes": re.compile(r"(^|_)(co_)?cnes($|_)|co_unidade", re.I),
    "municipio": re.compile(r"municip|ibge", re.I),
    "profissional": re.compile(r"prof|cns|cpf|cbo|conselho", re.I),
    "equipe": re.compile(r"equipe|ine", re.I),
    "servico": re.compile(r"servic|classif", re.I),
    "leito": re.compile(r"leito", re.I),
    "equipamento": re.compile(r"equip", re.I),
    "habilitacao": re.compile(r"habilit", re.I),
    "natureza": re.compile(r"natureza", re.I),
    "tipo_estabelecimento": re.compile(r"tipo.*estab|tp_estab", re.I),
}

def q(s: str) -> str:
    return "'" + s.replace("'", "''") + "'"

def duck(sql: str) -> str:
    p=subprocess.run(["duckdb","-csv","-noheader","-c",sql],text=True,capture_output=True)
    if p.returncode:
        raise RuntimeError(p.stderr or p.stdout)
    return p.stdout

def marker(path: Path) -> dict[str,str]:
    out={}
    for line in path.read_text(encoding="utf-8").splitlines():
        if "=" in line:
            k,v=line.split("=",1); out[k]=v
    return out

def main() -> int:
    ap=argparse.ArgumentParser(description="Perfila estruturalmente a Bronze CNES sem scan completo")
    ap.add_argument("--competencia",required=True)
    ap.add_argument("--lake-root",default=os.environ.get("LAKE_ROOT","/dados/abertos/suslabx"))
    args=ap.parse_args()

    if not re.fullmatch(r"\d{6}",args.competencia):
        raise SystemExit("competencia deve ser YYYYMM")
    if not shutil.which("duckdb"):
        raise SystemExit("duckdb CLI ausente")

    lake=Path(args.lake_root)
    state=lake/"state"/"cnes"
    bm=state/f"qc_bronze_{args.competencia}.ok"
    tm=state/f"qc_territorio_{args.competencia}.ok"
    if not bm.is_file() or not tm.is_file():
        raise SystemExit("CNES Bronze/territorio ainda nao homologado")

    bmeta=marker(bm)
    manifest=Path(bmeta["manifest"])
    rows_by_table={}
    parquet_by_table={}
    with manifest.open(encoding="utf-8",newline="") as f:
        for r in csv.DictReader(f,delimiter="\t"):
            rows_by_table[r["table"]]=int(r["rows"])
            parquet_by_table[r["table"]]=Path(r["parquet"])

    ts=subprocess.run(["date","+%Y%m%d_%H%M%S"],text=True,capture_output=True,check=True).stdout.strip()
    out=state/f"profile_{args.competencia}_{ts}.tsv"
    colsout=state/f"profile_columns_{args.competencia}_{ts}.tsv"

    summary=[]
    colsrows=[]

    for idx,table in enumerate(sorted(parquet_by_table),start=1):
        p=parquet_by_table[table]
        desc=duck(f"DESCRIBE SELECT * FROM read_parquet({q(str(p))});")
        cols=[r for r in csv.reader(desc.splitlines()) if r]
        names=[r[0] for r in cols]
        source_cols=[c for c in names if not c.startswith("_")]
        roles={}
        for role,rx in CANDIDATES.items():
            hits=[c for c in source_cols if rx.search(c)]
            roles[role]="|".join(hits)
        for ordinal,r in enumerate(cols,1):
            colsrows.append({
                "table":table,"ordinal":ordinal,"column":r[0],
                "duckdb_type":r[1] if len(r)>1 else "",
                "is_provenance":1 if r[0].startswith("_") else 0,
            })
        summary.append({
            "table":table,
            "rows":rows_by_table.get(table,0),
            "columns":len(source_cols),
            "has_cnes":1 if roles["cnes"] else 0,
            "cnes_columns":roles["cnes"],
            "municipio_columns":roles["municipio"],
            "profissional_columns":roles["profissional"],
            "equipe_columns":roles["equipe"],
            "servico_columns":roles["servico"],
            "leito_columns":roles["leito"],
            "equipamento_columns":roles["equipamento"],
            "habilitacao_columns":roles["habilitacao"],
            "natureza_columns":roles["natureza"],
            "tipo_estab_columns":roles["tipo_estabelecimento"],
            "parquet":str(p),
        })
        print(f"[{idx}/{len(parquet_by_table)}] PROFILE {table} rows={rows_by_table.get(table,0)} cols={len(source_cols)}")

    fields=list(summary[0].keys()) if summary else []
    with out.open("w",encoding="utf-8",newline="") as f:
        w=csv.DictWriter(f,fieldnames=fields,delimiter="\t",lineterminator="\n")
        w.writeheader(); w.writerows(summary)

    with colsout.open("w",encoding="utf-8",newline="") as f:
        fields2=["table","ordinal","column","duckdb_type","is_provenance"]
        w=csv.DictWriter(f,fieldnames=fields2,delimiter="\t",lineterminator="\n")
        w.writeheader(); w.writerows(colsrows)

    latest=state/"profile_latest.ok"
    latest.write_text("\n".join([
        f"competencia={args.competencia}",
        f"timestamp={ts}",
        f"zip_sha256={bmeta.get('zip_sha256','')}",
        f"tables={len(summary)}",
        f"profile={out}",
        f"columns={colsout}",
        "method=parquet_metadata_describe_no_full_scan",
        "status=complete",
        ""
    ]),encoding="utf-8")

    print(f"CNES_PROFILE_OK tables={len(summary)}")
    print(f"profile={out}")
    print(f"columns={colsout}")
    print(f"marker={latest}")
    return 0

if __name__=="__main__":
    raise SystemExit(main())
