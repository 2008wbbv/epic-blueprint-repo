from flask import Flask, render_template
import paho.mqtt.client as mqtt
import threading
import requests
import queue
from flask import Response, stream_with_context
from datetime import datetime

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
    client.subscribe(MQTT_TOPIC_SPEED)

def on_message(client, userdata, msg):
    global latest_speed
    try:
        value = float(msg.payload.decode())
    except ValueError:
        return

    latest_speed = value

    payload = str(latest_speed)
    for q in list(_sse_subscribers):
        q.put(payload)

# set up client and start background loop
mqtt_client = mqtt.Client()
mqtt_client.on_connect = on_connect
mqtt_client.on_message = on_message
mqtt_client.connect(MQTT_BROKER, MQTT_PORT, 60)
threading.Thread(target=mqtt_client.loop_forever, daemon=True).start()


# ─────────────────────────────────────────────────────────────────
#  Route configs: each entry defines a MBTA segment to measure
#  distance_m  = straight-line distance between the two stops
# ─────────────────────────────────────────────────────────────────
ROUTES = {
    "green": {
        "label": "Green Line (Boylston → Park St)",
        "start_url": "https://api-v3.mbta.com/predictions?filter[stop]=place-boyls&filter[route]=Green-B,Green-C,Green-D,Green-E&sort=departure_time&filter[direction_id]=1",
        "end_url":   "https://api-v3.mbta.com/predictions?filter[stop]=place-pktrm&filter[route]=Green-B,Green-C,Green-D,Green-E&sort=arrival_time&filter[direction_id]=1",
        "distance_m": 274,
    },
    "red": {
        "label": "Red Line (Park St → Downtown Crossing)",
        "start_url": "https://api-v3.mbta.com/predictions?filter[stop]=place-pktrm&filter[route]=Red&sort=departure_time&filter[direction_id]=0",
        "end_url":   "https://api-v3.mbta.com/predictions?filter[stop]=place-dwnxg&filter[route]=Red&sort=arrival_time&filter[direction_id]=0",
        "distance_m": 370,
    },
    "orange": {
        "label": "Orange Line (State → Downtown Crossing)",
        "start_url": "https://api-v3.mbta.com/predictions?filter[stop]=place-state&filter[route]=Orange&sort=departure_time&filter[direction_id]=0",
        "end_url":   "https://api-v3.mbta.com/predictions?filter[stop]=place-dwnxg&filter[route]=Orange&sort=arrival_time&filter[direction_id]=0",
        "distance_m": 400,
    },
}

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
}


def fetch_segment_speed(route_key: str) -> dict:
    """
    Fetch live MBTA predictions for one route segment and return
    the calculated speed in m/s plus metadata.

    Returns a dict with keys:
        status          "success" | "error"
        route           route_key
        label           human-readable route label
        train_id        MBTA trip ID (str)
        travel_time_s   integer seconds between dep and arr
        speed_ms        float m/s
        speed_kmh       float km/h
        error           error message (only when status == "error")
    """
    cfg = ROUTES[route_key]
    result = {
        "status": "error",
        "route": route_key,
        "label": cfg["label"],
        "train_id": None,
        "travel_time_s": None,
        "speed_ms": None,
        "speed_kmh": None,
    }

    try:
        start_resp = requests.get(cfg["start_url"], headers=HEADERS, timeout=8)
        end_resp   = requests.get(cfg["end_url"],   headers=HEADERS, timeout=8)

        if start_resp.status_code != 200:
            result["error"] = f"Start stop API returned {start_resp.status_code}"
            return result
        if end_resp.status_code != 200:
            result["error"] = f"End stop API returned {end_resp.status_code}"
            return result

        depart_data = start_resp.json().get("data", [])
        arrive_data = end_resp.json().get("data", [])

        if not depart_data:
            result["error"] = "No departure predictions found"
            return result

        # Take the soonest departing train
        first = depart_data[0]
        train_id = (
            first.get("relationships", {})
                 .get("trip", {})
                 .get("data", {})
                 .get("id")
        )
        dep_time = first.get("attributes", {}).get("departure_time")

        if not train_id or not dep_time:
            result["error"] = "Missing trip ID or departure time in prediction"
            return result

        print(f"[{route_key}] Train {train_id} departs at {dep_time}")

        # Find the matching arrival at the end stop
        arr_time = None
        for prediction in arrive_data:
            pid = (
                prediction.get("relationships", {})
                           .get("trip", {})
                           .get("data", {})
                           .get("id")
            )
            if pid == train_id:
                arr_time = prediction.get("attributes", {}).get("arrival_time")
                print(f"[{route_key}] Train {train_id} arrives at {arr_time}")
                break

        if not arr_time:
            result["error"] = f"No matching arrival prediction found for train {train_id}"
            return result

        dep_dt = datetime.fromisoformat(dep_time)
        arr_dt = datetime.fromisoformat(arr_time)
        travel_time_s = int((arr_dt - dep_dt).total_seconds())

        if travel_time_s <= 0:
            result["error"] = f"Invalid travel time ({travel_time_s}s) — arrival before departure?"
            return result

        speed_ms  = cfg["distance_m"] / travel_time_s
        speed_kmh = speed_ms * 3.6

        result.update({
            "status":        "success",
            "train_id":      train_id,
            "travel_time_s": travel_time_s,
            "speed_ms":      round(speed_ms,  4),
            "speed_kmh":     round(speed_kmh, 3),
        })
        print(f"[{route_key}] speed={speed_ms:.3f} m/s  ({speed_kmh:.2f} km/h)")

    except Exception as exc:
        result["error"] = str(exc)

    return result


def get_all_mbta_train_info() -> dict:
    """
    Fetch live speeds for Green, Red, and Orange lines in parallel.
    Returns a dict keyed by route ("green", "red", "orange").
    """
    results = {}
    threads = []

    def worker(key):
        results[key] = fetch_segment_speed(key)

    for key in ROUTES:
        t = threading.Thread(target=worker, args=(key,))
        t.start()
        threads.append(t)

    for t in threads:
        t.join()

    return results


# ─────────────────────────────────────────────────────────────────
#  Flask routes
# ─────────────────────────────────────────────────────────────────

@app.route('/')
def index():
    return render_template('index.html')


@app.route('/api/distance')
def get_distance():
    """Return the most recent sensor speed (m/s) as JSON."""
    return {"speed": latest_speed}


@app.route('/stream')
def stream():
    """Server‑sent events stream of speed updates."""
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


@app.route('/api/train')
def train_schedule():
    """
    Return live MBTA speeds for all three lines.

    Response shape:
    {
      "green":  { "status": "success", "speed_ms": 3.61, "speed_kmh": 13.0, ... },
      "red":    { "status": "success", "speed_ms": 8.89, "speed_kmh": 32.0, ... },
      "orange": { "status": "success", "speed_ms": 10.6, "speed_kmh": 38.1, ... }
    }
    """
    return get_all_mbta_train_info()


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
