# Modelo Silver — domínios e layouts DATASUS

## datasus_domain

Uma linha representa uma categoria ou faixa observada em um artefato oficial.

Campos principais:

- system, source_id, source_sha256;
- valid_from, valid_to;
- domain_id;
- code_literal;
- code_start, code_end, is_range;
- label;
- ordinal;
- domain_source_kind;
- domain_status;
- duplicate_count, conflicting_label;
- source_member.

Faixas CNV não são expandidas. Duplicatas não são eliminadas silenciosamente.

Para DBF relacionado, uma dimensão Silver só é emitida quando o DEF fornece
chave/rótulo inequívocos ou quando o DBF contém exatamente dois campos. Outros
casos permanecem apenas na Bronze e aparecem em build_issues.tsv.

## datasus_layout_field

Uma linha representa uma referência de campo observada em DEF:

- command: L/C/S/I quando reconhecido;
- display_label;
- source_field;
- label_field quando DEF aponta para DBF;
- code_width;
- reference_file;
- reference_kind CNV/DBF;
- bloco bruto e proveniência.

O parser é conservador. parse_status=partial não vira erro de carga, mas exige
curadoria antes de gerar transformação semântica.
