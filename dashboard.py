from flask import Flask, render_template_string
from flask_socketio import SocketIO
import paho.mqtt.client as mqtt
import json
import time

# =================================================================
# ==== CONFIGURAÇÃO ECOWORK ====
# =================================================================

# ATENÇÃO: Use o MESMO broker que está no seu código do ESP32
MQTT_BROKER = "broker.hivemq.com"
MQTT_PORT = 1883
MQTT_KEEPALIVE = 60

# ATENÇÃO: Use os MESMOS tópicos que estão no seu código do ESP32
MQTT_TOPIC_TELEMETRIA = "ecowork/telemetria"
MQTT_TOPIC_STATUS = "ecowork/status"
MQTT_TOPIC_ALERTA = "ecowork/alerta"

# Limiar do sensor LDR (do código C++ do ESP32)
# No Wokwi, valor < 1500 significa LUZ ALTA (desliga a lâmpada)
LIGHT_THRESHOLD_HIGH_LIGHT = 1500

# =================================================================
# ==== Flask / SocketIO ====
# =================================================================
app = Flask(__name__)
# O async_mode="threading" é importante para rodar o MQTT em background
socketio = SocketIO(app, async_mode="threading", cors_allowed_origins="*")

# Variáveis globais para guardar o último estado
ultimo_valor_telemetria = {}
ultimo_valor_status = "Aguardando..."
ultimo_valor_alerta = "Nenhum alerta recente."

# =================================================================
# ==== Callbacks MQTT (Paho V1 API) ====
# =================================================================
def on_connect(client, userdata, flags, rc):
    print(f"[MQTT] Conectado ao broker. Código: {rc}")
    
    # Se inscreve nos 3 tópicos do projeto EcoWork
    client.subscribe(MQTT_TOPIC_TELEMETRIA)
    client.subscribe(MQTT_TOPIC_STATUS)
    client.subscribe(MQTT_TOPIC_ALERTA)
    
    print(f"[MQTT] Inscrito em: {MQTT_TOPIC_TELEMETRIA}")
    print(f"[MQTT] Inscrito em: {MQTT_TOPIC_STATUS}")
    print(f"[MQTT] Inscrito em: {MQTT_TOPIC_ALERTA}")

def on_message(client, userdata, msg):
    global ultimo_valor_telemetria, ultimo_valor_status, ultimo_valor_alerta
    
    try:
        # Pega o tópico e o payload (mensagem)
        topic = msg.topic
        payload_str = msg.payload.decode("utf-8", errors="replace").strip()
        print(f"[MQTT] Mensagem recebida | Tópico: {topic} | Payload: {payload_str}")

        # LÓGICA DE ROTEAMENTO DE MENSAGEM
        # 1. Se for uma mensagem de TELEMETRIA (JSON)
        if topic == MQTT_TOPIC_TELEMETRIA:
            dados_json = json.loads(payload_str)
            
            # --- LÓGICA DA LÂMPADA CORRIGIDA ---
            # A lógica agora depende do status de presença!
            try:
                # Só pode estar "Ligada" se o status for "Presente"
                if ultimo_valor_status == "Presente" and dados_json.get('luminosidade') is not None:
                    
                    if dados_json['luminosidade'] < LIGHT_THRESHOLD_HIGH_LIGHT:
                        # Presente, mas com luz alta (claro)
                        dados_json['lamp_status'] = "Desligada"
                    else:
                        # Presente e com luz baixa (escuro)
                        dados_json['lamp_status'] = "Ligada"
                else:
                    # Se está "Ausente" ou não tem dados, a lâmpada está "Desligada"
                    dados_json['lamp_status'] = "Desligada"
            except Exception:
                dados_json['lamp_status'] = "N/A" # Caso o dado venha quebrado
            # --- FIM DA LÓGICA DA LÂMPADA ---
            
            ultimo_valor_telemetria = dados_json
            # Envia para o frontend no evento 'atualiza_telemetria'
            socketio.emit("atualiza_telemetria", {"valor": dados_json})
            print(f"[MQTT->SocketIO] Telemetria enviada: {dados_json}")

        # 2. Se for uma mensagem de STATUS (String)
        elif topic == MQTT_TOPIC_STATUS:
            ultimo_valor_status = payload_str
            # Envia para o frontend no evento 'atualiza_status'
            socketio.emit("atualiza_status", {"valor": payload_str})
            print(f"[MQTT->SocketIO] Status enviado: {payload_str}")
            
            # --- GATILHO EXTRA ---
            # Se o status mudou, força uma re-avaliação da lâmpada
            # Isso corrige o status da lâmpada IMEDIATAMENTE quando o usuário sai
            if ultimo_valor_status == "Ausente":
                # É importante atualizar o .get() para evitar erro se 'ultimo_valor_telemetria' estiver vazio
                if ultimo_valor_telemetria.get('lamp_status') != "Desligada":
                    ultimo_valor_telemetria['lamp_status'] = "Desligada"
                    socketio.emit("atualiza_telemetria", {"valor": ultimo_valor_telemetria})
                    print(f"[MQTT->SocketIO] Forçando status da lâmpada para Desligada (Ausente)")

        # 3. Se for uma mensagem de ALERTA (String)
        elif topic == MQTT_TOPIC_ALERTA:
            ultimo_valor_alerta = payload_str
            # Envia para o frontend no evento 'novo_alerta'
            socketio.emit("novo_alerta", {"valor": payload_str})
            print(f"[MQTT->SocketIO] Alerta enviado: {payload_str}")

    except json.JSONDecodeError:
        print(f"[MQTT] Erro: A mensagem no tópico de telemetria não era um JSON. Payload: {payload_str}")
    except Exception as e:
        print(f"[MQTT] Erro ao processar payload: {e}")

# ---- Configura e inicia o cliente MQTT ----
client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION1)
client.on_connect = on_connect
client.on_message = on_message

client.connect(MQTT_BROKER, MQTT_PORT, MQTT_KEEPALIVE)
client.loop_start() # Inicia o loop em uma thread separada

# =================================================================
# ==== Página Web (HTML/CSS/JS) ====
# =================================================================
@app.route("/")
def index():
    # Este HTML foi 100% adaptado para o projeto EcoWork
    return render_template_string("""
<!DOCTYPE html>
<html lang="pt-BR">
<head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0"/>
    <title>EcoWork Hub - Dashboard</title>
    <link rel="stylesheet" href="https://stackpath.bootstrapcdn.com/bootstrap/4.5.2/css/bootstrap.min.css">
    <script src="https://code.jquery.com/jquery-3.5.1.min.js"></script>
    <script src="https://cdn.socket.io/4.7.2/socket.io.min.js"></script>
    <script src="https://cdn.jsdelivr.net/npm/chart.js@3.7.0/dist/chart.min.js"></script>
    <script src="https://cdn.jsdelivr.net/npm/chartjs-adapter-date-fns/dist/chartjs-adapter-date-fns.bundle.min.js"></script>
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;600;700&display=swap" rel="stylesheet">
    <style>
        :root {
            --eco-green: #2d8a4a;
            --dark-blue: #0f1c2e;
            --light-grey: #f4f7f6;
            --text-color: #333;
            --card-shadow: 0 4px 12px rgba(0,0,0,0.05);
        }
        body {
            background-color: var(--light-grey);
            color: var(--text-color);
            font-family: 'Inter', sans-serif;
        }
        .container {
            max-width: 1200px;
            margin-top: 30px;
            margin-bottom: 30px;
        }
        h1 {
            font-family: 'Inter', sans-serif;
            font-weight: 700;
            color: var(--dark-blue);
            margin-bottom: 30px;
        }
        h1 .eco-title {
            color: var(--eco-green);
        }
        .card {
            margin-top: 20px;
            border: none;
            border-radius: 12px;
            box-shadow: var(--card-shadow);
            background-color: #fff;
            transition: transform 0.2s ease-in-out;
        }
        .card:hover {
            transform: translateY(-5px);
        }
        .card-body {
            padding: 25px;
        }
        .card-title {
            font-weight: 600;
            color: var(--dark-blue);
            font-size: 1.1rem;
            margin-bottom: 10px;
        }
        .kpi-value {
            font-size: 2.5rem;
            font-weight: 700;
            color: var(--eco-green);
        }
        .kpi-value small {
            font-size: 1.5rem;
            color: #6c757d;
        }
        .status-card {
            background: var(--dark-blue);
            color: white;
        }
        .status-card .kpi-value {
            color: white;
        }
        .alert-card {
            background-color: #fff8e1;
            border-left: 5px solid #ffc107;
        }
        .alert-card .kpi-value {
            font-size: 1.2rem;
            color: #856404;
            height: 60px; /* Altura fixa para o alerta */
            display: flex;
            align-items: center;
            justify-content: center;
        }
        /* Adicionado para alinhar os cards da Linha 2 */
        .kpi-row-2 .card-body {
            min-height: 168px; /* Altura mínima para todos os cards */
            display: flex;
            flex-direction: column;
            justify-content: center;
        }
        .kpi-row-2 .kpi-value {
            font-size: 2.2rem; /* Ajusta o tamanho da fonte */
        }
        .kpi-row-2 .alert-text {
            font-size: 1.2rem; /* Ajusta o texto do alerta */
            color: #856404;
        }
        #timestamp {
            font-size: 0.9rem;
            color: #6c757d;
            text-align: center;
            margin-top: 30px;
            font-style: italic;
        }
        .chart-container {
            position: relative;
            height: 250px; /* Altura maior para os gráficos */
            width: 100%;
            margin-top: 15px;
        }
    </style>
</head>
<body>
    <div class="container">
        <h1 class="mt-4 text-center">Dashboard de Sustentabilidade <span class="eco-title">EcoWork</span></h1>
        
        <div class="row">
            <div class="col-md-3">
                <div class="card text-center">
                    <div class="card-body">
                        <h5 class="card-title">🌡️ Temperatura</h5>
                        <p class="kpi-value">
                            <span id="val-temp">--</span><small> °C</small>
                        </p>
                    </div>
                </div>
            </div>
            <div class="col-md-3">
                <div class="card text-center">
                    <div class="card-body">
                        <h5 class="card-title">💧 Umidade</h5>
                        <p class="kpi-value">
                            <span id="val-hum">--</span><small> %</small>
                        </p>
                    </div>
                </div>
            </div>
            <div class="col-md-3">
                <div class="card text-center">
                    <div class="card-body">
                        <h5 class="card-title">💡 Luminosidade</h5>
                        <p class="kpi-value">
                            <span id="val-lum">--</span><small> %</small>
                        </p>
                    </div>
                </div>
            </div>
            <div class="col-md-3">
                <div class="card text-center">
                    <div class="card-body">
                        <h5 class="card-title">👤 Presença (Dist.)</h5>
                        <p class="kpi-value">
                            <span id="val-dist">--</span><small> cm</small>
                        </p>
                    </div>
                </div>
            </div>
        </div>

        <div class="row">
            <div class="col-md-4 kpi-row-2">
                <div class="card text-center status-card">
                    <div class="card-body">
                        <h5 class="card-title" style="color: white;">Status da Presença</h5>
                        <p class="kpi-value">
                            <span id="val-status">Aguardando...</span>
                        </p>
                    </div>
                </div>
            </div>
            
            <div class="col-md-4 kpi-row-2">
                <div class="card text-center" id="lamp-card">
                    <div class="card-body">
                        <h5 class="card-title">💡 Lâmpada Branca</h5>
                        <p class="kpi-value" style="color: var(--dark-blue);">
                            <span id="val-lamp">--</span>
                        </p>
                    </div>
                </div>
            </div>

            <div class="col-md-4 kpi-row-2">
                <div class="card text-center alert-card" id="alert-card-wrapper">
                    <div class="card-body">
                        <h5 class="card-title">🔔 Último Alerta</h5>
                        <p class="kpi-value alert-text"> <span id="val-alerta">Nenhum alerta recente.</span>
                        </p>
                    </div>
                </div>
            </div>
        </div>

        <div class="row">
            <div class="col-md-4">
                <div class="card">
                    <div class="card-body">
                        <div class="chart-container">
                            <canvas id="tempChart"></canvas>
                        </div>
                    </div>
                </div>
            </div>
            <div class="col-md-4">
                <div class="card">
                    <div class="card-body">
                        <div class="chart-container">
                            <canvas id="humChart"></canvas>
                        </div>
                    </div>
                </div>
            </div>
            <div class="col-md-4">
                <div class="card">
                    <div class="card-body">
                        <div class="chart-container">
                            <canvas id="lumChart"></canvas>
                        </div>
                    </div>
                </div>
            </div>
        </div>
        
        <div id="timestamp">
            Última telemetria: <span id="val-ts">Aguardando dados...</span>
        </div>
    </div>

    <script>
        $(function() {
            // Conecta ao servidor SocketIO
            const socket = io({ transports: ['websocket', 'polling'] });
            const MAX_DATA_POINTS = 20; // Pontos no gráfico

            // Configurações comuns dos gráficos
            const commonChartOptions = {
                responsive: true,
                maintainAspectRatio: false,
                animation: { duration: 0 },
                scales: {
                    x: {
                        type: 'time',
                        time: {
                            unit: 'second',
                            tooltipFormat: 'HH:mm:ss',
                            displayFormats: { second: 'HH:mm:ss' }
                        },
                        grid: { display: false }
                    },
                    y: {
                        beginAtZero: false,
                        grid: { color: 'rgba(0,0,0,0.05)' }
                    }
                },
                plugins: {
                    legend: { display: false }
                }
            };

            // --- Gráfico de Temperatura ---
            const tempCtx = document.getElementById('tempChart').getContext('2d');
            const tempChart = new Chart(tempCtx, {
                type: 'line',
                data: {
                    labels: [],
                    datasets: [{
                        label: 'Temperatura (°C)',
                        data: [],
                        borderColor: '#dc3545',
                        backgroundColor: 'rgba(220, 53, 69, 0.2)',
                        fill: true,
                        tension: 0.3
                    }]
                },
                options: { ...commonChartOptions, plugins: { ...commonChartOptions.plugins, title: { display: true, text: 'Histórico de Temperatura' } } }
            });

            // --- Gráfico de Umidade ---
            const humCtx = document.getElementById('humChart').getContext('2d');
            const humChart = new Chart(humCtx, {
                type: 'line',
                data: {
                    labels: [],
                    datasets: [{
                        label: 'Umidade (%)',
                        data: [],
                        borderColor: '#007bff',
                        backgroundColor: 'rgba(0, 123, 255, 0.2)',
                        fill: true,
                        tension: 0.3
                    }]
                },
                options: { ...commonChartOptions, plugins: { ...commonChartOptions.plugins, title: { display: true, text: 'Histórico de Umidade' } } }
            });

            // --- Gráfico de Luminosidade ---
            const lumCtx = document.getElementById('lumChart').getContext('2d');
            const lumChart = new Chart(lumCtx, {
                type: 'line',
                data: {
                    labels: [],
                    datasets: [{
                        label: 'Luminosidade (%)',
                        data: [],
                        borderColor: '#ffc107',
                        backgroundColor: 'rgba(255, 193, 7, 0.2)',
                        fill: true,
                        tension: 0.3
                    }]
                },
                options: { ...commonChartOptions, plugins: { ...commonChartOptions.plugins, title: { display: true, text: 'Histórico de Luminosidade' } } }
            });

            // --- Função para atualizar gráficos ---
            function updateChart(chart, label, data) {
                chart.data.labels.push(label);
                chart.data.datasets[0].data.push(data);
                if (chart.data.labels.length > MAX_DATA_POINTS) {
                    chart.data.labels.shift();
                    chart.data.datasets[0].data.shift();
                }
                chart.update();
            }

            // ======================================================
            // ==== LISTENERS DO SOCKET.IO ====
            // ======================================================

            // 1. Ouve por dados de TELEMETRIA
            socket.on('atualiza_telemetria', (data) => {
                let dados = data.valor;

                if (dados) {
                    const timestamp = new Date(); // Gera o timestamp na chegada
                    
                    // Atualiza os 4 KPIs de telemetria
                    $('#val-temp').text(dados.temperatura ? dados.temperatura.toFixed(1) : '--');
                    $('#val-hum').text(dados.umidade ? dados.umidade.toFixed(1) : '--');
                    
                    // ---- LÓGICA DA LUMINOSIDADE EM % ----
                    if (dados.luminosidade !== undefined) {
                        // Converte 0-4095 (invertido) para 0-100%
                        let lum_raw = dados.luminosidade;
                        // Clamp: Garante que o valor esteja entre 0 e 4095
                        if (lum_raw < 0) lum_raw = 0;
                        if (lum_raw > 4095) lum_raw = 4095;
                        
                        let lum_percent = ((4095 - lum_raw) / 4095) * 100;
                        
                        $('#val-lum').text(lum_percent.toFixed(0)); // Mostra 0-100%
                        updateChart(lumChart, timestamp, lum_percent); // Envia % para o gráfico
                    } else {
                        $('#val-lum').text('--');
                    }
                    // ---- FIM DA LÓGICA ----
                    
                    $('#val-dist').text(dados.distancia !== undefined ? dados.distancia : '--');
                    
                    $('#val-ts').text(timestamp.toLocaleString('pt-BR'));

                    // ---- LÓGICA DO CARD DA LÂMPADA ----
                    $('#val-lamp').text(dados.lamp_status ? dados.lamp_status : '--');
                    // Muda a cor do card da lâmpada para feedback visual
                    if (dados.lamp_status === "Ligada") {
                        $('#lamp-card').css('background-color', '#fff8e1'); // Amarelo claro
                    } else { // Desligada, --, N/A
                        $('#lamp-card').css('background-color', '#fff'); // Branco
                    }
                    // ---- FIM DA LÓGICA ----

                    // Atualiza os 2 gráficos restantes
                    if(dados.temperatura) updateChart(tempChart, timestamp, dados.temperatura);
                    if(dados.umidade) updateChart(humChart, timestamp, dados.umidade);
                }
            });

            // 2. Ouve por dados de STATUS
            socket.on('atualiza_status', (data) => {
                $('#val-status').text(data.valor);
            });

            // 3. Ouve por dados de ALERTA
            socket.on('novo_alerta', (data) => {
                $('#val-alerta').text(data.valor);
                
                // Efeito visual para destacar o novo alerta
                $("#alert-card-wrapper").css("opacity", 0.5).animate({ opacity: 1.0 }, 500);
            });
        });
    </script>
</body>
</html>
    """)

if __name__ == "__main__":
    print("[Flask] Iniciando servidor web com SocketIO...")
    # host='0.0.0.0' permite que você acesse o dashboard de outro dispositivo na sua rede
    # (ex: seu celular, acessando o IP do seu computador, ex: http://192.168.1.10:5000)
    socketio.run(app, debug=True, host='0.0.0.0', port=5000, allow_unsafe_werkzeug=True)