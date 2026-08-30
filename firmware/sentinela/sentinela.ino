/*
  Morangonet - firmware do sentinela
  --------------------------------------------------------------
  O Arduino e apenas sensor e display. Ele NAO decide a cor do LED.
  Manda uma linha JSON por leitura e recebe de volta um caractere:
      V = verde   A = amarelo   R = vermelho

  Assim a regra vive num lugar so (app/rules.py) e da para ajustar
  limiar durante a apresentacao sem regravar o firmware.
*/

#include <DHT.h>

#define DHTPIN 2
#define DHTTYPE DHT22

#define GREEN_LED_PIN 8
#define YELLOW_LED_PIN 7
#define RED_LED_PIN 6
#define SUN_PIN A0

#define INTERVALO_MS 5000   // DHT22 precisa de no minimo 2 s entre leituras

DHT dht(DHTPIN, DHTTYPE);

unsigned long ultimaLeitura = 0;
char estado = 'V';

void aplicarEstado(char c) {
  digitalWrite(GREEN_LED_PIN,  c == 'V');
  digitalWrite(YELLOW_LED_PIN, c == 'A');
  digitalWrite(RED_LED_PIN,    c == 'R');
}

void setup() {
  Serial.begin(9600);
  dht.begin();
  pinMode(GREEN_LED_PIN, OUTPUT);
  pinMode(YELLOW_LED_PIN, OUTPUT);
  pinMode(RED_LED_PIN, OUTPUT);
  aplicarEstado('V');
}

void loop() {
  // 1) recebe a cor decidida pelo servidor
  while (Serial.available() > 0) {
    char c = Serial.read();
    if (c == 'V' || c == 'A' || c == 'R') {
      estado = c;
      aplicarEstado(estado);
    }
  }

  // 2) manda a leitura, sem travar o loop com delay()
  if (millis() - ultimaLeitura < INTERVALO_MS) return;
  ultimaLeitura = millis();

  float umidade = dht.readHumidity();
  float temperatura = dht.readTemperature();
  int luz = analogRead(SUN_PIN);

  if (isnan(umidade) || isnan(temperatura)) {
    Serial.println("{\"erro\":\"falha na leitura do DHT22\"}");
    return;
  }

  // uma linha JSON por leitura - o Python le com json.loads, sem regex
  Serial.print("{\"ur\":");
  Serial.print(umidade, 1);
  Serial.print(",\"t\":");
  Serial.print(temperatura, 1);
  Serial.print(",\"luz\":");
  Serial.print(luz);
  Serial.println("}");
}
