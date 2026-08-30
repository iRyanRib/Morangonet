"""
Processo 2: o chat. Streamlit ja e servidor - nao precisa de FastAPI no meio.

Uso:  streamlit run app/ui.py
"""
import sys
from contextlib import closing
from datetime import datetime
from pathlib import Path

import streamlit as st

# `streamlit run app/ui.py` poe app/ no sys.path, nao a raiz do projeto.
RAIZ = str(Path(__file__).resolve().parent.parent)
if RAIZ not in sys.path:
    sys.path.insert(0, RAIZ)

from app import agent, config, db, rules  # noqa: E402

def _rotulo(minutos):
    if minutos < 60:
        return "%d min" % minutos
    if minutos % 1440 == 0:
        return "%d d" % (minutos // 1440)
    return "%g h" % (minutos / 60)


def _segundos_desde(ts):
    """O banco guarda hora local, sem fuso. Compara com o relogio local."""
    try:
        return (datetime.now() - datetime.fromisoformat(ts)).total_seconds()
    except (TypeError, ValueError):
        return None


CORES = {"ok": "#4E7A4A", "atencao": "#C08A18", "agir": "#B3242C"}
ROTULOS = {"ok": "Tudo certo", "atencao": "Atencao - fora da faixa",
           "agir": "URGENTE - precisa agir agora"}

st.set_page_config(page_title="Morangonet", page_icon="+", layout="centered")
db.init()

# Uma conexao por uso, nunca uma no topo do modulo: os fragmentos com run_every
# rodam em OUTRA thread, e o sqlite3 recusa conexao criada em thread diferente.
# Abrir e fechar sai barato; guardar a conexao entre threads nao funciona.

st.title("Morangonet")
st.caption("Sentinela de mofo para morango em cultivo protegido")

# 2 s: o custo de um ciclo e ~0,5 ms de SQLite, entao o limite nao e desempenho.
# Nao adianta baixar abaixo do intervalo do sensor - so gera consulta a toa.
SEGUNDOS_REFRESH = 2


# Fragmentos: so este pedaco recarrega a cada N segundos. O chat_input fica de
# fora, entao o que o produtor esta digitando nao se perde no meio da atualizacao.
@st.fragment(run_every=SEGUNDOS_REFRESH)
def painel():
    with closing(db.conectar()) as con:
        ultima = db.ultima_medicao(con)
    if not ultima:
        st.info("Nenhuma leitura ainda. Rode `python -m app.collector` (Arduino), "
                "`python -m app.collector --fake` ou `python scripts/seed_fake.py`.")
        return

    estado = ultima["estado"] or "ok"
    st.markdown(
        "<div style='background:%s;color:#fff;padding:14px 18px;border-radius:4px;"
        "font-weight:600;font-size:18px'>%s</div>"
        % (CORES.get(estado, "#4E7A4A"), ROTULOS.get(estado, estado)),
        unsafe_allow_html=True,
    )
    c1, c2, c3 = st.columns(3)
    c1.metric("Umidade", "%.0f %%" % ultima["ur"])
    c2.metric("Temperatura", "%.1f C" % ultima["temp_c"])
    c3.metric("Luz", rules.rotulo_luz(ultima["luz"], datetime.now(), curto=True),
              help=rules.rotulo_luz(ultima["luz"], datetime.now()))

    idade = _segundos_desde(ultima["ts"])
    if idade is not None and idade > 60:
        st.warning("Ultima leitura ha %d min (%s) - o collector esta rodando?"
                   % (idade / 60, ultima["ts"]))
    else:
        st.caption("Ultima leitura: %s  -  atualiza sozinho a cada %d s"
                   % (ultima["ts"], SEGUNDOS_REFRESH))


@st.fragment(run_every=SEGUNDOS_REFRESH)
def conversa():
    with closing(db.conectar()) as con:
        mensagens = db.mensagens(con, config.SESSION_ID)
    for m in mensagens:
        if m["role"] == "user":
            with st.chat_message("user"):
                st.write(m["content"])
        else:
            with st.chat_message("assistant"):
                if m["role"] == "system_alert":
                    st.markdown("**Alerta automatico**")
                st.write(m["content"])


painel()
st.divider()
conversa()

janela = st.session_state.get("janela_min", config.JANELA_PADRAO_MIN)
pergunta = st.chat_input("Pergunte sobre a lavoura (janela: %s)..." % _rotulo(janela))
if pergunta:
    with closing(db.conectar()) as con:
        agent.perguntar(con, config.SESSION_ID, pergunta, minutos=janela)
    st.rerun()

with st.sidebar:
    st.subheader("Periodo da consulta")
    opcoes = [5, 15, 30, 60, 180, 360, 720, 1440, 4320]
    if config.JANELA_PADRAO_MIN not in opcoes:
        opcoes = sorted(opcoes + [config.JANELA_PADRAO_MIN])
    st.selectbox(
        "O agente olha os ultimos:", opcoes, key="janela_min",
        index=opcoes.index(config.JANELA_PADRAO_MIN),
        format_func=_rotulo,
        help="Vale para a proxima pergunta. Janela curta responde 'e agora?'; "
             "janela longa responde 'como foi o dia?'.",
    )

    st.divider()
    st.subheader("Estado do sistema")
    with closing(db.conectar()) as con:
        resumo = db.resumo_periodo(con, janela, pontos_serie=0)
    n = resumo["agregado"].get("n", 0)
    st.write("Leituras em %s:" % _rotulo(janela), n)
    if n:
        st.write("Por estado:", resumo["por_estado"])
    else:
        st.caption("Nenhuma leitura nessa janela - o collector esta rodando?")
    faixas = rules.faixas_do_momento(datetime.now())
    st.caption("Estacao: %s" % rules.estacao_de(datetime.now()))
    st.caption("Faixa verde de dia: UR %g-%g%%, temp %g-%g C"
               % (faixas["dia"]["umidade_pct"][1], faixas["dia"]["umidade_pct"][2],
                  faixas["dia"]["temperatura_c"][1], faixas["dia"]["temperatura_c"][2]))
    st.caption("Faixa verde de noite: UR %g-%g%%, temp %g-%g C"
               % (faixas["noite"]["umidade_pct"][1], faixas["noite"]["umidade_pct"][2],
                  faixas["noite"]["temperatura_c"][1], faixas["noite"]["temperatura_c"][2]))
    st.caption("Muda de estado apos %d leituras seguidas" % config.LEITURAS_CONFIRMA)
    if st.button("Atualizar"):
        st.rerun()
    if st.button("Limpar conversa"):
        with closing(db.conectar()) as con:
            con.execute("DELETE FROM session_messages WHERE session_id=?",
                        (config.SESSION_ID,))
            con.commit()
        st.rerun()
