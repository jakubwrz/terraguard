/**
 * TerraGuard Rover - Seeed Studio XIAO ESP32S3 Sense Camera Streamer
 * 
 * Target Board: Seeed Studio XIAO ESP32S3
 * Settings in Arduino IDE:
 *  - Board: "XIAO_ESP32S3"
 *  - PSRAM: "OPI PSRAM"  (CRITICAL: Must be enabled for camera!)
 *  - Flash Size: "8MB (64Mb)"
 * 
 * Endpoints Provided:
 *  - http://<CAMERA_IP>/stream   -> Live MJPEG Video Stream (Used by Rover Vision)
 *  - http://<CAMERA_IP>/capture  -> Single High-Res JPEG Frame Snapshot
 *  - http://<CAMERA_IP>/         -> Web Browser Live Video Dashboard
 */

#include "esp_camera.h"
#include <WiFi.h>
#include "esp_http_server.h"

// =========================================================================
// 1. STANDALONE CAMERA ACCESS POINT (AP) SETTINGS
// =========================================================================
const char* ap_ssid     = "TerraGuard_Camera";
const char* ap_password = "terraguardcamera"; // Minimum 8 characters for WPA2

// =========================================================================
// 2. PIN DEFINITIONS FOR SEEED XIAO ESP32S3 SENSE
// =========================================================================
#ifndef LED_BUILTIN
#define LED_BUILTIN 21 // Onboard Orange User LED on XIAO ESP32S3
#endif

#define PWDN_GPIO_NUM  -1
#define RESET_GPIO_NUM -1
#define XCLK_GPIO_NUM  10
#define SIOD_GPIO_NUM  40
#define SIOC_GPIO_NUM  39

#define Y9_GPIO_NUM    48
#define Y8_GPIO_NUM    11
#define Y7_GPIO_NUM    12
#define Y6_GPIO_NUM    14
#define Y5_GPIO_NUM    16
#define Y4_GPIO_NUM    18
#define Y3_GPIO_NUM    17
#define Y2_GPIO_NUM    15
#define VSYNC_GPIO_NUM 38
#define HREF_GPIO_NUM  47
#define PCLK_GPIO_NUM  13

httpd_handle_t camera_httpd = NULL;

#define PART_BOUNDARY "123456789000000000000987654321"
static const char* _STREAM_CONTENT_TYPE = "multipart/x-mixed-replace;boundary=" PART_BOUNDARY;
static const char* _STREAM_BOUNDARY = "\r\n--" PART_BOUNDARY "\r\n";
static const char* _STREAM_PART = "Content-Type: image/jpeg\r\nContent-Length: %u\r\n\r\n";

// --- HANDLER: MJPEG VIDEO STREAM (/stream) ---
static esp_err_t stream_handler(httpd_req_t *req) {
    camera_fb_t * fb = NULL;
    esp_err_t res = ESP_OK;
    size_t _jpg_buf_len = 0;
    uint8_t * _jpg_buf = NULL;
    char * part_buf[64];

    res = httpd_resp_set_type(req, _STREAM_CONTENT_TYPE);
    if (res != ESP_OK) {
        return res;
    }
    httpd_resp_set_hdr(req, "Access-Control-Allow-Origin", "*");

    while (true) {
        fb = esp_camera_fb_get();
        if (!fb) {
            Serial.println("Camera capture failed");
            res = ESP_FAIL;
        } else {
            if (fb->format != PIXFORMAT_JPEG) {
                bool jpeg_converted = frame2jpg(fb, 80, &_jpg_buf, &_jpg_buf_len);
                esp_camera_fb_return(fb);
                fb = NULL;
                if (!jpeg_converted) {
                    Serial.println("JPEG compression failed");
                    res = ESP_FAIL;
                }
            } else {
                _jpg_buf_len = fb->len;
                _jpg_buf = fb->buf;
            }
        }
        if (res == ESP_OK) {
            size_t hlen = snprintf((char *)part_buf, 64, _STREAM_PART, _jpg_buf_len);
            res = httpd_resp_send_chunk(req, (const char *)part_buf, hlen);
        }
        if (res == ESP_OK) {
            res = httpd_resp_send_chunk(req, (const char *)_jpg_buf, _jpg_buf_len);
        }
        if (res == ESP_OK) {
            res = httpd_resp_send_chunk(req, _STREAM_BOUNDARY, strlen(_STREAM_BOUNDARY));
        }
        if (fb) {
            esp_camera_fb_return(fb);
            fb = NULL;
            _jpg_buf = NULL;
        } else if (_jpg_buf) {
            free(_jpg_buf);
            _jpg_buf = NULL;
        }
        if (res != ESP_OK) {
            break;
        }
    }
    return res;
}

// --- HANDLER: STILL IMAGE CAPTURE (/capture) ---
static esp_err_t capture_handler(httpd_req_t *req) {
    camera_fb_t * fb = NULL;
    esp_err_t res = ESP_OK;

    fb = esp_camera_fb_get();
    if (!fb) {
        Serial.println("Camera capture failed");
        httpd_resp_send_500(req);
        return ESP_FAIL;
    }

    httpd_resp_set_type(req, "image/jpeg");
    httpd_resp_set_hdr(req, "Content-Disposition", "inline; filename=capture.jpg");
    httpd_resp_set_hdr(req, "Access-Control-Allow-Origin", "*");

    res = httpd_resp_send(req, (const char *)fb->buf, fb->len);
    esp_camera_fb_return(fb);
    return res;
}

// --- HANDLER: WEB BROWSER LIVE DASHBOARD (/) ---
static esp_err_t index_handler(httpd_req_t *req) {
    const char index_html[] = 
        "<!DOCTYPE html><html><head><meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">"
        "<title>TerraGuard Xiao Camera</title>"
        "<style>body{background:#0b0f19;color:#e2e8f0;font-family:sans-serif;text-align:center;margin:0;padding:20px;}"
        "h2{color:#6366f1;margin-bottom:10px;}img{max-width:90%;border-radius:12px;border:2px solid #312e81;box-shadow:0 10px 25px rgba(0,0,0,0.5);}"
        ".badge{background:#1e1b4b;padding:8px 16px;border-radius:20px;display:inline-block;margin-top:15px;font-size:14px;color:#a5b4fc;}"
        "</style></head><body>"
        "<h2>🌱 TerraGuard Rover Vision</h2>"
        "<p>Seeed Studio XIAO ESP32S3 Sense Direct AP Stream</p>"
        "<img src=\"/stream\" />"
        "<br><div class=\"badge\">Direct AP Active at <code>http://192.168.4.1/stream</code></div>"
        "</body></html>";

    httpd_resp_set_type(req, "text/html");
    return httpd_resp_send(req, index_html, HTTPD_RESP_USE_STRLEN);
}

// --- START HTTP CAMERA SERVER ---
void startCameraServer() {
    httpd_config_t config = HTTPD_DEFAULT_CONFIG();
    config.server_port = 80;

    httpd_uri_t index_uri = {
        .uri       = "/",
        .method    = HTTP_GET,
        .handler   = index_handler,
        .user_ctx  = NULL
    };

    httpd_uri_t stream_uri = {
        .uri       = "/stream",
        .method    = HTTP_GET,
        .handler   = stream_handler,
        .user_ctx  = NULL
    };

    httpd_uri_t capture_uri = {
        .uri       = "/capture",
        .method    = HTTP_GET,
        .handler   = capture_handler,
        .user_ctx  = NULL
    };

    if (httpd_start(&camera_httpd, &config) == ESP_OK) {
        httpd_register_uri_handler(camera_httpd, &index_uri);
        httpd_register_uri_handler(camera_httpd, &stream_uri);
        httpd_register_uri_handler(camera_httpd, &capture_uri);
        Serial.println("Camera HTTP Server started on port 80");
    }
}

void setup() {
    // 0. Initialize Onboard Power/Status LED
    pinMode(LED_BUILTIN, OUTPUT);
    digitalWrite(LED_BUILTIN, LOW); // LOW = ON on XIAO ESP32S3 (Lights up immediately on boot!)

    Serial.begin(115200);
    delay(1000);
    Serial.println("\n==============================================");
    Serial.println("   TerraGuard - Seeed XIAO ESP32S3 Camera AP  ");
    Serial.println("==============================================");

    // 1. Configure Camera Hardware
    camera_config_t config;
    config.ledc_channel = LEDC_CHANNEL_0;
    config.ledc_timer = LEDC_TIMER_0;
    config.pin_d0 = Y2_GPIO_NUM;
    config.pin_d1 = Y3_GPIO_NUM;
    config.pin_d2 = Y4_GPIO_NUM;
    config.pin_d3 = Y5_GPIO_NUM;
    config.pin_d4 = Y6_GPIO_NUM;
    config.pin_d5 = Y7_GPIO_NUM;
    config.pin_d6 = Y8_GPIO_NUM;
    config.pin_d7 = Y9_GPIO_NUM;
    config.pin_xclk = XCLK_GPIO_NUM;
    config.pin_pclk = PCLK_GPIO_NUM;
    config.pin_vsync = VSYNC_GPIO_NUM;
    config.pin_href = HREF_GPIO_NUM;
    config.pin_sccb_sda = SIOD_GPIO_NUM;
    config.pin_sccb_scl = SIOC_GPIO_NUM;
    config.pin_pwdn = PWDN_GPIO_NUM;
    config.pin_reset = RESET_GPIO_NUM;
    config.xclk_freq_hz = 20000000;
    config.frame_size = FRAMESIZE_VGA;      // 640x480 resolution
    config.pixel_format = PIXFORMAT_JPEG;   // Direct JPEG output
    config.grab_mode = CAMERA_GRAB_WHEN_EMPTY;
    config.fb_location = CAMERA_FB_IN_PSRAM;
    config.jpeg_quality = 12;               // 10-63: Lower number means higher quality
    config.fb_count = 2;                    // Double buffering for smooth framerate

    // Check if PSRAM is available
    if (psramFound()) {
        config.jpeg_quality = 10;
        config.fb_count = 2;
        config.grab_mode = CAMERA_GRAB_LATEST;
        Serial.println("PSRAM detected: Running in high-performance mode.");
    } else {
        config.frame_size = FRAMESIZE_QVGA;
        config.fb_location = CAMERA_FB_IN_DRAM;
        Serial.println("Warning: PSRAM NOT detected. Lowering resolution.");
    }

    // Initialize Camera Sensor
    esp_err_t err = esp_camera_init(&config);
    if (err != ESP_OK) {
        Serial.printf("Camera initialization failed with error 0x%x\n", err);
        return;
    }
    Serial.println("Camera sensor initialized successfully!");

    // Flip & Mirror sensor 180° for upright camera mounting
    sensor_t * s = esp_camera_sensor_get();
    if (s != NULL) {
        s->set_vflip(s, 1);   // 1 = Flip vertical
        s->set_hmirror(s, 1); // 1 = Mirror horizontal (upright)
    }

    // 2. Start Standalone Access Point (AP) Mode
    Serial.printf("Starting Access Point: %s ...\n", ap_ssid);
    WiFi.mode(WIFI_AP);
    bool ap_started = WiFi.softAP(ap_ssid, ap_password);

    if (ap_started) {
        IPAddress ap_ip = WiFi.softAPIP();
        digitalWrite(LED_BUILTIN, LOW); // Solid ON when AP is active!
        Serial.println("==============================================");
        Serial.printf("Access Point Started! SSID: %s\n", ap_ssid);
        Serial.print("Camera IP Address: http://");
        Serial.println(ap_ip);
        Serial.print("Live Stream URL:   http://");
        Serial.print(ap_ip);
        Serial.println("/stream");
        Serial.print("Snapshot URL:      http://");
        Serial.print(ap_ip);
        Serial.println("/capture");
        Serial.println("==============================================");

        // 3. Start Camera Web Server
        startCameraServer();
    } else {
        digitalWrite(LED_BUILTIN, HIGH);
        Serial.println("Failed to start Access Point!");
    }
}

void loop() {
    delay(10000); // Server runs asynchronously in background tasks
}
