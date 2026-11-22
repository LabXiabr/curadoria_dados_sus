#!/usr/bin/env python3
from __future__ import annotations

import argparse, csv, re, subprocess, unicodedata
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from bs4 import BeautifulSoup

FORM_URL="http://tabnet.datasus.gov.br/cgi/deftohtm.exe?sih/cnv/qiuf.def"
POST_URL="http://tabnet.datasus.gov.br/cgi/tabcgi.exe?sih/cnv/qiuf.def"

UF_NAME={
"rondonia":"RO","acre":"AC","amazonas":"AM","roraima":"RR","para":"PA","amapa":"AP","tocantins":"TO",
"maranhao":"MA","piaui":"PI","ceara":"CE","rio grande do norte":"RN","paraiba":"PB","pernambuco":"PE",
"alagoas":"AL","sergipe":"SE","bahia":"BA","minas gerais":"MG","espirito santo":"ES","rio de janeiro":"RJ",
"sao paulo":"SP","parana":"PR","santa catarina":"SC","rio grande do sul":"RS","mato grosso do sul":"MS",
"mato grosso":"MT","goias":"GO","distrito federal":"DF"}
MONTH={"janeiro":1,"fevereiro":2,"marco":3,"abril":4,"maio":5,"junho":6,"julho":7,"agosto":8,
"setembro":9,"outubro":10,"novembro":11,"dezembro":12}

def norm(s):
    s=unicodedata.normalize("NFKD",s or "")
    return re.sub(r"\s+"," ","".join(c for c in s if not unicodedata.combining(c))).strip().lower()

def fetch(url,data=None,timeout=180):
    req=Request(url,data=data,headers={"User-Agent":"Mozilla/5.0 SUSLabX-QC","Content-Type":"application/x-www-form-urlencoded"})
    with urlopen(req,timeout=timeout) as r:
        if r.status != 200: raise RuntimeError(f"HTTP {r.status}: {url}")
        return r.read()

def choose(soup,name,terms):
    sel=soup.find("select",attrs={"name":name})
    if not sel: raise RuntimeError(f"select ausente: {name}")
    for o in sel.find_all("option"):
        if any(t in norm(o.get_text(" ",strip=True)) for t in terms):
            return o.get("value","")
    raise RuntimeError(f"opcao {terms} ausente em {name}")

def params_from_form(raw):
    soup=BeautifulSoup(raw.decode("iso-8859-1",errors="replace"),"html5lib")
    form=soup.find("form")
    wanted={
      "Linha":choose(soup,"Linha",["ano/mes processamento","ano/mes process"]),
      "Coluna":choose(soup,"Coluna",["unidade da federacao","uf"]),
      "Incremento":choose(soup,"Incremento",["aih aprovadas"])}
    out=[]; periods=0
    for sel in soup.find_all("select"):
        name=sel.get("name")
        if not name: continue
        if name=="Arquivos":
            vals=[(o.get("value") or "").strip() for o in sel.find_all("option")]
            vals=[v for v in vals if v]
            out += [(name,v) for v in vals]; periods=len(vals); continue
        if name in wanted:
            out.append((name,wanted[name])); continue
        selected=[o.get("value","") for o in sel.find_all("option") if o.has_attr("selected")]
        if selected: out += [(name,v) for v in selected]; continue
        allopt=next((o for o in sel.find_all("option") if "todas as categorias" in norm(o.get_text(" ",strip=True))),None)
        if allopt is not None: out.append((name,allopt.get("value","")))
    if form:
        for i in form.find_all("input"):
            if (i.get("type") or "").lower()=="hidden" and i.get("name"):
                out.append((i["name"],i.get("value","")))
    out += [("formato","table"),("mostre","Mostra")]
    return out,periods

def comp_of(s):
    x=norm(s).lstrip(".").strip()
    m=re.search(r"([a-z]+)[ /-]+(19\d{2}|20\d{2})",x)
    if m and m.group(1) in MONTH: return f"{int(m.group(2)):04d}{MONTH[m.group(1)]:02d}"
    m=re.search(r"(19\d{2}|20\d{2})[/-](\d{1,2})",x)
    return f"{int(m.group(1)):04d}{int(m.group(2)):02d}" if m else None

def num(s):
    s=(s or "").strip()
    if s in {"","-","..."}: return None
    z=re.sub(r"[^0-9-]","",s)
    return int(z) if z not in {"","-"} else None

def parse_tabnet(raw):
    soup=BeautifulSoup(raw.decode("iso-8859-1",errors="replace"),"html5lib")
    out=[]
    for table in soup.find_all("table"):
        trs=table.find_all("tr"); header=None
        for tr in trs[:12]:
            cells=[c.get_text(" ",strip=True) for c in tr.find_all(["th","td"],recursive=False)]
            mapped=[]
            for c in cells[1:]:
                n=norm(re.sub(r"^\d+\s*","",c))
                mapped.append(UF_NAME.get(n) or (n.upper() if re.fullmatch(r"[a-z]{2}",n) else None))
            if sum(x is not None for x in mapped)>=20: header=mapped; break
        if not header: continue
        for tr in trs:
            cells=[c.get_text(" ",strip=True) for c in tr.find_all(["th","td"],recursive=False)]
            if len(cells)<2: continue
            comp=comp_of(cells[0])
            if not comp: continue
            for uf,v in zip(header,cells[1:1+len(header)]):
                n=num(v)
                if uf and n is not None: out.append((comp,uf,n))
    if not out: raise RuntimeError("retorno TabNet sem matriz mensal x UF reconhecivel")
    return out

def parquet(glob):
    g=glob.replace("'","''")
    sql=f"""SELECT lpad(cast(competencia as varchar),6,'0') competencia,
upper(cast(uf as varchar)) uf,
count(DISTINCT trim(cast(n_aih as varchar)))::BIGINT parquet_aih_distintas
FROM read_parquet('{g}', hive_partitioning=true, union_by_name=true)
WHERE n_aih IS NOT NULL AND trim(cast(n_aih as varchar)) <> ''
GROUP BY 1,2 ORDER BY 1,2;"""
    p=subprocess.run(["duckdb","-csv","-c",sql],text=True,capture_output=True)
    if p.returncode: raise RuntimeError(p.stderr.strip())
    return {(r["competencia"],r["uf"]):int(r["parquet_aih_distintas"]) for r in csv.DictReader(p.stdout.splitlines())}

def main():
    ap=argparse.ArgumentParser(description="CQ SIH AIH aprovadas: TabNet qiuf.def x SUSLabX Parquet")
    ap.add_argument("--parquet-glob",required=True)
    ap.add_argument("--output",default="/dados/abertos/suslabx/state/sih/qc_tabnet_aih_aprovadas.csv")
    ap.add_argument("--tabnet-html")
    ap.add_argument("--save-tabnet-html")
    args=ap.parse_args()
    periods=-1
    if args.tabnet_html:
        raw=Path(args.tabnet_html).read_bytes()
    else:
        form=fetch(FORM_URL)
        ps,periods=params_from_form(form)
        raw=fetch(POST_URL,urlencode(ps,doseq=True,encoding="iso-8859-1").encode("ascii"),timeout=300)
        if args.save_tabnet_html:
            p=Path(args.save_tabnet_html); p.parent.mkdir(parents=True,exist_ok=True); p.write_bytes(raw)
    tn={(c,u):v for c,u,v in parse_tabnet(raw)}
    pq=parquet(args.parquet_glob)
    keys=sorted(set(tn)|set(pq)); rows=[]; bad=0
    for c,u in keys:
        a=tn.get((c,u)); b=pq.get((c,u)); dif=None if a is None or b is None else b-a
        st="ok" if dif==0 else "sem_tabnet" if a is None else "sem_parquet" if b is None else "divergente"
        bad += st!="ok"
        rows.append([c,u,a,b,dif,st])
    out=Path(args.output); out.parent.mkdir(parents=True,exist_ok=True)
    with out.open("w",encoding="utf-8",newline="") as f:
        w=csv.writer(f); w.writerow(["competencia","uf","tabnet_aih_aprovadas","parquet_aih_distintas","diferenca","status"]); w.writerows(rows)
    print(f"SIH_TABNET_QC periodos={periods} pares={len(rows)} divergentes={bad} output={out}")
    return 0 if bad==0 else 10

if __name__=="__main__":
    raise SystemExit(main())
