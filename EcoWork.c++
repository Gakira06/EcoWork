/*
 * GS Edge Computing 2025 - PROJETO ECOWORK HUB
 *
 * Este código controla um "EcoWork Hub" para monitorar um ambiente de
 * home office, focando em sustentabilidade e economia de energia.
 *
 * Componentes:
 * - ESP32
 * - Sensor de Presença (HC-SR04)
 * - Sensor de Luz (LDR Módulo)
 * - Sensor de Temp/Umidade (DHT22)
 * - Display LCD 16x2 I2C
 * - LED Branco (Luz do escritório)
 * - LED Vermelho (Alerta de Clima / AC)
 * - LED Verde (Modo Eco)
 *
 * Lógica:
 * 1. PRESENÇA: Se ninguém estiver perto, desliga tudo.
 * 2. LUZ: Se houver presença e a luz ambiente for ALTA, desliga o LED Branco.
 * 3. CLIMA: Se houver presença, controla o clima (LEDs Vermelho/Verde).
 */

// --- Bibliotecas ---
#include <WiFi.h>
#include <PubSubClient.h>
#include <Wire.h>
#include <LiquidCrystal_I2C.h>
#include <DHT.h>
#include <Adafruit_Sensor.h>

// --- Configuração de Pinos ---
// Sensor de Temperatura e Umidade
#define DHT_PIN 4
#define DHT_TYPE DHT22
// Sensor de Luz (LDR) - Pinar em um pino Analógico (ADC1)
#define LIGHT_SENSOR_PIN 34
// Sensor Ultrassônico (Presença)
#define TRIG_PIN 5
#define ECHO_PIN 18
// Atuadores (LEDs)
#define LED_WHITE_PIN 19 // Luz principal do escritório
#define LED_RED_PIN 23   // Alerta de Clima / "Ar Condicionado"
#define LED_GREEN_PIN 13 // Modo Eco / "Ventilador"

// --- Configuração de Rede (Wokwi) ---
const char* ssid = "Wokwi-GUEST";
const char* password = "";
const char* mqtt_broker = "broker.hivemq.com";
const int mqtt_port = 1883;
// Tópicos MQTT
const char* topic_telemetria = "ecowork/telemetria";
const char* topic_status = "ecowork/status";
const char* topic_alerta = "ecowork/alerta";

// --- Limiares da Lógica ---
// Distância em CM. Se maior que isso, considera "ausente".
const int PRESENCE_THRESHOLD_CM = 100;
// Valor analógico do LDR. Valores baixos = MUITA LUZ. (Ajuste no Wokwi)
const int LIGHT_THRESHOLD_HIGH_LIGHT = 1500;
// Limites de temperatura para o "conforto"
const float TEMP_HIGH_THRESHOLD = 26.0;
const float TEMP_LOW_THRESHOLD = 20.0;

// --- Intervalo de Leitura (em milissegundos) ---
const long READ_INTERVAL_MS = 3000; // Lê sensores a cada 3 segundos
unsigned long g_lastReadTime = 0;

// --- Inicialização dos Objetos ---
WiFiClient espClient;
PubSubClient mqttClient(espClient);
DHT dht(DHT_PIN, DHT_TYPE);
// Endereço I2C do LCD (0x27 é o padrão no Wokwi)
LiquidCrystal_I2C lcd(0x27, 16, 2);

// --- Variáveis Globais de Estado do LCD ---
String g_lcdLine1 = "";
String g_lcdLine2 = "";

// --- Protótipos das Funções ---
void setup_wifi();
void reconnect_mqtt();
void publishMQTT(const char* topic, const char* payload);
long getDistanceCM();
void updateLCD(String line1, String line2);

// =================================================================
//   SETUP
// =================================================================
void setup() {
  Serial.begin(115200);
  
  // Inicializa Pinos
  pinMode(TRIG_PIN, OUTPUT);
  pinMode(ECHO_PIN, INPUT);
  pinMode(LIGHT_SENSOR_PIN, INPUT);
  pinMode(LED_WHITE_PIN, OUTPUT);
  pinMode(LED_RED_PIN, OUTPUT);
  pinMode(LED_GREEN_PIN, OUTPUT);

  // Inicializa Sensores e LCD
  dht.begin();
  lcd.init();
  lcd.backlight();
  lcd.setCursor(0, 0);
  lcd.print("EcoWork Hub");
  lcd.setCursor(0, 1);
  lcd.print("Iniciando...");

  // Conecta à Rede
  setup_wifi();
  mqttClient.setServer(mqtt_broker, mqtt_port);

  delay(2000);
}

// =================================================================
//   LOOP PRINCIPAL
// =================================================================
void loop() {
  // Mantém a conexão MQTT ativa
  if (!mqttClient.connected()) {
    reconnect_mqtt();
  }
  mqttClient.loop();

  // Loop principal não-bloqueante (usa millis())
  if (millis() - g_lastReadTime > READ_INTERVAL_MS) {
    g_lastReadTime = millis();
    
    // Função principal que lê e decide o que fazer
    readSensorsAndAct();
  }
}

// =================================================================
//   FUNÇÃO PRINCIPAL DE LÓGICA
// =================================================================
void readSensorsAndAct() {
  // 1. Ler todos os sensores
  float temp = dht.readTemperature();
  float umid = dht.readHumidity();
  // Lê o valor analógico (0-4095). No Wokwi, MAIS LUZ = VALOR MENOR
  int light = analogRead(LIGHT_SENSOR_PIN); 
  long dist = getDistanceCM();

  // Verifica se a leitura do DHT falhou
  if (isnan(temp) || isnan(umid)) {
    Serial.println("Falha ao ler DHT!");
    updateLCD("Falha no Sensor", "Verificar DHT22");
    return;
  }

  // Variáveis para as mensagens do LCD
  String line1 = "";
  String line2 = "";
  bool presente = false;

  // Criar payload JSON para MQTT
  String jsonPayload = "{";
  jsonPayload += "\"temperatura\":" + String(temp, 1) + ",";
  jsonPayload += "\"umidade\":" + String(umid, 1) + ",";
  jsonPayload += "\"luminosidade\":" + String(light) + ",";
  jsonPayload += "\"distancia\":" + String(dist);
  

  // 2. LÓGICA DE PRESENÇA (Prioridade Máxima)
  // "ngm por perto dispositivo desligado"
  if (dist > PRESENCE_THRESHOLD_CM) {
    presente = false;
    line1 = "Ninguem por perto";
    line2 = "Modo Standby";
    
    // Desliga todos os atuadores
    digitalWrite(LED_WHITE_PIN, LOW);
    digitalWrite(LED_RED_PIN, LOW);
    digitalWrite(LED_GREEN_PIN, LOW);

    publishMQTT(topic_status, "Ausente");
    
  } else {
    // 3. LÓGICAS DE AMBIENTE (Se houver presença)
    presente = true;
    publishMQTT(topic_status, "Presente");

    // Lógica de Luz: "luz alta, lmpada desligada"
    if (light < LIGHT_THRESHOLD_HIGH_LIGHT) { // Lembre-se: Menor valor = Mais Luz
      digitalWrite(LED_WHITE_PIN, LOW);
      line1 = "Luz alta, Lmp OFF"; // Exatamente como pedido
      publishMQTT(topic_alerta, "Luz artificial desligada (ambiente claro)");
    } else {
      digitalWrite(LED_WHITE_PIN, HIGH);
      line1 = "Luz baixa, Lmp ON";
    }

    // Lógica de Clima:
    // "temperaturaa baixa desligando ar" (LED Vermelho = Ar Cond.)
    if (temp < TEMP_LOW_THRESHOLD) {
      digitalWrite(LED_RED_PIN, LOW);   // Desliga AC
      digitalWrite(LED_GREEN_PIN, LOW); // Desliga Vent.
      line2 = "Frio. AC Desligado"; // Exatamente como pedido
      publishMQTT(topic_alerta, "Clima Frio. AC Desligado.");
    
    } else if (temp > TEMP_HIGH_THRESHOLD) {
      digitalWrite(LED_RED_PIN, HIGH);  // Liga AC
      digitalWrite(LED_GREEN_PIN, LOW);
      line2 = "Calor. AC Ligado";
      publishMQTT(topic_alerta, "Clima Quente. AC Ligado.");
      
    } else { // Temperatura confortável
      digitalWrite(LED_RED_PIN, LOW);   // Desliga AC
      digitalWrite(LED_GREEN_PIN, HIGH); // Liga Modo Eco (Ventilador)
      line2 = "Temp OK. Modo Eco";
      publishMQTT(topic_alerta, "Clima Confortavel. Modo Eco.");
    }
  }

  // 4. Atualizar o LCD
  updateLCD(line1, line2);

  // 5. Publicar telemetria completa
  jsonPayload += "}";
  publishMQTT(topic_telemetria, jsonPayload.c_str());

  // Debug no Serial Monitor
  Serial.print("Dist: " + String(dist) + "cm | ");
  Serial.print("Luz: " + String(light) + " | ");
  Serial.println("Temp: " + String(temp) + "C");
  Serial.println("LCD1: " + line1);
  Serial.println("LCD2: " + line2);
}


// =================================================================
//   FUNÇÕES AUXILIARES
// =================================================================

// --- Conexão WiFi ---
void setup_wifi() {
  delay(10);
  Serial.println("Conectando ao WiFi...");
  WiFi.begin(ssid, password);
  while (WiFi.status() != WL_CONNECTED) {
    delay(500);
    Serial.print(".");
  }
  Serial.println("Conectado!");
}

// --- Reconexão MQTT ---
void reconnect_mqtt() {
  while (!mqttClient.connected()) {
    Serial.print("Conectando ao MQTT...");
    if (mqttClient.connect("EcoWorkHubClient-Gabriel")) {
      Serial.println("Conectado!");
    } else {
      Serial.print("Falha, rc=");
      Serial.print(mqttClient.state());
      Serial.println(" Tentando novamente em 5s");
      delay(5000);
    }
  }
}

// --- Publicar MQTT ---
void publishMQTT(const char* topic, const char* payload) {
  if (mqttClient.connected()) {
    mqttClient.publish(topic, payload);
  }
}

// --- Leitura Sensor Ultrassônico ---
long getDistanceCM() {
  // Gera o pulso de Trigger
  digitalWrite(TRIG_PIN, LOW);
  delayMicroseconds(2);
  digitalWrite(TRIG_PIN, HIGH);
  delayMicroseconds(10);
  digitalWrite(TRIG_PIN, LOW);
  
  // Lê o tempo de retorno do Echo
  long duration = pulseIn(ECHO_PIN, HIGH);
  
  // Converte o tempo em distância (cm)
  // Velocidade do som = 343 m/s = 0.0343 cm/us
  // Distância = (Tempo * Velocidade) / 2 (ida e volta)
  return duration * 0.0343 / 2;
}

// --- Atualizar LCD (Evita Piscar) ---
void updateLCD(String line1, String line2) {
  // Garante que o texto tenha 16 caracteres para preencher
  while(line1.length() < 16) line1 += " ";
  while(line2.length() < 16) line2 += " ";

  // Só atualiza se o texto mudou
  if (line1 != g_lcdLine1) {
    lcd.setCursor(0, 0);
    lcd.print(line1);
    g_lcdLine1 = line1;
  }
  if (line2 != g_lcdLine2) {
    lcd.setCursor(0, 1);
    lcd.print(line2);
    g_lcdLine2 = line2;
  }
}