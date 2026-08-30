# Morangonet

Sentinela de mofo para morango em cultivo protegido.

Sensores medem umidade, temperatura e luz dentro do tunel. O computador guarda
as leituras, decide o estado e — **so quando o estado muda** — pede ao LLM um
alerta em linguagem de produtor. O mesmo banco alimenta um chat de perguntas.

---

## O princípio que organiza o código

> **O código decide. O LLM só traduz.**

`app/rules.py` calcula o estado (verde / amarelo / vermelho) e escolhe **a ação**.
Ele deriva a estação pelo mês e o ciclo (dia/noite) pela luminosidade, classifica
temperatura, umidade e luz contra a faixa daquela estação+ciclo, aplica os
overrides (>32 °C aborto floral, <3 °C geada) e resolve os conflitos — quando o
frio pede fechar e a umidade alta pede abrir, ventilar ganha em janelas curtas,
porque fungo custa mais caro que atraso de crescimento.

É código puro e testado (18 testes). O LLM entra depois, apenas para escrever o
texto a partir da decisão pronta. Isso mantém a decisão auditável e imune a
alucinação — e é a resposta para "como vocês garantem que a IA não inventa?".

**Unidades:** as regras trabalham em lux. O LDR devolve 0–1023, e o collector
converte com `LUZ_LUX_POR_ADC` — uma reta provisória que **precisa de calibração
com luxímetro**. É o primeiro número a acertar antes de confiar nos alertas de luz.

---

## Rodar

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env        # coloque a GROQ_API_KEY e a SERIAL_PORT
```

**Sem hardware** (para a frente do agente trabalhar em paralelo):

```bash
python scripts/seed_fake.py 3     # 3 dias de dados plausíveis
streamlit run app/ui.py
```

**Com o Arduino:** dois terminais.

```bash
python -m app.collector           # terminal 1 — serial → banco → alerta
streamlit run app/ui.py           # terminal 2 — chat
```

Sem Arduino mas com o loop rodando: `python -m app.collector --fake`

**Testes:** `python -m pytest tests/ -q`

---

## Estrutura

```
firmware/sentinela/    lê sensores, manda JSON, recebe V/A/R
app/config.py          limiares e .env num lugar só
app/db.py              conexão, schema, WAL
app/rules.py           máquina de estados — o núcleo. SEM LLM
app/collector.py       loop serial → banco → regras → alerta
app/llm.py             cliente Groq e carregamento dos prompts
app/agent.py           fluxo de consulta, busca no banco
app/ui.py              chat Streamlit
prompts/*.md           texto editável sem mexer em código
scripts/seed_fake.py   gera dados falsos
scripts/demo_crise.py  reproduz o roteiro do palco sem hardware
```

---

## As regras da máquina de estados

| Regra | Por quê |
|---|---|
| **Histerese** — entra com UR ≥ 90, sai só com UR ≤ 85 | Sem isso o estado pisca em volta do limiar e o produtor recebe dez alertas em dez minutos |
| **Confirmação** — N leituras seguidas | Uma leitura solta pode ser respingo de irrigação no sensor |
| **Duração, não valor** — conta tempo acumulado | Ninguém decide com "UR = 92 agora" |
| **A luz decide se dá para agir** | Não adianta mandar abrir o túnel de madrugada |
| **Temperatura é peso, não porteira** | O bafo sobe umidade **e** temperatura juntas. Se a faixa fria fosse obrigatória, a demo não dispararia |

---

## Duas coisas que o LLM nunca faz

1. **Não decide o estado.** Ele recebe um estado já calculado e escreve o texto.
2. **Não nomeia produto nem dose.** Recomendação de defensivo é atribuição de
   agrônomo. Está escrito nos dois prompts e precisa continuar lá.

---

## Demonstração

A classificação é imediata: basta `LEITURAS_CONFIRMA` leituras seguidas (3 por
padrão, ~15 s a 5 s por leitura) para o estado virar. Não há mais acúmulo de
horas — o vermelho dispara em tempo de palco sem configuração extra.

Roteiro com a mini estufa:

1. Tampa fechada, tudo na faixa → **verde**
2. Bafo ou pano úmido → umidade passa do teto da estação → **amarelo**
3. Continua subindo → passa do corte vermelho → **URGENTE**, "abre as laterais"
4. Abre a tampa → umidade cai → **verde** ("secou")

A lanterna do celular no LDR satura o sensor e serve para mostrar a virada
dia/noite: as faixas de umidade e temperatura mudam junto.

Plano B sem hardware: `python scripts/demo_crise.py` roda o roteiro inteiro.

O passo 5 é o mais forte: abrir a tampa **é** a ação que o produtor faz no túnel.
Não é simulação, é o sistema rodando em escala reduzida.

**Plano B se o cabo USB falhar:** `python scripts/demo_crise.py` reproduz o
roteiro inteiro direto no banco.

**Cuidado:** não borrife água no sensor. Gota líquida no DHT22 satura a leitura
por muito tempo. Use bafo ou pano úmido sem encostar.

---

## Limiares

Os valores em `.env.example` são **provisórios** e precisam ser calibrados com
agrônomo antes de qualquer apresentação. O contexto agronômico está no mural de
evidências do projeto.
