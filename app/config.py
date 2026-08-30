"""Todos os parametros num lugar so. Nada de numero magico espalhado pelo codigo."""
import os
from dotenv import load_dotenv

load_dotenv()


def _f(chave, padrao):
    return float(os.getenv(chave, padrao))


def _i(chave, padrao):
    return int(os.getenv(chave, padrao))


def _b(chave, padrao):
    return str(os.getenv(chave, padrao)).strip().lower() in ("1", "true", "sim", "yes")


# --- LLM (Groq) ---
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
LLM_MODEL = os.getenv("LLM_MODEL", "openai/gpt-oss-120b")
LLM_TEMPERATURA = _f("LLM_TEMPERATURA", 0.3)

# --- Serial ---
SERIAL_PORT = os.getenv("SERIAL_PORT", "/dev/ttyUSB0")
SERIAL_BAUD = _i("SERIAL_BAUD", 9600)

# --- Regras (provisorias, calibrar com agronomo) ---
# As faixas por estacao/ciclo vivem em rules.py. Aqui so o que se ajusta no .env.

LEITURAS_CONFIRMA = _i("LEITURAS_CONFIRMA", 3)   # leituras seguidas para mudar de estado

# Overrides de temperatura: passam por cima da faixa da estacao
TEMP_ABORTO = _f("TEMP_ABORTO", 32)   # acima disso, aborto floral - sempre vermelho
TEMP_GEADA = _f("TEMP_GEADA", 3)      # abaixo disso, geada - manda em tudo

# Ciclo dia/noite
LUZ_DIA_LUX = _f("LUZ_DIA_LUX", 500)

# Luz baixa so vira vermelho depois de N dias seguidos abaixo do corte
DIAS_LUZ_BAIXA = _i("DIAS_LUZ_BAIXA", 3)
DIAS_LUZ_BAIXA_INVERNO = _i("DIAS_LUZ_BAIXA_INVERNO", 2)

# O LDR devolve 0-1023, nao lux. Neste circuito o valor SOBE quando escurece
# (LDR no ramo de cima do divisor) - confira tapando o sensor com a mao.
LUZ_INVERTIDA = _b("LUZ_INVERTIDA", "1")
LUZ_ADC_MAX = _f("LUZ_ADC_MAX", 1023)

# A resposta do LDR e logaritmica, nao linear: a conversao interpola em decadas
# entre escuro total e sol pleno. Continua sendo aproximacao - por isso a
# interface mostra "luminosidade baixa/boa/alta", nunca o numero.
LUZ_LUX_MIN = _f("LUZ_LUX_MIN", 1)
LUZ_LUX_MAX = _f("LUZ_LUX_MAX", 100000)

# Nao alerta duas vezes seguidas em menos que isto (evita spam na demo)
SEGUNDOS_ENTRE_ALERTAS = _f("SEGUNDOS_ENTRE_ALERTAS", 30)

# Janela que o agente enxerga por padrao. Minutos: no tunel o que importa
# na conversa e o agora, nao a media do dia.
JANELA_PADRAO_MIN = _i("JANELA_PADRAO_MIN", 5)

DB_PATH = os.getenv("DB_PATH", "data/morangonet.db")
SESSION_ID = os.getenv("SESSION_ID", "produtor-demo")

# "agir" = vermelho, "atencao" = amarelo, "ok" = verde
LED = {"ok": "V", "atencao": "A", "agir": "R"}
