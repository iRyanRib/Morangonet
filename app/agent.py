"""Fluxo 2: o produtor pergunta, o agente responde ancorado no banco."""
from datetime import datetime

from app import config, db, llm, rules



def _historico(con, session_id, limite=10):
    linhas = db.mensagens(con, session_id)[-limite:]
    msgs = []
    for l in linhas:
        papel = "assistant" if l["role"] in ("assistant", "system_alert") else "user"
        msgs.append({"role": papel, "content": l["content"]})
    # a API exige que a conversa comece com o usuario
    while msgs and msgs[0]["role"] != "user":
        msgs.pop(0)
    return msgs


def _sem_lux(ultima):
    """A luz sai em palavra. O lux e aproximado demais para o LLM citar."""
    if not ultima:
        return None
    d = dict(ultima)
    d["luminosidade"] = rules.rotulo_luz(
        d.pop("luz"), datetime.fromisoformat(d["ts"]))
    return d


def _classificar_ultima(con, ultima):
    """Quem classifica e o rules.py. O agente recebe o veredito pronto - senao
    ele chuta a faixa errada (ja aconteceu: leu 20 mil lux e falou em 'noite')."""
    if not ultima:
        return None
    leitura = rules.Leitura(
        ts=datetime.fromisoformat(ultima["ts"]),
        temp_c=ultima["temp_c"], ur=ultima["ur"], luz=ultima["luz"],
    )
    dias = db.dias_luz_baixa(con, rules.FAIXAS["luz"][
        (rules.estacao_de(leitura.ts), "dia")][0])
    estacao, ciclo, niveis, alertas, nivel = rules.avaliar_leitura(leitura, dias)
    acao, risco = rules.escolher_acao(alertas, leitura.temp_c)
    return {
        "estacao": estacao,
        "ciclo": ciclo,
        "nivel_geral": nivel,
        "por_variavel": niveis,
        "faixa_que_vale_agora": rules.faixas_do_momento(leitura.ts)[ciclo],
        "fora_da_faixa": [
            {"variavel": rules.ROTULO_VAR[a.variavel], "situacao": a.lado,
             "nivel": a.nivel, "valor": a.valor,
             "faixa_normal": list(a.faixa_verde)}
            for a in alertas
        ],
        "acao_recomendada": acao,
        "risco": risco,
    }


def montar_contexto(con, minutos=None):
    minutos = minutos or config.JANELA_PADRAO_MIN
    ultima = db.ultima_medicao(con)
    return {
        "agora": datetime.now().isoformat(sep=" ", timespec="seconds"),
        "ultima_leitura": _sem_lux(ultima),
        "diagnostico_da_ultima": _classificar_ultima(con, ultima),
        "janela_minutos": minutos,
        "resumo": db.resumo_periodo(con, minutos),
        "regras": {
            "temp_aborto_floral": config.TEMP_ABORTO,
            "temp_geada": config.TEMP_GEADA,
            "luz_dia_lux": config.LUZ_DIA_LUX,
            "legenda_faixa": ("[vermelho abaixo, amarelo abaixo, amarelo acima, "
                              "vermelho acima]; null = sem teto"),
        },
    }


def perguntar(con, session_id, pergunta, minutos=None):
    ts = datetime.now().isoformat(sep=" ", timespec="seconds")
    db.salvar_mensagem(con, session_id, "user", pergunta, ts)

    historico = _historico(con, session_id)
    contexto = montar_contexto(con, minutos)

    try:
        resposta = llm.responder(pergunta, contexto, historico)
    except Exception as e:  # noqa: BLE001
        resposta = "Nao consegui responder agora (%s). Tenta de novo em instantes." % e

    db.salvar_mensagem(
        con, session_id, "assistant", resposta,
        datetime.now().isoformat(sep=" ", timespec="seconds"),
    )
    return resposta
