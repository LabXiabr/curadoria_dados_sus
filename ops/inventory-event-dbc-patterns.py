#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import os
import re
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
POLICY = ROOT / "systems" / "dissemin" / "source_policy.tsv"
TARGETS = {"SIM","SINASC","SINAN","CIH","CIHA"}
UFS = {
    "AC","AL","AP","AM","BA","CE","DF","ES","GO","MA","MT","MS","MG",
    "PA","PB","PR","PE","PI","RJ","RN","RS","RO","RR","SC","SP","SE","TO"
}

def read_tsv(path: Path):
    with path.open(encoding="utf-8",newline="") as f:
        return list(csv.DictReader(f,delimiter="\t"))

def load_subsystems(system: str):
    p=ROOT/"systems"/system.lower()/"subsystems.tsv"
    if not p.is_file():
        return []
    return sorted(
        {r["subsystem"].upper() for r in read_tsv(p) if r.get("subsystem")},
        key=lambda x:(-len(x),x)
    )

def shape(stem: str) -> str:
    s=stem.upper()
    for uf in sorted(UFS):
        s=re.sub(rf"(?<=[A-Z]){uf}(?=\d)", "<UF>", s)
    s=re.sub(r"(19|20)\d{2}", "<YYYY>", s)
    s=re.sub(r"\d{4}$", "<NNNN>", s)
    s=re.sub(r"\d{2}$", "<NN>", s)
    return s

def main():
    ap=argparse.ArgumentParser(description="Inventaria padrões físicos DBC de SIM/SINASC/SINAN/CIH/CIHA")
    ap.add_argument("--lake-root",default=os.environ.get("LAKE_ROOT","/dados/abertos/suslake"))
    args=ap.parse_args()
    lake=Path(args.lake_root)
    raw=lake/"raw"/"dissemin"/"publicos"
    state=lake/"state"/"dissemin"
    state.mkdir(parents=True,exist_ok=True)

    rows=[]
    summary=Counter()
    examples=defaultdict(list)

    for pol in read_tsv(POLICY):
        system=pol["system"]
        if system not in TARGETS or pol["etl_policy"]!="etl":
            continue
        root=raw/pol["source_root"]
        subs=load_subsystems(system)
        if not root.is_dir():
            rows.append({
                "system":system,"source_root":pol["source_root"],"filename":"",
                "relative_path":"","candidate_subsystem":"","shape":"",
                "status":"source_root_absent"
            })
            continue
        for p in sorted(root.rglob("*.dbc")):
            stem=p.stem.upper()
            candidate=""
            for sub in subs:
                if stem.startswith(sub):
                    candidate=sub
                    break
            sh=shape(stem)
            rel=p.relative_to(raw).as_posix()
            row={
                "system":system,"source_root":pol["source_root"],"filename":p.name,
                "relative_path":rel,"candidate_subsystem":candidate,
                "shape":sh,"status":"observed"
            }
            rows.append(row)
            summary[(system,pol["source_root"],candidate,sh)]+=1
            if len(examples[(system,pol["source_root"],candidate,sh)])<3:
                examples[(system,pol["source_root"],candidate,sh)].append(p.name)

    report=state/"event_dbc_filename_inventory.tsv"
    fields=["system","source_root","filename","relative_path","candidate_subsystem","shape","status"]
    with report.open("w",encoding="utf-8",newline="") as f:
        w=csv.DictWriter(f,fieldnames=fields,delimiter="\t",lineterminator="\n")
        w.writeheader();w.writerows(rows)

    summary_path=state/"event_dbc_filename_patterns.tsv"
    with summary_path.open("w",encoding="utf-8",newline="") as f:
        w=csv.writer(f,delimiter="\t",lineterminator="\n")
        w.writerow(["system","source_root","candidate_subsystem","shape","files","examples"])
        for key,n in sorted(summary.items()):
            w.writerow([*key,n,"|".join(examples[key])])

    print(f"EVENT_DBC_FILENAME_INVENTORY_OK files={sum(1 for r in rows if r['status']=='observed')}")
    print(f"report={report}")
    print(f"patterns={summary_path}")
    print("system\tsource_root\tcandidate_subsystem\tshape\tfiles\texamples")
    for key,n in sorted(summary.items()):
        print("\t".join([*key,str(n),"|".join(examples[key])]))
    return 0

if __name__=="__main__":
    raise SystemExit(main())
