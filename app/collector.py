"""
Processo 1: le a serial, grava, avalia o estado e alerta quando ele MUDA.

O LLM so e chamado na virada de estado. Nunca a cada leitura -
senao o produtor recebe um alerta por minuto e para de ler na terceira.

Uso:
    python -m app.collector
    python -m app.collector --porta /dev/cu.usbserial-1140
    python -m app.collector --fake    # sem Arduino, gera leituras
"""
import argparse
import json
import os
import random
import re
import sys
import time
from datetime import datetime

from app import config, db, llm
from app.rules import Avaliador, Leitura, contexto_para_llm


# "Umidade: 63.30 %  Temperatura: 29.10 C  Luz: 151 (ambiente iluminado)"
_TEXTO = re.compile(
    r"umidade\s*:\s*(?P<ur>-?[\d.,]+).*?"
    r"temperatura\s*:\s*(?P<t>-?[\d.,]+).*?"
    r"luz\s*:\s*(?P<luz>-?[\d.,]+)",
    re.IGNORECASE | re.DOTALL,
)


# o sketch avisa quando o sensor nao responde - nao e "formato desconhecido"
_FALHA = re.compile(r"falha|erro|nan", re.IGNORECASE)


def _num(txt):
    return float(txt.replace(",", "."))


def _para_lux(bruto):
    """O LDR devolve 0-1023; as regras trabalham em lux.

    Neste circuito o valor sobe quando escurece, dai a inversao. A escala e
    logaritmica porque a resposta do LDR tambem e: cada passo igual no ADC
    corresponde a uma fracao igual das decadas entre escuro e sol pleno.
    """
    frac = float(bruto) / config.LUZ_ADC_MAX
    if config.LUZ_INVERTIDA:
        frac = 1.0 - frac
    frac = min(1.0, max(0.0, frac))
    razao = config.LUZ_LUX_MAX / config.LUZ_LUX_MIN
    return round(config.LUZ_LUX_MIN * (razao ** frac), 1)


def _parse(linha: str):
    """Aceita os dois formatos que ja apareceram na serial:

    JSON  (firmware/sentinela)  {"ur":62.3,"t":21.4,"luz":812}
    Texto (sketch do produtor)  Umidade: 63.30 %  Temperatura: 29.10 C  Luz: 151
    """
    linha = linha.strip()
    if not linha:
        return None

    if linha.startswith("{"):
        try:
            d = json.loads(linha)
            return Leitura(
                ts=datetime.now(),
                temp_c=float(d["t"]),
                ur=float(d["ur"]),
                luz=_para_lux(d["luz"]),
            )
        except (ValueError, KeyError):
            return None

    m = _TEXTO.search(linha)
    if not m:
        return None
    try:
        return Leitura(
            ts=datetime.now(),
            temp_c=_num(m.group("t")),
            ur=_num(m.group("ur")),
            luz=_para_lux(_num(m.group("luz"))),
        )
    except ValueError:
        return None


def _descobrir_porta():
    """O nome da porta muda a cada vez que se troca o conector USB no Mac."""
    if config.SERIAL_PORT and os.path.exists(config.SERIAL_PORT):
        return config.SERIAL_PORT

    from serial.tools import list_ports

    candidatas = [
        p.device for p in list_ports.comports()
        if any(marca in p.device for marca in ("usbserial", "usbmodem", "ttyUSB", "ttyACM"))
    ]
    if not candidatas:
        raise RuntimeError(
            "nenhuma porta serial encontrada (SERIAL_PORT=%s). "
            "Conecte o Arduino ou ajuste SERIAL_PORT no .env" % config.SERIAL_PORT
        )
    if config.SERIAL_PORT:
        print("[collector] SERIAL_PORT=%s nao existe - usando %s"
              % (config.SERIAL_PORT, candidatas[0]))
    return candidatas[0]


def _corte_luz_baixa(ts):
    """O corte de 'dia escuro' muda com a estacao - e o 1o valor da faixa de luz."""
    from app.rules import FAIXAS, estacao_de

    return FAIXAS["luz"][(estacao_de(ts), "dia")][0]


def _fonte_serial(porta_nome=None):
    """Reconecta sozinho. O cabo USB cai, o Arduino reinicia, o DHT trava -
    nada disso pode derrubar o processo no meio de uma apresentacao."""
    import serial

    espera = 1.0
    while True:
        porta = None
        try:
            nome = porta_nome or _descobrir_porta()
            porta = serial.Serial(nome, config.SERIAL_BAUD, timeout=5)
            time.sleep(2)  # Arduino reinicia ao abrir a porta
            porta.reset_input_buffer()
            print("[collector] escutando %s a %d baud" % (nome, config.SERIAL_BAUD))
            espera = 1.0  # reconectou: zera o recuo

            ignoradas = 0
            while True:
                linha = porta.readline().decode("utf-8", errors="ignore")
                leitura = _parse(linha)
                if leitura:
                    ignoradas = 0
                    yield leitura, porta
                    continue
                # sem isto, um formato inesperado deixa o collector mudo para sempre
                texto = linha.strip()
                if not texto:
                    continue
                ignoradas += 1
                if ignoradas in (5, 50) or ignoradas % 500 == 0:
                    rotulo = ("sensor sem responder" if _FALHA.search(texto)
                              else "linhas nao reconhecidas")
                    print("[collector] %d %s. Ultima: %r"
                          % (ignoradas, rotulo, texto[:120]))

        except (OSError, RuntimeError) as e:
            # SerialException herda de OSError; RuntimeError vem de _descobrir_porta
            print("[collector] serial caiu (%s) - reconectando em %.0f s" % (e, espera))
        finally:
            if porta is not None:
                try:
                    porta.close()
                except Exception:  # noqa: BLE001
                    pass

        time.sleep(espera)
        espera = min(espera * 2, 30)  # recuo exponencial, teto de 30 s


def _fonte_fake():
    """Sem hardware. Sobe a umidade devagar e depois deixa cair."""
    print("[collector] modo fake - sem Arduino")
    ur, subindo = 70.0, True
    while True:
        ur += random.uniform(2, 5) if subindo else -random.uniform(2, 5)
        if ur > 96:
            subindo = False
        if ur < 65:
            subindo = True
        yield Leitura(
            ts=datetime.now(),
            temp_c=round(random.uniform(15, 21), 1),
            ur=round(min(99, max(40, ur)), 1),
            luz=round(random.uniform(20000, 60000)),
        ), None
        time.sleep(2)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--fake", action="store_true", help="roda sem Arduino")
    ap.add_argument("--porta", help="porta serial (sobrepoe SERIAL_PORT do .env)")
    args = ap.parse_args()

    db.init()
    con = db.conectar()
    aval = Avaliador()
    fonte = _fonte_fake() if args.fake else _fonte_serial(args.porta)

    dias_escuros, checado_em = 0, 0.0
    ultimo_alerta = 0.0

    for leitura, porta in fonte:
        # quantos dias seguidos de luz fraca - so vale a pena recalcular de vez
        # em quando, o resultado muda no maximo uma vez por dia
        if time.time() - checado_em > 300:
            dias_escuros = db.dias_luz_baixa(con, _corte_luz_baixa(leitura.ts))
            checado_em = time.time()

        res = aval.avaliar(leitura, dias_luz_baixa=dias_escuros)

        db.salvar_medicao(
            con, leitura.ts.isoformat(sep=" ", timespec="seconds"),
            leitura.temp_c, leitura.ur, leitura.luz, res.estado,
        )

        # devolve a cor para o Arduino: a logica vive num lugar so
        if porta is not None:
            try:
                porta.write(config.LED[res.estado].encode())
            except Exception as e:  # noqa: BLE001
                print("[collector] falha ao escrever na serial: %s" % e)

        from app.rules import rotulo_luz
        print("UR=%5.1f  T=%4.1f  %-26s %s/%s  ->  %s%s"
              % (leitura.ur, leitura.temp_c,
                 rotulo_luz(leitura.luz, leitura.ts, dias_escuros),
                 res.estacao, res.ciclo, res.estado,
                 "  << MUDOU" if res.mudou else ""))

        if not res.mudou:
            continue

        # anti-spam: numa demo o estado pode oscilar; nao vale um alerta por segundo
        if time.time() - ultimo_alerta < config.SEGUNDOS_ENTRE_ALERTAS:
            print("[collector] mudou para %s, mas o alerta anterior foi ha pouco"
                  % res.estado)
            continue
        ultimo_alerta = time.time()

        ts = leitura.ts.isoformat(sep=" ", timespec="seconds")
        evento_id = db.salvar_evento(
            con, ts, res.anterior, res.estado, res.motivo,
            round(res.segundos_risco / 60, 1),
        )

        ctx = contexto_para_llm(res, leitura)
        try:
            texto = llm.gerar_alerta(ctx)
        except Exception as e:  # noqa: BLE001
            print("[collector] LLM indisponivel (%s) - usando texto de reserva" % e)
            texto = "Situacao mudou para %s. %s. O que fazer: %s." % (
                res.estado, res.motivo, res.acao or "acompanhar")

        db.salvar_mensagem(con, config.SESSION_ID, "system_alert", texto, ts, evento_id)
        print("[alerta] %s" % texto)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(0)
