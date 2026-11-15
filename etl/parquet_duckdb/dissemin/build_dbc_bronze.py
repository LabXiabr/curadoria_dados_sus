#!/usr/bin/env python3
import sys

print(
    "ERRO: este loader DBC foi desativado. "
    "A migracao inicial usa PostgreSQL -> Parquet; "
    "recomposicao DBC futura deve usar a ETL Wine existente.",
    file=sys.stderr,
)
raise SystemExit(78)
