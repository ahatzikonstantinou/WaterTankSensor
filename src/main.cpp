#include <FS.h> //for WiFiManager this needs to be first, or it all crashes and burns...
#include <ESP8266WiFi.h>
// #include <ESP8266mDNS.h>
// #include <WiFiUdp.h>
#include <ArduinoOTA.h>
#include <PubSubClient.h>
// #include <ESP8266WebServer.h>

#include <ArduinoJson.h>  //https://github.com/bblanchon/ArduinoJson
#include <WiFiManager.h>  //https://github.com/tzapu/WiFiManager

#define PIN_SWITCH 5 // ahat: this is GPIO5 = D1 in nodemcu v3
#define PIN_LED 13
#define PIN_FLASH 0

volatile bool flashButtonPressed = false;
// volatile int flashButtonState = LOW;
// int previousFlashState = 1; //ahat: this is important. 0: PRESSED, 1: RELEASED. previousFlashState must start with 1
//                             //or else as soon as the first input is read it will look like FLASH was pressed

const char* ssid = "ahat_v";
const char* password = "423hh[23";
const int echoPin = 12; 
const int trigPin = 14;   
long duration;  
uint distance;
uint previous_distance = 0;
const uint sensor_samples_size = 15;
long sensor_samples[sensor_samples_size];
unsigned long last_mqtt_publish_time = 0;
double max_quiet_percentDiff = 0.01; // if the percent difference between distance and previous_distance 
                                        // is <= max_quiet_percentDiff don't send mqtt message
char mqtt_server[40];
char mqtt_port[6];
char publish_topic[256];
char subscribe_topic[256];

char sensor_id[256];
uint max_quiet_time;

WiFiClient espClient;
PubSubClient client( espClient );


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

void mqttPublish( String message )
{
    if( client.connected() )
    {
      Serial.printf( "Publishing: [%s] ", publish_topic );
      Serial.println( message );
      client.publish( publish_topic, message.c_str() );
    }
    else
    {
      Serial.println( "Cannot publish because client is not connected." );
    }
}

void loopReadSensorMqttPublish( bool changesOnly )
{
    for( uint i = 0 ; i < sensor_samples_size ; i++ )
    {
        // Clears the trigPin  
        digitalWrite(trigPin, HIGH);  
        delayMicroseconds(10);  
        // Sets the trigPin on HIGH state for 10 micro seconds  
        digitalWrite(trigPin, LOW);  
        delayMicroseconds(100);  
        // digitalWrite(trigPin, LOW);  
        // Reads the echoPin, returns the sound wave travel time in microseconds  
        duration = pulseIn(echoPin, HIGH);  
        sensor_samples[i] = duration;
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
    Serial.printf("Max[%u]=%dl, Min[%u]=%dl\n", max_index, max, min_index, min);  

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
    Serial.println(String("Avg duration: ") + avg + " over " + valid_samples_count + " samples." );  

    // Calculating the distance  
    distance = avg*0.034/2;  
    // Prints the distance on the Serial Monitor  
    Serial.print("Distance: ");  
    Serial.println(distance);  
    
    double percentDiff = abs(int(distance - previous_distance))/(double)previous_distance;
    Serial.println( String("percentDiff: ") + percentDiff );

    unsigned long now = millis();
    if( percentDiff > max_quiet_percentDiff || now - last_mqtt_publish_time > (max_quiet_time*1000) )
    {
        last_mqtt_publish_time = now;
        previous_distance = distance;
        String msg = String( "{\"sensor_id\":\"" ) + sensor_id + String("\", \"measurement\":") + distance + String("}");
        Serial.println(msg);  
        mqttPublish(msg);
        client.loop();
    }    
    // Uncomment for debugging
    else
    {
        if( percentDiff <= max_quiet_percentDiff )
        {
            Serial.println( String("No publishing yet, percentDiff: ") + percentDiff );
        }
        if( now - last_mqtt_publish_time <= (max_quiet_time*1000) )
        {
            Serial.println( String("No publishing yet, now(") + now + ") - last_mqtt_publish_time(" + last_mqtt_publish_time + ") <= (max_quiet_time(" + max_quiet_time + "*1000) ");
        }
    }
}

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

  loopReadSensorMqttPublish( false );
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

//flag for saving data
bool shouldSaveConfig = false;

//callback notifying us of the need to save config
void saveConfigCallback ()
{
  Serial.println("Should save config");
  shouldSaveConfig = true;
}

// if autoConnect = true wifimanager will attempt to connect with previous known SSID and password
// else it will try ondemand configuration
void setupWifiManager( bool autoConnect )
{
  //read configuration from FS json
  Serial.println("mounting FS...");

  if (SPIFFS.begin()) 
  {
        Serial.println("mounted file system");
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
                    if( !doc["mqtt_server"].isNull() ){ strncpy(mqtt_server, doc["mqtt_server"], 40); }
                    if( !doc["mqtt_port"].isNull() ){ strncpy(mqtt_port, doc["mqtt_port"], 6); }
                    if( !doc["publish_topic"].isNull() ){ strncpy(publish_topic, doc["publish_topic"], 256); }
                    if( !doc["subscribe_topic"].isNull() ){ strncpy(subscribe_topic, doc["subscribe_topic"], 256); }
                    if( !doc["sensor_id"].isNull() ){ strncpy(sensor_id, doc["sensor_id"], 256); }
                    if( !doc["max_quiet_time"].isNull() ){ max_quiet_time = doc["max_quiet_time"]; }
                    Serial.println(String("mqtt_server: [") + mqtt_server + "]");
                    Serial.println(String("mqtt_port: [") + mqtt_port + "]");
                    Serial.println(String("publish_topic: [") + publish_topic + "]");
                    Serial.println(String("subscribe_topic: [") + subscribe_topic + "]");
                    Serial.println(String("sensor_id: [") + sensor_id + "]");
                    Serial.println(String("max_quiet_time: [") + max_quiet_time + "]");                    
                }
            }
        }
    } else {
        Serial.println("failed to mount FS");
    }
    //end read
  // The extra parameters to be configured (can be either global or just in the setup)
  // After connecting, parameter.getValue() will get you the configured value
  // id/name placeholder/prompt default length
  WiFiManagerParameter custom_mqtt_server("server", "mqtt server", mqtt_server, 40);
  WiFiManagerParameter custom_mqtt_port("port", "mqtt port", mqtt_port, 6);
  WiFiManagerParameter custom_publish_topic( "publish_topic", "publish topic", publish_topic, 256);
  WiFiManagerParameter custom_subscribe_topic( "subscribe_topic", "subscribe topic", subscribe_topic, 256);
  WiFiManagerParameter custom_sensor_id( "sensor_id", "sensor id", sensor_id, 256);
  WiFiManagerParameter custom_max_quiet_time( "max_quiet_time", "max quiet time (in secs)", String(max_quiet_time).c_str(), 256);

  //WiFiManager
  //Local intialization. Once its business is done, there is no need to keep it around
  WiFiManager wifiManager;

  //set config save notify callback
  wifiManager.setSaveConfigCallback(saveConfigCallback);

  //set static ip
  // wifiManager.setSTAStaticIPConfig(IPAddress(10,0,1,99), IPAddress(10,0,1,1), IPAddress(255,255,255,0));

  //add all your parameters here
  wifiManager.addParameter( &custom_mqtt_server );
  wifiManager.addParameter( &custom_mqtt_port );
  wifiManager.addParameter( &custom_publish_topic );
  wifiManager.addParameter( &custom_subscribe_topic );
  wifiManager.addParameter( &custom_sensor_id );
  wifiManager.addParameter( &custom_max_quiet_time );
  
  //reset settings - for testing
  //wifiManager.resetSettings();

  //set minimu quality of signal so it ignores AP's under that quality
  //defaults to 8%
  //wifiManager.setMinimumSignalQuality();

  //sets timeout until configuration portal gets turned off
  //useful to make it all retry or go to sleep
  //in seconds
  //wifiManager.setTimeout(120);

  if( autoConnect )
  {
    //fetches ssid and pass and tries to connect
    //if it does not connect it starts an access point with the specified name
    //here  "AutoConnectAP"
    //and goes into a blocking loop awaiting configuration
    if (!wifiManager.autoConnect("AutoConnectAP", "password"))
    {
      Serial.println("failed to connect and hit timeout");
      delay(3000);
      //reset and try again, or maybe put it to deep sleep
      ESP.reset();
      delay(5000);
    }
  }
  else
  {
    WiFi.mode(WIFI_STA);
    WiFi.disconnect();
    delay( 2000 );
    if (!wifiManager.startConfigPortal("OnDemandAP"))
    {
      Serial.println("failed to connect and hit timeout");
      delay(3000);
      //reset and try again, or maybe put it to deep sleep
      ESP.reset();
      delay(5000);
    }
  }

  //if you get here you have connected to the WiFi
  Serial.println("connected...yeey :)");

  //read updated parameters
  strcpy( mqtt_server, custom_mqtt_server.getValue() );
  strcpy( mqtt_port, custom_mqtt_port.getValue() );
  strcpy( publish_topic, custom_publish_topic.getValue() );
  strcpy( subscribe_topic, custom_subscribe_topic.getValue() );
  strcpy( sensor_id, custom_sensor_id.getValue() );
  max_quiet_time = atol(custom_max_quiet_time.getValue());
  
  //save the custom parameters to FS
  if (shouldSaveConfig) {
    Serial.println("saving config");
    DynamicJsonDocument json(1024);

    json["mqtt_server"] = mqtt_server;
    json["mqtt_port"] = mqtt_port;
    json["publish_topic"] = publish_topic;
    json["subscribe_topic"] = subscribe_topic;
    json["sensor_id"] = sensor_id;
    json["max_quiet_time"] = max_quiet_time;


    File configFile = SPIFFS.open("/config.json", "w");
    if (!configFile) {
      Serial.println("failed to open config file for writing");
    }

    serializeJson(json, Serial);
    serializeJson(json, configFile);
    configFile.close();
    //end save
  }

  Serial.println("local ip");
  Serial.println(WiFi.localIP());

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
        setupWifiManager( false );
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

    setupWifiManager( true );
    Serial.println( "setupWifiManager finished" );

    mqttSetup();
    Serial.println( "mqttSetup finished" );

    ArduinoOTASetup();
    Serial.println( "ArduinoOTASetup finished" );
}

void loop() 
{
    ArduinoOTA.handle();
    loopMqttConnect();
    loopReadSensorMqttPublish( true );
    loopReadFlash();

    delay(2000);
}