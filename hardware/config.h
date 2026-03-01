#define WIFI_SSID "A14 Hotspot"
#define WIFI_PASS "testyt1234"

#define MQTT_BROKER "test.mosquitto.org"
#define MQTT_PORT 1883
#define MQTT_TOPIC "epic-blueprint/sensor/distance"
#define MQTT_TOPIC_SPEED "epic-blueprint/sensor/speed"

#define DEADBAND_CM 4.0
#define STRIDE_LENGTH_M 0.78   // average stride length in metres

// Speed thresholds for LEDs (m/s) — match the train speeds in the dashboard
#define SPEED_GREEN  1   // Green Line (13 km/h)
#define SPEED_YELLOW 0.7    // Red Line   (32 km/h)
#define SPEED_RED    0.3   // Orange Line (38 km/h)