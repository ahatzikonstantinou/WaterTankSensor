$(document).ready(function() {
  //
  // get all water tank info for initial setup
  var water_tanks = null;
  var water_tank_settings = null;

  setInterval(updateLastSensorUpdate, 1000);

  function updateLastSensorUpdate()
  {
    if( water_tanks == null || water_tank_settings == null)
    {
      return; // no data has come in yet
    }

    Object.keys(water_tanks).forEach(e => {
      // console.log(`key= $${e} value=$${water_tanks[e]}`);
      const id = e;
      const water_tank = water_tanks[e];
      const time_passed_str = get_time_passed_str(water_tank.last_updated);
      const exceeded = get_exceeded_4_dead_sensor(water_tank);
      $(`#${water_tank.id}_last_updated`).text(time_passed_str);
      if( exceeded.length == 0 )
      {
        $(`#${water_tank.id}_last_updated`).removeClass('exceeded');
      }
      else
      {
        $(`#${water_tank.id}_last_updated`).addClass('exceeded');
      }
    });
  }

  function get_exceeded_4_dead_sensor(water_tank)
  {
    return (Date.now() - new Date(water_tank.last_updated)) > water_tank_settings.max_sensor_no_signal_time*1000 ? "exceeded" : "";
  }

  function get_whole_values(base_value, time_fractions) {
    time_data = [base_value];
    for (i = 0; i < time_fractions.length; i++) {
        time_data.push(parseInt(time_data[i]/time_fractions[i]));
        time_data[i] = time_data[i] % time_fractions[i];
    }; return time_data;
  };

  function get_time_passed_str(last_updated)
  {
    const time_passed = get_whole_values(Date.now() - new Date(last_updated), [1000,  60, 60, 24]);
    // console.log("time_passed: ", time_passed);
    let time_passed_str = "";
    if(time_passed[4]>0)
    {
      time_passed_str = time_passed[4] + "d ";
    }
    if(time_passed[3]>0)
    {
      time_passed_str += new String(time_passed[3]).padStart(2,0) + "h ";
    }
    time_passed_str += (new String(time_passed[2]).padStart(2,0)) + "m";
    time_passed_str += " " + (new String(time_passed[1]).padStart(2,0)) + "s";
    time_passed_str += " ago";

    return time_passed_str;
  }

  function template(water_tank, state="" )
  {
    // console.log(`Will generate tr for id: ${water_tank.id}, label: ${water_tank.label}, percentage: ${water_tank.percentage}, sensor_error: ${water_tank.invalid_sensor_measurement}, last_updated: ${water_tank.last_updated}, state: "${state}"`);
    let str_percentage = "";
    let width_percentage = 0;
    // let last_updated = water_tank.last_updated;
    // console.log("date last update:", last_updated);
    
    // const time_passed = get_whole_values(Date.now() - new Date(water_tank.last_updated), [1000,  60, 60, 24]);
    // // console.log("time_passed: ", time_passed);
    // let time_passed_str = "";
    // if(time_passed[4]>0)
    // {
    //   time_passed_str = time_passed[4] + "d ";
    // }
    // if(time_passed[3]>0)
    // {
    //   time_passed_str += new String(time_passed[3]).padStart(2,0) + "h ";
    // }
    // time_passed_str += (new String(time_passed[2]).padStart(2,0)) + "m ago";
    const time_passed_str = get_time_passed_str(water_tank.last_updated);
    // console.log(time_passed_str);

    // redundant
    // if(last_updated == null)
    // {
    //   last_updated = "";
    // }
    if(water_tank.invalid_sensor_measurement)
    {
      state = "sensor_error";
    }
    else if(water_tank.percentage != null)
    {
      let percentage = Math.round(water_tank.percentage);
      str_percentage = percentage + "%";
      width_percentage = percentage;
    }
    let hidden = !water_tank.enabled ? "hidden" : "";
    // console.log(`Water_tank_id:${water_tank.id}, enabled: ${water_tank.enabled}, hidden:${hidden}`);

    // I need to synchronously fetch the water_tank plugin settings to get the max_station_no_signal_time
    // since jQuery.getJson uses ajax configuration  just set the global ajax configs
    // from https://stackoverflow.com/a/23057124
    $.ajaxSetup({
      async: false
    });
    
    // The $.getJSON() request is now synchronous...
    $.getJSON('water_tank_get_settings_json', function(data)
    {
      water_tank_settings = data;
      // console.log("water_tank_settings: ", water_tank_settings);
    });
    
    // Set the global configs back to asynchronous 
    $.ajaxSetup({
        async: true
    });
    
    // console.log("water_tank_settings: ", water_tank_settings);
    // console.log("Time passed millis: " + (Date.now() - new Date(water_tank.last_updated)));
    // console.log("max_sensor_no_signal_time in millis: " + water_tank_settings.max_sensor_no_signal_time);
    // const exceeded = (Date.now() - new Date(water_tank.last_updated)) > water_tank_settings.max_sensor_no_signal_time*60000 ? "exceeded" : "";
    const exceeded = get_exceeded_4_dead_sensor(water_tank);
    // console.log( "exceeded: " + exceeded);
    return `<tr id="${water_tank.id}" ${hidden}>
      <td style="white-space: nowrap;">
        <div class="water-tank-label">${water_tank.label}</div>
        <div id="${water_tank.id}_last_updated" class="last_updated ${exceeded}">${time_passed_str}</div>
      </td>
      <td style="width:100%">
        <div style="width: 100%;
        height: 2em;
        background-color: lightcyan;
        border-radius: 10px;
        border:1px solid cyan;
        text-align: center;
        vertical-align: middle;
        position: relative;">
          <div class="percent-bar ${state}" style="width: ${width_percentage}%;
          height: 100%;
          position: absolute;
          z-index: 2;">
          </div>
          <div class="status-bar-text" style="width: 100%;
          height: 100%;
          z-index: 3;
          position: absolute;">
          <h4 class="${state}" style="display:inline;text-align: center;
          line-height:2em;" class="${state}">${str_percentage}</h4>
        </div>
      </td>
    </tr>`;
  }


  // Create a new div element
  var many_water_tank_div = $(`<p style="padding-top:1em;">Water Tanks</p><div id="water_tank_container">
    <table id="water_tank_table" style="width:100%;border: 1px solid #2E3959;border-radius: 12px;padding: 4px;">        
    </table>
  </div>`);

  var single_water_tank_div = $(`<div id="water_tank_container" style="padding-top:1em;">
    <table id="water_tank_table" style="width:100%;padding: 4px;">        
    </table>
  </div>`);

  // add water tank display only to home page
  let url_parts = window.location.href.split('/');
  if(url_parts[url_parts.length-1].length == 0)
  {
    $.getJSON('water-tank-get-all', function(data){
      water_tanks = data;
      // Add the new div right after the "options" div
      if(data.length > 1)
      {        
        $('#options').after(many_water_tank_div);
      }
      else
      {      
        $('#options').after(single_water_tank_div);
      }

      $.each( data, function( i, water_tank ) {
        let tr = template( water_tank, DetermineWaterTankState(water_tank) );
        $('#water_tank_table').append(tr);

      });  
    });
  }

  //
  // Register mqtt client to update water tank data based on incoming mqtt messages
  // Create a client instance
  $.getJSON('water-tank-get_mqtt_settings', function(data)
  {
    let mqtt_settings = null;
  
    console.log('mqtt_settings: ', data);
    mqtt_settings = data;

    const client_id = "browser_" + uuidv4();
    console.log('water_tank.js connecting to mqtt broker with ' +
      mqtt_settings.broker_host + ", " + mqtt_settings.mqtt_broker_ws_port + ", " + client_id);
    client = new Paho.MQTT.Client(mqtt_settings.broker_host, mqtt_settings.mqtt_broker_ws_port, client_id);

    // set callback handlers
    client.onConnectionLost = onConnectionLost;
    client.onMessageArrived = onMessageArrived;

    // connect the client
    client.connect({onSuccess:onConnect});

    // called when the client connects
    function onConnect() {
      // Once a connection has been made, make a subscription and send a message.
      console.log("onConnect");
      client.subscribe(mqtt_settings.data_publish_mqtt_topic);
    }

    // called when the client loses its connection
    function onConnectionLost(responseObject) {
      if (responseObject.errorCode !== 0) {
        console.log("onConnectionLost:"+responseObject.errorMessage);
      }
    }

    // called when a message arrives
    function onMessageArrived(message) {
      // console.log("onMessageArrived:"+message.payloadString);
      try
      {
        water_tanks = JSON.parse(message.payloadString);
        Object.keys(water_tanks).forEach(e => {
            // console.log(`key= $${e} value=$${water_tanks[e]}`);
            const id = e;
            const water_tank = water_tanks[e];
            // console.log('id: ' + id + ", last_updated: " + water_tank.last_updated);
            
            if(water_tank.invalid_sensor_measurement)
            {
              $(`#${water_tank.id}`).replaceWith( template( water_tank ) );
            }
            else if(water_tank.percentage != null)
            {
              let state = "normal";              

              if(water_tank.critical_level != null &&
                water_tank.percentage <= water_tank.critical_level)
              {
                state = "critical";
              }
              else if(water_tank.warning_level != null &&
                water_tank.percentage <= water_tank.warning_level)
              {
                state = "warning";
              }
              else if(water_tank.overflow_level != null &&
                water_tank.percentage >= water_tank.overflow_level)
              {
                state = "overflow";
              }              
              $(`#${water_tank.id}`).replaceWith( template( water_tank, DetermineWaterTankState(water_tank) ) );
            }
            
        });        
      }
      catch(e)
      {
        console.error(e);
      }
    }
  });

});

function DetermineWaterTankState(water_tank)
{
  let state = "normal";

  if(water_tank.invalid_sensor_measurement)
  {
    state = "sensor_error";
  }
  else if(water_tank.percentage != null)
  {                  
   if(water_tank.critical_level != null &&
      water_tank.percentage <= water_tank.critical_level)
    {
      state = "critical";
    }
    else if(water_tank.warning_level != null &&
      water_tank.percentage <= water_tank.warning_level)
    {
      state = "warning";
    }
    else if(water_tank.overflow_level != null &&
      water_tank.percentage >= water_tank.overflow_level)
    {
      state = "overflow";
    }
  }

  return state;
}

function uuidv4() {
  return "10000000-1000-4000-8000-100000000000".replace(/[018]/g, c =>
    (c ^ crypto.getRandomValues(new Uint8Array(1))[0] & 15 >> c / 4).toString(16)
  );
}