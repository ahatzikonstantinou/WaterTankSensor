#include <FS.h> // for WiFiManager this needs to be first, or it all crashes and burns... Of course I have now completely removed WifiManager.
                // but I still use it to store config
#include <ESP8266WiFi.h>
#include <ESP8266mDNS.h>
#include <DNSServer.h>
#include <ArduinoOTA.h>
#include <PubSubClient.h>
#include <ESP8266WebServer.h>

#include <ArduinoJson.h>  //https://github.com/bblanchon/ArduinoJson

#define PIN_SWITCH 5 // ahat: this is GPIO5 = D1 in nodemcu v3
#define PIN_LED 13
#define PIN_FLASH 0

// uncomment the following define if ESP8266 is powered by a battery and ESP8266 is monitoring 
// the battery level. The code is from https://iotprojectsideas.com/esp8266-monitor-its-own-battery-level-using-iot/
// The battery voltage is read via a resistor divider created with two 100K resistors 
#define BATTERY

volatile bool flashButtonPressed = false;

char ssid[60] = "ahat_v";
char password[40] = "423hh[23";
char AP_ssid[60] = "ESP8266";
char AP_password[40] = "312ggp12";
bool AP_is_on = false;
bool AP_is_autostarted = false;
const int echoPin = 12; 
const int trigPin = 14;   
long duration;  
uint distance;
uint previous_distance = 0;
const uint sensor_samples_size = 15;
long sensor_samples[sensor_samples_size];
unsigned long last_mqtt_publish_time = 0;
double max_quiet_percentDiff_sensor = 0.01; // if the percent difference between distance and previous_distance 
                                        // is <= max_quiet_percentDiff_sensor don't send mqtt message
char mqtt_server[40];
char mqtt_port[6];
char publish_topic[256];
char subscribe_topic[256];
bool mqtt_publish_sensor = false; // set to true when there is a sensor measurment for publishing
#ifdef BATTERY
bool mqtt_publish_battery = false; // set to true when there is a battery measurment for publishing
#endif
char sensor_id[256];
uint max_quiet_time;

WiFiClient espClient;
PubSubClient client( espClient );

ESP8266WebServer  server(80);
// Variable to store the HTTP request
String header;
// Current time
unsigned long currentTime = millis();
// Previous time
unsigned long previousTime = 0; 
// Define timeout time in milliseconds (example: 2000ms = 2s)
const long timeoutTime = 2000;

#ifdef BATTERY
float voltage;
uint battery_percentage;
uint previous_battery_percentage = 0;
uint battery_warning_level = 30;  //if battery percentage reaches this level it must be recharged immediately
uint battery_recharge_warning = false;
double max_quiet_percentDiff_battery = 1; // if the difference between battery_percentage and previous_battery_percentage is > 1 then publish mqtt message
int analogInPin  = A0;    // Analog input pin
int adc_value;
float battery_calibration = 0.40; // Check Battery voltage using multimeter against the value reported by 
                                  // this program. Add/subtract the difference so that this program reports
                                  // the same battery voltage as the multimeter reading.
#endif

void mqttSetup();
void setupWifiSTA(const String, const String);
void startAP();
void stopAP();

void saveConfig()
{
  DynamicJsonDocument json(1024);

  json["ssid"] = ssid;
  json["password"] = password;
  json["AP_ssid"] = AP_ssid;
  json["AP_password"] = AP_password;
  json["mqtt_server"] = mqtt_server;
  json["mqtt_port"] = mqtt_port;
  json["publish_topic"] = publish_topic;
  json["subscribe_topic"] = subscribe_topic;
  json["sensor_id"] = sensor_id;
  json["max_quiet_time"] = max_quiet_time;
#ifdef BATTERY
  json["battery_warning_level"] = battery_warning_level;
  json["battery_calibration"] = battery_calibration;
#endif

  File configFile = SPIFFS.open("/config.json", "w");
  if (!configFile) {
    Serial.println("failed to open config file for writing");
  }

  serializeJson(json, Serial);
  serializeJson(json, configFile);
  configFile.close();
}

void handle_NotFound()
{
  server.send(404, "text/plain", "Not found");
}

String getWifiClients()
{
  // from https://www.esp8266.com/viewtopic.php?f=32&t=5669&start=24
  String wf_clients = "";
  struct station_info *station_list = wifi_softap_get_station_info();
  while (station_list != NULL) {
    char station_mac[18] = {0}; 
    sprintf(station_mac, "%02X:%02X:%02X:%02X:%02X:%02X", MAC2STR(station_list->bssid));
    String station_ip = IPAddress((&station_list->ip)->addr).toString();

    Serial.print(station_mac); Serial.print(" "); Serial.println(station_ip);
    wf_clients += ",{\"ip\":\"" + station_ip + "\",\"mac\":\"" + station_mac + "\"}";

    station_list = STAILQ_NEXT(station_list, next);
  }
  wifi_softap_free_station_info();
  return wf_clients.substring(1);
}

String SendHTML( bool show_stop_AP = false, bool show_start_AP = false )
{
  String ptr = "<!DOCTYPE html> <html>\n";
  ptr +="<head><meta name=\"viewport\" content=\"width=device-width, initial-scale=1.0, user-scalable=no\">\n";
  ptr +="<title>Water Tank Sensor</title>\n";
  ptr +="<style>html { font-family: Helvetica; display: inline-block; margin: 0px auto; text-align: center;}\n";
  ptr +="body{margin-top: 50px;} h1 {color: #444444;margin: 50px auto 30px;} h3 {color: #444444;margin-bottom: 50px;}\n";
  ptr +="button {display: block;background-color: #1abc9c;border: none;color: white;padding: 13px 30px;text-decoration: none;font-size: 25px;margin: 0px auto 35px;cursor: pointer;border-radius: 4px;}\n";
  ptr +=".button-on {background-color: #1abc9c;}\n";
  ptr +=".button-on:active {background-color: #16a085;}\n";
  ptr +=".button-off {background-color: #34495e;}\n";
  ptr +=".button-off:active {background-color: #2c3e50;}\n";
  ptr +="p {font-size: 14px;color: #888;margin-bottom: 10px;}\n";
  ptr +="table {border-collapse: collapse;}\n";
  ptr +="th, td {padding: 8px;text-align: left;border-bottom: 1px solid #ddd; border-top: 1px solid #ddd}\n";
  ptr +="th {text-align: right;font-weight: normal;}\n";
  ptr +="td {font-weight: bold;}\n";
  ptr +=".info {width: 100%; overflow-x: auto; overflow-y: hidden; margin-bottom: 2em;}\n";
  ptr +="</style>\n";
  ptr +="<script>\
  function Restart(){\
  var xhttp = new XMLHttpRequest();\
  xhttp.open(\"GET\", \"/restart\", true);\
  xhttp.send();\
  let timerInSeconds = 5;\
  let button = document.querySelector('#restart');\
  button.disabled = true;\
  button.className = \"button button-off\";\
  var timerId = setInterval(() => {\
  timerInSeconds -= 1;\
  var button = document.querySelector('#restart');\
  button.innerText = button.textContent = `Reloading in ${timerInSeconds} seconds`;\
  if (timerInSeconds == 0) {\
    clearInterval(timerId);\
    window.location.reload();\
  }\
  }, 1000);\
  }\n\
  function start_AP(){\
  window.location = \"/start_AP\";\
  }\
  function stop_AP(){\
  window.location = \"/stop_AP\";\
  }\
  \n";

  ptr +="</script>\n";
  ptr +="</head>\n";
  ptr +="<body>\n";
  ptr +="<h1>Water Tank Sensor</h1>\n";
  if(show_stop_AP)
  {
    ptr +="<p>Access Point Stopped</p>";
  }
  else if(show_start_AP)
  {
    ptr += String("<p>Access Point ") + String(AP_ssid) + " is started</p>";
  }
  ptr +="<div class=\"info\">\n";
  ptr +="<hr>\n";
  ptr +="<h2>Status</h2>\n";
  ptr +="<table>\n";
  ptr +="<tr><th>sensor_id:</th>\n";
  ptr +="<td>" + String(sensor_id) + "</td></tr>\n";
  ptr +="<tr><th>measurement:</th>\n";
  ptr +="<td>" + String(distance) + "</td></tr>\n";
  ptr +="<tr><th>ip:</th>\n";
  ptr +="<td>" + WiFi.localIP().toString() + "</td></tr>\n";
  ptr +="<tr><th>battery_percentage:</th>\n";
  ptr +="<td>" + String(battery_percentage) + "</td></tr>\n";
  ptr +="<tr><th>battery_voltage:</th>\n";
  ptr +="<td>" + String(voltage) + "</td></tr>\n";
  ptr +="<tr><th>adc_value:</th>\n";
  ptr +="<td>" + String(adc_value) + "</td></tr>\n";
  ptr +="<tr><th>wifi clients:</th>\n";
  ptr +="<td>" + getWifiClients() + "</td></tr>\n";
  ptr +="</table>\n";
  ptr +="</div>\n";
  ptr +="<hr>\n";
  ptr +="<div class=\"info\">\n";
  ptr +="<h2>Configuration</h2>\n";
  ptr +="<form action=\"/update\" method=\"POST\">\n";
  ptr +="<table>\n";
  ptr +="<tr><th>SSID:</th>\n";
  ptr +="<td><input type=\"text\" name=\"ssid\" value=\"" + String(ssid) + "\"/></td></tr>\n";
  ptr +="<tr><th>Password:</th>\n";
  ptr +="<td><input type=\"text\" name=\"password\" value=\"" + String(password) + "\"/></td></tr>\n";
  ptr +="<tr><th>AP SSID:</th>\n";
  ptr +="<td><input type=\"text\" name=\"AP_ssid\" type=\"number\" value=\"" + String(AP_ssid) + "\"/></td></tr>\n";
  ptr +="<tr><th>AP Password:</th>\n";
  ptr +="<td><input type=\"text\" name=\"AP_password\" type=\"number\" value=\"" + String(AP_password) + "\"/></td></tr>\n";
  ptr +="<tr><th>mqtt_server:</th>\n";
  ptr +="<td><input type=\"text\" name=\"mqtt_server\" value=\"" + String(mqtt_server) + "\"/></td></tr>\n";
  ptr +="<tr><th>mqtt_port:</th>\n";
  ptr +="<td><input type=\"text\" name=\"mqtt_port\" type=\"number\" value=\"" + String(mqtt_port) + "\"/></td></tr>\n";
  ptr +="<tr><th>publish_topic:</th>\n";
  ptr +="<td><input type=\"text\" name=\"publish_topic\" value=\"" + String(publish_topic) + "\"/></td></tr>\n";
  ptr +="<tr><th>subscribe_topic:</th>\n";
  ptr +="<td><input type=\"text\" name=\"subscribe_topic\" value=\"" + String(subscribe_topic) + "\"/></td></tr>\n";
  ptr +="<tr><th>sensor_id:</th>\n";
  ptr +="<td><input type=\"text\" name=\"sensor_id\" value=\"" + String(sensor_id) + "\"/></td></tr>\n";
  ptr +="<tr><th>max_quiet_time:</th>\n";
  ptr +="<td><input type=\"text\" name=\"max_quiet_time\" type=\"number\" value=\"" + String(max_quiet_time) + "\"/></td></tr>\n";
#ifdef BATTERY
  ptr +="<tr><th>battery_warning_level:</th>\n";
  ptr +="<td><input type=\"text\" name=\"battery_warning_level\" type=\"number\" value=\"" + String(battery_warning_level) + "\"/></td></tr>\n";
  ptr +="<tr><th>battery_calibration:</th>\n";
  ptr +="<td><input type=\"text\" name=\"battery_calibration\" type=\"number\" value=\"" + String(battery_calibration) + "\"/></td></tr>\n";
#endif
  ptr +="</table>\n";
  ptr +="</div>\n";
  ptr +="<button class=\"button button-on\">Submit</button>\n";
  ptr +="</form>\n";
  ptr +="<button id=\"restart\" class=\"button button-on\" onclick=\"Restart()\">Restart</button>\n";

  // I chose to have the access point always on, so this part is not used.
  // if(AP_is_on)
  // {
  //     ptr +="<button id=\"stop_AP\" class=\"button button-on\" onclick=\"stop_AP()\">Stop Access Point</button>\n";
  // }
  // else
  // {
  //     ptr +="<button id=\"start_AP\" class=\"button button-on\" onclick=\"start_AP()\">Start Access Point</button>\n";
  // }

  ptr +="</body>\n";
  ptr +="</html>\n";
  return ptr;
}

// ahat: https://techtutorialsx.com/2017/12/29/esp8266-arduino-software-restart/
// resetting with ESP.reset() leaves registers with old values, retarting is recommended
void handle_OnRestart()
{
  server.send(200, "text/html", SendHTML()); 
  Serial.println("Restarting ESP8266");
  ESP.restart();
}

void handle_OnStartAP()
{
    Serial.println("Starting Access Point");
    startAP();  // this comes before server.send to set the appropriate flags
    server.send(200, "text/html", SendHTML(false, true));
}

// I chose to have the access point always on, so this function is not used.
void handle_OnStopAP()
{
    Serial.println("Stopping Access Point");
    stopAP();  // this comes before server.send to set the appropriate flags
    server.send(200, "text/html", SendHTML(true, false));
}

void handle_Form() {
  String new_ssid = server.arg("ssid");
  String new_password = server.arg("password");
  strncpy(AP_ssid, server.arg("AP_ssid").c_str(), 60);
  strncpy(AP_password, server.arg("AP_password").c_str(), 40);
  strncpy(mqtt_server, server.arg("mqtt_server").c_str(), 40);
  strncpy(mqtt_port, server.arg("mqtt_port").c_str(), 6);
  strncpy(publish_topic, server.arg("publish_topic").c_str(), 256);
  strncpy(subscribe_topic, server.arg("subscribe_topic").c_str(), 256);
  strncpy(sensor_id, server.arg("sensor_id").c_str(), 256);
  max_quiet_time = server.arg("max_quiet_time").toInt();
#ifdef BATTERY
  battery_warning_level = server.arg("battery_warning_level").toInt();
  battery_calibration = server.arg("battery_calibration").toFloat();
#endif

  Serial.println("saving config: ");
  saveConfig();
  server.send(200, "text/html", SendHTML());

  if( new_ssid != String(ssid) || new_password != String(password) )
  {
    WiFi.disconnect();
    setupWifiSTA(new_ssid, new_password);
    if (WiFi.status() == WL_CONNECTED)
    {
      strncpy(ssid, new_ssid.c_str(), 60);
      strncpy(password, new_password.c_str(), 40);
      Serial.println("saving config again to include new ssid, password: ");
      saveConfig();

      // I chose to have the access point always on, so this part is not used.
      // if(AP_is_autostarted)
      // {
      //   AP_is_autostarted = false;
      //   stopAP();
      // }
    }    
  }

  client.disconnect();
  mqttSetup();
}

void handle_OnConnect() 
{
  Serial.println("Web Server handling connection");
  server.send(200, "text/html", SendHTML()); 
}

void webServerSetup()
{
    server.on("/", handle_OnConnect);
    server.on("/restart", handle_OnRestart);
    server.on("/update", handle_Form); 

    // I chose to have the access point always on, so this part is not used.
    // server.on("/start_AP", handle_OnStartAP); 
    // server.on("/stop_AP", handle_OnStopAP); 

    server.onNotFound(handle_NotFound);
    
    server.begin();
    Serial.println("HTTP server started");
}

void loopWebServer()
{
  server.handleClient();  
}

void mqttReconnect()
{
  // Loop until we're reconnected
  if( !client.connected() )
  {
    Serial.print( "Attempting MQTT connection..." );
    // Attempt to connect
    if( client.connect( "ESP8266 Client" ) )
    {
      Serial.println( "connected" );
      // ... and subscribe to topic
      client.subscribe( subscribe_topic );
    }
    else
    {
      Serial.print( "failed, rc=" );
      Serial.print( client.state() );
      Serial.println( " try again in 2 seconds" );
      // Wait 5 seconds before retrying
      delay( 2000 );
    }
  }
  client.loop();
}

void loopMqttConnect()
{
  if( !client.connected() )
  {
    mqttReconnect();
  }
}

void loopMqttPublish()
{
  unsigned long now = millis();

  if(mqtt_publish_sensor 
#ifdef BATTERY
  || mqtt_publish_battery
#endif
  || now - last_mqtt_publish_time > (max_quiet_time*1000)
  )
  {
    mqtt_publish_sensor = false;
#ifdef BATTERY
    mqtt_publish_battery = false;
#endif    
    if( client.connected() )
    {
      last_mqtt_publish_time = now;
      Serial.printf( "Publishing: [%s] ", publish_topic );

      String message = String( "{\"sensor_id\":\"" ) + sensor_id + 
        String("\", \"measurement\":") + distance + 
        String(", \"ip\":\"") + WiFi.localIP().toString() + "\"" +
        String(", \"wifi_cients\":[") + getWifiClients() + "]";
#ifdef BATTERY
      message += String(", \"battery_percentage\":") + battery_percentage +
        String(", \"battery_voltage\":") + voltage +
        String(", \"adc_value\":") + adc_value;
      if(battery_recharge_warning)
      {
        message += String(", \"warning\": \"Recharge battery immediately, less than ") + battery_warning_level + "% charge remaining.\"";
      }
#endif
      message += String("}");
      Serial.println(message);  

      Serial.println( message );
      client.publish( publish_topic, message.c_str() );
      client.loop();
    }
    else
    {
      Serial.println( "Cannot publish because client is not connected." );
    }
  }
}

void loopReadSensor()
{
    for( uint i = 0 ; i < sensor_samples_size ; i++ )
    {
      // from https://forum.arduino.cc/t/hc-sr04-tests-on-accuracy-precision-and-resolution-of-ultrasonic-measurement/236505/2
        digitalWrite(trigPin, LOW);  // Give a short LOW pulse beforehand to ensure a clean HIGH pulse);  
        delayMicroseconds(2);
        digitalWrite(trigPin, HIGH);  
        delayMicroseconds(12);  
        digitalWrite(trigPin, LOW);  
        // Reads the echoPin, returns the sound wave travel time in microseconds  
        duration = pulseIn(echoPin, HIGH, 35000);   // 35000 to prevent echos and not wait for tiemeout
        sensor_samples[i] = duration;
        delay(1);  
    }

    // process the samples
    //
    // find max and min
    long max = sensor_samples[0];
    uint max_index = 0;
    long min = sensor_samples[0];
    uint min_index = 0;
    for( uint i = 0 ; i < sensor_samples_size ; i++ )
    {
        if( sensor_samples[i] > max )
        {
            max = sensor_samples[i];
            max_index = i;
        }
        if( sensor_samples[i] < min )
        {
            min = sensor_samples[i];
            min_index = i;
        }
    }
    // Serial.printf("Max[%u]=%dl, Min[%u]=%dl\n", max_index, max, min_index, min);  

    //
    // calculate average excluding min and max
    double avg = 0.0;
    uint valid_samples_count = 0;
    for( uint i = 0 ; i < sensor_samples_size ; i++ )
    {
        if( i == max_index || i == min_index )
        {
            continue;
        }
        valid_samples_count++;
        avg += sensor_samples[i];
    }
    avg = avg / (valid_samples_count);
    // Serial.println(String("Avg duration: ") + avg + " over " + valid_samples_count + " samples." );  

    // Calculating the distance  
    distance = avg*0.034/2;  
    // Prints the distance on the Serial Monitor  
    // Serial.print("Distance: ");  
    // Serial.println(distance);  
    
    double percentDiff = abs(int(distance - previous_distance))/(double)previous_distance;
    // Serial.println( String("percentDiff: ") + percentDiff );

    if( percentDiff > max_quiet_percentDiff_sensor )
    {
        previous_distance = distance;
        mqtt_publish_sensor = true;
    }    
    // Uncomment for debugging
    // else
    // {
    //     if( percentDiff <= max_quiet_percentDiff_sensor )
    //     {
    //         Serial.println( String("No publishing yet, percentDiff: ") + percentDiff );
    //     }
    //     if( now - last_mqtt_publish_time <= (max_quiet_time*1000) )
    //     {
    //         Serial.println( String("No publishing yet, now(") + now + ") - last_mqtt_publish_time(" + last_mqtt_publish_time + ") <= (max_quiet_time(" + max_quiet_time + "*1000) ");
    //     }
    // }
}

#ifdef BATTERY
float mapfloat(float x, float in_min, float in_max, float out_min, float out_max)
{
  return (x - in_min) * (out_max - out_min) / (in_max - in_min) + out_min;
}

void loopReadBattery()
{
  adc_value = analogRead(analogInPin);
  // Serial.println(String("adc_value: ") + adc_value);
  voltage = (((adc_value * 3.3) / 1024) * 2 + battery_calibration); //multiply by two as voltage divider network is 100K & 100K Resistor
  // Serial.println(String("voltage: ") + voltage);
  battery_percentage = mapfloat(voltage, 2.8, 4.2, 0, 100); //2.8V as Battery Cut off Voltage & 4.2V as Maximum Voltage
  // Serial.println(String("battery_percentage: ") + battery_percentage);
  if (battery_percentage >= 100)
  {
    battery_percentage = 100;
  }
  if (battery_percentage <= 0)
  {
    battery_percentage = 1;
  }
  // Serial.println(String("After normalization battery_percentage: ") + battery_percentage);

  if( battery_percentage > battery_warning_level )
  {
    battery_recharge_warning = false;
  }
  else
  {
    battery_recharge_warning = true;
    Serial.println("battery_percentage warning!");
  }

  double percentDiff = abs(int(battery_percentage - previous_battery_percentage));
  if( percentDiff > max_quiet_percentDiff_battery )
  {      
    previous_battery_percentage = battery_percentage;
    mqtt_publish_battery = true;
  }  
}
#endif

void mqttCallback( char* topic, byte* payload, unsigned int length)
{
  Serial.print( "Message arrived [" );
  Serial.print( topic );
  Serial.print( "] " );
  for (uint i=0;i<length;i++)
  {
    char receivedChar = (char)payload[i];
    Serial.print(receivedChar);
    // if (receivedChar == '0')
    // {
    //   // ESP8266 outputs are "reversed"
    //   digitalWrite( PIN_LED, HIGH );
    // }
    // if (receivedChar == '1')
    // {
    //   digitalWrite( PIN_LED, LOW );
    // }
  }
  Serial.println();

  loopReadSensor();

#ifdef BATTERY
  loopReadBattery();
#endif
}

void mqttSetup()
{
  // Serial.printf( "Will try to read mqtt_port %s in a String\n", mqtt_port );
  String port( mqtt_port );
  Serial.printf( "Set mqtt server to %s and port to %d\n", mqtt_server, port.toInt() );
  client.setServer( mqtt_server, port.toInt() );
  // Serial.printf( "Will try to set mqtt callback\n" );
  client.setCallback( mqttCallback );
}

void configFileSetup()
{
  //read configuration from FS json
  Serial.println("mounting FS...");

  if (SPIFFS.begin()) 
  {
      Serial.println("mounted file system");
  } else {
      Serial.println("failed to mount FS");
  }
}

void readConfigFile()
{
    if (SPIFFS.exists("/config.json")) 
    {
        //file exists, reading and loading
        Serial.println("reading config file");
        File configFile = SPIFFS.open("/config.json", "r");
        if (configFile) 
        {
            Serial.println("opened config file");
            size_t size = configFile.size();
            // Allocate a buffer to store contents of the file.
            std::unique_ptr<char[]> buf(new char[size]);

            configFile.readBytes(buf.get(), size);
            DynamicJsonDocument doc(1024);
            DeserializationError error = deserializeJson(doc, buf.get());
            if (error)
            {            
                Serial.println("failed to load json config");
            }
            else
            {
                if( !doc["ssid"].isNull() ){ strncpy(ssid, doc["ssid"], 60); }
                Serial.println(String("ssid: [") + ssid + "]");
                if( !doc["password"].isNull() ){ strncpy(password, doc["password"], 40); }
                Serial.println(String("password: [") + password + "]");
                if( !doc["AP_ssid"].isNull() ){ strncpy(AP_ssid, doc["AP_ssid"], 60); }
                Serial.println(String("AP_ssid: [") + AP_ssid + "]");
                if( !doc["AP_password"].isNull() ){ strncpy(AP_password, doc["AP_password"], 40); }
                Serial.println(String("AP_password: [") + AP_password + "]");
                if( !doc["mqtt_server"].isNull() ){ strncpy(mqtt_server, doc["mqtt_server"], 40); }
                Serial.println(String("mqtt_server: [") + mqtt_server + "]");
                if( !doc["mqtt_port"].isNull() ){ strncpy(mqtt_port, doc["mqtt_port"], 6); }
                Serial.println(String("mqtt_port: [") + mqtt_port + "]");
                if( !doc["publish_topic"].isNull() ){ strncpy(publish_topic, doc["publish_topic"], 256); }
                Serial.println(String("publish_topic: [") + publish_topic + "]");
                if( !doc["subscribe_topic"].isNull() ){ strncpy(subscribe_topic, doc["subscribe_topic"], 256); }
                Serial.println(String("subscribe_topic: [") + subscribe_topic + "]");
                if( !doc["sensor_id"].isNull() ){ strncpy(sensor_id, doc["sensor_id"], 256); }
                Serial.println(String("sensor_id: [") + sensor_id + "]");
                if( !doc["max_quiet_time"].isNull() ){ max_quiet_time = doc["max_quiet_time"]; }
                Serial.println(String("max_quiet_time: [") + max_quiet_time + "]");                    
#ifdef BATTERY
                if( !doc["battery_warning_level"].isNull() ){ battery_warning_level = doc["battery_warning_level"]; }
                Serial.println(String("battery_warning_level: [") + battery_warning_level + "]");                    
                if( !doc["battery_calibration"].isNull() ){ battery_calibration = doc["battery_calibration"]; }
                Serial.println(String("battery_calibration: [") + battery_calibration + "]");                    
#endif
            }
        }
    }
    else
    {
      Serial.println("File /config.json does not exist");
    }
}

void startAP()
{
  WiFi.softAP(AP_ssid, AP_password);
  AP_is_on = true;

  IPAddress IP = WiFi.softAPIP();
  Serial.print("AP ");
  Serial.print(WiFi.SSID());
  Serial.print(" IP address: ");
  Serial.println(IP);

  // Print ESP8266 Local IP Address
  Serial.println(WiFi.localIP());
}

// I chose to have the access point always on, so this function is not used.
void stopAP()
{
  WiFi.softAPdisconnect();
  AP_is_on = false;
}

void setupWifiSTA( const String ssid, const String password )
{
  WiFi.begin(ssid, password);             // Connect to the network
  Serial.print("Connecting to ");
  Serial.print(ssid); Serial.println(" ...");

  unsigned long timeout_millis = 15000;
  unsigned long time = millis();
  
  int i = 0;
  // Wait for the Wi-Fi to connect or timeout
  while (WiFi.status() != WL_CONNECTED && (millis() - time < timeout_millis )) 
  { 
    delay(1000);
    Serial.print(++i); Serial.print(' ');
  }

  if(WiFi.status() != WL_CONNECTED)
  {
    Serial.println(String("Connection to ") + ssid + " timedout. Starting Access Point.");
    AP_is_autostarted = true;
    startAP();
  }
}

void wifiSetup()
{
  WiFi.mode(WIFI_AP_STA);
  startAP();
  setupWifiSTA(ssid, password);
}

// ahat: On ESP8266 and ESP32 use attribute IRAM_ATTR to instruct the compiler to put 
// interrupt-handler function into IRAM which means internal RAM or else it crashes
void IRAM_ATTR ISR_flash_button_pressed() 
{
    // Serial.println(String("flashButtonState was: ") + flashButtonState);
    // flashButtonState = digitalRead( PIN_FLASH );
    // Serial.println(String("flashButtonState now is: ") + flashButtonState);
    flashButtonPressed = true;
    Serial.println(String("flashButtonPressed: ") + flashButtonPressed);
}

void flashSetup()
{
    pinMode( PIN_FLASH, INPUT_PULLUP );
    //ahat: this is important. 0: PRESSED, 1: RELEASED. previousFlashState must start with 1
    //or else as soon as the first input is read it will look like FLASH was pressed
    // previousFlashState = 1; // Starting with Flash RELEASED
    // Serial.print( "Starting with previousFlashState:" );
    // Serial.println( previousFlashState );

    flashButtonPressed = false;
    attachInterrupt(digitalPinToInterrupt(PIN_FLASH), ISR_flash_button_pressed, RISING);
}

void loopReadFlash()
{
    if( flashButtonPressed == 1 )
    {
        Serial.println("The flash button was pressed, starting Wifi setup");
        flashButtonPressed = false; // so that we don't handle it again
    }
}

void ArduinoOTASetup()
{
    // Port defaults to 8266
    // ArduinoOTA.setPort(8266);

    // Hostname defaults to esp8266-[ChipID]
    // ArduinoOTA.setHostname("myesp8266");

    // No authentication by default
    // ArduinoOTA.setPassword("admin");

    // Password can be set with it's md5 value as well
    // MD5(admin) = 21232f297a57a5a743894a0e4a801fc3
    // ArduinoOTA.setPasswordHash("21232f297a57a5a743894a0e4a801fc3");

    ArduinoOTA.onStart([]() {
        String type;
        if (ArduinoOTA.getCommand() == U_FLASH)
            type = "sketch";
        else // U_SPIFFS
            type = "filesystem";

        // NOTE: if updating SPIFFS this would be the place to unmount SPIFFS using SPIFFS.end()
        Serial.println("Start updating " + type);
    });
    ArduinoOTA.onEnd([]() {
        Serial.println("\nEnd");
    });
    ArduinoOTA.onProgress([](unsigned int progress, unsigned int total) {
        Serial.printf("Progress: %u%%\r", (progress / (total / 100)));
    });
    ArduinoOTA.onError([](ota_error_t error) {
        Serial.printf("Error[%u]: ", error);
        if (error == OTA_AUTH_ERROR) Serial.println("Auth Failed");
        else if (error == OTA_BEGIN_ERROR) Serial.println("Begin Failed");
        else if (error == OTA_CONNECT_ERROR) Serial.println("Connect Failed");
        else if (error == OTA_RECEIVE_ERROR) Serial.println("Receive Failed");
        else if (error == OTA_END_ERROR) Serial.println("End Failed");
    });
    ArduinoOTA.begin();
    Serial.println("Ready");
    Serial.print("IP address: ");
    Serial.println(WiFi.localIP());
}

void sensorSetup()
{
    pinMode(trigPin, OUTPUT); // Sets the trigPin as an Output  
    pinMode(echoPin, INPUT); // Sets the echoPin as an Input
}

void setup() {      
    Serial.begin(115200); // Starts the serial communication  

    sensorSetup();
    Serial.println( "sensorSetup finished" );

    flashSetup();
    Serial.println( "flashSetup finished" );

    configFileSetup();
    Serial.println( "configFileSetup finished" );

    readConfigFile();
    Serial.println( "readConfigFile finished" );

    wifiSetup();
    Serial.println( "wifiSetup finished" );

    mqttSetup();
    Serial.println( "mqttSetup finished" );

    ArduinoOTASetup();
    Serial.println( "ArduinoOTASetup finished" );

    webServerSetup();
}

void loop() 
{
    ArduinoOTA.handle();

    loopMqttConnect();
    
    loopReadSensor();
    
#ifdef BATTERY
    loopReadBattery();
#endif

    loopMqttPublish();

    loopReadFlash();

    loopWebServer();

    delay(1500);
}