#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import os
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

def die(msg: str, code: int = 2):
    print(f"ERRO: {msg}", file=sys.stderr)
    raise SystemExit(code)

def sqls(v: str) -> str:
    return "'" + v.replace("'", "''") + "'"

def run(sql: str, capture: bool = False) -> str:
    p = subprocess.run(["duckdb", "-csv", "-noheader", "-c", sql],
                       text=True, capture_output=True)
    if p.returncode:
        if p.stderr: print(p.stderr, file=sys.stderr)
        raise RuntimeError(f"duckdb rc={p.returncode}")
    return p.stdout if capture else ""

def marker(path: Path) -> dict[str, str]:
    out = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if "=" in line:
            k,v = line.split("=",1)
            out[k]=v
    return out

def decode_to_utf8(data: bytes) -> str:
    for enc in ("utf-8-sig","cp1252","latin-1"):
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            continue
    raise RuntimeError("encoding nao reconhecido")

def main() -> int:
    ap=argparse.ArgumentParser(description="CEP_BRASIL.ZIP -> Bronze reference Parquet")
    ap.add_argument("--lake-root", default=os.environ.get("LAKE_ROOT","/dados/abertos/suslake"))
    ap.add_argument("--zip", type=Path)
    args=ap.parse_args()

    if not shutil.which("duckdb"):
        die("duckdb CLI ausente",3)

    lake=Path(args.lake_root)
    state=lake/"state"/"cnes"
    if args.zip:
        zp=args.zip
        sha=zp.parent.name.removeprefix("sha256=")
    else:
        m=marker(state/"reference_cep_brasil_latest.ok")
        zp=Path(m["path"])
        sha=m["sha256"]
    if not zp.is_file():
        die(f"ZIP ausente: {zp}",4)

    version=sha[:16]
    work=Path(tempfile.mkdtemp(prefix="cep_",dir=lake/"work"))
    try:
        with zipfile.ZipFile(zp) as zf:
            names={Path(x).name.upper():x for x in zf.namelist() if not x.endswith("/")}
            required=["CEP.TXT","CEPALTERADO.TXT"]
            missing=[x for x in required if x not in names]
            if missing:
                die(f"arquivos ausentes no ZIP: {missing}; presentes={sorted(names)[:30]}",5)
            specs=[
                ("cep_cnes","CEP.TXT",["cep","uf","co_municipio"]),
                ("cep_cnes_alterado","CEPALTERADO.TXT",["cep","uf","co_municipio","alteracao"]),
            ]
            for table,base,cols in specs:
                text=decode_to_utf8(zf.read(names[base]))
                src=work/f"{table}.tsv"
                src.write_text(text,encoding="utf-8")
                with src.open(encoding="utf-8",newline="") as f:
                    rows=sum(1 for r in csv.reader(f,delimiter="\t") if r and any(x != "" for x in r))
                destdir=lake/"bronze"/"reference"/table/f"version={version}"
                destdir.mkdir(parents=True,exist_ok=True)
                dest=destdir/"part-000.parquet"
                partial=dest.with_name(dest.name+f".partial.{os.getpid()}")
                names_sql=", ".join(f"column{i} AS {c}" for i,c in enumerate(cols))
                run(f"""
COPY (
 SELECT {names_sql},
        {sqls(sha)}::VARCHAR AS _source_sha256,
        {sqls(zp.name)}::VARCHAR AS _source_file,
        current_timestamp AS _ingested_at
 FROM read_csv_auto(
      {sqls(str(src))},
      delim='\\t',
      header=false,
      all_varchar=true,
      sample_size=-1
 )
)
TO {sqls(str(partial))} (FORMAT PARQUET, COMPRESSION ZSTD);
""")
                pq=int(run(f"SELECT count(*) FROM read_parquet({sqls(str(partial))});",True).strip())
                if pq != rows:
                    raise RuntimeError(f"{table}: TXT={rows} Parquet={pq}")
                os.replace(partial,dest)
                print(f"OK {table} rows={rows} version={version}")

        out=state/"qc_reference_cep_brasil.ok"
        out.write_text("\n".join([
            f"timestamp={subprocess.run(['date','-Is'],text=True,capture_output=True,check=True).stdout.strip()}",
            f"sha256={sha}",
            f"version={version}",
            f"source={zp}",
            "tables=cep_cnes|cep_cnes_alterado",
            "qc=source_record_count_vs_parquet_count",
            ""
        ]),encoding="utf-8")
        print(f"CEP_BRONZE_QC_OK {out}")
        return 0
    finally:
        shutil.rmtree(work,ignore_errors=True)

if __name__=="__main__":
    raise SystemExit(main())
