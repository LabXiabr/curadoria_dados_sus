#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import os
import shutil
import subprocess
import sys
from pathlib import Path

EXPECTED_TABLES = {
    "rl_municip_divadm","rl_municip_dsei","rl_municip_macsaud",
    "rl_municip_micibge","rl_municip_pndr","rl_municip_regmetr",
    "rl_municip_regsaud","rl_municip_terrcid","rl_regsaud_macsaud",
    "tb_divadm","tb_dsei","tb_macsaud","tb_micibge","tb_mis",
    "tb_municip","tb_pndr","tb_regiao","tb_regmetr","tb_regsaud",
    "tb_terrcid","tb_uf",
}

EXPECTED_RELATIONSHIPS = {
    "regiao_saude","macrorregiao_saude","microrregiao_ibge",
    "regiao_metropolitana","territorio_cidadania","pndr",
    "divisao_administrativa","dsei",
}

META = {
    "_SOURCE_SNAPSHOT","_SOURCE_ZIP","_SOURCE_SHA256",
    "_SOURCE_FILE","_INGESTED_AT","SNAPSHOT",
}

def die(msg: str, code: int = 20):
    print(f"ERRO: {msg}", file=sys.stderr)
    raise SystemExit(code)

def sqls(v: str) -> str:
    return "'" + str(v).replace("'", "''") + "'"

def duck(sql: str, capture: bool = False) -> str:
    p = subprocess.run(
        ["duckdb","-csv","-noheader","-c",sql],
        text=True,capture_output=True
    )
    if p.returncode:
        if p.stdout: print(p.stdout,file=sys.stderr)
        if p.stderr: print(p.stderr,file=sys.stderr)
        raise RuntimeError(f"duckdb rc={p.returncode}")
    return p.stdout if capture else ""

def marker(path: Path) -> dict[str,str]:
    out={}
    if not path.is_file():
        return out
    for line in path.read_text(encoding="utf-8").splitlines():
        if "=" in line:
            k,v=line.split("=",1); out[k]=v
    return out

def describe(path: Path) -> list[str]:
    out=duck(f"DESCRIBE SELECT * FROM read_parquet({sqls(str(path))});",True)
    return [r[0] for r in csv.reader(out.splitlines()) if r]

def qident(v: str) -> str:
    return '"' + v.replace('"','""') + '"'

def find_col(cols: list[str], *cands: str) -> str | None:
    m={c.upper():c for c in cols}
    for c in cands:
        if c.upper() in m:
            return m[c.upper()]
    return None

def relation_diagnostic(root: Path, rel: str, dim: str, key_candidates: tuple[str,...]):
    rp=root/rel/"current.parquet"
    dp=root/dim/"current.parquet"
    if not rp.is_file() or not dp.is_file():
        return {
            "rel":rel,"dim":dim,"status":"missing_file",
            "rel_cols":[],"dim_cols":[]
        }
    rc=describe(rp); dc=describe(dp)
    rm=find_col(rc,"CO_MUNICIP","CO_MUNINIP")
    rk=find_col(rc,*key_candidates)
    dk=find_col(dc,*key_candidates)
    return {
        "rel":rel,"dim":dim,
        "status":"ok" if rm and rk and dk else "unresolved_schema",
        "municip_col":rm or "",
        "rel_key":rk or "",
        "dim_key":dk or "",
        "rel_cols":rc,
        "dim_cols":dc,
    }

def main() -> int:
    ap=argparse.ArgumentParser()
    ap.add_argument("--lake-root",default=os.environ.get("LAKE_ROOT","/dados/abertos/suslake"))
    args=ap.parse_args()
    if not shutil.which("duckdb"):
        die("duckdb CLI ausente",3)

    lake=Path(args.lake_root)
    state=lake/"state"/"reference"
    terr=lake/"silver"/"reference"/"territorio"
    ctx=lake/"silver"/"reference"/"municipio_contexto"/"current.parquet"
    failures=[]
    warnings=[]

    cur=marker(state/"territorio_current.ok")
    bronze=marker(state/f"territorio_{cur.get('snapshot','')}.bronze.ok") if cur else {}
    mctx=marker(state/"municipio_contexto_current.ok")
    pop=marker(state/"popsvs_complete.ok")
    regportal=marker(state/"regionalizacao_saude_current.ok")

    if not cur:
        failures.append("territorio_current.ok ausente")
    if not bronze:
        failures.append("marker Bronze do snapshot corrente ausente")
    if cur and bronze and cur.get("source_sha256") != bronze.get("source_sha256"):
        failures.append("SHA256 diverge entre current e Bronze")
    if cur and cur.get("tables") != "21":
        failures.append(f"snapshot corrente tem tables={cur.get('tables')} esperado=21")

    current_tables={p.parent.name for p in terr.glob("*/current.parquet")}
    miss_tables=sorted(EXPECTED_TABLES-current_tables)
    extra_tables=sorted(current_tables-EXPECTED_TABLES)
    if miss_tables:
        failures.append("tabelas current ausentes: "+",".join(miss_tables))
    if extra_tables:
        warnings.append("tabelas current adicionais: "+",".join(extra_tables))

    if not ctx.is_file():
        failures.append("municipio_contexto/current.parquet ausente")
    else:
        stats=duck(f"""
SELECT
 count(*) AS rows,
 count(DISTINCT co_municipio) AS mun6,
 count(DISTINCT co_municipio_ibge) AS mun7,
 count(DISTINCT co_uf) AS ufs,
 count(DISTINCT co_regiao) AS regioes,
 count(DISTINCT co_regiao_saude) AS cir,
 count(DISTINCT co_macrorregiao_saude) AS macro,
 count(*) FILTER (WHERE co_regiao_saude IS NULL OR co_regiao_saude='') AS miss_cir,
 count(*) FILTER (WHERE co_macrorregiao_saude IS NULL OR co_macrorregiao_saude='') AS miss_macro,
 max(qt_regiao_saude) AS max_cir_mun,
 max(qt_macrorregiao_saude) AS max_macro_mun,
 count(*) FILTER (WHERE in_capital) AS capitais
FROM read_parquet({sqls(str(ctx))});
""",True).strip()
        vals=list(map(int,next(csv.reader([stats]))))
        keys=["rows","mun6","mun7","ufs","regioes","cir","macro",
              "miss_cir","miss_macro","max_cir_mun","max_macro_mun","capitais"]
        s=dict(zip(keys,vals))
        print("CONTEXTO " + " ".join(f"{k}={v}" for k,v in s.items()))
        if not (s["rows"]==s["mun6"]==s["mun7"]==5571):
            failures.append(f"universo municipal inesperado: {s}")
        if s["ufs"] != 27 or s["regioes"] != 5 or s["capitais"] != 27:
            failures.append(f"cobertura UF/regiao/capital inesperada: {s}")
        if s["miss_cir"] or s["miss_macro"]:
            failures.append(f"faltam CIR/macro: cir={s['miss_cir']} macro={s['miss_macro']}")
        if s["max_cir_mun"] != 1 or s["max_macro_mun"] != 1:
            failures.append(
                f"multiplicidade CIR/macro inesperada: "
                f"cir={s['max_cir_mun']} macro={s['max_macro_mun']}"
            )

    rels=set(filter(None,mctx.get("relationships","").split("|")))
    missing_rels=sorted(EXPECTED_RELATIONSHIPS-rels)
    if missing_rels:
        failures.append("relationships ausentes do contexto: "+",".join(missing_rels))
        diag_specs={
            "regiao_metropolitana":("rl_municip_regmetr","tb_regmetr",
                                     ("CO_REGMETR","CO_REGMET","CO_REGMETRO","CO_RMETR")),
            "divisao_administrativa":("rl_municip_divadm","tb_divadm",
                                      ("CO_DIVADM",)),
        }
        for slug in missing_rels:
            if slug in diag_specs:
                d=relation_diagnostic(terr,*diag_specs[slug])
                print(f"DIAG {slug} status={d['status']} "
                      f"municip_col={d.get('municip_col','')} "
                      f"rel_key={d.get('rel_key','')} dim_key={d.get('dim_key','')}")
                if d["status"]!="ok":
                    print("  rel_cols="+",".join(d["rel_cols"]))
                    print("  dim_cols="+",".join(d["dim_cols"]))

    # DF: reporta todas as divisões administrativas ligadas a Brasília.
    divrel=terr/"rl_municip_divadm"/"current.parquet"
    divdim=terr/"tb_divadm"/"current.parquet"
    if divrel.is_file() and divdim.is_file():
        rc=describe(divrel); dc=describe(divdim)
        rm=find_col(rc,"CO_MUNICIP")
        rk=find_col(rc,"CO_DIVADM")
        dk=find_col(dc,"CO_DIVADM")
        dn=find_col(dc,"DS_NOME","DS_NOMEPAD","DS_ABREV")
        if rm and rk and dk:
            name_expr=f"d.{qident(dn)}" if dn else f"d.{qident(dk)}"
            dfout=duck(f"""
SELECT
 count(DISTINCT cast(r.{qident(rk)} as varchar)),
 string_agg(
   DISTINCT coalesce(nullif(trim(cast({name_expr} as varchar)),''),cast(r.{qident(rk)} as varchar)),
   ' | ' ORDER BY coalesce(nullif(trim(cast({name_expr} as varchar)),''),cast(r.{qident(rk)} as varchar))
 )
FROM read_parquet({sqls(str(divrel))}) r
LEFT JOIN read_parquet({sqls(str(divdim))}) d
 ON cast(d.{qident(dk)} as varchar)=cast(r.{qident(rk)} as varchar)
WHERE trim(cast(r.{qident(rm)} as varchar))='530010';
""",True).strip()
            row=next(csv.reader([dfout]))
            print(f"DF_DIVADM count={row[0]} names={row[1] if len(row)>1 else ''}")

    if not pop:
        failures.append("POPSVS complete marker ausente")
    else:
        if pop.get("from")!="2000" or pop.get("to")!="2025" or pop.get("anos")!="26":
            failures.append(f"POPSVS cobertura inesperada: {pop}")

    if not regportal:
        failures.append("regionalizacao_saude_current.ok ausente")

    # QC portal: divergência conhecida é informativa, não bloqueante.
    qcp=state/"qc_territorio_regionalizacao_latest.ok"
    if qcp.is_file():
        qcm=marker(qcp)
        non_ok={k:v for k,v in qcm.items()
                if k not in {"timestamp","report","ok"} and v not in {"0",""}}
        if non_ok:
            warnings.append("QC Portal divergencias: "+str(non_ok))
    else:
        warnings.append("QC Portal latest marker ausente")

    for w in warnings:
        print("WARN:",w)

    if failures:
        for f in failures:
            print("FAIL:",f,file=sys.stderr)
        print(f"TERRITORIO_CURRENT_QC_FAIL failures={len(failures)}")
        return 20

    ts=subprocess.run(
        ["date","+%Y%m%d_%H%M%S"],
        text=True,capture_output=True,check=True
    ).stdout.strip()
    out=state/"territorio_current_complete.ok"
    out.write_text("\n".join([
        f"timestamp={ts}",
        f"snapshot={cur.get('snapshot','')}",
        f"source_sha256={cur.get('source_sha256','')}",
        "tables=21",
        "municipios=5571",
        "ufs=27",
        "regioes=5",
        f"relationships={'|'.join(sorted(rels))}",
        "popsvs=2000-2025",
        "history=deferred",
        ""
    ]),encoding="utf-8")
    print(f"TERRITORIO_CURRENT_COMPLETE_OK {out}")
    return 0

if __name__=="__main__":
    raise SystemExit(main())
