-- DROP SCHEMA bd_sigtap_202502;

CREATE SCHEMA bd_sigtap_202502 AUTHORIZATION ferre;
-- bd_sigtap_202502.tb_cid definition

-- Drop table

-- DROP TABLE bd_sigtap_202502.tb_cid;

CREATE TABLE bd_sigtap_202502.tb_cid (
	co_cid varchar(4) NOT NULL,
	no_cid varchar(100) NULL,
	tp_agravo bpchar(1) NULL,
	tp_sexo bpchar(1) NULL,
	tp_estadio bpchar(1) NULL,
	vl_campos_irradiados numeric NULL,
	CONSTRAINT tb_cid_pkey PRIMARY KEY (co_cid)
);


-- bd_sigtap_202502.tb_detalhe definition

-- Drop table

-- DROP TABLE bd_sigtap_202502.tb_detalhe;

CREATE TABLE bd_sigtap_202502.tb_detalhe (
	co_detalhe varchar(3) NOT NULL,
	no_detalhe varchar(100) NULL,
	dt_competencia bpchar(6) NULL,
	CONSTRAINT tb_detalhe_pkey PRIMARY KEY (co_detalhe)
);


-- bd_sigtap_202502.tb_financiamento definition

-- Drop table

-- DROP TABLE bd_sigtap_202502.tb_financiamento;

CREATE TABLE bd_sigtap_202502.tb_financiamento (
	co_financiamento varchar(2) NOT NULL,
	no_financiamento varchar(100) NULL,
	dt_competencia bpchar(6) NULL,
	CONSTRAINT tb_financiamento_pkey PRIMARY KEY (co_financiamento)
);


-- bd_sigtap_202502.tb_grupo definition

-- Drop table

-- DROP TABLE bd_sigtap_202502.tb_grupo;

CREATE TABLE bd_sigtap_202502.tb_grupo (
	co_grupo varchar(2) NOT NULL,
	no_grupo varchar(100) NULL,
	dt_competencia bpchar(6) NULL,
	CONSTRAINT tb_grupo_pkey PRIMARY KEY (co_grupo)
);


-- bd_sigtap_202502.tb_grupo_habilitacao definition

-- Drop table

-- DROP TABLE bd_sigtap_202502.tb_grupo_habilitacao;

CREATE TABLE bd_sigtap_202502.tb_grupo_habilitacao (
	nu_grupo_habilitacao varchar(4) NOT NULL,
	no_grupo_habilitacao varchar(20) NULL,
	ds_grupo_habilitacao varchar(250) NULL,
	CONSTRAINT tb_grupo_habilitacao_pkey PRIMARY KEY (nu_grupo_habilitacao)
);


-- bd_sigtap_202502.tb_habilitacao definition

-- Drop table

-- DROP TABLE bd_sigtap_202502.tb_habilitacao;

CREATE TABLE bd_sigtap_202502.tb_habilitacao (
	co_habilitacao varchar(4) NOT NULL,
	no_habilitacao varchar(150) NULL,
	dt_competencia bpchar(6) NULL,
	CONSTRAINT tb_habilitacao_pkey PRIMARY KEY (co_habilitacao)
);


-- bd_sigtap_202502.tb_modalidade definition

-- Drop table

-- DROP TABLE bd_sigtap_202502.tb_modalidade;

CREATE TABLE bd_sigtap_202502.tb_modalidade (
	co_modalidade varchar(2) NOT NULL,
	no_modalidade varchar(100) NULL,
	dt_competencia bpchar(6) NULL,
	CONSTRAINT tb_modalidade_pkey PRIMARY KEY (co_modalidade)
);


-- bd_sigtap_202502.tb_ocupacao definition

-- Drop table

-- DROP TABLE bd_sigtap_202502.tb_ocupacao;

CREATE TABLE bd_sigtap_202502.tb_ocupacao (
	co_ocupacao bpchar(6) NOT NULL,
	no_ocupacao varchar(150) NULL,
	CONSTRAINT tb_ocupacao_pkey PRIMARY KEY (co_ocupacao)
);


-- bd_sigtap_202502.tb_rede_atencao definition

-- Drop table

-- DROP TABLE bd_sigtap_202502.tb_rede_atencao;

CREATE TABLE bd_sigtap_202502.tb_rede_atencao (
	co_rede_atencao varchar(3) NOT NULL,
	no_rede_atencao varchar(50) NULL,
	CONSTRAINT tb_rede_atencao_pkey PRIMARY KEY (co_rede_atencao)
);


-- bd_sigtap_202502.tb_registro definition

-- Drop table

-- DROP TABLE bd_sigtap_202502.tb_registro;

CREATE TABLE bd_sigtap_202502.tb_registro (
	co_registro varchar(2) NOT NULL,
	no_registro varchar(50) NULL,
	dt_competencia bpchar(6) NULL,
	CONSTRAINT tb_registro_pkey PRIMARY KEY (co_registro)
);


-- bd_sigtap_202502.tb_regra_condicionada definition

-- Drop table

-- DROP TABLE bd_sigtap_202502.tb_regra_condicionada;

CREATE TABLE bd_sigtap_202502.tb_regra_condicionada (
	co_regra_condicionada varchar(4) NOT NULL,
	no_regra_condicionada varchar(150) NULL,
	ds_regra_condicionada text NULL,
	CONSTRAINT tb_regra_condicionada_pkey PRIMARY KEY (co_regra_condicionada)
);


-- bd_sigtap_202502.tb_renases definition

-- Drop table

-- DROP TABLE bd_sigtap_202502.tb_renases;

CREATE TABLE bd_sigtap_202502.tb_renases (
	co_renases varchar(10) NOT NULL,
	no_renases varchar(150) NULL,
	CONSTRAINT tb_renases_pkey PRIMARY KEY (co_renases)
);


-- bd_sigtap_202502.tb_rubrica definition

-- Drop table

-- DROP TABLE bd_sigtap_202502.tb_rubrica;

CREATE TABLE bd_sigtap_202502.tb_rubrica (
	co_rubrica varchar(6) NOT NULL,
	no_rubrica varchar(100) NULL,
	dt_competencia bpchar(6) NULL,
	CONSTRAINT tb_rubrica_pkey PRIMARY KEY (co_rubrica)
);


-- bd_sigtap_202502.tb_servico definition

-- Drop table

-- DROP TABLE bd_sigtap_202502.tb_servico;

CREATE TABLE bd_sigtap_202502.tb_servico (
	co_servico varchar(3) NOT NULL,
	no_servico varchar(120) NULL,
	dt_competencia bpchar(6) NULL,
	CONSTRAINT tb_servico_pkey PRIMARY KEY (co_servico)
);


-- bd_sigtap_202502.tb_sia_sih definition

-- Drop table

-- DROP TABLE bd_sigtap_202502.tb_sia_sih;

CREATE TABLE bd_sigtap_202502.tb_sia_sih (
	co_procedimento_sia_sih varchar(10) NOT NULL,
	no_procedimento_sia_sih varchar(100) NULL,
	tp_procedimento varchar(1) NOT NULL,
	dt_competencia bpchar(6) NULL,
	CONSTRAINT tb_sia_sih_pkey PRIMARY KEY (co_procedimento_sia_sih, tp_procedimento)
);


-- bd_sigtap_202502.tb_tipo_leito definition

-- Drop table

-- DROP TABLE bd_sigtap_202502.tb_tipo_leito;

CREATE TABLE bd_sigtap_202502.tb_tipo_leito (
	co_tipo_leito varchar(2) NOT NULL,
	no_tipo_leito varchar(60) NULL,
	dt_competencia bpchar(6) NULL,
	CONSTRAINT tb_tipo_leito_pkey PRIMARY KEY (co_tipo_leito)
);


-- bd_sigtap_202502.tb_tuss definition

-- Drop table

-- DROP TABLE bd_sigtap_202502.tb_tuss;

CREATE TABLE bd_sigtap_202502.tb_tuss (
	co_tuss varchar(10) NOT NULL,
	no_tuss text NULL,
	CONSTRAINT tb_tuss_pkey PRIMARY KEY (co_tuss)
);


-- bd_sigtap_202502.tb_componente_rede definition

-- Drop table

-- DROP TABLE bd_sigtap_202502.tb_componente_rede;

CREATE TABLE bd_sigtap_202502.tb_componente_rede (
	co_componente_rede varchar(10) NOT NULL,
	no_componente_rede varchar(150) NULL,
	co_rede_atencao varchar(3) NULL,
	CONSTRAINT tb_componente_rede_pkey PRIMARY KEY (co_componente_rede),
	CONSTRAINT fk_componente_rede_atencao FOREIGN KEY (co_rede_atencao) REFERENCES bd_sigtap_202502.tb_rede_atencao(co_rede_atencao)
);


-- bd_sigtap_202502.tb_descricao_detalhe definition

-- Drop table

-- DROP TABLE bd_sigtap_202502.tb_descricao_detalhe;

CREATE TABLE bd_sigtap_202502.tb_descricao_detalhe (
	co_detalhe varchar(3) NOT NULL,
	ds_detalhe text NULL,
	dt_competencia bpchar(6) NULL,
	CONSTRAINT tb_descricao_detalhe_pkey PRIMARY KEY (co_detalhe),
	CONSTRAINT fk_detalhe_descricao FOREIGN KEY (co_detalhe) REFERENCES bd_sigtap_202502.tb_detalhe(co_detalhe)
);


-- bd_sigtap_202502.tb_servico_classificacao definition

-- Drop table

-- DROP TABLE bd_sigtap_202502.tb_servico_classificacao;

CREATE TABLE bd_sigtap_202502.tb_servico_classificacao (
	co_servico varchar(3) NOT NULL,
	co_classificacao varchar(3) NOT NULL,
	no_classificacao varchar(150) NULL,
	dt_competencia bpchar(6) NULL,
	CONSTRAINT tb_servico_classificacao_pkey PRIMARY KEY (co_servico, co_classificacao),
	CONSTRAINT fk_servico_classificacao_servico FOREIGN KEY (co_servico) REFERENCES bd_sigtap_202502.tb_servico(co_servico)
);


-- bd_sigtap_202502.tb_sub_grupo definition

-- Drop table

-- DROP TABLE bd_sigtap_202502.tb_sub_grupo;

CREATE TABLE bd_sigtap_202502.tb_sub_grupo (
	co_grupo varchar(2) NOT NULL,
	co_sub_grupo varchar(2) NOT NULL,
	no_sub_grupo varchar(100) NULL,
	dt_competencia bpchar(6) NULL,
	CONSTRAINT tb_sub_grupo_pkey PRIMARY KEY (co_grupo, co_sub_grupo),
	CONSTRAINT fk_sub_grupo_grupo FOREIGN KEY (co_grupo) REFERENCES bd_sigtap_202502.tb_grupo(co_grupo)
);


-- bd_sigtap_202502.tb_forma_organizacao definition

-- Drop table

-- DROP TABLE bd_sigtap_202502.tb_forma_organizacao;

CREATE TABLE bd_sigtap_202502.tb_forma_organizacao (
	co_grupo varchar(2) NOT NULL,
	co_sub_grupo varchar(2) NOT NULL,
	co_forma_organizacao varchar(2) NOT NULL,
	no_forma_organizacao varchar(100) NULL,
	dt_competencia bpchar(6) NULL,
	CONSTRAINT tb_forma_organizacao_pkey PRIMARY KEY (co_grupo, co_sub_grupo, co_forma_organizacao),
	CONSTRAINT fk_forma_organizacao_grupo FOREIGN KEY (co_grupo) REFERENCES bd_sigtap_202502.tb_grupo(co_grupo),
	CONSTRAINT fk_forma_organizacao_sub_grupo FOREIGN KEY (co_grupo,co_sub_grupo) REFERENCES bd_sigtap_202502.tb_sub_grupo(co_grupo,co_sub_grupo)
);


-- bd_sigtap_202502.tb_procedimento definition

-- Drop table

-- DROP TABLE bd_sigtap_202502.tb_procedimento;

CREATE TABLE bd_sigtap_202502.tb_procedimento (
	co_procedimento varchar(10) NOT NULL,
	no_procedimento varchar(250) NULL,
	tp_complexidade varchar(1) NULL,
	tp_sexo varchar(1) NULL,
	qt_maxima_execucao numeric NULL,
	qt_dias_permanencia numeric NULL,
	qt_pontos numeric NULL,
	vl_idade_minima numeric NULL,
	vl_idade_maxima numeric NULL,
	vl_sh numeric NULL,
	vl_sa numeric NULL,
	vl_sp numeric NULL,
	co_financiamento varchar(2) NULL,
	co_rubrica varchar(6) NULL,
	qt_tempo_permanencia numeric NULL,
	dt_competencia bpchar(6) NULL,
	co_grupo varchar(2) NULL,
	co_forma_organizacao varchar(2) NULL,
	co_sub_grupo varchar(2) NULL,
	CONSTRAINT tb_procedimento_pkey PRIMARY KEY (co_procedimento),
	CONSTRAINT fk_procedimento_financiamento FOREIGN KEY (co_financiamento) REFERENCES bd_sigtap_202502.tb_financiamento(co_financiamento),
	CONSTRAINT fk_procedimento_forma_organizacao FOREIGN KEY (co_grupo,co_sub_grupo,co_forma_organizacao) REFERENCES bd_sigtap_202502.tb_forma_organizacao(co_grupo,co_sub_grupo,co_forma_organizacao),
	CONSTRAINT fk_procedimento_rubrica FOREIGN KEY (co_rubrica) REFERENCES bd_sigtap_202502.tb_rubrica(co_rubrica)
);


-- bd_sigtap_202502.rl_excecao_compatibilidade definition

-- Drop table

-- DROP TABLE bd_sigtap_202502.rl_excecao_compatibilidade;

CREATE TABLE bd_sigtap_202502.rl_excecao_compatibilidade (
	co_procedimento_restricao varchar(10) NULL,
	co_procedimento_principal varchar(10) NULL,
	co_registro_principal varchar(2) NULL,
	co_procedimento_compativel varchar(10) NULL,
	co_registro_compativel varchar(2) NULL,
	tp_compatibilidade varchar(1) NULL,
	dt_competencia bpchar(6) NULL,
	CONSTRAINT fk_excecao_compat_procedimento_compativel FOREIGN KEY (co_procedimento_compativel) REFERENCES bd_sigtap_202502.tb_procedimento(co_procedimento),
	CONSTRAINT fk_excecao_compat_procedimento_principal FOREIGN KEY (co_procedimento_principal) REFERENCES bd_sigtap_202502.tb_procedimento(co_procedimento),
	CONSTRAINT fk_excecao_compat_procedimento_restricao FOREIGN KEY (co_procedimento_restricao) REFERENCES bd_sigtap_202502.tb_procedimento(co_procedimento)
);


-- bd_sigtap_202502.rl_procedimento_cid definition

-- Drop table

-- DROP TABLE bd_sigtap_202502.rl_procedimento_cid;

CREATE TABLE bd_sigtap_202502.rl_procedimento_cid (
	co_procedimento varchar(10) NOT NULL,
	co_cid varchar(4) NOT NULL,
	st_principal bpchar(1) NULL,
	dt_competencia bpchar(6) NULL,
	CONSTRAINT rl_procedimento_cid_pkey PRIMARY KEY (co_procedimento, co_cid),
	CONSTRAINT fk_procedimento_cid FOREIGN KEY (co_procedimento) REFERENCES bd_sigtap_202502.tb_procedimento(co_procedimento),
	CONSTRAINT fk_procedimento_cid_cid FOREIGN KEY (co_cid) REFERENCES bd_sigtap_202502.tb_cid(co_cid)
);


-- bd_sigtap_202502.rl_procedimento_comp_rede definition

-- Drop table

-- DROP TABLE bd_sigtap_202502.rl_procedimento_comp_rede;

CREATE TABLE bd_sigtap_202502.rl_procedimento_comp_rede (
	co_procedimento varchar(10) NOT NULL,
	co_componente_rede varchar(10) NOT NULL,
	CONSTRAINT rl_procedimento_comp_rede_pkey PRIMARY KEY (co_procedimento, co_componente_rede),
	CONSTRAINT fk_comp_rede_co_componente_rede FOREIGN KEY (co_componente_rede) REFERENCES bd_sigtap_202502.tb_componente_rede(co_componente_rede),
	CONSTRAINT fk_comp_rede_co_procedimento FOREIGN KEY (co_procedimento) REFERENCES bd_sigtap_202502.tb_procedimento(co_procedimento)
);


-- bd_sigtap_202502.rl_procedimento_compativel definition

-- Drop table

-- DROP TABLE bd_sigtap_202502.rl_procedimento_compativel;

CREATE TABLE bd_sigtap_202502.rl_procedimento_compativel (
	co_procedimento_principal varchar(10) NOT NULL,
	co_registro_principal varchar(2) NOT NULL,
	co_procedimento_compativel varchar(10) NOT NULL,
	co_registro_compativel varchar(2) NOT NULL,
	tp_compatibilidade varchar(1) NOT NULL,
	qt_permitida numeric NULL,
	dt_competencia bpchar(6) NULL,
	CONSTRAINT rl_procedimento_compativel_pkey PRIMARY KEY (co_procedimento_principal, co_registro_principal, co_procedimento_compativel, co_registro_compativel, tp_compatibilidade),
	CONSTRAINT fk_compativel_compativel_procedimento FOREIGN KEY (co_procedimento_compativel) REFERENCES bd_sigtap_202502.tb_procedimento(co_procedimento),
	CONSTRAINT fk_compativel_principal_procedimento FOREIGN KEY (co_procedimento_principal) REFERENCES bd_sigtap_202502.tb_procedimento(co_procedimento),
	CONSTRAINT fk_compativel_registro_compativel FOREIGN KEY (co_registro_compativel) REFERENCES bd_sigtap_202502.tb_registro(co_registro)
);


-- bd_sigtap_202502.rl_procedimento_detalhe definition

-- Drop table

-- DROP TABLE bd_sigtap_202502.rl_procedimento_detalhe;

CREATE TABLE bd_sigtap_202502.rl_procedimento_detalhe (
	co_procedimento varchar(10) NOT NULL,
	co_detalhe varchar(3) NOT NULL,
	dt_competencia bpchar(6) NULL,
	CONSTRAINT rl_procedimento_detalhe_pkey PRIMARY KEY (co_procedimento, co_detalhe),
	CONSTRAINT fk_detalhe_procedimento FOREIGN KEY (co_procedimento) REFERENCES bd_sigtap_202502.tb_procedimento(co_procedimento),
	CONSTRAINT fk_detalhe_procedimento_co_detalhe FOREIGN KEY (co_detalhe) REFERENCES bd_sigtap_202502.tb_detalhe(co_detalhe)
);


-- bd_sigtap_202502.rl_procedimento_habilitacao definition

-- Drop table

-- DROP TABLE bd_sigtap_202502.rl_procedimento_habilitacao;

CREATE TABLE bd_sigtap_202502.rl_procedimento_habilitacao (
	co_procedimento varchar(10) NOT NULL,
	co_habilitacao varchar(4) NOT NULL,
	nu_grupo_habilitacao varchar(4) NOT NULL,
	dt_competencia bpchar(6) NULL,
	CONSTRAINT rl_procedimento_habilitacao_pkey PRIMARY KEY (co_procedimento, co_habilitacao, nu_grupo_habilitacao),
	CONSTRAINT fk_habilitacao_procedimento FOREIGN KEY (co_procedimento) REFERENCES bd_sigtap_202502.tb_procedimento(co_procedimento),
	CONSTRAINT fk_procedimento_habilitacao_grupo_habilitacao FOREIGN KEY (nu_grupo_habilitacao) REFERENCES bd_sigtap_202502.tb_grupo_habilitacao(nu_grupo_habilitacao),
	CONSTRAINT fk_procedimento_habilitacao_habilitacao FOREIGN KEY (co_habilitacao) REFERENCES bd_sigtap_202502.tb_habilitacao(co_habilitacao)
);


-- bd_sigtap_202502.rl_procedimento_incremento definition

-- Drop table

-- DROP TABLE bd_sigtap_202502.rl_procedimento_incremento;

CREATE TABLE bd_sigtap_202502.rl_procedimento_incremento (
	co_procedimento varchar(10) NOT NULL,
	co_habilitacao varchar(4) NOT NULL,
	vl_percentual_sh numeric NULL,
	vl_percentual_sa numeric NULL,
	vl_percentual_sp numeric NULL,
	dt_competencia bpchar(6) NULL,
	CONSTRAINT rl_procedimento_incremento_pkey PRIMARY KEY (co_procedimento, co_habilitacao),
	CONSTRAINT fk_incremento_habilitacao FOREIGN KEY (co_habilitacao) REFERENCES bd_sigtap_202502.tb_habilitacao(co_habilitacao),
	CONSTRAINT fk_incremento_procedimento FOREIGN KEY (co_procedimento) REFERENCES bd_sigtap_202502.tb_procedimento(co_procedimento)
);


-- bd_sigtap_202502.rl_procedimento_leito definition

-- Drop table

-- DROP TABLE bd_sigtap_202502.rl_procedimento_leito;

CREATE TABLE bd_sigtap_202502.rl_procedimento_leito (
	co_procedimento varchar(10) NOT NULL,
	co_tipo_leito varchar(2) NOT NULL,
	dt_competencia bpchar(6) NULL,
	CONSTRAINT rl_procedimento_leito_pkey PRIMARY KEY (co_procedimento, co_tipo_leito),
	CONSTRAINT fk_leito_procedimento FOREIGN KEY (co_procedimento) REFERENCES bd_sigtap_202502.tb_procedimento(co_procedimento),
	CONSTRAINT fk_leito_procedimento_co_tipo_leito FOREIGN KEY (co_tipo_leito) REFERENCES bd_sigtap_202502.tb_tipo_leito(co_tipo_leito)
);


-- bd_sigtap_202502.rl_procedimento_modalidade definition

-- Drop table

-- DROP TABLE bd_sigtap_202502.rl_procedimento_modalidade;

CREATE TABLE bd_sigtap_202502.rl_procedimento_modalidade (
	co_procedimento varchar(10) NOT NULL,
	co_modalidade varchar(2) NOT NULL,
	dt_competencia bpchar(6) NULL,
	CONSTRAINT rl_procedimento_modalidade_pkey PRIMARY KEY (co_procedimento, co_modalidade),
	CONSTRAINT fk_modalidade_modalidade FOREIGN KEY (co_modalidade) REFERENCES bd_sigtap_202502.tb_modalidade(co_modalidade),
	CONSTRAINT fk_modalidade_procedimento FOREIGN KEY (co_procedimento) REFERENCES bd_sigtap_202502.tb_procedimento(co_procedimento)
);


-- bd_sigtap_202502.rl_procedimento_ocupacao definition

-- Drop table

-- DROP TABLE bd_sigtap_202502.rl_procedimento_ocupacao;

CREATE TABLE bd_sigtap_202502.rl_procedimento_ocupacao (
	co_procedimento varchar(10) NOT NULL,
	co_ocupacao bpchar(6) NOT NULL,
	dt_competencia bpchar(6) NULL,
	CONSTRAINT rl_procedimento_ocupacao_pkey PRIMARY KEY (co_procedimento, co_ocupacao),
	CONSTRAINT fk_ocupacao_ocupacao FOREIGN KEY (co_ocupacao) REFERENCES bd_sigtap_202502.tb_ocupacao(co_ocupacao),
	CONSTRAINT fk_ocupacao_procedimento FOREIGN KEY (co_procedimento) REFERENCES bd_sigtap_202502.tb_procedimento(co_procedimento)
);


-- bd_sigtap_202502.rl_procedimento_origem definition

-- Drop table

-- DROP TABLE bd_sigtap_202502.rl_procedimento_origem;

CREATE TABLE bd_sigtap_202502.rl_procedimento_origem (
	co_procedimento varchar(10) NOT NULL,
	co_procedimento_origem varchar(10) NOT NULL,
	dt_competencia bpchar(6) NULL,
	CONSTRAINT rl_procedimento_origem_pkey PRIMARY KEY (co_procedimento, co_procedimento_origem),
	CONSTRAINT fk_origem_procedimento FOREIGN KEY (co_procedimento) REFERENCES bd_sigtap_202502.tb_procedimento(co_procedimento),
	CONSTRAINT fk_origem_procedimento_procedimento FOREIGN KEY (co_procedimento_origem) REFERENCES bd_sigtap_202502.tb_procedimento(co_procedimento)
);


-- bd_sigtap_202502.rl_procedimento_registro definition

-- Drop table

-- DROP TABLE bd_sigtap_202502.rl_procedimento_registro;

CREATE TABLE bd_sigtap_202502.rl_procedimento_registro (
	co_procedimento varchar(10) NOT NULL,
	co_registro varchar(2) NOT NULL,
	dt_competencia bpchar(6) NULL,
	CONSTRAINT rl_procedimento_registro_pkey PRIMARY KEY (co_procedimento, co_registro),
	CONSTRAINT fk_registro_procedimento FOREIGN KEY (co_procedimento) REFERENCES bd_sigtap_202502.tb_procedimento(co_procedimento)
);


-- bd_sigtap_202502.rl_procedimento_regra_cond definition

-- Drop table

-- DROP TABLE bd_sigtap_202502.rl_procedimento_regra_cond;

CREATE TABLE bd_sigtap_202502.rl_procedimento_regra_cond (
	co_procedimento varchar(10) NOT NULL,
	co_regra_condicionada varchar(4) NOT NULL,
	CONSTRAINT rl_procedimento_regra_cond_pkey PRIMARY KEY (co_procedimento, co_regra_condicionada),
	CONSTRAINT fk_regra_cond_procedimento FOREIGN KEY (co_procedimento) REFERENCES bd_sigtap_202502.tb_procedimento(co_procedimento),
	CONSTRAINT fk_regra_cond_regra FOREIGN KEY (co_regra_condicionada) REFERENCES bd_sigtap_202502.tb_regra_condicionada(co_regra_condicionada)
);


-- bd_sigtap_202502.rl_procedimento_renases definition

-- Drop table

-- DROP TABLE bd_sigtap_202502.rl_procedimento_renases;

CREATE TABLE bd_sigtap_202502.rl_procedimento_renases (
	co_procedimento varchar(10) NOT NULL,
	co_renases varchar(10) NOT NULL,
	CONSTRAINT rl_procedimento_renases_pkey PRIMARY KEY (co_procedimento, co_renases),
	CONSTRAINT fk_renases_procedimento FOREIGN KEY (co_procedimento) REFERENCES bd_sigtap_202502.tb_procedimento(co_procedimento),
	CONSTRAINT fk_rl_renases_to_tb_renases FOREIGN KEY (co_renases) REFERENCES bd_sigtap_202502.tb_renases(co_renases)
);


-- bd_sigtap_202502.rl_procedimento_servico definition

-- Drop table

-- DROP TABLE bd_sigtap_202502.rl_procedimento_servico;

CREATE TABLE bd_sigtap_202502.rl_procedimento_servico (
	co_procedimento varchar(10) NOT NULL,
	co_servico varchar(3) NOT NULL,
	co_classificacao varchar(3) NOT NULL,
	dt_competencia bpchar(6) NULL,
	CONSTRAINT rl_procedimento_servico_pkey PRIMARY KEY (co_procedimento, co_servico, co_classificacao),
	CONSTRAINT fk_servico_procedimento FOREIGN KEY (co_procedimento) REFERENCES bd_sigtap_202502.tb_procedimento(co_procedimento),
	CONSTRAINT fk_servico_servico FOREIGN KEY (co_servico) REFERENCES bd_sigtap_202502.tb_servico(co_servico)
);


-- bd_sigtap_202502.rl_procedimento_sia_sih definition

-- Drop table

-- DROP TABLE bd_sigtap_202502.rl_procedimento_sia_sih;

CREATE TABLE bd_sigtap_202502.rl_procedimento_sia_sih (
	co_procedimento varchar(10) NOT NULL,
	co_procedimento_sia_sih varchar(10) NOT NULL,
	tp_procedimento varchar(1) NULL,
	dt_competencia bpchar(6) NULL,
	CONSTRAINT rl_procedimento_sia_sih_pkey PRIMARY KEY (co_procedimento, co_procedimento_sia_sih),
	CONSTRAINT fk_sia_sih_procedimento FOREIGN KEY (co_procedimento) REFERENCES bd_sigtap_202502.tb_procedimento(co_procedimento)
);


-- bd_sigtap_202502.rl_procedimento_tuss definition

-- Drop table

-- DROP TABLE bd_sigtap_202502.rl_procedimento_tuss;

CREATE TABLE bd_sigtap_202502.rl_procedimento_tuss (
	co_procedimento varchar(10) NOT NULL,
	co_tuss varchar(10) NOT NULL,
	CONSTRAINT rl_procedimento_tuss_pkey PRIMARY KEY (co_procedimento, co_tuss),
	CONSTRAINT fk_proc_tuss_tuss FOREIGN KEY (co_tuss) REFERENCES bd_sigtap_202502.tb_tuss(co_tuss),
	CONSTRAINT fk_tuss_procedimento FOREIGN KEY (co_procedimento) REFERENCES bd_sigtap_202502.tb_procedimento(co_procedimento)
);


-- bd_sigtap_202502.tb_descricao definition

-- Drop table

-- DROP TABLE bd_sigtap_202502.tb_descricao;

CREATE TABLE bd_sigtap_202502.tb_descricao (
	co_procedimento varchar(10) NOT NULL,
	ds_procedimento text NULL,
	dt_competencia bpchar(6) NULL,
	CONSTRAINT tb_descricao_pkey PRIMARY KEY (co_procedimento),
	CONSTRAINT fk_descricao_procedimento FOREIGN KEY (co_procedimento) REFERENCES bd_sigtap_202502.tb_procedimento(co_procedimento)
);


-- bd_sigtap_202502.tf_procedimento source

CREATE MATERIALIZED VIEW bd_sigtap_202502.tf_procedimento
TABLESPACE pg_default
AS SELECT p.co_procedimento,
    p.no_procedimento,
    p.tp_complexidade,
    p.tp_sexo,
    p.qt_maxima_execucao,
    p.qt_dias_permanencia,
    p.qt_pontos,
    p.vl_idade_minima,
    p.vl_idade_maxima,
    p.vl_sh / 100::numeric AS vl_sh,
    p.vl_sa / 100::numeric AS vl_sa,
    p.vl_sp / 100::numeric AS "?column?",
    p.co_financiamento,
    p.co_rubrica,
    p.qt_tempo_permanencia,
    p.dt_competencia,
    p.co_grupo,
    p.co_forma_organizacao,
    p.co_sub_grupo,
    f.no_financiamento,
    string_agg(DISTINCT (pl.co_tipo_leito::text || ' '::text) || TRIM(BOTH FROM tl.no_tipo_leito), ' | '::text) AS tp_leito,
    string_agg(DISTINCT (pm.co_modalidade::text || ' '::text) || TRIM(BOTH FROM m.no_modalidade), ' | '::text) AS tp_modalidade,
    string_agg(DISTINCT (ph.co_habilitacao::text || ' '::text) || TRIM(BOTH FROM h.no_habilitacao), ' | '::text) AS tp_habilitacao,
    json_agg(json_build_object('co_habilitacao', pi.co_habilitacao, 'no_habilitacao', TRIM(BOTH FROM h1.no_habilitacao), 'sh', round(pi.vl_percentual_sh / 100::numeric, 2), 'sa', round(pi.vl_percentual_sa / 100::numeric, 2), 'sp', round(pi.vl_percentual_sp / 100::numeric, 2))) AS tp_habilitacao_incremento,
    json_agg(json_build_object('co_detalhe', d.co_detalhe, 'no_detalhe', TRIM(BOTH FROM d.no_detalhe))) AS tp_detalhes
   FROM bd_sigtap_202502.tb_procedimento p
     LEFT JOIN bd_sigtap_202502.tb_financiamento f ON p.co_financiamento::text = f.co_financiamento::text
     LEFT JOIN bd_sigtap_202502.rl_procedimento_leito pl ON p.co_procedimento::text = pl.co_procedimento::text
     LEFT JOIN bd_sigtap_202502.tb_tipo_leito tl ON pl.co_tipo_leito::text = pl.co_tipo_leito::text
     LEFT JOIN bd_sigtap_202502.rl_procedimento_modalidade pm ON p.co_procedimento::text = pm.co_procedimento::text
     LEFT JOIN bd_sigtap_202502.tb_modalidade m ON m.co_modalidade::text = pm.co_modalidade::text
     LEFT JOIN bd_sigtap_202502.rl_procedimento_habilitacao ph ON p.co_procedimento::text = ph.co_procedimento::text
     LEFT JOIN bd_sigtap_202502.tb_habilitacao h ON h.co_habilitacao::text = ph.co_habilitacao::text
     LEFT JOIN bd_sigtap_202502.rl_procedimento_incremento pi ON p.co_procedimento::text = pi.co_procedimento::text
     LEFT JOIN bd_sigtap_202502.tb_habilitacao h1 ON h1.co_habilitacao::text = pi.co_habilitacao::text
     LEFT JOIN bd_sigtap_202502.rl_procedimento_detalhe rd ON p.co_procedimento::text = rd.co_procedimento::text
     LEFT JOIN bd_sigtap_202502.tb_detalhe d ON rd.co_detalhe::text = d.co_detalhe::text
  WHERE p.co_grupo::text = '04'::text
  GROUP BY p.co_procedimento, p.no_procedimento, p.tp_complexidade, p.tp_sexo, p.qt_maxima_execucao, p.qt_dias_permanencia, p.qt_pontos, p.vl_idade_minima, p.vl_idade_maxima, p.vl_sh, p.vl_sa, p.vl_sp, p.co_financiamento, p.co_rubrica, p.qt_tempo_permanencia, p.dt_competencia, p.co_grupo, p.co_forma_organizacao, p.co_sub_grupo, f.no_financiamento
WITH DATA;
