# ADR 0007 — Projeção pública do Raw oficial

Status: superseded por ADR 0008

Este ADR documenta a política anterior, na qual artefatos Raw autorizados eram
projetados por hardlink em `/dados/abertos/raw/` e publicados em
`/files/raw/`.

A decisão foi substituída em 2026-11-16 para manter uma única árvore de dados
sob `/dados/abertos/suslake/{raw,bronze,silver}`.

As garantias que permanecem válidas são:

- publicação somente por allowlist;
- hardlink em vez de cópia quando uma projeção seletiva for necessária;
- ausência de cópia silenciosa entre filesystems;
- gate de CQ antes de publicação;
- HTTP somente leitura;
- preservação da fonte canônica quando um link público é removido.

A superfície e as regras correntes estão no ADR 0008.
