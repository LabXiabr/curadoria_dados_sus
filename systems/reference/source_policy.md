# Política de fontes — referências territoriais e populacionais

## Objetivo

Manter referências geográficas e demográficas reutilizáveis por todo o lake,
sem depender de tabelas derivadas de CNES, SIA ou SIH.

## Fontes

### 1. Base territorial DATASUS — fonte principal de geografia SUS/TABNET

Origem:

`ftp://ftp.datasus.gov.br/territorio/tabelas/<ANO>/`

Uso:

- município;
- UF;
- região geográfica;
- capital e demais atributos municipais presentes em `tb_municip`;
- Região de Saúde (CIR);
- Macrorregião de Saúde;
- microrregião IBGE;
- Região Metropolitana / RIDE;
- Território da Cidadania;
- Mesorregião PNDR;
- divisões administrativas estaduais;
- DSEI;
- demais classificações e flags territoriais distribuídas no snapshot.

O Raw preserva o ZIP oficial inteiro. A Bronze converte todos os CSV do ZIP,
sem selecionar previamente apenas algumas tabelas. Portanto novas tabelas
publicadas pelo DATASUS também entram no inventário e no QC.

Tabelas esperadas nos snapshots recentes:

| Conceito | Tabela(s) |
|---|---|
| Município | `tb_municip` |
| UF | `tb_uf` |
| Região | `tb_regiao` |
| Região de Saúde | `tb_regsaud`, `rl_municip_regsaud` |
| Macrorregião de Saúde | `tb_macsaud`, `rl_municip_macsaud`, `rl_regsaud_macsaud` |
| Microrregião IBGE | `tb_micibge`, `rl_municip_micibge` |
| Região Metropolitana / RIDE | `tb_regmetr`, `rl_municip_regmetr` |
| Território da Cidadania | `tb_terrcid`, `rl_municip_terrcid` |
| Mesorregião PNDR | `tb_pndr`, `rl_municip_pndr` |
| Divisão administrativa | `tb_divadm`, `tb_divadmant`, `rl_municip_divadm` |
| DSEI | `tb_dsei`, `rl_municip_dsei` |

Flags como Amazônia Legal, semiárido, faixa/zona de fronteira, capital e
município de extrema pobreza devem ser vinculadas apenas depois de inspecionar
o schema efetivo do snapshot corrente. A Bronze preserva todas as colunas;
não inferir semântica pelo nome da coluna.

### 2. Regionalização de saúde corrente — fonte complementar

Origem:

`https://s3.sa-east-1.amazonaws.com/ckan.saude.gov.br/dbgeral/macroregiao_de_saude_csv.zip`

Uso:

- referência corrente específica para Região de Saúde e Macrorregião de Saúde;
- QC contra o snapshot territorial;
- não sobrescrever silenciosamente a base territorial histórica.

Se houver divergência, manter ambas as proveniências e produzir relatório de
diferenças antes de definir uma visão consolidada.

### 3. POPSVS — fonte principal de população detalhada

Origem:

`ftp://ftp.datasus.gov.br/dissemin/publicos/IBGE/POPSVS/`

Arquivos:

`POPSBR00.zip` a `POPSBR25.zip`.

Granularidade Silver:

`co_municipio × ano × sexo × idade`

O arquivo DBF é preservado no ZIP Raw; a Bronze mantém os valores da fonte e a
Silver tipa `ano` e `populacao`.

### 4. TabNet população — QC independente

O repositório `LabXiabr/tabnet-populacao` continua útil para consulta
independente dos totais municipais publicados no TabNet. Ele não substitui o
POPSVS detalhado no lake.

## Política temporal

- Raw: nunca sobrescrever conteúdo diferente.
- Bronze territorial: `snapshot=AAAAMM`.
- Silver territorial corrente: somente o snapshot mais novo pode atualizar
  `current.parquet`; carregar histórico não regride a referência atual.
- POPSVS: partição anual de 2000 a 2025.
- Regionalização de saúde: conteúdo versionado por SHA-256.

## Próxima etapa semântica

Após a primeira carga territorial, gerar uma visão
`reference.municipio_contexto_current` somente com chaves e colunas
confirmadas no schema real do snapshot. Essa visão deve combinar códigos e
nomes de município/UF/região e classificações territoriais, mantendo colunas de
proveniência por fonte.


## Memória temporal e integração com sistemas

A memória territorial consolidada é uma derivação, não a fonte primária.
Ela deve ser construída somente depois que todos os snapshots disponíveis
estiverem homologados por `territorio_backfill_complete.ok`.

O Git preserva a lógica, os contratos de chave e os scripts de reconstrução.
Os ZIPs oficiais, Bronze por snapshot e Parquet derivados permanecem no lake.

A integração futura com CNES, SIA, SIH, CIH/CIHA, SIM, SINAN, SINASC e SIPNI
segue `systems/reference/integration_contract.md` e
`systems/reference/system_temporal_keys.tsv`.
