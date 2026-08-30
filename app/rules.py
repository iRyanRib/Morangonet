"""
Maquina de estados. NAO tem IA aqui, e nao pode ter.

O LLM so escreve texto DEPOIS que este modulo ja decidiu o estado, qual variavel
esta fora da faixa e qual acao tomar. Isso mantem a decisao testavel, auditavel
e imune a alucinacao.

Como decide:
  1. Estacao   - derivada do mes da leitura
  2. Ciclo     - dia ou noite, derivado da luminosidade
  3. Faixa     - cada variavel tem 4 cortes por estacao+ciclo:
                 [vermelho abaixo, amarelo abaixo, amarelo acima, vermelho acima]
                 entre o 2o e o 3o corte e verde
  4. Override  - temperatura >32 C (aborto floral) ou <3 C (geada) e sempre vermelho
  5. Confirmacao - N leituras seguidas para mudar de estado, senao um respingo
                   no sensor faz o painel piscar
  6. Acao      - uma so, escolhida por prioridade. Fungo custa mais que atraso
                 de crescimento; geada manda em tudo.

Unidades: temperatura em C, umidade em %, luminosidade em LUX (o collector
converte a leitura crua do LDR antes de chegar aqui).
"""
from dataclasses import dataclass, field
from datetime import datetime

from app import config

VERDE, AMARELO, VERMELHO = "verde", "amarelo", "vermelho"

# nomes que o banco, o LED e a UI ja usam
ESTADO = {VERDE: "ok", AMARELO: "atencao", VERMELHO: "agir"}
SEVERIDADE = {VERDE: 0, AMARELO: 1, VERMELHO: 2}

ESTACAO_POR_MES = {
    12: "verao", 1: "verao", 2: "verao", 3: "verao",
    4: "outono", 5: "outono",
    6: "inverno", 7: "inverno", 8: "inverno",
    9: "primavera", 10: "primavera", 11: "primavera",
}

# (vermelho abaixo de, amarelo abaixo de, amarelo acima de, vermelho acima de)
# None no 3o/4o valor = sem teto
FAIXAS = {
    "temp": {
        ("verao", "dia"):     (14, 18, 24, 27),
        ("verao", "noite"):   (7, 10, 18, 21),
        ("outono", "dia"):    (14, 18, 24, 27),
        ("outono", "noite"):  (5, 8, 15, 19),
        ("inverno", "dia"):   (13, 18, 25, 29),
        ("inverno", "noite"): (5, 8, 15, 20),
        ("primavera", "dia"):   (14, 18, 25, 28),
        ("primavera", "noite"): (6, 8, 15, 20),
    },
    "ur": {
        ("verao", "dia"):     (52, 62, 78, 88),
        ("verao", "noite"):   (48, 55, 85, 92),
        ("outono", "dia"):    (50, 60, 75, 85),
        ("outono", "noite"):  (48, 55, 80, 90),
        ("inverno", "dia"):   (55, 62, 75, 85),
        ("inverno", "noite"): (50, 58, 80, 90),
        ("primavera", "dia"):   (50, 60, 75, 85),
        ("primavera", "noite"): (48, 55, 80, 90),
    },
    # a noite a luminosidade e sempre verde - nao entra na tabela
    "luz": {
        ("verao", "dia"):     (9000, 18000, 55000, 70000),
        ("outono", "dia"):    (9000, 18000, 60000, 75000),
        ("inverno", "dia"):   (8000, 16000, None, None),
        ("primavera", "dia"): (9000, 18000, 60000, 75000),
    },
}

ROTULO_VAR = {"temp": "temperatura", "ur": "umidade", "luz": "luminosidade"}
UNIDADE = {"temp": "C", "ur": "%", "luz": "lux"}

# A luz nunca aparece como numero na interface nem para o LLM: a conversao do
# LDR para lux e aproximada, e um numero com 4 digitos finge uma precisao que o
# sensor nao tem. O produtor precisa saber se esta claro ou escuro, nao o valor.
ROTULO_LUZ = {
    (VERMELHO, "baixo"): "Iluminação muito baixa",
    (AMARELO, "baixo"): "Iluminação baixa",
    (VERDE, None): "Iluminação boa",
    (AMARELO, "alto"): "Iluminação alta",
    (VERMELHO, "alto"): "Iluminação muito alta",
}
ROTULO_NOITE = "escuro (noite)"

# Versao de uma palavra para o painel: a metrica do Streamlit corta texto longo,
# e a coluna ja se chama "Luz" - repetir "luminosidade" ali nao informa nada.
ROTULO_LUZ_CURTO = {
    (VERMELHO, "baixo"): "Escassa",
    (AMARELO, "baixo"): "Fraca",
    (VERDE, None): "Adequada",
    (AMARELO, "alto"): "Forte",
    (VERMELHO, "alto"): "Excessiva",
}
ROTULO_NOITE_CURTO = "Noite"

# (variavel, lado) -> (chave da acao, texto, risco)
ACOES = {
    ("ur", "alto"): ("ventilar", "abrir as laterais para ventilar a estufa",
                     "mofo cinzento"),
    ("ur", "baixo"): ("fechar", "reduzir a ventilacao e conferir a irrigacao",
                      "estresse da planta e falha na polinizacao"),
    ("temp", "alto"): ("ventilar", "abrir as laterais e avaliar sombreamento",
                       "aborto das flores"),
    ("temp", "baixo"): ("fechar", "fechar as laterais para conservar calor",
                        "dano por frio ou geada"),
    ("luz", "baixo"): ("plastico", "conferir se o plastico esta sujo ou rasgado",
                       "oidio"),
    ("luz", "alto"): ("sombrear", "instalar tela de sombreamento",
                      "queimar folhas e frutos"),
}

ACAO_GEADA = ("geada", "fechar tudo e proteger as plantas do frio",
              "geada - perde a planta, nao so a flor")

# quando duas variaveis pedem coisas opostas, esta e a ordem de quem manda
PESO_VAR = {"ur": 3, "temp": 2, "luz": 1}


@dataclass
class Leitura:
    ts: datetime
    temp_c: float
    ur: float
    luz: float          # em LUX


@dataclass
class Alerta:
    variavel: str       # temp | ur | luz
    nivel: str          # amarelo | vermelho
    lado: str           # alto | baixo
    valor: float
    faixa_verde: tuple  # (min, max) - o que seria normal agora


@dataclass
class Resultado:
    estado: str          # ok | atencao | agir
    nivel: str           # verde | amarelo | vermelho
    mudou: bool
    anterior: str
    motivo: str
    acao: str
    risco: str
    estacao: str
    ciclo: str
    niveis: dict         # variavel -> verde|amarelo|vermelho
    alertas: list        # list[Alerta], do mais grave para o menos
    segundos_no_estado: float

    # compatibilidade com quem le o resultado antigo
    @property
    def em_risco(self):
        return self.nivel != VERDE

    @property
    def segundos_risco(self):
        return self.segundos_no_estado


# ---------- classificacao pura (sem estado, facil de testar) ----------

def estacao_de(ts: datetime) -> str:
    return ESTACAO_POR_MES[ts.month]


def ciclo_de(luz_lux: float) -> str:
    return "dia" if luz_lux >= config.LUZ_DIA_LUX else "noite"


def classificar(valor, cortes):
    """Devolve (nivel, lado). lado e None quando esta verde."""
    v_baixo, a_baixo, a_alto, v_alto = cortes
    if v_baixo is not None and valor < v_baixo:
        return VERMELHO, "baixo"
    if a_baixo is not None and valor < a_baixo:
        return AMARELO, "baixo"
    if a_alto is not None and valor > a_alto:
        if v_alto is not None and valor > v_alto:
            return VERMELHO, "alto"
        return AMARELO, "alto"
    return VERDE, None


def nivel_luz(luz_lux, ts, dias_luz_baixa=0):
    """(nivel, lado) da luz, ou None quando e noite."""
    if ciclo_de(luz_lux) == "noite":
        return None
    cortes = FAIXAS["luz"][(estacao_de(ts), "dia")]
    nivel, lado = classificar(luz_lux, cortes)
    if nivel == VERMELHO and lado == "baixo":
        minimo = (config.DIAS_LUZ_BAIXA_INVERNO if estacao_de(ts) == "inverno"
                  else config.DIAS_LUZ_BAIXA)
        if dias_luz_baixa < minimo:
            nivel = AMARELO
    return nivel, lado


def rotulo_luz(luz_lux, ts, dias_luz_baixa=0, curto=False):
    """Como a luz deve ser MOSTRADA: em palavra, nunca em numero.

    curto=True devolve uma palavra so, para caber na metrica do painel.
    """
    chave = nivel_luz(luz_lux, ts, dias_luz_baixa)
    if chave is None:
        return ROTULO_NOITE_CURTO if curto else ROTULO_NOITE
    return (ROTULO_LUZ_CURTO if curto else ROTULO_LUZ)[chave]


def faixa_verde(cortes):
    return (cortes[1], cortes[2])


def avaliar_leitura(leitura: Leitura, dias_luz_baixa: int = 0):
    """Classifica uma leitura isolada. Sem histerese, sem memoria."""
    estacao = estacao_de(leitura.ts)
    ciclo = ciclo_de(leitura.luz)

    niveis, alertas = {}, []

    for var, valor in (("temp", leitura.temp_c), ("ur", leitura.ur)):
        cortes = FAIXAS[var][(estacao, ciclo)]
        nivel, lado = classificar(valor, cortes)
        if var == "temp":
            # override: passa por cima da faixa da estacao
            if valor > config.TEMP_ABORTO:
                nivel, lado = VERMELHO, "alto"
            elif valor < config.TEMP_GEADA:
                nivel, lado = VERMELHO, "baixo"
        niveis[var] = nivel
        if nivel != VERDE:
            alertas.append(Alerta(var, nivel, lado, valor, faixa_verde(cortes)))

    # luz: a noite e sempre verde; luz baixa so vira vermelho com dias seguidos
    if ciclo == "noite":
        niveis["luz"] = VERDE
    else:
        cortes = FAIXAS["luz"][(estacao, "dia")]
        nivel, lado = classificar(leitura.luz, cortes)
        if nivel == VERMELHO and lado == "baixo":
            minimo = config.DIAS_LUZ_BAIXA_INVERNO if estacao == "inverno" \
                else config.DIAS_LUZ_BAIXA
            if dias_luz_baixa < minimo:
                nivel = AMARELO  # leitura isolada nao condena
        niveis["luz"] = nivel
        if nivel != VERDE:
            alertas.append(Alerta("luz", nivel, lado, leitura.luz, faixa_verde(cortes)))

    alertas.sort(key=lambda a: (SEVERIDADE[a.nivel], PESO_VAR[a.variavel]), reverse=True)
    nivel_geral = max([VERDE] + [a.nivel for a in alertas], key=lambda n: SEVERIDADE[n])
    return estacao, ciclo, niveis, alertas, nivel_geral


def escolher_acao(alertas, temp_c):
    """Uma acao so. Nunca tres coisas para fazer ao mesmo tempo."""
    if not alertas:
        return "", ""

    # geada manda em tudo
    if temp_c < config.TEMP_GEADA:
        return ACAO_GEADA[1], ACAO_GEADA[2]

    lados = {(a.variavel, a.lado) for a in alertas}

    # conflito 1: frio pede fechar, umidade alta pede abrir.
    # ventilar ganha - fungo custa mais caro que atraso de crescimento.
    if ("ur", "alto") in lados and ("temp", "baixo") in lados:
        _, texto, risco = ACOES[("ur", "alto")]
        return texto + ", em janelas curtas para nao esfriar demais", risco

    # conflito 2: seco pede fechar, calor pede abrir. Fechar no calor piora o
    # calor; abrir resseca mais. Sombrear baixa a temperatura sem ressecar.
    if ("ur", "baixo") in lados and ("temp", "alto") in lados:
        return ("sombrear a estufa para baixar a temperatura sem ressecar mais, "
                "e conferir a irrigacao"), "aborto das flores e estresse da planta"

    principal = alertas[0]
    _, texto, risco = ACOES[(principal.variavel, principal.lado)]

    # duas variaveis, mesma acao: fala uma vez so, mas soma os riscos
    chave = ACOES[(principal.variavel, principal.lado)][0]
    juntos = [a for a in alertas[1:]
              if ACOES[(a.variavel, a.lado)][0] == chave]
    if juntos:
        risco = risco + " e " + ACOES[(juntos[0].variavel, juntos[0].lado)][2]
    return texto, risco


def descrever(alertas, estacao, ciclo):
    if not alertas:
        return "todas as variaveis dentro da faixa de %s, de %s" % (estacao, ciclo)
    partes = []
    for a in alertas:
        if a.variavel == "luz":
            partes.append(ROTULO_LUZ[(a.nivel, a.lado)] + " para " + ciclo)
            continue
        partes.append("%s %s (%.1f %s, normal entre %g e %s)" % (
            ROTULO_VAR[a.variavel],
            "alta" if a.lado == "alto" else "baixa",
            a.valor, UNIDADE[a.variavel],
            a.faixa_verde[0],
            "sem teto" if a.faixa_verde[1] is None else "%g" % a.faixa_verde[1],
        ))
    return "; ".join(partes)


# ---------- avaliador com memoria (anti-piscada) ----------

@dataclass
class Avaliador:
    estado: str = "ok"
    nivel: str = VERDE
    segundos_no_estado: float = 0.0
    _candidato: str = None
    _confirmando: int = 0
    _ultima_ts: datetime = None
    _historico: list = field(default_factory=list)

    def avaliar(self, leitura: Leitura, dias_luz_baixa: int = 0) -> Resultado:
        self._historico.append(leitura)
        self._historico = self._historico[-50:]

        delta = 0.0
        if self._ultima_ts is not None:
            delta = max(0.0, (leitura.ts - self._ultima_ts).total_seconds())
        self._ultima_ts = leitura.ts

        estacao, ciclo, niveis, alertas, nivel_bruto = avaliar_leitura(
            leitura, dias_luz_baixa)

        # confirmacao: so muda depois de N leituras seguidas apontando o mesmo
        if nivel_bruto == self.nivel:
            self._candidato, self._confirmando = None, 0
        else:
            if nivel_bruto == self._candidato:
                self._confirmando += 1
            else:
                self._candidato, self._confirmando = nivel_bruto, 1

        anterior = self.estado
        mudou = False
        if self._confirmando >= config.LEITURAS_CONFIRMA:
            self.nivel = nivel_bruto
            self.estado = ESTADO[nivel_bruto]
            self.segundos_no_estado = 0.0
            self._candidato, self._confirmando = None, 0
            mudou = self.estado != anterior
        else:
            self.segundos_no_estado += delta

        acao, risco = escolher_acao(alertas, leitura.temp_c)

        return Resultado(
            estado=self.estado,
            nivel=self.nivel,
            mudou=mudou,
            anterior=anterior,
            motivo=descrever(alertas, estacao, ciclo),
            acao=acao,
            risco=risco,
            estacao=estacao,
            ciclo=ciclo,
            niveis=niveis,
            alertas=alertas,
            segundos_no_estado=self.segundos_no_estado,
        )


def faixas_do_momento(ts: datetime) -> dict:
    """As faixas que valem agora, para o agente citar sem chutar."""
    estacao = estacao_de(ts)
    saida = {}
    for ciclo in ("dia", "noite"):
        saida[ciclo] = {
            "temperatura_c": list(FAIXAS["temp"][(estacao, ciclo)]),
            "umidade_pct": list(FAIXAS["ur"][(estacao, ciclo)]),
        }
    saida["dia"]["luminosidade_lux"] = list(FAIXAS["luz"][(estacao, "dia")])
    saida["legenda"] = ("[vermelho abaixo de, amarelo abaixo de, "
                        "amarelo acima de, vermelho acima de]; null = sem teto")
    return saida


def contexto_para_llm(res: Resultado, leitura: Leitura) -> dict:
    """O que o LLM recebe. So fatos ja decididos - ele nao classifica nada."""
    return {
        "estado_anterior": res.anterior,
        "estado_atual": res.estado,
        "nivel": res.nivel,
        "estacao": res.estacao,
        "ciclo": res.ciclo,
        "motivo": res.motivo,
        "acao_recomendada": res.acao,
        "risco": res.risco,
        "variaveis": [
            ({"nome": "luminosidade", "situacao": a.lado, "nivel": a.nivel,
              "descricao": ROTULO_LUZ[(a.nivel, a.lado)]}
             if a.variavel == "luz" else
             {"nome": ROTULO_VAR[a.variavel], "situacao": a.lado, "nivel": a.nivel,
              "valor": a.valor, "unidade": UNIDADE[a.variavel],
              "faixa_normal": list(a.faixa_verde)})
            for a in res.alertas
        ],
        # a luz vai em palavra: o LLM nao pode citar um lux que nao e confiavel
        "leitura": {"temperatura": leitura.temp_c, "umidade": leitura.ur,
                    "luminosidade": rotulo_luz(leitura.luz, leitura.ts)},
        "minutos_no_estado_anterior": round(res.segundos_no_estado / 60, 1),
    }
