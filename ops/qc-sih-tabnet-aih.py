#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import re
import subprocess
import unicodedata
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen

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
    req=Request(url,data=data,headers={
        "User-Agent":"Mozilla/5.0 SUSLabX-QC",
        "Content-Type":"application/x-www-form-urlencoded",
    })
    with urlopen(req,timeout=timeout) as r:
        if r.status != 200:
            raise RuntimeError(f"HTTP {r.status}: {url}")
        return r.read()

class FormParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.selects=[]
        self.current=None
        self.option=None
        self.hidden=[]

    def flush_option(self):
        if self.current is not None and self.option is not None:
            self.option["label"]=" ".join(self.option["label"].split())
            self.current["options"].append(self.option)
            self.option=None

    def handle_starttag(self,tag,attrs):
        tag=tag.lower()
        a=dict(attrs)
        if tag=="select":
            self.flush_option()
            self.current={
                "name":a.get("name",""),
                "options":[],
            }
        elif tag=="option" and self.current is not None:
            self.flush_option()
            self.option={
                "value":a.get("value",""),
                "label":"",
                "selected":"selected" in a,
            }
        elif tag=="input" and (a.get("type") or "").lower()=="hidden" and a.get("name"):
            self.hidden.append((a["name"],a.get("value","")))

    def handle_data(self,data):
        if self.option is not None:
            self.option["label"] += data

    def handle_endtag(self,tag):
        tag=tag.lower()
        if tag=="option":
            self.flush_option()
        elif tag=="select" and self.current is not None:
            self.flush_option()
            self.selects.append(self.current)
            self.current=None

    def close(self):
        super().close()
        self.flush_option()
        if self.current is not None:
            self.selects.append(self.current)
            self.current=None

def parse_form(raw):
    p=FormParser()
    p.feed(raw.decode("iso-8859-1",errors="replace"))
    p.close()
    return p

def choose(form,name,terms):
    sel=next((x for x in form.selects if x["name"]==name),None)
    if not sel:
        raise RuntimeError(f"select ausente: {name}")
    for o in sel["options"]:
        if any(t in norm(o["label"]) for t in terms):
            return o["value"]
    raise RuntimeError(f"opcao {terms} ausente em {name}")

def params_from_form(raw):
    form=parse_form(raw)
    wanted={
      "Linha":choose(form,"Linha",["ano/mes processamento","ano/mes process"]),
      "Coluna":choose(form,"Coluna",["unidade da federacao","uf"]),
      "Incremento":choose(form,"Incremento",["aih aprovadas"]),
    }
    out=[]
    periods=0
    for sel in form.selects:
        name=sel["name"]
        if not name:
            continue
        options=sel["options"]
        if name=="Arquivos":
            vals=[(o["value"] or "").strip() for o in options]
            vals=[v for v in vals if v]
            out += [(name,v) for v in vals]
            periods=len(vals)
            continue
        if name in wanted:
            out.append((name,wanted[name]))
            continue
        selected=[o["value"] for o in options if o["selected"]]
        if selected:
            out += [(name,v) for v in selected]
            continue
        allopt=next(
            (o for o in options if "todas as categorias" in norm(o["label"])),
            None,
        )
        if allopt is not None:
            out.append((name,allopt["value"]))
    out += form.hidden
    out += [("formato","table"),("mostre","Mostra")]
    return out,periods

class TableParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.tables=[]
        self.table=None
        self.row=None
        self.cell=None

    def flush_cell(self):
        if self.cell is not None and self.row is not None:
            self.row.append(" ".join(self.cell.split()))
            self.cell=None

    def flush_row(self):
        self.flush_cell()
        if self.row is not None and self.table is not None:
            if self.row:
                self.table.append(self.row)
            self.row=None

    def flush_table(self):
        self.flush_row()
        if self.table is not None:
            if self.table:
                self.tables.append(self.table)
            self.table=None

    def handle_starttag(self,tag,attrs):
        tag=tag.lower()
        if tag=="table":
            # TabNet usa HTML 4 permissivo e pode omitir varios fechamentos.
            # Uma nova tabela encerra defensivamente a anterior.
            if self.table is not None:
                self.flush_table()
            self.table=[]
        elif tag=="tr" and self.table is not None:
            # <TR> fecha implicitamente a linha anterior.
            self.flush_row()
            self.row=[]
        elif tag in {"th","td"} and self.row is not None:
            # <TH>/<TD> fecha implicitamente a celula anterior. Esse e o
            # formato real retornado pelo CGI TabNet (sem </TH>, </TD>, </TR>).
            self.flush_cell()
            self.cell=""

    def handle_data(self,data):
        if self.cell is not None:
            self.cell += data

    def handle_endtag(self,tag):
        tag=tag.lower()
        if tag in {"th","td"}:
            self.flush_cell()
        elif tag=="tr":
            self.flush_row()
        elif tag=="table":
            self.flush_table()

    def close(self):
        super().close()
        self.flush_table()

def comp_of(s):
    x=norm(s).lstrip(".").strip()
    m=re.search(r"([a-z]+)[ /-]+(19\d{2}|20\d{2})",x)
    if m and m.group(1) in MONTH:
        return f"{int(m.group(2)):04d}{MONTH[m.group(1)]:02d}"
    m=re.search(r"(19\d{2}|20\d{2})[/-](\d{1,2})",x)
    return f"{int(m.group(1)):04d}{int(m.group(2)):02d}" if m else None

def num(s):
    s=(s or "").strip()
    if s in {"","-","..."}:
        return None
    z=re.sub(r"[^0-9-]","",s)
    return int(z) if z not in {"","-"} else None

def parse_tabnet(raw):
    parser=TableParser()
    parser.feed(raw.decode("iso-8859-1",errors="replace"))
    parser.close()
    out=[]
    for rows in parser.tables:
        header=None
        for cells in rows[:12]:
            mapped=[]
            for c in cells[1:]:
                n=norm(re.sub(r"^\d+\s*","",c))
                mapped.append(
                    UF_NAME.get(n)
                    or (n.upper() if re.fullmatch(r"[a-z]{2}",n) else None)
                )
            if sum(x is not None for x in mapped)>=20:
                header=mapped
                break
        if not header:
            continue
        for cells in rows:
            if len(cells)<2:
                continue
            comp=comp_of(cells[0])
            if not comp:
                continue
            for uf,v in zip(header,cells[1:1+len(header)]):
                n=num(v)
                if uf and n is not None:
                    out.append((comp,uf,n))
    if not out:
        raise RuntimeError("retorno TabNet sem matriz mensal x UF reconhecivel")
    return out

def parquet(glob):
    g=glob.replace("'","''")
    sql=f"""SELECT lpad(cast(competencia as varchar),6,'0') competencia,
upper(cast(uf as varchar)) uf,
count(*)::BIGINT parquet_rd_segmentos,
count(DISTINCT trim(cast(n_aih as varchar)))::BIGINT parquet_aih_distintas
FROM read_parquet('{g}', hive_partitioning=true, union_by_name=true)
GROUP BY 1,2 ORDER BY 1,2;"""
    p=subprocess.run(["duckdb","-csv","-c",sql],text=True,capture_output=True)
    if p.returncode:
        raise RuntimeError(p.stderr.strip())
    return {
        (r["competencia"],r["uf"]):(
            int(r["parquet_rd_segmentos"]),
            int(r["parquet_aih_distintas"]),
        )
        for r in csv.DictReader(p.stdout.splitlines())
    }

def main():
    ap=argparse.ArgumentParser(
        description="CQ SIH AIH aprovadas: TabNet qiuf.def x SUSLabX Parquet"
    )
    ap.add_argument("--parquet-glob")
    ap.add_argument("--preflight-only",action="store_true",
                    help="Valida formulario, POST e parser TabNet sem consultar Parquet")
    ap.add_argument(
        "--output",
        default="/dados/abertos/suslabx/state/sih/qc_tabnet_aih_aprovadas.csv",
    )
    ap.add_argument("--tabnet-html")
    ap.add_argument("--save-tabnet-html")
    args=ap.parse_args()

    periods=-1
    if args.tabnet_html:
        raw=Path(args.tabnet_html).read_bytes()
    else:
        form=fetch(FORM_URL)
        ps,periods=params_from_form(form)
        raw=fetch(
            POST_URL,
            urlencode(ps,doseq=True,encoding="iso-8859-1").encode("ascii"),
            timeout=300,
        )
        if args.save_tabnet_html:
            p=Path(args.save_tabnet_html)
            p.parent.mkdir(parents=True,exist_ok=True)
            p.write_bytes(raw)

    tn={(c,u):v for c,u,v in parse_tabnet(raw)}
    if args.preflight_only:
        comps=sorted({c for c,_ in tn})
        print(
            f"SIH_TABNET_PREFLIGHT_OK periodos_form={periods} "
            f"pares={len(tn)} intervalo={comps[0]}-{comps[-1]}"
        )
        return 0
    if not args.parquet_glob:
        raise SystemExit("--parquet-glob e obrigatorio fora de --preflight-only")
    pq=parquet(args.parquet_glob)
    if not pq:
        raise RuntimeError("Bronze Parquet sem pares competencia x UF")
    comps=[comp for comp,_ in pq]
    min_comp=min(comps)
    max_comp=max(comps)
    tn_scope={k:v for k,v in tn.items() if min_comp <= k[0] <= max_comp}

    # Em RD, N_AIH identifica a AIH logica, mas a linha fisica e um segmento.
    # O TabNet "AIH aprovadas" e confrontado primariamente com quantidade de
    # registros RD/segmentos; distinct N_AIH fica como diagnostico longitudinal.
    keys=sorted(pq)
    rows=[]
    bad=0
    distinct_matches=0
    for comp,uf in keys:
        tab=tn_scope.get((comp,uf))
        seg,dist=pq[(comp,uf)]
        dif_seg=None if tab is None else seg-tab
        dif_dist=None if tab is None else dist-tab
        if tab is None:
            st="sem_tabnet"
        elif dif_seg==0:
            st="ok_segmentos"
        elif dif_dist==0:
            st="match_distinct_diagnostico"
            distinct_matches += 1
        else:
            st="divergente"
        bad += st not in {"ok_segmentos"}
        rows.append([comp,uf,tab,seg,dist,dif_seg,dif_dist,st])

    out=Path(args.output)
    out.parent.mkdir(parents=True,exist_ok=True)
    with out.open("w",encoding="utf-8",newline="") as f:
        w=csv.writer(f)
        w.writerow([
            "competencia","uf","tabnet_aih_aprovadas",
            "parquet_rd_segmentos","parquet_aih_distintas",
            "diferenca_segmentos","diferenca_distinct","status",
        ])
        w.writerows(rows)

    print(
        f"SIH_TABNET_QC periodos={periods} intervalo={min_comp}-{max_comp} "
        f"pares={len(rows)} divergentes_segmentos={bad} "
        f"matches_distinct_diagnostico={distinct_matches} output={out}"
    )
    return 0 if bad==0 else 10

if __name__=="__main__":
    raise SystemExit(main())
