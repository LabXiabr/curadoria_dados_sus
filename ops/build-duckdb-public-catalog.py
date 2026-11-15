#!/usr/bin/env python3
from __future__ import annotations
import argparse, csv, html.parser, re, subprocess, sys
from dataclasses import dataclass
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import unquote, urljoin, urlparse, urlunparse
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ENDPOINTS = ROOT / "catalog" / "endpoints.tsv"
DEFAULT_DATASETS = ROOT / "catalog" / "datasets.tsv"
DEFAULT_SQL = ROOT / "sql" / "duckdb" / "generated" / "public_catalog.sql"

class LinkParser(html.parser.HTMLParser):
    def __init__(self):
        super().__init__()
        self.links = []
    def handle_starttag(self, tag, attrs):
        if tag.lower() != "a":
            return
        for key, value in attrs:
            if key.lower() == "href" and value:
                self.links.append(value)

@dataclass(frozen=True)
class Endpoint:
    endpoint_id: str
    base_url: str
    protocol: str
    public: str
    range_requests: str
    origin: str
    path_scope: str
    status: str
    description: str

@dataclass(frozen=True)
class DatasetRule:
    dataset_id: str
    system: str
    layer: str
    status: str
    endpoint_id: str
    discovery_path: str
    grouping: str
    duckdb_schema: str
    duckdb_view: str
    file_regex: str
    description: str

def read_tsv(path):
    with Path(path).open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f, delimiter="\t"))

def load_endpoints(path):
    out = {}
    for row in read_tsv(path):
        ep = Endpoint(**row)
        if not ep.base_url.endswith("/"):
            ep = Endpoint(**{**ep.__dict__, "base_url": ep.base_url + "/"})
        out[ep.endpoint_id] = ep
    return out

def load_rules(path):
    return [DatasetRule(**row) for row in read_tsv(path)]

def clean_url(url):
    p = urlparse(url)
    return urlunparse((p.scheme, p.netloc, p.path, "", "", ""))

def http_links(url, timeout):
    req = Request(url, headers={"User-Agent": "LabX-Curadoria-DuckDB-Catalog/1.0"})
    with urlopen(req, timeout=timeout) as r:
        ctype = r.headers.get_content_type()
        if ctype not in {"text/html", "application/xhtml+xml"}:
            return []
        data = r.read().decode(r.headers.get_content_charset() or "utf-8", errors="replace")
    parser = LinkParser()
    parser.feed(data)
    return parser.links

def discover_parquet(base_url, discovery_path, file_regex, timeout=30, max_depth=8):
    root = urljoin(base_url, discovery_path.lstrip("/"))
    if not root.endswith("/"):
        root += "/"
    root = clean_url(root)
    pattern = re.compile(file_regex, re.I) if file_regex else re.compile(r".*\.parquet$", re.I)
    visited, files, warnings = set(), [], []
    def walk(url, depth):
        url = clean_url(url)
        if url in visited or depth > max_depth:
            return
        visited.add(url)
        try:
            links = http_links(url, timeout)
        except HTTPError as e:
            warnings.append(f"{e.code} {url}")
            return
        except (URLError, TimeoutError, OSError) as e:
            warnings.append(f"{type(e).__name__} {url}: {e}")
            return
        for href in links:
            if href.startswith(("#", "?", "../")):
                continue
            child = clean_url(urljoin(url, href))
            if not child.startswith(root):
                continue
            parsed = urlparse(child)
            name = unquote(parsed.path.rstrip("/").split("/")[-1])
            if parsed.path.endswith("/"):
                walk(child, depth + 1)
            elif name.lower().endswith(".parquet") and pattern.search(name):
                files.append(child)
    walk(root, 0)
    return sorted(set(files)), warnings

def sql_ident(value):
    return '"' + value.replace('"', '""') + '"'

def sql_str(value):
    return "'" + value.replace("'", "''") + "'"

def sanitize_ident(value):
    value = unquote(value).strip().lower()
    value = re.sub(r"[^a-z0-9_]+", "_", value)
    value = re.sub(r"_+", "_", value).strip("_")
    if not value:
        return "dados"
    if value[0].isdigit():
        value = "v_" + value
    return value

def relative_first_dir(root_url, file_url):
    root_path = urlparse(root_url).path
    if not root_path.endswith("/"):
        root_path += "/"
    file_path = urlparse(file_url).path
    rel = file_path[len(root_path):] if file_path.startswith(root_path) else file_path.rsplit("/", 1)[-1]
    parts = [unquote(p) for p in rel.split("/") if p]
    return parts[0] if len(parts) > 1 else "_root"

def parquet_expr(urls):
    items = ",\n            ".join(sql_str(u) for u in urls)
    return "read_parquet([\n            " + items + "\n        ], union_by_name=true, filename=true, hive_partitioning=true)"

def values_sql(rows):
    rendered = []
    for row in rows:
        rendered.append("(" + ", ".join(sql_str(str(v)) for v in row) + ")")
    return ",\n    ".join(rendered)

def build_sql(endpoints, rules, timeout=30, max_depth=8):
    lines = [
        "-- GERADO AUTOMATICAMENTE. Nao editar manualmente.",
        "-- Fonte: catalog/endpoints.tsv + catalog/datasets.tsv + autoindex HTTP.",
        "CREATE SCHEMA IF NOT EXISTS catalogo;",
        "",
    ]
    warnings, catalog_rows = [], []
    for schema in sorted({r.duckdb_schema for r in rules if r.duckdb_schema}):
        lines.append(f"CREATE SCHEMA IF NOT EXISTS {sql_ident(schema)};")
    lines.append("")
    ep_rows = [(e.endpoint_id, e.base_url, e.protocol, e.public, e.range_requests, e.origin, e.path_scope, e.status, e.description) for e in endpoints.values()]
    if ep_rows:
        lines += [
            "CREATE OR REPLACE TABLE catalogo.endpoints AS",
            "SELECT * FROM (VALUES",
            "    " + values_sql(ep_rows),
            ") AS t(endpoint_id, base_url, protocol, public, range_requests, origin, path_scope, status, description);",
            "",
        ]
    for rule in rules:
        ep = endpoints.get(rule.endpoint_id)
        if not ep:
            warnings.append(f"{rule.dataset_id}: endpoint inexistente {rule.endpoint_id}")
            continue
        root_url = urljoin(ep.base_url, rule.discovery_path.lstrip("/"))
        if not root_url.endswith("/"):
            root_url += "/"
        files, errs = discover_parquet(ep.base_url, rule.discovery_path, rule.file_regex, timeout=timeout, max_depth=max_depth)
        warnings.extend(f"{rule.dataset_id}: {x}" for x in errs)
        groups = {}
        if rule.grouping == "single":
            if files:
                groups[rule.duckdb_view or rule.dataset_id] = files
        elif rule.grouping == "first_dir":
            for url in files:
                name = sanitize_ident(relative_first_dir(root_url, url))
                groups.setdefault(name, []).append(url)
        else:
            warnings.append(f"{rule.dataset_id}: grouping desconhecido {rule.grouping}")
            continue
        if not groups:
            catalog_rows.append({
                "dataset_id": rule.dataset_id, "system": rule.system, "layer": rule.layer,
                "duckdb_schema": rule.duckdb_schema, "duckdb_view": "", "source_files": "0",
                "status": "unavailable", "discovery_url": root_url, "description": rule.description,
            })
            continue
        for view_name, urls in sorted(groups.items()):
            schema, view = sanitize_ident(rule.duckdb_schema), sanitize_ident(view_name)
            lines += [
                f"CREATE OR REPLACE VIEW {sql_ident(schema)}.{sql_ident(view)} AS",
                "SELECT * EXCLUDE(filename), filename AS _source_url",
                "FROM " + parquet_expr(sorted(urls)) + ";",
                "",
            ]
            catalog_rows.append({
                "dataset_id": rule.dataset_id, "system": rule.system, "layer": rule.layer,
                "duckdb_schema": schema, "duckdb_view": view, "source_files": str(len(urls)),
                "status": "available", "discovery_url": root_url, "description": rule.description,
            })
    cols = ["dataset_id","system","layer","duckdb_schema","duckdb_view","source_files","status","discovery_url","description"]
    rows = [[r[c] for c in cols] for r in catalog_rows]
    if rows:
        lines += [
            "CREATE OR REPLACE TABLE catalogo.datasets AS",
            "SELECT * FROM (VALUES",
            "    " + values_sql(rows),
            ") AS t(dataset_id, system, layer, duckdb_schema, duckdb_view, source_files, status, discovery_url, description);",
            "",
        ]
    else:
        lines += [
            "CREATE OR REPLACE TABLE catalogo.datasets(",
            "dataset_id VARCHAR, system VARCHAR, layer VARCHAR, duckdb_schema VARCHAR, duckdb_view VARCHAR,",
            "source_files VARCHAR, status VARCHAR, discovery_url VARCHAR, description VARCHAR);",
            "",
        ]
    lines += [
        "CREATE OR REPLACE VIEW catalogo.views_disponiveis AS",
        "SELECT * FROM catalogo.datasets WHERE status = 'available' ORDER BY system, duckdb_schema, duckdb_view;",
        "",
    ]
    return "\n".join(lines), catalog_rows, warnings

def apply_sql(database, sql_path):
    database = Path(database).expanduser().resolve()
    database.parent.mkdir(parents=True, exist_ok=True)
    try:
        subprocess.run(["duckdb", str(database), "-f", str(sql_path)], check=True)
    except FileNotFoundError:
        raise SystemExit("ERRO: CLI duckdb nao encontrado. O SQL foi gerado; abra-o no DBeaver e execute na conexao bureta.duckdb.")

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--endpoints", type=Path, default=DEFAULT_ENDPOINTS)
    ap.add_argument("--datasets", type=Path, default=DEFAULT_DATASETS)
    ap.add_argument("--output-sql", type=Path, default=DEFAULT_SQL)
    ap.add_argument("--database", type=Path)
    ap.add_argument("--timeout", type=int, default=30)
    ap.add_argument("--max-depth", type=int, default=8)
    args = ap.parse_args()
    endpoints, rules = load_endpoints(args.endpoints), load_rules(args.datasets)
    sql, rows, warnings = build_sql(endpoints, rules, timeout=args.timeout, max_depth=args.max_depth)
    args.output_sql.parent.mkdir(parents=True, exist_ok=True)
    args.output_sql.write_text(sql + "\n", encoding="utf-8")
    available = [r for r in rows if r["status"] == "available"]
    unavailable = [r for r in rows if r["status"] != "available"]
    print(f"SQL: {args.output_sql}")
    print(f"Views disponiveis: {len(available)}")
    for r in available:
        print(f"  {r['duckdb_schema']}.{r['duckdb_view']} ({r['source_files']} parquet)")
    if unavailable:
        print(f"Conjuntos ainda indisponiveis: {len(unavailable)}")
        for r in unavailable:
            print(f"  {r['dataset_id']}: {r['discovery_url']}")
    if warnings:
        print("Avisos:", file=sys.stderr)
        for w in warnings:
            print(f"  {w}", file=sys.stderr)
    if args.database:
        apply_sql(args.database, args.output_sql)
        print(f"DuckDB atualizado: {args.database.expanduser()}")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
