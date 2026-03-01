#include "config.h"
#include <WiFiS3.h>
#include <PubSubClient.h>

WiFiClient wifiClient;
PubSubClient mqtt(wifiClient);

#define CAL_BUTTON 2

#define LED_GREEN 9
#define LED_YELLOW 10
#define LED_RED 11

#define ULTRASONIC_TRIG 5
#define ULTRASONIC_ECHO 6

#define AVG_WINDOW 5

float land_threshold;
volatile bool cal_requested = false;
float readings[AVG_WINDOW];
int read_index = 0;
bool buffer_full = false;

void cal_isr() {
    cal_requested = true;
}

void setup() {
    pinMode(CAL_BUTTON, INPUT_PULLUP);
    pinMode(LED_GREEN, OUTPUT);
    pinMode(LED_YELLOW, OUTPUT);
    pinMode(LED_RED, OUTPUT);

    pinMode(ULTRASONIC_TRIG, OUTPUT);
    pinMode(ULTRASONIC_ECHO, INPUT);

    attachInterrupt(digitalPinToInterrupt(CAL_BUTTON), cal_isr, FALLING);

    Serial.begin(115200);

    Serial.print("Connecting wifi");
    WiFi.begin(WIFI_SSID, WIFI_PASS);
    while (WiFi.status() != WL_CONNECTED) {
        delay(500);
        Serial.print(".");
    }
    Serial.println("\nConnected! IP:");
    Serial.println(WiFi.localIP());

    mqtt.setServer(MQTT_BROKER, MQTT_PORT);
    mqtt_reconnect();
}

void loop() {
    if (cal_requested) {
        cal_requested = false;
        calibrate();
        Serial.print("Calibrated – threshold: ");
        Serial.println(land_threshold);
    }

    float raw = get_distance() - land_threshold;
    readings[read_index] = raw;
    read_index = (read_index + 1) % AVG_WINDOW;
    if (!buffer_full && read_index == 0) buffer_full = true;

    int count = buffer_full ? AVG_WINDOW : read_index;
    float sum = 0;
    for (int i = 0; i < count; i++) sum += readings[i];
    float distance = sum / count;

    Serial.println("New distance: " + String(distance));

    if (!mqtt.connected()) mqtt_reconnect();
    mqtt.loop();

    String payload = String(distance);
    mqtt.publish(MQTT_TOPIC, payload.c_str());

    delay(200);
}

///
void calibrate() {
    land_threshold = get_distance();
}
float get_distance() {
    digitalWrite(ULTRASONIC_TRIG, LOW);
    delay(2); 
    digitalWrite(ULTRASONIC_TRIG, HIGH);
    delay(10);
    digitalWrite(ULTRASONIC_TRIG, LOW);

    long timing = pulseIn(ULTRASONIC_ECHO, HIGH);
    float distance = (timing * 0.034) / 2;
    return distance;
}

void mqtt_reconnect() {
    while (!mqtt.connected()) {
        Serial.print("Connecting to MQTT...");
        if (mqtt.connect("arduino-sensor")) {
            Serial.println(" connected");
        } else {
            Serial.print(" failed, rc=");
            Serial.print(mqtt.state());
            Serial.println(" retrying in 2s");
            delay(2000);
        }
    }
}