# Layout SIGTAP

`fwf.tsv` foi inicialmente transcrito do notebook de ETL fornecido pelo projeto,
cujo exemplo usa a competência 202408.

A partir da competência 202506, o layout de `tb_procedimento` ampliou os campos
monetários `vl_sh`, `vl_sa` e `vl_sp` em duas posições. O pipeline valida a
largura real de todas as linhas antes de publicar Parquet.

Qualquer TXT novo ou mudança de largura bloqueia a carga completa e gera um
relatório em `state/sigtap/`; o contrato deve então ser atualizado por revisão
de curadoria.
