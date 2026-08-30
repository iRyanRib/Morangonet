"""
Processo 2: interface Streamlit do MorangoNet.

Mantém as integrações existentes com banco, regras e agente. As alterações
deste arquivo são exclusivamente de apresentação e experiência do usuário.

Uso: streamlit run app/ui.py
"""

import html
import logging
import sys
from contextlib import closing
from datetime import datetime
from pathlib import Path

import streamlit as st

# `streamlit run app/ui.py` coloca app/ no sys.path, não a raiz do projeto.
RAIZ = str(Path(__file__).resolve().parent.parent)
if RAIZ not in sys.path:
    sys.path.insert(0, RAIZ)

from app import agent, config, db, rules  # noqa: E402

logger = logging.getLogger(__name__)

SEGUNDOS_REFRESH = 2

STATUS_ESTILO = {
    "ok": {
        "fundo": "#2ECC71",
        "texto": "#062B18",
        "borda": "#55E391",
    },
    "atencao": {
        "fundo": "#F5C542",
        "texto": "#3B2800",
        "borda": "#FFDA70",
    },
    "agir": {
        "fundo": "#DC3545",
        "texto": "#FFFFFF",
        "borda": "#F06471",
    },
    "indisponivel": {
        "fundo": "#52615B",
        "texto": "#FFFFFF",
        "borda": "#71817B",
    },
}

ICONES = {
    "ok": "✓",
    "atencao": "!",
    "agir": "!",
    "indisponivel": "?",
}

ROTULOS = {
    "ok": "Tudo certo!",
    "atencao": "Atenção às Condições!",
    "agir": "Alerta Crítico!",
    "indisponivel": "Estado indisponível",
}

ESTADOS_SENSOR = {"ok", "atencao", "agir"}

# Estados individuais são opcionais. Se o backend passar algum deles, a
# interface o exibe. Caso contrário, a UI chama a classificação pura de
# rules.py; os limites continuam centralizados no módulo de domínio.
CAMPOS_ESTADO_SENSOR = {
    "ur": ("estado_ur",),
    "temp_c": ("estado_temp", "estado_temp_c"),
    "luz": ("estado_luz",),
}

CHAVES_SENSOR_RULES = {
    "ur": "ur",
    "temp_c": "temp",
    "luz": "luz",
}


def _rotulo(minutos):
    if minutos < 60:
        return "%d min" % minutos
    if minutos % 1440 == 0:
        return "%d d" % (minutos // 1440)
    return "%g h" % (minutos / 60)


def _segundos_desde(ts):
    """O banco guarda hora local, sem fuso. Compara com o relógio local."""
    try:
        return (datetime.now() - datetime.fromisoformat(ts)).total_seconds()
    except (TypeError, ValueError):
        return None


def _formatar_data_hora(ts):
    try:
        valor = datetime.fromisoformat(ts)
        return valor.strftime("%d/%m às %H:%M:%S")
    except (TypeError, ValueError):
        return "horário indisponível"


def _formatar_faixa(faixas, periodo):
    """Formata as referências sem derrubar a tela se o contrato vier incompleto."""
    try:
        umidade = faixas[periodo]["umidade_pct"]
        temperatura = faixas[periodo]["temperatura_c"]
        return "%s · UR %g–%g%% · %g–%g °C" % (
            periodo.capitalize(),
            umidade[1],
            umidade[2],
            temperatura[1],
            temperatura[2],
        )
    except (IndexError, KeyError, TypeError):
        return "%s · referências indisponíveis" % periodo.capitalize()


def _normalizar_estado_sensor(estado):
    if estado in ESTADOS_SENSOR:
        return estado
    mapa_backend = getattr(rules, "ESTADO", {})
    return mapa_backend.get(estado, "neutro")


def _estado_salvo(dados, campo):
    """Lê estados individuais já persistidos, quando disponíveis."""
    for chave in CAMPOS_ESTADO_SENSOR.get(campo, ()):
        estado = _normalizar_estado_sensor(dados.get(chave))
        if estado != "neutro":
            return estado

    niveis = dados.get("niveis")
    if isinstance(niveis, dict):
        estado = _normalizar_estado_sensor(niveis.get(CHAVES_SENSOR_RULES.get(campo)))
        if estado != "neutro":
            return estado

    return "neutro"


def _datetime_da_leitura(ts):
    if isinstance(ts, datetime):
        return ts
    return datetime.fromisoformat(ts)


def _estados_dos_sensores(dados):
    """Obtém os três estados usando exclusivamente as regras do domínio."""
    estados = {campo: _estado_salvo(dados, campo) for campo in CHAVES_SENSOR_RULES}
    pendentes = [campo for campo, estado in estados.items() if estado == "neutro"]
    if not pendentes:
        return estados

    try:
        leitura = rules.Leitura(
            ts=_datetime_da_leitura(dados["ts"]),
            temp_c=float(dados["temp_c"]),
            ur=float(dados["ur"]),
            luz=float(dados["luz"]),
        )
        dias_luz_baixa = int(dados.get("dias_luz_baixa", 0) or 0)
        _, _, niveis, _, _ = rules.avaliar_leitura(
            leitura,
            dias_luz_baixa=dias_luz_baixa,
        )
    except (AttributeError, KeyError, TypeError, ValueError):
        logger.exception("Não foi possível classificar individualmente os sensores")
        return estados

    for campo in pendentes:
        estados[campo] = _normalizar_estado_sensor(
            niveis.get(CHAVES_SENSOR_RULES[campo])
        )
    return estados


def _rotulo_estado_sensor(estado):
    return {
        "ok": "Na faixa",
        "atencao": "Fora da faixa",
        "agir": "Requer ação",
        "neutro": "Monitorado",
    }.get(estado, "Monitorado")


def _cartao_sensor(rotulo, valor, estado, detalhe):
    estado = estado if estado in ESTADOS_SENSOR else "neutro"
    st.markdown(
        """
        <div class="sensor-card sensor-%s">
            <div class="sensor-topline">
                <span class="sensor-label">%s</span>
                <span class="sensor-pill">
                    <span class="sensor-dot"></span>%s
                </span>
            </div>
            <div class="sensor-value">%s</div>
            <div class="sensor-detail">%s</div>
        </div>
        """
        % (
            estado,
            html.escape(str(rotulo)),
            html.escape(_rotulo_estado_sensor(estado)),
            html.escape(str(valor)),
            html.escape(str(detalhe)),
        ),
        unsafe_allow_html=True,
    )


def _injetar_estilos():
    st.markdown(
        """
        <style>
            :root {
                color-scheme: dark;
                --mn-bg: #0A0F0E;
                --mn-surface: #111816;
                --mn-surface-raised: #17201D;
                --mn-surface-soft: #1B2622;
                --mn-border: #27342F;
                --mn-border-strong: #34463F;
                --mn-text: #EFF6F2;
                --mn-text-soft: #C5D0CA;
                --mn-muted: #8E9E96;
                --mn-green: #68D391;
                --mn-green-deep: #286E4B;
                --mn-strawberry: #F06A72;
            }

            html,
            body,
            [class*="css"] {
                color: var(--mn-text);
            }

            .stApp {
                background:
                    radial-gradient(circle at 92% 2%, rgba(40, 110, 75, 0.15), transparent 31rem),
                    radial-gradient(circle at 8% 34%, rgba(240, 106, 114, 0.055), transparent 26rem),
                    var(--mn-bg);
            }

            .block-container {
                max-width: 980px;
                padding-top: 4.75rem;
                padding-bottom: 5rem;
            }

            [data-testid="stHeader"] {
                background: rgba(10, 15, 14, 0.72);
                backdrop-filter: blur(16px);
            }

            [data-testid="stToolbar"] {
                right: 1rem;
            }

            .mn-hero {
                background:
                    linear-gradient(135deg, rgba(104, 211, 145, 0.08), transparent 46%),
                    var(--mn-surface);
                border: 1px solid var(--mn-border);
                border-radius: 22px;
                box-shadow: 0 18px 60px rgba(0, 0, 0, 0.2);
                margin-bottom: 1.6rem;
                overflow: hidden;
                padding: 0.75rem 1.65rem;
                position: relative;
            }

            .mn-hero::after {
                background: var(--mn-strawberry);
                border-radius: 999px;
                content: "";
                height: 5rem;
                opacity: 0.08;
                position: absolute;
                right: -1.8rem;
                top: -2.3rem;
                width: 5rem;
            }

            .brand-title {
                color: var(--mn-text);
                font-size: clamp(2rem, 5vw, 2.9rem);
                font-weight: 740;
                letter-spacing: -0.04em;
                line-height: 1;
                margin: 0;
            }

            .brand-title span {
                color: var(--mn-strawberry);
            }

            .brand-subtitle {
                color: var(--mn-text-soft);
                font-size: 0.96rem;
                line-height: 1.55;
                margin: 0.7rem 0 0;
                max-width: 680px;
            }

            .status-card {
    align-items: center;
    border: 1px solid transparent;
    border-radius: 15px;
    box-shadow: 0 10px 30px rgba(0, 0, 0, 0.28);
    display: flex;
    gap: 0.7rem;
    margin: 0.35rem 0 1.1rem;
    padding: 0.78rem 0.9rem;
}

.status-icon {
    align-items: center;
    background: rgba(0, 0, 0, 0.16);
    border-radius: 999px;
    color: inherit;
    display: flex;
    flex: 0 0 25px;
    font-size: 0.82rem;
    font-weight: 800;
    height: 25px;
    justify-content: center;
}

.status-title {
    color: inherit;
    font-size: 0.98rem;
    font-weight: 800;
    letter-spacing: 0.075em;
    line-height: 1.25;
    text-transform: uppercase;
}

            .sensor-card {
                --sensor-color: var(--mn-muted);
                background: var(--mn-surface);
                border: 1px solid var(--mn-border);
                border-radius: 14px;
                box-shadow: 0 10px 28px rgba(0, 0, 0, 0.12);
                min-height: 146px;
                padding: 15px 16px 14px;
                transition: border-color 160ms ease, transform 160ms ease;
            }

            .sensor-card:hover {
                border-color: var(--sensor-color);
                transform: translateY(-1px);
            }

            .sensor-card.sensor-ok {
    --sensor-color: #68D391;
    background:
        linear-gradient(
            145deg,
            rgba(104, 211, 145, 0.14),
            transparent 64%
        ),
        var(--mn-surface);
    border-color: #68D391;
    box-shadow:
        inset 0 3px 0 #68D391,
        0 10px 28px rgba(0, 0, 0, 0.14);
}

.sensor-card.sensor-atencao {
    --sensor-color: #F4BE5B;
    background:
        linear-gradient(
            145deg,
            rgba(244, 190, 91, 0.15),
            transparent 64%
        ),
        var(--mn-surface);
    border-color: #F4BE5B;
    box-shadow:
        inset 0 3px 0 #F4BE5B,
        0 10px 28px rgba(0, 0, 0, 0.14);
}

.sensor-card.sensor-agir {
    --sensor-color: #FF727A;
    background:
        linear-gradient(
            145deg,
            rgba(255, 114, 122, 0.16),
            transparent 64%
        ),
        var(--mn-surface);
    border-color: #FF727A;
    box-shadow:
        inset 0 3px 0 #FF727A,
        0 10px 28px rgba(0, 0, 0, 0.14);
}

            .sensor-topline {
                align-items: center;
                display: flex;
                gap: 0.5rem;
                justify-content: space-between;
            }

            .sensor-label {
                color: var(--mn-text-soft);
                font-size: 1.2rem;
                font-weight: 720;
                letter-spacing: 0.01em;
                line-height: 1.25;
            }

            .sensor-pill {
    align-items: center;
    background: rgba(255, 255, 255, 0.06);
    border: 1px solid var(--sensor-color);
    border-radius: 999px;
    color: var(--sensor-color);
    display: inline-flex;
    font-size: 0.66rem;
    font-weight: 700;
    gap: 0.32rem;
    line-height: 1;
    padding: 0.3rem 0.46rem;
    white-space: nowrap;
}

.sensor-dot {
    background: var(--sensor-color);
    border-radius: 999px;
    box-shadow: 0 0 8px currentColor;
    height: 0.4rem;
    width: 0.4rem;
}

            .sensor-value {
                color: var(--mn-text);
                font-size: 1.72rem;
                font-weight: 650;
                letter-spacing: -0.035em;
                line-height: 1.1;
                margin-top: 1.05rem;
            }

            .sensor-detail {
                color: var(--mn-muted);
                font-size: 0.95rem;
                line-height: 1.35;
                margin-top: 0.42rem;
            }

            .automatic-alert {
                align-items: flex-start;
                background: var(--mn-surface);
                border: 1px solid var(--mn-border);
                border-radius: 14px;
                display: flex;
                gap: 0.8rem;
                padding: 0.95rem 1rem;
            }

            .automatic-alert-active {
                background: linear-gradient(145deg, rgba(255, 114, 122, 0.08), transparent 64%), var(--mn-surface);
                border-color: #613138;
            }

            .automatic-alert-empty {
                background: linear-gradient(145deg, rgba(104, 211, 145, 0.055), transparent 64%), var(--mn-surface);
                border-color: #294D39;
            }

            .automatic-alert-icon {
                align-items: center;
                background: #FF727A;
                border-radius: 999px;
                color: #FFFFFF;
                display: flex;
                flex: 0 0 1.65rem;
                font-size: 0.8rem;
                font-weight: 800;
                height: 1.65rem;
                justify-content: center;
            }

            .automatic-alert-empty .automatic-alert-icon {
                background: #286E4B;
            }

            .automatic-alert-title {
                color: var(--mn-text);
                font-size: 0.88rem;
                font-weight: 700;
                line-height: 1.35;
            }

            .automatic-alert-content {
                color: var(--mn-text-soft);
                font-size: 0.84rem;
                line-height: 1.5;
                margin-top: 0.2rem;
            }

            [data-testid="stChatMessage"] {
                background: rgba(17, 24, 22, 0.82);
                border: 1px solid var(--mn-border);
                border-radius: 15px;
                margin-bottom: 0.6rem;
                padding: 0.35rem 0.55rem;
            }

            [data-testid="stChatMessage"] p,
            [data-testid="stChatMessage"] li {
                color: var(--mn-text-soft);
                line-height: 1.62;
            }

            [data-testid="stChatMessage"] strong {
                color: var(--mn-text);
            }

            [data-testid="stSidebar"] {
                background: #0E1513;
                border-right: 1px solid var(--mn-border);
            }

            [data-testid="stSidebar"] h2,
            [data-testid="stSidebar"] h3 {
                color: var(--mn-text);
                letter-spacing: -0.02em;
            }

            .section-label {
                color: var(--mn-muted);
                font-size: 0.72rem;
                font-weight: 700;
                letter-spacing: 0.11em;
                margin: 1.1rem 0 0.5rem;
                text-transform: uppercase;
            }

            .reading-time {
                color: var(--mn-muted);
                font-size: 0.84rem;
                margin: 0.8rem 0 0.2rem;
            }

            .reading-time::first-letter {
                color: var(--mn-green);
            }

            [data-testid="stChatInput"] {
                background: var(--mn-surface-raised);
                border-color: var(--mn-border-strong);
                border-radius: 14px;
                color: var(--mn-text);
            }

            [data-testid="stChatInput"]:focus-within {
                border-color: var(--mn-green-deep);
                box-shadow: 0 0 0 1px var(--mn-green-deep);
            }

            [data-testid="stChatInput"] textarea {
                color: var(--mn-text);
            }

            [data-testid="stChatInput"] textarea::placeholder {
                color: var(--mn-muted);
            }

            .stButton > button,
            [data-testid="stBaseButton-secondary"] {
                background: var(--mn-surface-raised);
                border: 1px solid var(--mn-border-strong);
                border-radius: 10px;
                color: var(--mn-text-soft);
                transition: background 150ms ease, border-color 150ms ease, color 150ms ease;
            }

            .stButton > button:hover,
            [data-testid="stBaseButton-secondary"]:hover {
                background: var(--mn-surface-soft);
                border-color: var(--mn-green-deep);
                color: var(--mn-text);
            }

            [data-baseweb="select"] > div {
                background: var(--mn-surface-raised);
                border-color: var(--mn-border-strong);
                color: var(--mn-text);
            }

            [data-baseweb="popover"],
            [role="listbox"] {
                background: var(--mn-surface-raised);
                color: var(--mn-text);
            }

            [data-testid="stAlert"] {
                background: var(--mn-surface-raised);
                border: 1px solid var(--mn-border);
                color: var(--mn-text-soft);
            }

            [data-testid="stExpander"] {
                background: var(--mn-surface);
                border-color: var(--mn-border);
            }

            [data-testid="stCode"] {
                border: 1px solid var(--mn-border);
            }

            hr {
                border-color: var(--mn-border) !important;
                margin: 1.6rem 0 !important;
            }

            p,
            label,
            .stCaption {
                color: var(--mn-text-soft);
            }

            small,
            [data-testid="stCaptionContainer"] {
                color: var(--mn-muted);
            }

            @media (max-width: 640px) {
                .block-container {
                    padding-left: 1rem;
                    padding-right: 1rem;
                    padding-top: 4.1rem;
                }

                .mn-hero {
                    border-radius: 17px;
                    padding: 1.25rem 1.15rem;
                }

                .sensor-card {
                    min-height: 132px;
                }
            }
        </style>
        """,
        unsafe_allow_html=True,
    )


def _cabecalho():
    st.markdown(
        """
        <div class="mn-hero">
            <h1 class="brand-title">Morango<span>Net</span></h1>
            <p class="brand-subtitle">
                Monitoramento para prevenção do mofo-cinzento em uma visão simples para o produtor.
            </p>
        </div>
        """,
        unsafe_allow_html=True,
    )


def _cartao_estado(estado):
    estado = estado if estado in STATUS_ESTILO else "indisponivel"
    estilo = STATUS_ESTILO[estado]

    st.markdown(
        """
        <div class="status-card" style="
            background: %s;
            color: %s;
            border-color: %s;
        ">
            <div class="status-icon">%s</div>
            <div class="status-title">%s</div>
        </div>
        """
        % (
            estilo["fundo"],
            estilo["texto"],
            estilo["borda"],
            ICONES[estado],
            ROTULOS[estado],
        ),
        unsafe_allow_html=True,
    )


def _mensagem_vazia():
    with st.chat_message("assistant", avatar="🍓"):
        st.markdown(
            "Olá! Posso explicar as condições atuais da estufa ou resumir um período. "
            "Experimente perguntar: **Como está a estufa agora?**"
        )


def _separar_mensagens(mensagens):
    """Separa o alerta mais recente das mensagens normais da conversa."""
    mensagens = list(mensagens or [])
    alerta = next(
        (
            mensagem
            for mensagem in reversed(mensagens)
            if mensagem["role"] == "system_alert"
        ),
        None,
    )
    conversa = [
        mensagem for mensagem in mensagens if mensagem["role"] != "system_alert"
    ]
    return alerta, conversa


def _cartao_alerta(alerta):
    if not alerta:
        st.markdown(
            """
            <div class="automatic-alert automatic-alert-empty">
                <div class="automatic-alert-icon">✓</div>
                <div>
                    <div class="automatic-alert-title">Nenhum alerta no momento</div>
                    <div class="automatic-alert-content">
                        Todas as condições confirmadas estão dentro das faixas esperadas.
                    </div>
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )
        return

    conteudo = html.escape(str(alerta["content"])).replace("\n", "<br>")
    st.markdown(
        """
        <div class="automatic-alert automatic-alert-active">
            <div class="automatic-alert-icon">!</div>
            <div>
                <div class="automatic-alert-title">Alerta automático mais recente</div>
                <div class="automatic-alert-content">%s</div>
            </div>
        </div>
        """ % conteudo,
        unsafe_allow_html=True,
    )


st.set_page_config(
    page_title="MorangoNet",
    page_icon="🍓",
    layout="centered",
    initial_sidebar_state="collapsed",
)

db.init()
_injetar_estilos()
_cabecalho()


# Só o painel recarrega automaticamente; o campo de chat permanece estável.
@st.fragment(run_every=SEGUNDOS_REFRESH)
def painel():
    with closing(db.conectar()) as con:
        ultima = db.ultima_medicao(con)

    st.markdown(
        '<div class="section-label">Condições Ambientais na Estufa</div>',
        unsafe_allow_html=True,
    )

    if not ultima:
        st.info(
            "Ainda não recebemos leituras. Inicie o coletor do Arduino ou use o modo "
            "de demonstração para visualizar o painel."
        )
        with st.expander("Como iniciar os dados de demonstração"):
            st.code(
                "python -m app.collector --fake\n"
                "# ou\n"
                "python scripts/seed_fake.py",
                language="bash",
            )
        return

    estado = ultima["estado"] or "indisponivel"
    _cartao_estado(estado)

    dados = dict(ultima)
    agora = datetime.now()
    estados_sensores = _estados_dos_sensores(dados)
    estado_ur = estados_sensores["ur"]
    estado_temp = estados_sensores["temp_c"]
    estado_luz = estados_sensores["luz"]

    detalhe_ur = "Umidade do ar no interior da estufa"
    detalhe_temp = "Temperatura no interior da estufa"
    try:
        instante_leitura = _datetime_da_leitura(ultima["ts"])
    except (TypeError, ValueError):
        instante_leitura = agora
    rotulo_luz_curto = rules.rotulo_luz(ultima["luz"], instante_leitura, curto=True)
    detalhe_luz = rules.rotulo_luz(ultima["luz"], instante_leitura)

    c1, c2, c3 = st.columns(3, gap="medium")
    with c1:
        _cartao_sensor(
            "UMIDADE RELATIVA",
            "%.0f %%" % ultima["ur"],
            estado_ur,
            detalhe_ur,
        )
    with c2:
        _cartao_sensor(
            "TEMPERATURA",
            "%.1f °C" % ultima["temp_c"],
            estado_temp,
            detalhe_temp,
        )
    with c3:
        _cartao_sensor(
            "LUMINOSIDADE",
            rotulo_luz_curto,
            estado_luz,
            detalhe_luz,
        )

    idade = _segundos_desde(ultima["ts"])
    horario = _formatar_data_hora(ultima["ts"])

    if idade is None:
        st.warning(
            "A leitura foi recebida, mas o horário é inválido. Verifique o relógio "
            "e o formato enviado pelo coletor."
        )
    elif idade > 60:
        minutos = max(1, int(idade // 60))
        st.warning(
            "Os dados podem estar desatualizados: última leitura há %d min (%s). "
            "Verifique se o coletor está em execução." % (minutos, horario)
        )
    else:
        st.markdown(
            '<div class="reading-time">● Dados ativos · Última leitura: %s · Atualização a cada %d s</div>'
            % (horario, SEGUNDOS_REFRESH),
            unsafe_allow_html=True,
        )


@st.fragment(run_every=SEGUNDOS_REFRESH)
def conversa():
    with closing(db.conectar()) as con:
        mensagens = db.mensagens(con, config.SESSION_ID)
        ultima = db.ultima_medicao(con)

    alerta, mensagens = _separar_mensagens(mensagens)

    # O estado global já passou pela confirmação de leituras do rules.py.
    estado_atual = ultima["estado"] if ultima and ultima["estado"] else "indisponivel"

    # Um alerta antigo continua no banco, mas não deve aparecer como ativo
    # quando as condições já voltaram ao normal.
    if estado_atual == "ok":
        alerta = None

    st.markdown(
        '<div class="section-label">Alerta automático</div>',
        unsafe_allow_html=True,
    )
    _cartao_alerta(alerta)

    st.divider()
    st.markdown(
        '<div class="section-label">Converse com o MorangoNet</div>',
        unsafe_allow_html=True,
    )

    _mensagem_vazia()

    for mensagem in mensagens:
        if mensagem["role"] == "user":
            with st.chat_message("user", avatar="👨‍🌾"):
                st.markdown(mensagem["content"])
        else:
            with st.chat_message("assistant", avatar="🍓"):
                st.markdown(mensagem["content"])


painel()

st.divider()
conversa()

janela = st.session_state.get("janela_min", config.JANELA_PADRAO_MIN)
pergunta = st.chat_input(
    "Pergunte sobre a estufa — análise dos últimos %s" % _rotulo(janela)
)

if pergunta:
    try:
        with st.spinner("Analisando as leituras da estufa..."):
            with closing(db.conectar()) as con:
                agent.perguntar(
                    con,
                    config.SESSION_ID,
                    pergunta,
                    minutos=janela,
                )
        st.rerun()
    except Exception:  # A interface não deve expor detalhes internos ao produtor.
        logger.exception("Falha ao consultar o agente")
        st.error(
            "Não foi possível obter a resposta agora. Verifique a conexão e tente novamente."
        )


with st.sidebar:
    st.markdown("## 🍓 MorangoNet")
    st.caption("Configurações da consulta do microclima.")

    st.divider()
    st.subheader("Período analisado")

    opcoes = [5, 15, 30, 60, 180, 360, 720, 1440, 4320]
    if config.JANELA_PADRAO_MIN not in opcoes:
        opcoes = sorted(opcoes + [config.JANELA_PADRAO_MIN])

    st.selectbox(
        "O agente consulta os últimos:",
        opcoes,
        key="janela_min",
        index=opcoes.index(config.JANELA_PADRAO_MIN),
        format_func=_rotulo,
        help=(
            "Uma janela curta responde ‘como está agora?’. Uma janela longa ajuda a "
            "entender como as condições evoluíram durante o dia."
        ),
    )

    st.divider()
    st.subheader("Referências atuais")

    agora = datetime.now()
    faixas = rules.faixas_do_momento(agora)
    st.caption("Estação considerada: %s" % rules.estacao_de(agora))
    st.caption(_formatar_faixa(faixas, "dia"))
    st.caption(_formatar_faixa(faixas, "noite"))
    st.caption(
        "O estado muda após %d leituras consecutivas." % config.LEITURAS_CONFIRMA
    )

    st.divider()
    if st.button("Atualizar agora", use_container_width=True):
        st.rerun()

    if st.button("Limpar conversa", use_container_width=True, type="secondary"):
        with closing(db.conectar()) as con:
            con.execute(
                "DELETE FROM session_messages " "WHERE session_id=? AND role<>?",
                (config.SESSION_ID, "system_alert"),
            )
            con.commit()
        st.rerun()
