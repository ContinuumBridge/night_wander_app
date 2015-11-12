# night_wander_app
App to detect and report on people wandering around at night

This is controlled via the data client using (eg):

    {
        "night_wandering": true,
        "data_send_delay": 2,
        "night_start": "23:00",
        "night_end": "07:00",
        "ignore_time": 600
    }

The night_start and stop times are the times when night wandering is monitored. During this time, if any connected sensor is triggered, an alert will be sent (which may cause and email and/or text to be sent). At the end of ignore_time, if any other sensors have been triggered, another alert will be sent with a list of all the sensors that were triggered.

During the "on" time, any sensor that is triggered will cause data to be sent, which may be stored by the client in a database.

Once a day, at the night_end time, the following information is sent for storing:

    night_start
    night_end
    number of night wanders during the preceeding period
    
A night wander is recorded only as the first event in an ignore_time interval. 

The state (which is currently just the count of night wanders) is maintained through restarts and reboots of the bridge, but not if there is a power failure. 
