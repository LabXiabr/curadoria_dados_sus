#!/usr/bin/env python3
from __future__ import annotations
import argparse,csv,os,re,sys
from pathlib import Path

MATERIALIZED={
"tb_estabelecimento","tb_servico_especializado","tb_classificacao_servico","tb_equipamento",
"tb_tipo_equipamento","tb_leito","tb_tipo_estabelecimento","tb_natureza_juridica",
"tb_dados_profissional_sus","rl_estab_serv_class","rl_estab_equipamento",
"rl_estab_complementar","tb_equipe","rl_estab_equipe_prof","tb_carga_horaria_sus",
}
DOMAIN_RX=re.compile(r"^(tb_)?(tipo|classificacao|atividade|atributo|avaliacao|conselho|convenio|etnia|gestao|grupo|motivo|orgao|servico_apoio|subtipo|turno|estado|fluxo|coleta|instal_fisica)",re.I)
SILVER_RX=re.compile(r"(estab|equipe|prof|dialise|quimio|radio|hemoterapia|residencia|samu|aten_psico|incentiv|mantenedora|servico_referenciado|polo|aldeia|segmento|area)",re.I)

def marker(path:Path)->dict[str,str]:
    out={}
    for line in path.read_text(encoding="utf-8").splitlines():
        if "=" in line:
            k,v=line.split("=",1); out[k]=v
    return out

def main()->int:
    ap=argparse.ArgumentParser(description="Classifica tabelas CNES: Silver necessaria, dominio ou Bronze suficiente")
    ap.add_argument("--lake-root",default=os.environ.get("LAKE_ROOT","/dados/abertos/suslake"))
    args=ap.parse_args()
    lake=Path(args.lake_root); state=lake/"state"/"cnes"
    pm=state/"profile_latest.ok"
    if not pm.is_file(): raise SystemExit(f"profile ausente: {pm}")
    meta=marker(pm); profile=Path(meta["profile"])
    rows=[]
    with profile.open(encoding="utf-8",newline="") as f:
        for r in csv.DictReader(f,delimiter="\t"):
            table=r["table"]; n=int(r["rows"])
            if table in MATERIALIZED:
                cls="silver_necessaria"; reason="materializada_no_modelo_core"
            elif n==0:
                cls="bronze_suficiente"; reason="sem_registros_na_competencia_corrente"
            elif DOMAIN_RX.search(table) and n<=5000:
                cls="dominio"; reason="tabela_de_dominio_lookup"
            elif SILVER_RX.search(table):
                cls="silver_necessaria"; reason="entidade_ou_relacao_analitica_reutilizavel"
            elif table.startswith("rl_") and n>0:
                cls="silver_necessaria"; reason="relacao_com_registros;avaliar_bridge_fact"
            else:
                cls="bronze_suficiente"; reason="preservar_fonte;sem_consumo_semantico_core_identificado"
            rows.append({
              "table":table,"rows":n,"classification":cls,"reason":reason,
              "has_cnes":r.get("has_cnes",""),"cnes_columns":r.get("cnes_columns",""),
            })
    out=state/f"table_classification_{meta.get('competencia','current')}.tsv"
    with out.open("w",encoding="utf-8",newline="") as f:
        fields=list(rows[0].keys()); w=csv.DictWriter(f,fieldnames=fields,delimiter="\t",lineterminator="\n")
        w.writeheader(); w.writerows(rows)
    counts={}
    for r in rows: counts[r["classification"]]=counts.get(r["classification"],0)+1
    marker_out=state/"table_classification_current.ok"
    marker_out.write_text("\n".join([
      f"profile={profile}",f"report={out}",f"tables={len(rows)}",
      *(f"{k}={v}" for k,v in sorted(counts.items())),
      "policy=classificacao_inicial_reprodutivel;revisao_semantica_pode_promover_bronze_para_silver",""
    ]),encoding="utf-8")
    print("CNES_TABLE_CLASSIFICATION_OK "+" ".join(f"{k}={v}" for k,v in sorted(counts.items())))
    print(f"report={out}"); return 0
if __name__=="__main__": raise SystemExit(main())
