#!/usr/bin/env python3
from __future__ import annotations

import argparse, csv, time
from html.parser import HTMLParser
from pathlib import Path
from urllib.request import Request, urlopen

class Parser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.form=None; self.fields=[]; self.cur=None; self.opt=None

    def flush_option(self):
        # HTML permite omitir </option>. O TabNet usa esse padrao em varios
        # formularios; portanto a opcao anterior tambem deve ser encerrada
        # quando uma nova <option> comeca ou quando </select> e encontrado.
        if self.opt is not None and self.cur is not None:
            self.opt["label"]=" ".join(self.opt["label"].split())
            self.cur["options"].append(self.opt)
            self.opt=None

    def handle_starttag(self,tag,attrs):
        a=dict(attrs); tag=tag.lower()
        if tag=="form" and self.form is None:
            self.form={"method":a.get("method","GET").upper(),"action":a.get("action","")}
        elif tag=="select":
            self.flush_option()
            self.cur={"name":a.get("name",""),"id":a.get("id",""),"multiple":int("multiple" in a),"options":[]}
        elif tag=="option" and self.cur is not None:
            self.flush_option()
            self.opt={"value":a.get("value",""),"label":"","selected":int("selected" in a)}
        elif tag=="input" and (a.get("type") or "").lower()=="hidden":
            self.fields.append({"type":"hidden","name":a.get("name",""),"id":a.get("id",""),"multiple":0,"options":[{"value":a.get("value",""),"label":"","selected":1}]})
    def handle_data(self,data):
        if self.opt is not None: self.opt["label"] += data
    def handle_endtag(self,tag):
        tag=tag.lower()
        if tag=="option":
            self.flush_option()
        elif tag=="select" and self.cur is not None:
            self.flush_option()
            self.cur["type"]="select"; self.fields.append(self.cur); self.cur=None

def role(name):
    n=(name or "").lower()
    if n in {"linha","coluna"}: return "dimension"
    if n=="incremento": return "metric"
    if n=="arquivos": return "period"
    if n.startswith("s"): return "domain_filter"
    return "parameter"

def read_tsv(path):
    with path.open(encoding="utf-8",newline="") as f: return list(csv.DictReader(f,delimiter="\t"))

def write_tsv(path,fields,rows):
    path.parent.mkdir(parents=True,exist_ok=True)
    with path.open("w",encoding="utf-8",newline="") as f:
        w=csv.DictWriter(f,fieldnames=fields,delimiter="\t",lineterminator="\n"); w.writeheader(); w.writerows(rows)

def fetch(url,timeout):
    req=Request(url,headers={"User-Agent":"Mozilla/5.0 SUSLabX metadata harvester"})
    with urlopen(req,timeout=timeout) as r:
        if r.status!=200: raise RuntimeError(f"HTTP {r.status}")
        return r.read().decode("iso-8859-1",errors="replace")

def main():
    ap=argparse.ArgumentParser(description="Colhe dimensoes, metricas e dominios dos formularios TabNet")
    ap.add_argument("--catalog",default="catalog/tabulators.tsv")
    ap.add_argument("--output-dir",default="/dados/abertos/suslabx/state/metadata/tabnet")
    ap.add_argument("--limit",type=int,default=0)
    ap.add_argument("--sleep",type=float,default=0.25)
    ap.add_argument("--timeout",type=int,default=45)
    args=ap.parse_args()

    src=read_tsv(Path(args.catalog))
    src=[r for r in src if r.get("form_url") and r.get("kind")=="tabnet_def"]
    if args.limit>0: src=src[:args.limit]

    fields=[]; options=[]; summary=[]
    for i,r in enumerate(src,1):
        tid=r["tabulator_id"]; url=r["form_url"]; status="ok"; err=""
        try:
            html=fetch(url,args.timeout); p=Parser(); p.feed(html)
            for pos,f in enumerate(p.fields,1):
                fname=f.get("name",""); rr=role(fname)
                fields.append({
                    "tabulator_id":tid,"field_ordinal":pos,"field_name":fname,"field_id":f.get("id",""),
                    "field_type":f.get("type",""),"role":rr,"multiple":f.get("multiple",0),
                    "option_count":len(f.get("options",[])),"source_url":url})
                for j,o in enumerate(f.get("options",[]),1):
                    options.append({
                        "tabulator_id":tid,"field_name":fname,"role":rr,"option_ordinal":j,
                        "option_value":o.get("value",""),"option_label":o.get("label",""),
                        "selected":o.get("selected",0),"source_url":url})
            summary.append({
                "tabulator_id":tid,"system_guess":r.get("system_guess",""),"def_path":r.get("def_path",""),
                "field_count":len(p.fields),"dimension_count":sum(role(x.get("name",""))=="dimension" for x in p.fields),
                "metric_count":sum(role(x.get("name",""))=="metric" for x in p.fields),
                "domain_filter_count":sum(role(x.get("name",""))=="domain_filter" for x in p.fields),
                "period_option_count":sum(len(x.get("options",[])) for x in p.fields if role(x.get("name",""))=="period"),
                "status":"ok","error":""})
        except Exception as e:
            status="error"; err=str(e)
            summary.append({"tabulator_id":tid,"system_guess":r.get("system_guess",""),"def_path":r.get("def_path",""),
                "field_count":0,"dimension_count":0,"metric_count":0,"domain_filter_count":0,"period_option_count":0,
                "status":status,"error":err})
        print(f"[{i}/{len(src)}] {tid} {status}" + (f" {err}" if err else ""))
        time.sleep(max(args.sleep,0))

    out=Path(args.output_dir)
    write_tsv(out/"tabulator_fields.tsv",
        ["tabulator_id","field_ordinal","field_name","field_id","field_type","role","multiple","option_count","source_url"],fields)
    write_tsv(out/"tabulator_options.tsv",
        ["tabulator_id","field_name","role","option_ordinal","option_value","option_label","selected","source_url"],options)
    write_tsv(out/"tabulator_summary.tsv",
        ["tabulator_id","system_guess","def_path","field_count","dimension_count","metric_count","domain_filter_count","period_option_count","status","error"],summary)
    ok=sum(r["status"]=="ok" for r in summary)
    print(f"TABNET_METADATA_DONE tabulators={len(summary)} ok={ok} error={len(summary)-ok} fields={len(fields)} options={len(options)} output={out}")
    return 0 if ok==len(summary) else 10

if __name__=="__main__":
    raise SystemExit(main())
