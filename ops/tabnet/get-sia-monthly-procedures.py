#!/usr/bin/env python3
import csv
import hashlib
import html
import io
import re
import sys
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen

FORM_URL = "http://tabnet.datasus.gov.br/cgi/deftohtm.exe?sia/cnv/qabr.def"
POST_URL = "http://tabnet.datasus.gov.br/cgi/tabcgi.exe?sia/cnv/qabr.def"
UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/156 Safari/537.36"

class SelectParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.selects = {}
        self.current_select = None
        self.current_option = None

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        tag = tag.lower()
        if tag == "select":
            self.current_select = a.get("name") or a.get("id")
            if self.current_select:
                self.selects.setdefault(self.current_select, [])
        elif tag == "option" and self.current_select:
            self.current_option = [a.get("value", ""), []]

    def handle_data(self, data):
        if self.current_option is not None:
            self.current_option[1].append(data)

    def handle_endtag(self, tag):
        tag = tag.lower()
        if tag == "option" and self.current_option is not None and self.current_select:
            value, parts = self.current_option
            label = " ".join("".join(parts).split())
            self.selects[self.current_select].append((value, label))
            self.current_option = None
        elif tag == "select":
            self.current_select = None

def norm(s):
    import unicodedata
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", s).strip().lower()

def fetch(url):
    req = Request(url, headers={"User-Agent": UA})
    with urlopen(req, timeout=60) as r:
        return r.read()

def choose(options, predicate, label):
    for value, text in options:
        if predicate(norm(text), value):
            return value
    raise RuntimeError(f"Nao encontrei opcao para {label}: {options[:20]}")

def main():
    if len(sys.argv) != 2:
        raise SystemExit("Uso: get-sia-monthly-procedures.py OUTDIR")

    outdir = Path(sys.argv[1])
    outdir.mkdir(parents=True, exist_ok=True)

    form_raw = fetch(FORM_URL)
    form_text = form_raw.decode("iso-8859-1", errors="replace")

    parser = SelectParser()
    parser.feed(form_text)
    selects = parser.selects

    for req_name in ("Linha", "Coluna", "Incremento", "Arquivos"):
        if req_name not in selects:
            raise RuntimeError(f"SELECT ausente no formulario: {req_name}")

    linha = choose(
        selects["Linha"],
        lambda t, v: t == "procedimento" or v == "Procedimento",
        "Linha=Procedimento",
    )
    coluna = choose(
        selects["Coluna"],
        lambda t, v: "nao ativa" in t or "n" in t and "ativa" in t,
        "Coluna=Nao ativa",
    )
    incremento = choose(
        selects["Incremento"],
        lambda t, v: ("qtd" in t or "quant" in t) and "aprov" in t,
        "Qtd.aprovada",
    )

    periods = []
    for value, label in selects["Arquivos"]:
        m = re.search(r"qabr(\d{2})(\d{2})\.dbf", value, re.I)
        if not m:
            continue
        yy, mm = map(int, m.groups())
        yyyy = 2000 + yy
        comp = f"{yyyy:04d}{mm:02d}"
        periods.append((comp, value, label))

    if not periods:
        raise RuntimeError("Nenhum qabrYYMM.dbf encontrado em Periodos Disponiveis")

    comp, arquivo, period_label = sorted(periods)[-1]

    payload = {
        "Linha": linha,
        "Coluna": coluna,
        "Incremento": incremento,
        "Arquivos": arquivo,
        "formato": "prn",
        "mostre": "Mostra",
    }

    # Todos os filtros opcionais permanecem em "Todas as categorias".
    for name, options in selects.items():
        if not name.startswith("S"):
            continue
        chosen = None
        for value, label in options:
            if "todas as categorias" in norm(label) or value.upper().startswith("TODAS_AS_CATEGORIAS"):
                chosen = value
                break
        if chosen is not None:
            payload[name] = chosen

    body = urlencode(payload, encoding="iso-8859-1").encode("ascii")
    req = Request(
        POST_URL,
        data=body,
        headers={
            "User-Agent": UA,
            "Referer": FORM_URL,
            "Content-Type": "application/x-www-form-urlencoded",
        },
        method="POST",
    )
    with urlopen(req, timeout=120) as r:
        raw = r.read()

    response = raw.decode("iso-8859-1", errors="replace")

    if "VEJA A" in response.upper() and "LIMIT" in response.upper():
        raise RuntimeError("TabNet retornou indicacao de limite")

    pre = re.search(r"<pre[^>]*>(.*?)</pre>", response, flags=re.I | re.S)
    if not pre:
        raise RuntimeError("Resposta TabNet sem bloco PRE")

    text = html.unescape(re.sub(r"<[^>]+>", "", pre.group(1)))
    rows = list(csv.reader(io.StringIO(text), delimiter=";"))

    procedures = {}
    for row in rows:
        if not row:
            continue
        first = row[0].strip().strip('"')
        m = re.match(r"^(\d{10})\s+(.*)$", first)
        if not m:
            continue
        code, desc = m.groups()

        # Sem "Exibir linhas zeradas", a expectativa e que sejam linhas observadas.
        # Ainda assim, se houver numeros e todos forem zero, descartamos.
        nums = []
        for cell in row[1:]:
            x = cell.strip().strip('"')
            if not x or x in {"-", "..."}:
                continue
            x2 = x.replace(".", "").replace(",", ".")
            try:
                nums.append(float(x2))
            except ValueError:
                pass
        if nums and sum(nums) == 0:
            continue

        procedures[code] = desc.strip()

    if not procedures:
        raise RuntimeError("Nenhum procedimento foi extraido da tabulacao mensal")

    raw_path = outdir / f"tabnet_sia_{comp}_raw.html"
    raw_path.write_bytes(raw)

    tsv = outdir / f"procedimento_producao_{comp}.tsv"
    with tsv.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f, delimiter="\t", lineterminator="\n")
        w.writerow(["codigo", "descricao"])
        for code in sorted(procedures):
            w.writerow([code, procedures[code]])

    meta = outdir / f"tabnet_sia_{comp}.meta.tsv"
    with meta.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f, delimiter="\t", lineterminator="\n")
        w.writerow(["extracted_at", "form_url", "post_url", "competencia", "arquivo", "period_label",
                    "linha", "coluna", "incremento", "procedures", "raw_sha256", "tsv_sha256"])
        w.writerow([
            datetime.now(timezone.utc).astimezone().isoformat(),
            FORM_URL, POST_URL, comp, arquivo, period_label,
            linha, coluna, incremento, len(procedures),
            hashlib.sha256(raw).hexdigest(),
            hashlib.sha256(tsv.read_bytes()).hexdigest(),
        ])

    print(f"competencia={comp}")
    print(f"arquivo={arquivo}")
    print(f"procedures={len(procedures)}")
    print(f"tsv={tsv}")
    print(f"meta={meta}")

if __name__ == "__main__":
    main()
