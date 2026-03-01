from flask import Flask, render_template, request
import paho.mqtt.client as mqtt
import threading
import queue
from flask import Response, stream_with_context

app = Flask(__name__)

# MQTT configuration (should match hardware/config.h)
MQTT_BROKER = "test.mosquitto.org"
MQTT_PORT = 1883
MQTT_TOPIC = "sensor/distance"
MQTT_TOPIC_SPEED = "sensor/speed"

# store the most recent reading
latest_distance = None
# latest speed as published by the hardware (m/s)
latest_speed = None
# computed speed (m/s) based on distance differences; used when
# the hardware does not supply a speed topic.
computed_speed = None

# keep previous distance/time for computing computed_speed
_last_dist = None
_last_time = None

# simple list of queues for server‑sent events subscribers
_sse_subscribers = []


# MQTT callbacks
def on_connect(client, userdata, flags, rc):
    # subscribe to both topics
    client.subscribe([(MQTT_TOPIC, 0), (MQTT_TOPIC_SPEED, 0)])

def on_message(client, userdata, msg):
    global latest_distance, latest_speed, computed_speed, _last_dist, _last_time
    topic = msg.topic
    payload = msg.payload.decode()
    try:
        value = float(payload)
    except ValueError:
        return

    if topic == MQTT_TOPIC:
        # distance update; compute speed from previous measurement if
        # the hardware isn't supplying one.
        import time
        now = time.time()
        if latest_distance is not None and _last_time is not None:
            dt = now - _last_time
            if dt > 0:
                computed_speed = (value - latest_distance) / dt
        latest_distance = value
        _last_time = now
    elif topic == MQTT_TOPIC_SPEED:
        latest_speed = value
    # choose which speed to send: prefer hardware speed if available
    speed_to_send = latest_speed if latest_speed is not None else computed_speed
    combo = f"{latest_distance},{speed_to_send if speed_to_send is not None else ''}"
    for q in list(_sse_subscribers):
        q.put(combo)

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

@app.route('/api/distance')
def get_distance():
    """Return the most recent reading and speed as JSON.

    If the hardware speed topic hasn't arrived yet the value here is
    computed from consecutive distance measurements, replicating the
    behaviour of the earlier version of the application.
    """
    speed = latest_speed if latest_speed is not None else computed_speed
    return {"distance": latest_distance, "speed": speed}


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


@app.route('/api/raw', methods=['POST'])
def raw_data():
    data = request.get_json()
    print(f"Distance received: {data}")
    return {"status": "ok"}

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)