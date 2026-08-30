"""
Testes da maquina de estados. Rode com: python -m pytest tests/ -q

Estes testes existem porque rules.py e o unico lugar do sistema onde uma
decisao errada vira recomendacao errada. O LLM nao decide nada.
"""
import sys
from datetime import datetime, timedelta

sys.path.insert(0, ".")

from app import config  # noqa: E402
from app.rules import (  # noqa: E402
    AMARELO, VERDE, VERMELHO, Avaliador, Leitura,
    avaliar_leitura, ciclo_de, classificar, escolher_acao, estacao_de,
)

DIA = 30000.0     # lux, bem acima do corte dia/noite
NOITE = 0.0

INVERNO = datetime(2026, 7, 15, 12, 0, 0)
VERAO = datetime(2026, 1, 15, 12, 0, 0)


def _ler(ts=INVERNO, temp=20, ur=68, luz=DIA):
    return Leitura(ts=ts, temp_c=temp, ur=ur, luz=luz)


# ---------- passo 1 e 2: estacao e ciclo ----------

def test_estacao_por_mes():
    assert estacao_de(datetime(2026, 1, 5)) == "verao"
    assert estacao_de(datetime(2026, 4, 5)) == "outono"
    assert estacao_de(datetime(2026, 8, 5)) == "inverno"
    assert estacao_de(datetime(2026, 10, 5)) == "primavera"
    assert estacao_de(datetime(2026, 12, 5)) == "verao"


def test_ciclo_pelo_corte_de_lux():
    assert ciclo_de(config.LUZ_DIA_LUX) == "dia"        # o corte e inclusivo
    assert ciclo_de(config.LUZ_DIA_LUX - 1) == "noite"


# ---------- passo 3: classificacao ----------

def test_classificar_respeita_as_bordas():
    cortes = (14, 18, 24, 27)
    assert classificar(13.9, cortes) == (VERMELHO, "baixo")
    assert classificar(14, cortes) == (AMARELO, "baixo")
    assert classificar(18, cortes) == (VERDE, None)      # 2o corte ja e verde
    assert classificar(24, cortes) == (VERDE, None)      # 3o corte ainda e verde
    assert classificar(24.1, cortes) == (AMARELO, "alto")
    assert classificar(27, cortes) == (AMARELO, "alto")
    assert classificar(27.1, cortes) == (VERMELHO, "alto")


def test_faixa_sem_teto_no_inverno():
    """Inverno nao tem limite superior de luz - sol demais nao e problema."""
    _, _, niveis, _, _ = avaliar_leitura(_ler(ts=INVERNO, luz=200000.0))
    assert niveis["luz"] == VERDE


def test_mesma_umidade_muda_de_nivel_conforme_o_ciclo():
    """78% e alto de dia no inverno (teto 75), mas normal de noite (teto 80)."""
    _, _, dia, _, _ = avaliar_leitura(_ler(ts=INVERNO, ur=78, luz=DIA))
    _, _, noite, _, _ = avaliar_leitura(_ler(ts=INVERNO, ur=78, luz=NOITE))
    assert dia["ur"] == AMARELO
    assert noite["ur"] == VERDE


# ---------- passo 3: overrides ----------

def test_override_aborto_floral():
    """Acima de 32 C e sempre vermelho, mesmo que a faixa da estacao aceitasse."""
    _, _, niveis, _, nivel = avaliar_leitura(_ler(ts=INVERNO, temp=33))
    assert niveis["temp"] == VERMELHO
    assert nivel == VERMELHO


def test_override_geada():
    _, _, niveis, _, _ = avaliar_leitura(_ler(ts=VERAO, temp=2, luz=NOITE))
    assert niveis["temp"] == VERMELHO


# ---------- luz ----------

def test_luz_e_sempre_verde_a_noite():
    _, ciclo, niveis, _, _ = avaliar_leitura(_ler(luz=NOITE))
    assert ciclo == "noite"
    assert niveis["luz"] == VERDE


def test_luz_baixa_isolada_nao_passa_de_amarelo():
    """Um dia nublado nao condena. So 2 dias seguidos (inverno) viram vermelho."""
    _, _, niveis, _, _ = avaliar_leitura(_ler(ts=INVERNO, luz=3000.0),
                                         dias_luz_baixa=0)
    assert niveis["luz"] == AMARELO


def test_luz_baixa_repetida_vira_vermelho():
    _, _, niveis, _, _ = avaliar_leitura(_ler(ts=INVERNO, luz=3000.0),
                                         dias_luz_baixa=2)
    assert niveis["luz"] == VERMELHO


def test_inverno_condena_mais_rapido_que_verao():
    """2 dias no inverno, 3 nas outras estacoes."""
    _, _, inv, _, _ = avaliar_leitura(_ler(ts=INVERNO, luz=3000.0), dias_luz_baixa=2)
    _, _, ver, _, _ = avaliar_leitura(_ler(ts=VERAO, temp=20, luz=3000.0),
                                      dias_luz_baixa=2)
    assert inv["luz"] == VERMELHO
    assert ver["luz"] == AMARELO


# ---------- passo 4: acao ----------

def test_uma_acao_so_quando_duas_variaveis_alertam():
    _, _, _, alertas, _ = avaliar_leitura(_ler(ts=INVERNO, temp=27, ur=80))
    acao, _ = escolher_acao(alertas, 27)
    assert len(alertas) == 2
    assert acao.count(",") <= 1, "acao virou lista de tarefas: %r" % acao


def test_conflito_frio_com_umidade_alta_manda_ventilar():
    """Frio pede fechar, umidade alta pede abrir. Fungo custa mais caro."""
    _, _, _, alertas, _ = avaliar_leitura(_ler(ts=INVERNO, temp=15, ur=88))
    acao, risco = escolher_acao(alertas, 15)
    assert "ventilar" in acao
    assert "janelas curtas" in acao, "ventilou sem proteger do frio"
    assert "mofo" in risco


def test_geada_manda_em_tudo():
    """Abaixo de 3 C, nem umidade alta faz o sistema mandar abrir."""
    _, _, _, alertas, _ = avaliar_leitura(_ler(ts=VERAO, temp=1, ur=95, luz=NOITE))
    acao, risco = escolher_acao(alertas, 1)
    assert "proteger" in acao and "frio" in acao
    assert "geada" in risco


def test_verde_nao_recomenda_nada():
    _, _, _, alertas, nivel = avaliar_leitura(_ler(ts=INVERNO, temp=20, ur=68))
    assert nivel == VERDE
    assert escolher_acao(alertas, 20) == ("", "")


# ---------- confirmacao (anti-piscada) ----------

def _rodar(aval, leituras, passo_s=60):
    ts = INVERNO
    res = None
    for l in leituras:
        res = aval.avaliar(Leitura(ts=ts, temp_c=l[0], ur=l[1], luz=l[2]))
        ts += timedelta(seconds=passo_s)
    return res


def test_leitura_solta_nao_muda_o_estado():
    """Um respingo no sensor nao pode virar alerta."""
    aval = Avaliador()
    res = _rodar(aval, [(20, 68, DIA), (20, 95, DIA), (20, 68, DIA)])
    assert res.estado == "ok"


def test_muda_depois_de_confirmar():
    aval = Avaliador()
    res = _rodar(aval, [(20, 95, DIA)] * (config.LEITURAS_CONFIRMA + 1))
    assert res.estado == "agir"
    assert res.mudou or aval.estado == "agir"


def test_volta_para_ok_tambem_precisa_confirmar():
    aval = Avaliador()
    _rodar(aval, [(20, 95, DIA)] * (config.LEITURAS_CONFIRMA + 1))
    assert aval.estado == "agir"
    _rodar(aval, [(20, 68, DIA)])          # uma leitura boa so
    assert aval.estado == "agir", "voltou para ok sem confirmar"
    _rodar(aval, [(20, 68, DIA)] * config.LEITURAS_CONFIRMA)
    assert aval.estado == "ok"


def test_conflito_seco_com_calor_nao_manda_fechar():
    """Umidade baixa pede fechar, calor pede abrir. Fechar a 28 C piora o calor."""
    _, _, _, alertas, _ = avaliar_leitura(_ler(ts=INVERNO, temp=28, ur=60))
    acao, risco = escolher_acao(alertas, 28)
    assert "fechar" not in acao, "mandou fechar a estufa no calor: %r" % acao
    assert "sombrear" in acao
    assert "aborto" in risco


def test_luz_nunca_sai_como_numero():
    """A conversao do LDR e aproximada: mostrar lux fingiria precisao."""
    from app.rules import ROTULO_NOITE, rotulo_luz

    assert rotulo_luz(30000.0, INVERNO) == "luminosidade boa"
    assert rotulo_luz(3000.0, INVERNO) == "luminosidade baixa"
    assert rotulo_luz(3000.0, INVERNO, dias_luz_baixa=2) == "luminosidade muito baixa"
    assert rotulo_luz(10.0, INVERNO) == ROTULO_NOITE
    for lux in (0.0, 10.0, 3000.0, 30000.0, 200000.0):
        assert not any(c.isdigit() for c in rotulo_luz(lux, INVERNO))


def test_rotulo_curto_cabe_na_metrica():
    """A metrica do Streamlit corta texto longo - uma palavra so, ate 11 letras."""
    from app.rules import rotulo_luz

    for lux, dias in ((0.0, 0), (3000.0, 0), (3000.0, 2), (30000.0, 0),
                      (200000.0, 0), (60000.0, 0)):
        curto = rotulo_luz(lux, VERAO, dias_luz_baixa=dias, curto=True)
        assert " " not in curto, "rotulo curto com espaco: %r" % curto
        assert len(curto) <= 11, "rotulo curto longo demais: %r" % curto


def test_conversao_do_ldr_e_invertida():
    """Neste circuito o ADC sobe quando escurece."""
    from app.collector import _para_lux

    assert _para_lux(0) > _para_lux(500) > _para_lux(1023)
    assert _para_lux(1023) < 10, "escuro total deveria dar quase zero lux"
