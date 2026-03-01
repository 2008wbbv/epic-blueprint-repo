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

// Step detection state
bool in_step = false;              // true while distance is within deadband (foot down)
unsigned long last_step_time = 0;  // millis() of the previous step
unsigned long prev_step_time = 0;  // millis() of the step before that
float step_speed = 0;              // speed derived from cadence (steps/min)
unsigned long step_count = 0;

#define SPEED_AVG_WINDOW 5
float speed_readings[SPEED_AVG_WINDOW];
int speed_index = 0;
bool speed_buffer_full = false;
float avg_speed = 0;

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

/*     float raw = get_distance() - land_threshold;
    readings[read_index] = raw;
    read_index = (read_index + 1) % AVG_WINDOW;
    if (!buffer_full && read_index == 0) buffer_full = true;

    int count = buffer_full ? AVG_WINDOW : read_index;
    float sum = 0;
    for (int i = 0; i < count; i++) sum += readings[i];
    float distance = sum / count; */
    float distance = get_distance() - land_threshold;

    // Step detection: a step is when distance falls within DEADBAND_CM of 0
    bool foot_down = (abs(distance) <= DEADBAND_CM);
    //Serial.println(foot_down);
    if (foot_down && !in_step) {
        // Rising edge – new step detected
        in_step = true;
        step_count++;

        unsigned long now = millis();
        if (last_step_time > 0) {
            float interval_s = (now - last_step_time) / 1000.0;
            if (interval_s > 0) {
                float cadence = 60.0 / interval_s;       // steps per minute
                // Approximate running speed from cadence
                // Average stride ≈ 0.78 m; speed = stride × cadence / 60
                step_speed = (STRIDE_LENGTH_M * cadence) / 60.0;  // m/s

                // Update speed moving average
                speed_readings[speed_index] = step_speed;
                speed_index = (speed_index + 1) % SPEED_AVG_WINDOW;
                if (!speed_buffer_full && speed_index == 0) speed_buffer_full = true;
                int sp_count = speed_buffer_full ? SPEED_AVG_WINDOW : speed_index;
                float sp_sum = 0;
                for (int i = 0; i < sp_count; i++) sp_sum += speed_readings[i];
                avg_speed = sp_sum / sp_count;
            }
        }
        prev_step_time = last_step_time;
        last_step_time = now;

        Serial.println("Step #" + String(step_count)
                       + "  speed: " + String(step_speed) + " m/s"
                       + "  avg: " + String(avg_speed) + " m/s"
                       + "  dist: " + String(distance) + " cm");

        // publish speed only when a new step is detected
        if (!mqtt.connected()) mqtt_reconnect();
        mqtt.loop();
        String speedPayload = String(avg_speed);
        mqtt.publish(MQTT_TOPIC_SPEED, speedPayload.c_str());
    } else if (!foot_down) {
        in_step = false;
    }

    // MQTT keep-alive (no publish every cycle)
    if (!mqtt.connected()) mqtt_reconnect();
    mqtt.loop();

    delay(50);
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