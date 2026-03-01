from flask import Flask, render_template, request
import paho.mqtt.client as mqtt
import threading

app = Flask(__name__)

# MQTT configuration (should match hardware/config.h)
MQTT_BROKER = "10.29.153.191"
MQTT_PORT = 1883
MQTT_TOPIC = "sensor/distance"

# store the most recent reading
latest_distance = None

# MQTT callbacks
def on_connect(client, userdata, flags, rc):
    client.subscribe(MQTT_TOPIC)

def on_message(client, userdata, msg):
    global latest_distance
    try:
        latest_distance = float(msg.payload.decode())
    except ValueError:
        pass

# set up client and start background loop
mqtt_client = mqtt.Client()
mqtt_client.on_connect = on_connect
mqtt_client.on_message = on_message
mqtt_client.connect(MQTT_BROKER, MQTT_PORT, 60)
threading.Thread(target=mqtt_client.loop_forever, daemon=True).start()

@app.route('/')
def index():
    # pass the latest MQTT value to the template
    return render_template('index.html', distance=latest_distance)

@app.route('/api/raw', methods=['POST'])
def raw_data():
    data = request.get_json()
    print(f"Distance received: {data}")
    return {"status": "ok"}

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)