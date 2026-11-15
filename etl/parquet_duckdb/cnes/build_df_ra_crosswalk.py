#!/usr/bin/env python3
from __future__ import annotations
import argparse,csv,os,re,shutil,subprocess,sys,unicodedata
from pathlib import Path
ALIASES={"BRASILIA":"PLANOPILOTO","RIACHOFUNDOI":"RIACHOFUNDO"}
def die(msg:str,code:int=20): print(f"ERRO: {msg}",file=sys.stderr); raise SystemExit(code)
def qs(v:str)->str: return "'" + str(v).replace("'","''") + "'"
def qi(v:str)->str: return '"' + v.replace('"','""') + '"'
def duck(sql:str,capture:bool=False)->str:
    p=subprocess.run(["duckdb","-csv","-noheader","-c",sql],text=True,capture_output=True)
    if p.returncode: raise RuntimeError(p.stderr or p.stdout)
    return p.stdout if capture else ""
def cols(path:Path)->dict[str,str]:
    out=duck(f"DESCRIBE SELECT * FROM read_parquet({qs(str(path))});",True)
    return {r[0].upper():r[0] for r in csv.reader(out.splitlines()) if r}
def choose(m:dict[str,str],*cands:str)->str|None:
    for c in cands:
        if c.upper() in m: return m[c.upper()]
    return None
def norm(v:str|None)->str:
    s=unicodedata.normalize("NFKD",v or "")
    s="".join(c for c in s if not unicodedata.combining(c)).upper()
    return re.sub(r"[^A-Z0-9]+","",s)
def code6(v:str)->str:
    d=re.sub(r"[^0-9]","",v or ""); return d[:6] if len(d)>=6 else d
def main()->int:
    ap=argparse.ArgumentParser(); ap.add_argument("--competencia",required=True); ap.add_argument("--lake-root",default=os.environ.get("LAKE_ROOT","/dados/abertos/suslake")); args=ap.parse_args()
    if not re.fullmatch(r"\d{6}",args.competencia): die("competencia deve ser YYYYMM",2)
    lake=Path(args.lake_root)
    estab=lake/"bronze"/"cnes"/"tb_estabelecimento"/f"competencia={args.competencia}"/"part-000.parquet"
    ra=lake/"silver"/"reference"/"ra_df"/"current.parquet"
    out=lake/"silver"/"cnes"/"bridge_localidade_cnes_ra_df"/"current.parquet"; state=lake/"state"/"cnes"
    for p in (estab,ra):
        if not p.is_file(): die(f"arquivo ausente: {p}",4)

    ec=cols(estab)
    e_mun=choose(ec,"CO_MUNICIPIO_GESTOR","CO_MUNICIP_GESTOR"); e_cnes=choose(ec,"CO_CNES")
    if not all([e_mun,e_cnes]):
        die(f"schema estabelecimento nao resolvido: {sorted(ec.values())}",5)

    candidates=[]
    for p in sorted((lake/"bronze"/"cnes").glob(f"*/competencia={args.competencia}/part-000.parquet")):
        mc=cols(p)
        m_code=choose(mc,"CO_MUNICIPIO","CO_MUNICIP","CO_MUN")
        m_name=choose(mc,"NO_MUNICIPIO","DS_NOME","NM_MUNICIPIO","NO_MUNICIP")
        if not all([m_code,m_name]):
            continue
        table=p.parents[1].name
        score=(100 if "municip" in table.lower() else 0) + (10 if table.lower().startswith("tb_") else 0)
        candidates.append((score,table,p,mc,m_code,m_name))
    if not candidates:
        die("nenhuma tabela Bronze CNES com codigo+nome de municipio/localidade foi encontrada",5)
    candidates.sort(key=lambda x:(-x[0],x[1]))
    _,mun_table,mun,mc,m_code,m_name=candidates[0]
    print(f"CNES_DF_RA_DOMAIN table={mun_table} path={mun}")
    raw=f"regexp_replace(trim(cast(e.{qi(e_mun)} as varchar)), '[^0-9]', '', 'g')"
    used=duck(f"""
SELECT CASE WHEN length({raw})>=6 THEN substr({raw},1,6) ELSE {raw} END,count(*),min(trim(cast(e.{qi(e_cnes)} as varchar)))
FROM read_parquet({qs(str(estab))}) e
WHERE substr(CASE WHEN length({raw})>=6 THEN substr({raw},1,6) ELSE {raw} END,1,2)='53'
GROUP BY 1 ORDER BY 1;
""",True)
    used_rows=[r for r in csv.reader(used.splitlines()) if r]
    catalog=duck(f"SELECT trim(cast({qi(m_code)} as varchar)),trim(cast({qi(m_name)} as varchar)) FROM read_parquet({qs(str(mun))}) WHERE substr(regexp_replace(trim(cast({qi(m_code)} as varchar)),'[^0-9]','','g'),1,2)='53';",True)
    names={}
    for code,name in csv.reader(catalog.splitlines()): names[code6(code)]=name
    ra_rows=duck(f"SELECT co_ra_ibge,no_ra FROM read_parquet({qs(str(ra))});",True)
    idx={}
    for code,name in csv.reader(ra_rows.splitlines()): idx.setdefault(norm(name),[]).append((code,name))
    rows=[]; unresolved=0; ambiguous=0
    for code,n,example in used_rows:
        name=names.get(code,""); source_norm=norm(name); target=ALIASES.get(source_norm,source_norm); cand=idx.get(target,[])
        if len(cand)==1:
            ra_code,ra_name=cand[0]; status="matched"; method="alias" if source_norm in ALIASES else "name_exact_normalized"
        elif len(cand)>1:
            ra_code=ra_name=""; status="ambiguous"; method="name_ambiguous"; ambiguous+=1
        else:
            ra_code=ra_name=""; status="unresolved"; method="name_unresolved"; unresolved+=1
        rows.append({"co_localidade_cnes":code,"no_localidade_cnes":name,"rows_estabelecimento":n,"exemplo_cnes":example,"co_ra_ibge":ra_code,"no_ra":ra_name,"match_status":status,"match_method":method})
    out.parent.mkdir(parents=True,exist_ok=True); state.mkdir(parents=True,exist_ok=True)
    detail=state/f"df_ra_crosswalk_{args.competencia}.tsv"
    with detail.open("w",encoding="utf-8",newline="") as f:
        fields=list(rows[0].keys()); w=csv.DictWriter(f,fieldnames=fields,delimiter="\t",lineterminator="\n"); w.writeheader(); w.writerows(rows)
    tmp_tsv=out.with_suffix(".tsv")
    shutil.copyfile(detail,tmp_tsv)
    tmp=out.with_name(out.name+f".partial.{os.getpid()}")
    duck(f"COPY (SELECT *,{qs(args.competencia)}::VARCHAR AS _silver_competencia,current_timestamp AS _built_at FROM read_csv({qs(str(tmp_tsv))},delim='\t',header=true,all_varchar=true)) TO {qs(str(tmp))} (FORMAT PARQUET,COMPRESSION ZSTD);")
    os.replace(tmp,out); tmp_tsv.unlink(missing_ok=True)
    matched=len(rows)-unresolved-ambiguous
    marker=state/f"df_ra_crosswalk_{args.competencia}.ok"; marker.unlink(missing_ok=True)
    if unresolved or ambiguous:
        print(f"CNES_DF_RA_CROSSWALK_FAIL matched={matched} unresolved={unresolved} ambiguous={ambiguous}",file=sys.stderr); print(f"detail={detail}",file=sys.stderr); return 20
    marker.write_text("\n".join([
      f"competencia={args.competencia}",f"timestamp={subprocess.run(['date','+%Y%m%d_%H%M%S'],text=True,capture_output=True,check=True).stdout.strip()}",
      f"localidades={len(rows)}",f"matched={matched}",f"path={out}",f"detail={detail}",
      f"cnes_locality_domain_table={mun_table}",
      "source_ra=IBGE_Localidades_do_Brasil_2022",
      "policy=name_exact_normalized_plus_explicit_aliases;never_CO_UNIDADE_prefix",""
    ]),encoding="utf-8")
    print(f"CNES_DF_RA_CROSSWALK_OK localidades={len(rows)} matched={matched}"); print(f"detail={detail}"); print(f"marker={marker}"); return 0
if __name__=="__main__": raise SystemExit(main())
