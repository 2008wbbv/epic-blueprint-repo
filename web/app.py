from flask import Flask, render_template
import paho.mqtt.client as mqtt
import threading
import queue
from flask import Response, stream_with_context

app = Flask(__name__)

# MQTT configuration (should match hardware/config.h)
MQTT_BROKER = "test.mosquitto.org"
MQTT_PORT = 1883
MQTT_TOPIC = "epic-blueprint/sensor/distance"
MQTT_TOPIC_SPEED = "epic-blueprint/sensor/speed"

# store the most recent speed (m/s)
latest_speed = None

# simple list of queues for server‑sent events subscribers
_sse_subscribers = []


# MQTT callbacks
def on_connect(client, userdata, flags, rc):
    # only need speed topic now (published per step)
    client.subscribe(MQTT_TOPIC_SPEED)

def on_message(client, userdata, msg):
    global latest_speed
    try:
        value = float(msg.payload.decode())
    except ValueError:
        return

    latest_speed = value

    # push to all SSE subscribers
    payload = str(latest_speed)
    for q in list(_sse_subscribers):
        q.put(payload)

# set up client and start background loop
mqtt_client = mqtt.Client()
mqtt_client.on_connect = on_connect
mqtt_client.on_message = on_message
mqtt_client.connect(MQTT_BROKER, MQTT_PORT, 60)
threading.Thread(target=mqtt_client.loop_forever, daemon=True).start()

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/api/distance')
def get_distance():
    """Return the most recent speed (m/s) as JSON."""
    return {"speed": latest_speed}


@app.route('/stream')
def stream():
    """Server‑sent events stream of distance updates."""
    def event_stream():
        q = queue.Queue()
        _sse_subscribers.append(q)
        try:
            while True:
                data = q.get()
                yield f"data: {data}\n\n"
        except GeneratorExit:
            _sse_subscribers.remove(q)
    headers = {"Content-Type": "text/event-stream", "Cache-Control": "no-cache"}
    return Response(stream_with_context(event_stream()), headers=headers)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)