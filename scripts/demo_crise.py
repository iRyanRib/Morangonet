"""
Plano B do palco: reproduz o roteiro inteiro sem Arduino.

Injeta leituras direto no banco na sequencia da apresentacao:
  verde -> umidade sobe (amarelo) -> umidade alta (vermelho) -> calor (vermelho) -> verde

Uso: python scripts/demo_crise.py
Antes: opcional, LEITURAS_CONFIRMA=2 no .env deixa a virada mais rapida
"""
import sys
import time
from datetime import datetime

sys.path.insert(0, ".")

from app import config, db, llm  # noqa: E402
from app.rules import Avaliador, Leitura, contexto_para_llm  # noqa: E402

# (umidade, temperatura, luz, segundos parado depois) - o roteiro dos 5 passos
ROTEIRO = (
    #  ur  temp   lux  espera
    [(70, 18, 40000, 1)] * 4        # 1. tudo na faixa -> verde
    + [(80, 18, 40000, 2)] * 4      # 2. umidade passa do teto de dia -> amarelo
    + [(93, 19, 40000, 2)] * 4      # 3. umidade bem alta -> vermelho, URGENTE
    + [(72, 33, 40000, 2)] * 4      # 4. ventilou e o sol bateu: >32 C, aborto floral
    + [(70, 18, 40000, 2)] * 4      # 5. sombreou -> verde de novo
)


def main():
    db.init()
    con = db.conectar()
    aval = Avaliador()

    for ur, temp, luz, espera in ROTEIRO:
        leitura = Leitura(ts=datetime.now(), temp_c=temp, ur=ur, luz=luz)
        res = aval.avaliar(leitura)
        stamp = leitura.ts.isoformat(sep=" ", timespec="seconds")
        db.salvar_medicao(con, stamp, temp, ur, luz, res.estado)
        print("UR=%3d luz=%6d lux -> %s%s" % (ur, luz, res.estado,
                                          "  << MUDOU" if res.mudou else ""))

        if res.mudou:
            ev = db.salvar_evento(con, stamp, res.anterior, res.estado, res.motivo,
                                  round(res.segundos_risco / 60, 1))
            try:
                texto = llm.gerar_alerta(contexto_para_llm(res, leitura))
            except Exception:  # noqa: BLE001
                texto = "Situacao mudou para %s. %s. O que fazer: %s." % (
                    res.estado, res.motivo, res.acao or "acompanhar")
            db.salvar_mensagem(con, config.SESSION_ID, "system_alert", texto, stamp, ev)
            print("  [alerta] %s" % texto)

        time.sleep(espera)


if __name__ == "__main__":
    main()
