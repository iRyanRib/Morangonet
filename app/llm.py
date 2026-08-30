"""Cliente do modelo. Os prompts moram em prompts/*.md para editar sem mexer no codigo."""
import json
from pathlib import Path

from app import config

_client = None
_RAIZ = Path(__file__).resolve().parent.parent


def cliente():
    """Import tardio: o resto do sistema roda sem a lib e sem chave."""
    global _client
    if _client is None:
        from groq import Groq

        if not config.GROQ_API_KEY:
            raise RuntimeError("GROQ_API_KEY nao configurada no .env")
        _client = Groq(api_key=config.GROQ_API_KEY)
    return _client


def prompt(nome):
    return (_RAIZ / "prompts" / ("%s.md" % nome)).read_text(encoding="utf-8")


def _completar(sistema, mensagens, max_tokens):
    # ATENCAO: gpt-oss e modelo de raciocinio. Os tokens de raciocinio saem do
    # mesmo orcamento, entao um teto apertado corta o texto no meio da frase.
    resp = cliente().chat.completions.create(
        model=config.LLM_MODEL,
        max_tokens=max_tokens,
        temperature=config.LLM_TEMPERATURA,
        messages=[{"role": "system", "content": sistema}] + list(mensagens),
    )
    return (resp.choices[0].message.content or "").strip()


def gerar_alerta(ctx: dict) -> str:
    """Fluxo 1. O estado JA foi decidido - aqui e so traducao para linguagem de produtor."""
    return _completar(
        prompt("alerta"),
        [{"role": "user", "content": json.dumps(ctx, ensure_ascii=False)}],
        max_tokens=1200,
    )


def responder(pergunta: str, contexto: dict, historico: list) -> str:
    """Fluxo 2. Responde ancorado nos dados do banco."""
    msgs = list(historico) + [
        {
            "role": "user",
            "content": "DADOS DA LAVOURA:\n%s\n\nPERGUNTA:\n%s"
            % (json.dumps(contexto, ensure_ascii=False, default=str), pergunta),
        }
    ]
    return _completar(prompt("consulta"), msgs, max_tokens=1500)
