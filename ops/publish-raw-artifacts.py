#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import fnmatch
import hashlib
import os
import re
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote

ROOT=Path(__file__).resolve().parents[1]
DEFAULT_POLICY=ROOT/"catalog"/"raw_publication.tsv"

def die(msg: str, code: int=20):
    print(f"ERRO: {msg}",file=sys.stderr)
    raise SystemExit(code)

def sha256(path: Path) -> str:
    h=hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda:f.read(1024*1024),b""):
            h.update(block)
    return h.hexdigest()

def read_policy(path: Path) -> list[dict[str,str]]:
    with path.open(encoding="utf-8",newline="") as f:
        return list(csv.DictReader(f,delimiter="\t"))

def read_marker(path: Path) -> dict[str,str]:
    out={}
    if not path.is_file():
        return out
    for line in path.read_text(encoding="utf-8").splitlines():
        if "=" in line:
            k,v=line.split("=",1)
            out[k]=v
    return out

def gate_allows(rule: dict[str,str], src: Path, lake: Path) -> tuple[bool,str]:
    policy=(rule.get("gate_policy") or "").strip()
    if not policy:
        return True,""

    if policy=="cnes_global_qc_by_competencia":
        m=re.match(r"^BASE_DE_DADOS_CNES_(\d{6})\.ZIP$",src.name,re.I)
        if not m:
            # Referencias CNES sem competencia no nome sao artefatos oficiais
            # independentes do snapshot mensal.
            return True,""
        comp=m.group(1)
        marker=lake/"state"/"cnes"/f"qc_global_{comp}.ok"
        meta=read_marker(marker)
        if meta.get("competencia")!=comp or meta.get("status")!="validated":
            return False,f"gate CNES ausente/invalido: {marker}"
        return True,f"qc_global_{comp}.ok"

    raise RuntimeError(f"gate_policy desconhecida: {policy}")

def iter_matches(root: Path, pattern: str):
    # pathlib.glob suporta ** e mantem a politica declarativa simples.
    for p in sorted(root.glob(pattern)):
        if p.is_file():
            yield p

def relative_target(dataset_id: str, src_root: Path, src: Path, prefix: str) -> Path:
    rel=src.relative_to(src_root)
    if dataset_id=="sigtap":
        m=re.match(r"^TabelaUnificada_(\d{6}).*\.zip$",src.name,re.I)
        comp=m.group(1) if m else "desconhecida"
        return Path(prefix)/f"competencia={comp}"/src.name
    return Path(prefix)/rel

def source_url(dataset_id: str, src_root: Path, src: Path, base: str) -> str:
    if not base.endswith("/"):
        base+="/"
    if dataset_id=="territorio":
        rel=src.relative_to(src_root)
        year=""
        for part in rel.parts:
            if part.startswith("year="):
                year=part.split("=",1)[1]
                break
        return base + (quote(year)+"/" if year else "") + quote(src.name)
    return base + quote(src.name)

def hardlink(src: Path, dst: Path):
    dst.parent.mkdir(parents=True,exist_ok=True)
    if dst.exists():
        try:
            if os.path.samefile(src,dst):
                return
        except OSError:
            pass
        dst.unlink()
    try:
        os.link(src,dst)
    except OSError as exc:
        if exc.errno == 18:
            die(
                f"hardlink impossivel entre filesystems: {src} -> {dst}; "
                "nao foi feita copia para evitar duplicacao de disco",
                30,
            )
        raise

def http_qc(public_root: Path, rows: list[dict[str,str]], host: str, base: str):
    if not rows:
        return
    if not shutil.which("curl"):
        print("WARN: curl ausente; QC HTTP ignorado")
        return
    # Um arquivo por dataset basta para validar Alias, GET/HEAD e Range.
    seen=set()
    for row in rows:
        ds=row["dataset_id"]
        if ds in seen:
            continue
        seen.add(ds)
        rel=Path(row["public_path"]).relative_to(public_root)
        url=base.rstrip("/")+"/"+"/".join(quote(x) for x in rel.parts)
        common=["curl","-sS","-o","/dev/null","-H",f"Host: {host}"]
        head=subprocess.run(
            common+["-I","-w","%{http_code}",url],
            text=True,capture_output=True
        )
        code=head.stdout.strip()[-3:] if head.returncode==0 else ""
        if code not in {"200","206"}:
            die(f"QC HTTP HEAD falhou {ds}: {url} -> {code or head.stderr}",40)
        rng=subprocess.run(
            common+["-H","Range: bytes=0-0","-w","%{http_code}",url],
            text=True,capture_output=True
        )
        rcode=rng.stdout.strip()[-3:] if rng.returncode==0 else ""
        if rcode != "206":
            die(f"QC HTTP Range falhou {ds}: {url} -> {rcode or rng.stderr}",41)
        print(f"HTTP_QC_OK dataset={ds} head={code} range={rcode} url={url}")

def main() -> int:
    ap=argparse.ArgumentParser(description="Projeta Raw canonico publicavel em /dados/abertos/raw por hardlink")
    ap.add_argument("--lake-root",default=os.environ.get("LAKE_ROOT","/dados/abertos/suslake"))
    ap.add_argument("--public-root",default=os.environ.get("RAW_PUBLIC_ROOT","/dados/abertos/raw"))
    ap.add_argument("--policy",type=Path,default=DEFAULT_POLICY)
    ap.add_argument("--dataset",action="append",help="publicar apenas dataset_id indicado; repetivel")
    ap.add_argument("--http-base",default=os.environ.get("RAW_HTTP_TEST_BASE","http://127.0.0.1:8766/files/raw"))
    ap.add_argument("--http-host",default=os.environ.get("RAW_HTTP_TEST_HOST","dados.labx.ia.br"))
    ap.add_argument("--skip-http-qc",action="store_true")
    args=ap.parse_args()

    lake=Path(args.lake_root).resolve()
    canonical=lake/"raw"
    public=Path(args.public_root).resolve()
    policy=read_policy(args.policy)

    if not canonical.is_dir():
        die(f"Raw canonico ausente: {canonical}",3)
    public.mkdir(parents=True,exist_ok=True)

    wanted=set(args.dataset or [])
    unknown=wanted-{r["dataset_id"] for r in policy}
    if unknown:
        die("dataset desconhecido: "+",".join(sorted(unknown)),2)

    now=datetime.now(timezone.utc).isoformat()
    rows=[]
    for rule in policy:
        if rule["status"].lower()!="published":
            continue
        if wanted and rule["dataset_id"] not in wanted:
            continue
        src_root=canonical/rule["source_rel"]
        if not src_root.is_dir():
            die(f"fonte Raw ausente para {rule['dataset_id']}: {src_root}",4)

        matches=list(iter_matches(src_root,rule["glob"]))
        if not matches:
            die(f"nenhum arquivo para {rule['dataset_id']} pattern={rule['glob']}",5)

        published_for_rule=0
        for src in matches:
            allowed,gate_note=gate_allows(rule,src,lake)
            if not allowed:
                print(f"RAW_PUBLIC_SKIP dataset={rule['dataset_id']} file={src.name} reason={gate_note}")
                continue
            if gate_note:
                print(f"RAW_PUBLIC_GATE_OK dataset={rule['dataset_id']} file={src.name} gate={gate_note}")
            rel=relative_target(rule["dataset_id"],src_root,src,rule["public_prefix"])
            dst=public/rel
            hardlink(src,dst)
            st=src.stat()
            digest=sha256(src)
            public_url="https://dados.labx.ia.br/files/raw/"+"/".join(quote(x) for x in rel.parts)
            rows.append({
                "dataset_id":rule["dataset_id"],
                "system":rule["system"],
                "filename":src.name,
                "bytes":str(st.st_size),
                "sha256":digest,
                "source_url":source_url(rule["dataset_id"],src_root,src,rule["source_base_url"]),
                "public_path":str(dst),
                "public_url":public_url,
                "link_type":"hardlink",
                "published_at":now,
                "description":rule["description"],
            })
            published_for_rule+=1

    rows.sort(key=lambda r:(r["dataset_id"],r["public_path"]))
    current_rows=list(rows)
    catalog=public/"catalog.tsv"

    # Publicacao seletiva deve preservar datasets ja catalogados.
    if wanted and catalog.is_file():
        with catalog.open(encoding="utf-8",newline="") as f:
            previous=list(csv.DictReader(f,delimiter="\t"))
        retained=[r for r in previous if r.get("dataset_id") not in wanted]
        rows=retained+rows
        rows.sort(key=lambda r:(r["dataset_id"],r["public_path"]))
    tmp=public/f".catalog.tsv.partial.{os.getpid()}"
    fields=[
        "dataset_id","system","filename","bytes","sha256","source_url",
        "public_path","public_url","link_type","published_at","description"
    ]
    with tmp.open("w",encoding="utf-8",newline="") as f:
        w=csv.DictWriter(f,fieldnames=fields,delimiter="\t",lineterminator="\n")
        w.writeheader()
        w.writerows(rows)
    os.replace(tmp,catalog)

    if not args.skip_http_qc:
        http_qc(public,current_rows,args.http_host,args.http_base)

    by_ds={}
    for r in current_rows:
        by_ds[r["dataset_id"]]=by_ds.get(r["dataset_id"],0)+1
    print(
        "RAW_PUBLIC_OK published_files="+str(len(current_rows))
        +" catalog_files="+str(len(rows))
        +" catalog="+str(catalog)
    )
    for ds,n in sorted(by_ds.items()):
        print(f"dataset={ds} files={n}")
    print("url=https://dados.labx.ia.br/files/raw/")
    return 0

if __name__=="__main__":
    raise SystemExit(main())
