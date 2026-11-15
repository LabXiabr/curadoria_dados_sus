# CIHA — modelo canônico

CIHA continua a série da CIH a partir de 2011 e acrescenta características
ambulatoriais, como quantidade de procedimentos e modalidade assistencial.

Silver:
- `fact_ciha_evento`: uma linha por registro disseminado;
- `vw_cih_ciha_evento_core`: núcleo compartilhado com CIH.

CNES, procedimento/SIGTAP, CID e território são referências temporais; seus
rótulos não substituem os códigos originais. `TAB_CIHA.zip` é versionado por
hash e preservado junto dos DEF/CNV/DBD/DBF.
