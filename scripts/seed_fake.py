"""
Gera 3 dias de leituras plausiveis. Roda ANTES do Arduino existir - e o que
permite as frentes do agente e do Streamlit trabalharem em paralelo no sabado.

Uso: python scripts/seed_fake.py [dias]
"""
import math
import random
import sys
from datetime import datetime, timedelta

sys.path.insert(0, ".")

from app import config, db  # noqa: E402
from app.rules import Avaliador, Leitura  # noqa: E402

PASSO_MIN = 5


def gerar(dias=3):
    db.init()
    con = db.conectar()
    con.execute("DELETE FROM measurements")
    con.execute("DELETE FROM state_events")
    con.commit()

    aval = Avaliador()
    inicio = datetime.now() - timedelta(days=dias)
    n = int(dias * 24 * 60 / PASSO_MIN)

    for i in range(n):
        ts = inicio + timedelta(minutes=i * PASSO_MIN)
        h = ts.hour + ts.minute / 60

        # dia claro entre 6h e 18h
        # em LUX: pico ~60000 ao meio-dia, 0 a noite
        luz = max(0, 60000 * math.sin(math.pi * (h - 6) / 12)) if 6 <= h <= 18 else 0
        luz = max(0, luz + random.uniform(-4000, 4000))

        # temperatura minima de madrugada, maxima a tarde
        temp = 17 + 7 * math.sin(math.pi * (h - 8) / 12) + random.uniform(-1, 1)

        # umidade alta de madrugada; num dos dias, fica alta o dia todo
        dia_ruim = (ts.day % 3 == 0)
        base = 94 if (h < 8 or h > 19) else (91 if dia_ruim else 68)
        ur = min(99, max(45, base + random.uniform(-4, 4)))

        leitura = Leitura(ts=ts, temp_c=round(temp, 1), ur=round(ur, 1), luz=round(luz))
        res = aval.avaliar(leitura)
        stamp = ts.isoformat(sep=" ", timespec="seconds")
        db.salvar_medicao(con, stamp, leitura.temp_c, leitura.ur, leitura.luz, res.estado)
        if res.mudou:
            db.salvar_evento(con, stamp, res.anterior, res.estado, res.motivo,
                             round(res.segundos_risco / 60, 1))

    print("Gerados %d registros em %s" % (n, config.DB_PATH))
    print("Eventos de mudanca de estado:",
          con.execute("SELECT COUNT(*) c FROM state_events").fetchone()["c"])


if __name__ == "__main__":
    gerar(int(sys.argv[1]) if len(sys.argv) > 1 else 3)
