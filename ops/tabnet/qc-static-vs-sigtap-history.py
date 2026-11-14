#!/usr/bin/env python3
import csv
import io
import re
import sys
import zipfile
from pathlib import Path
from datetime import datetime

if len(sys.argv) != 4:
    raise SystemExit("Uso: qc-static-vs-sigtap-history.py RAW_ZIP_DIR TABNET_DIR STATE_DIR")

raw_dir = Path(sys.argv[1])
tab_dir = Path(sys.argv[2])
state = Path(sys.argv[3])
state.mkdir(parents=True, exist_ok=True)

specs = {
    "grupo": ("tb_grupo", ["CO_GRUPO"]),
    "subgrupo": ("tb_sub_grupo", ["CO_GRUPO", "CO_SUB_GRUPO"]),
    "forma": ("tb_forma_organizacao", ["CO_GRUPO", "CO_SUB_GRUPO", "CO_FORMA_ORGANIZACAO"]),
    "procedimento": ("tb_procedimento", ["CO_PROCEDIMENTO"]),
}

history = {k: {} for k in specs}
zips = sorted(raw_dir.glob("TabelaUnificada_*.zip"))

if not zips:
    raise SystemExit(f"Nenhum ZIP SIGTAP em {raw_dir}")

def member_by_basename(zf, basename):
    target = basename.lower()
    for n in zf.namelist():
        if Path(n).name.lower() == target:
            return n
    return None

for idx, zp in enumerate(zips, 1):
    m = re.search(r"TabelaUnificada_(\d{6})", zp.name)
    if not m:
        continue
    comp = m.group(1)

    try:
        with zipfile.ZipFile(zp) as z:
            for domain, (table, parts) in specs.items():
                lm = member_by_basename(z, f"{table}_layout.txt")
                dm = member_by_basename(z, f"{table}.txt")
                if not lm or not dm:
                    continue

                layout_text = z.read(lm).decode("latin-1", errors="replace")
                rows = list(csv.DictReader(io.StringIO(layout_text)))
                positions = {}
                for r in rows:
                    key = (r.get("Coluna") or "").strip().upper()
                    positions[key] = (int(r["Inicio"]), int(r["Fim"]))

                if any(p not in positions for p in parts):
                    continue

                for line in z.read(dm).splitlines():
                    vals = []
                    for p in parts:
                        start, end = positions[p]
                        vals.append(line[start-1:end].strip(b" ").decode("latin-1"))
                    code = "".join(vals)
                    if not code:
                        continue
                    rec = history[domain].setdefault(code, [comp, comp])
                    if comp < rec[0]:
                        rec[0] = comp
                    if comp > rec[1]:
                        rec[1] = comp
    except zipfile.BadZipFile:
        print(f"WARNING bad_zip={zp}", file=sys.stderr)

    if idx % 25 == 0:
        print(f"processed_zips={idx}/{len(zips)}", file=sys.stderr)

ts = datetime.now().strftime("%Y%m%d_%H%M%S")
summary = state / f"qc_tabnet_static_vs_sigtap_history_{ts}.tsv"
detail = state / f"qc_tabnet_static_only_{ts}.tsv"

with summary.open("w", encoding="utf-8", newline="") as fs, \
     detail.open("w", encoding="utf-8", newline="") as fd:
    sw = csv.writer(fs, delimiter="\t", lineterminator="\n")
    dw = csv.writer(fd, delimiter="\t", lineterminator="\n")
    sw.writerow(["domain", "tabnet_static", "sigtap_historical_union", "intersection",
                 "only_tabnet", "only_sigtap_history", "status"])
    dw.writerow(["domain", "codigo"])

    for domain in specs:
        tab_file = tab_dir / f"{domain}.tsv"
        if not tab_file.exists():
            raise SystemExit(f"Arquivo TabNet ausente: {tab_file}")

        with tab_file.open(encoding="utf-8") as f:
            tab = {r["codigo"] for r in csv.DictReader(f, delimiter="\t") if r.get("codigo")}

        hist = set(history[domain])
        only_tab = sorted(tab - hist)
        only_hist = hist - tab

        for code in only_tab:
            dw.writerow([domain, code])

        status = "ok" if not only_tab else "warning_tabnet_not_found_in_raw_history"
        sw.writerow([
            domain, len(tab), len(hist), len(tab & hist),
            len(only_tab), len(only_hist), status
        ])

print(f"zips={len(zips)}")
print(f"summary={summary}")
print(f"detail={detail}")
