# Contrato de integração territorial

Este documento define como as referências territoriais do lake serão usadas
por CNES, bases de produção, internação e notificação. O objetivo é impedir
joins ad hoc que misturem códigos e regionalizações de épocas diferentes.

## Chaves canônicas

- `co_municipio`: código DATASUS/IBGE de 6 dígitos, usado como chave
  territorial operacional.
- `co_municipio_ibge`: código IBGE de 7 dígitos com dígito verificador.
- `snapshot_key`: competência AAAAMM em que uma configuração territorial foi
  observada na Base Territorial DATASUS.
- códigos de CIR/macrorregião permanecem texto para preservar zeros à esquerda.

## Regra temporal

Para fatos mensais, o vínculo territorial é feito pelo município e pelo último
snapshot territorial homologado menor ou igual à competência do fato.

Para fatos com data de evento, deriva-se AAAAMM da data escolhida para o papel
territorial em questão e aplica-se a mesma regra "as-of".

A data observada no snapshot não é automaticamente a data jurídica de vigência.
Atos CIB/CIR serão ligados posteriormente em camada normativa separada.

## Papéis municipais por sistema

| Sistema | Âncora temporal preferencial | Papéis territoriais a preservar |
|---|---|---|
| CNES | competência CNES | município do estabelecimento |
| SIA | competência de produção | município do estabelecimento; residência quando disponível |
| SIH | competência/internação conforme análise | município do estabelecimento; residência |
| CIH/CIHA | competência/evento conforme schema | estabelecimento; residência |
| SIM | data do óbito | residência; ocorrência |
| SINASC | data do nascimento | residência da mãe; ocorrência |
| SINAN | data de notificação ou início de sintomas, explicitada por análise | residência; notificação; infecção quando disponível |
| SIPNI | data de vacinação | residência; estabelecimento/aplicação conforme schema |

Nenhum adaptador deve substituir silenciosamente um papel municipal por outro.

## Camadas

- Raw/Bronze territorial: snapshots oficiais, imutáveis por conteúdo.
- Silver corrente: referências territoriais atuais, por exemplo
  `municipio_contexto/current.parquet`.
- Memória temporal: materialização derivada de todos os snapshots homologados;
  construída apenas após o backfill global estar completo.
- Camada normativa: atos CIB/CIR e datas jurídicas, futura, ligada aos eventos
  detectados nos snapshots.

## Uso futuro

A memória temporal deverá permitir views ou bridges do tipo:

`municipio × competencia -> CIR/macrorregiao`

Essa bridge será usada pelos adapters de CNES/SIA/SIH/CIH/CIHA/SIM/SINAN/
SINASC/SIPNI, evitando gravar regionalização diretamente nas tabelas fato.
