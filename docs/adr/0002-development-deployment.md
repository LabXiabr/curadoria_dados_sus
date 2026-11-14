# ADR 0002 - Desenvolvimento e implantação

- bequer: desenvolvimento, commits e push;
- bureta: execução operacional; sem edição/commit local;
- pipeta: processamento/cache especializado quando necessário.

Branches:

- `develop`: desenvolvimento/homologação;
- `main`: versão homologada para operação.

A bureta recebe código exclusivamente por `git fetch/pull --ff-only`.
