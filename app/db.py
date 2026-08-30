"""Conexao e schema. WAL ligado: dois processos escrevem sem travar."""
import sqlite3
from pathlib import Path

from app.config import DB_PATH

SCHEMA = """
CREATE TABLE IF NOT EXISTS measurements (
    id      INTEGER PRIMARY KEY AUTOINCREMENT,
    ts      TEXT NOT NULL,
    temp_c  REAL,
    ur      REAL,
    luz     REAL,
    estado  TEXT
);

CREATE TABLE IF NOT EXISTS state_events (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    ts            TEXT NOT NULL,
    de            TEXT,
    para          TEXT,
    motivo        TEXT,
    minutos_risco REAL
);

CREATE TABLE IF NOT EXISTS session_messages (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id     TEXT NOT NULL,
    role           TEXT NOT NULL,
    content        TEXT NOT NULL,
    ts             TEXT NOT NULL,
    state_event_id INTEGER
);

CREATE INDEX IF NOT EXISTS idx_meas_ts ON measurements(ts);
CREATE INDEX IF NOT EXISTS idx_msg_ts  ON session_messages(ts);
"""


def conectar():
    Path(DB_PATH).parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(DB_PATH, timeout=10)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL;")
    con.execute("PRAGMA busy_timeout=5000;")
    return con


def init():
    con = conectar()
    con.executescript(SCHEMA)
    con.commit()
    con.close()


# ---------- escrita ----------

def salvar_medicao(con, ts, temp_c, ur, luz, estado):
    cur = con.execute(
        "INSERT INTO measurements (ts, temp_c, ur, luz, estado) VALUES (?,?,?,?,?)",
        (ts, temp_c, ur, luz, estado),
    )
    con.commit()
    return cur.lastrowid


def salvar_evento(con, ts, de, para, motivo, minutos_risco):
    cur = con.execute(
        "INSERT INTO state_events (ts, de, para, motivo, minutos_risco) VALUES (?,?,?,?,?)",
        (ts, de, para, motivo, minutos_risco),
    )
    con.commit()
    return cur.lastrowid


def salvar_mensagem(con, session_id, role, content, ts, state_event_id=None):
    cur = con.execute(
        "INSERT INTO session_messages (session_id, role, content, ts, state_event_id)"
        " VALUES (?,?,?,?,?)",
        (session_id, role, content, ts, state_event_id),
    )
    con.commit()
    return cur.lastrowid


# ---------- leitura ----------

def mensagens(con, session_id, depois_de=0):
    return con.execute(
        "SELECT * FROM session_messages WHERE session_id=? AND id>? ORDER BY id",
        (session_id, depois_de),
    ).fetchall()


def ultima_medicao(con):
    return con.execute("SELECT * FROM measurements ORDER BY id DESC LIMIT 1").fetchone()


def resumo_periodo(con, minutos=1440, pontos_serie=40):
    """Numeros agregados que o agente usa como contexto.

    ATENCAO ao fuso: salvamos ts com datetime.now() (hora local) e o SQLite
    responde datetime('now') em UTC. Sem o modificador 'localtime' a janela sai
    deslocada - inofensivo em 24 h, fatal numa janela de minutos.
    """
    desde = "-%d minutes" % minutos

    row = con.execute(
        """
        SELECT COUNT(*) n, AVG(ur) ur_media, MIN(ur) ur_min, MAX(ur) ur_max,
               AVG(temp_c) temp_media, MIN(temp_c) temp_min, MAX(temp_c) temp_max,
               MIN(ts) primeira, MAX(ts) ultima
        FROM measurements WHERE ts >= datetime('now', 'localtime', ?)
        """,
        (desde,),
    ).fetchone()

    por_estado = con.execute(
        "SELECT estado, COUNT(*) n FROM measurements"
        " WHERE ts >= datetime('now', 'localtime', ?) GROUP BY estado",
        (desde,),
    ).fetchall()

    eventos = con.execute(
        "SELECT * FROM state_events WHERE ts >= datetime('now', 'localtime', ?)"
        " ORDER BY id DESC LIMIT 20",
        (desde,),
    ).fetchall()

    return {
        "agregado": dict(row) if row else {},
        "por_estado": {r["estado"]: r["n"] for r in por_estado},
        "eventos": [dict(e) for e in eventos],
        "serie": serie_periodo(con, minutos, pontos_serie),
    }


def _linha_serie(r):
    """A luz vira palavra tambem aqui - o LLM nunca ve lux."""
    from datetime import datetime

    from app import rules

    d = dict(r)
    try:
        quando = datetime.fromisoformat(d["ts"])
    except (TypeError, ValueError):
        quando = datetime.now()
    d["luminosidade"] = rules.rotulo_luz(d.pop("luz"), quando)
    return d


def serie_periodo(con, minutos=1440, pontos=40):
    """A sequencia das leituras, amostrada. Sem isto o agente so ve medias -
    e media nao mostra se a umidade esta subindo ou caindo agora."""
    if pontos <= 0:
        return []
    linhas = con.execute(
        "SELECT ts, ur, temp_c, luz, estado FROM measurements"
        " WHERE ts >= datetime('now', 'localtime', ?) ORDER BY id",
        ("-%d minutes" % minutos,),
    ).fetchall()
    if not linhas:
        return []
    if len(linhas) <= pontos:
        return [_linha_serie(r) for r in linhas]


    passo = len(linhas) / float(pontos)
    amostra = [linhas[int(i * passo)] for i in range(pontos)]
    if amostra[-1]["ts"] != linhas[-1]["ts"]:
        amostra[-1] = linhas[-1]  # a leitura mais recente nunca pode sumir
    return [_linha_serie(r) for r in amostra]


def dias_luz_baixa(con, corte_lux, max_dias=7):
    """Dias seguidos, terminando hoje, em que a luz do dia nunca passou do corte.

    A regra de luz baixa nao condena uma leitura isolada: so vira vermelho
    depois de N dias seguidos escuros. Usa o MAXIMO do dia - se em algum momento
    bateu sol, o dia nao foi escuro.
    """
    linhas = con.execute(
        "SELECT date(ts) dia, MAX(luz) pico FROM measurements"
        " WHERE ts >= datetime('now', 'localtime', ?)"
        " GROUP BY date(ts) ORDER BY dia DESC",
        ("-%d days" % max_dias,),
    ).fetchall()

    seguidos = 0
    for l in linhas:
        if l["pico"] is None or l["pico"] >= corte_lux:
            break
        seguidos += 1
    return seguidos
