# ADR 0008 — Superfície pública dentro da árvore SUS Lake

Status: aceito

## Contexto

A política anterior mantinha a lake canônica em `/dados/abertos/suslake` e
criava projeções públicas paralelas em `/dados/abertos/raw`,
`/dados/abertos/bronze` e `/dados/abertos/silver`.

Isso criava duas árvores concorrentes e tornava a descoberta de dados ambígua.

## Decisão

A única árvore de dados é:

```text
/dados/abertos/suslake/
├── raw/
├── bronze/
└── silver/
```

A URL pública correspondente começa em:

`https://dados.labx.ia.br/files/suslake/`

Não são criadas novas raízes `/dados/abertos/raw`, `bronze` ou `silver`.

## Política default-deny

A árvore SUS Lake é privada por padrão. O Apache concede acesso somente aos
datasets explicitamente autorizados.

Áreas operacionais como `state`, `staging`, `work` e `logs` nunca fazem
parte da superfície pública.

## Raw seletivo

Artefatos Raw autorizados são projetados por hardlink em `raw/public/`, mantendo o acervo Raw canônico privado por padrão. A URL é `/files/suslake/raw/public/`.

## Dataset totalmente público

Quando o dataset canônico inteiro pode ser distribuído, o próprio caminho
canônico pode receber regra explícita de leitura.

## Publicação seletiva

Quando apenas um subconjunto da fonte pode/deve ser publicado, cria-se uma
projeção por hardlink **dentro da mesma camada**, com nome distinto.

Exemplo CNES:

```text
bronze/cnes/             # canônico completo, privado
bronze/cnes_reference/   # subconjunto autorizado, público

silver/cnes/             # canônico, privado por padrão
silver/cnes_reference/   # snapshots homologados, públicos
```

A projeção seletiva deve apontar para os mesmos inodes e nunca duplicar bytes.

## Gates

CNES Bronze de referência exige `base_complete_<competencia>.ok`.
CNES Silver exige snapshot homologado e `qc_global_<competencia>.ok`.

SIA/SIH e demais sistemas só são publicados após CQ estrutural e, quando
aplicável, CQ externo oficial conforme ADR 0004 e ADR 0005.

## Compatibilidade

URLs antigos fora de `/files/suslake/` podem ser retirados depois que:

1. o novo caminho estiver publicado;
2. os hardlinks forem verificados;
3. HEAD/Range HTTP passarem;
4. catálogos apontarem para a nova superfície.

Não se mantém indefinidamente duas superfícies equivalentes.
