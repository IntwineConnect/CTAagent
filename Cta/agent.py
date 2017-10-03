from __future__ import absolute_import
from volttron.platform.vip.agent import Agent, Core, RPC
from volttron.platform.agent import utils
from datetime import datetime, timedelta
from volttron.platform.agent.known_identities import (CONTROL, CONFIGURATION_STORE)
import time
#TODO: settings?
from . import settings
import logging
import sys
import urllib2
import json

utils.setup_logging()
_log = logging.getLogger(__name__)
_load_agent_path = '/home/kirtan/.volttron/packaged/Loadagent-3.0-py2-none-any.whl'


class CtaAgent(Agent):
    currentPriority = 0
    HTTPmethods = {'shed': 'POST',
                   'normal': 'POST',
                   'grid_emergency': 'POST',
                   'critical_peak': 'POST',
                   'cur_price': 'POST',
                   'next_price': 'POST',
                   'change_level': 'POST',
                   'time_remaining': 'POST',
                   'time_sync': 'POST',
                   'state_sgd': 'GET',
                   'info_sgd': 'GET',
                   'load_up': 'POST',
                   'start_cycling': 'POST',
                   'stop_cycling': 'POST',
                   'comm_state': 'POST',
                   'commodity': 'GET'
                   }
    URLmap = {'shed': '/load.cgi?',
              'normal': '/load.cgi?',
              'grid_emergency': '/load.cgi?',
              'critical_peak': '/load.cgi?',
              'cur_price': '/price.cgi?',
              'next_price': '/price.cgi?',
              'change_level': '/load.cgi?',
              'time_remaining': '/price.cgi?',
              'time_sync': '/time.cgi?',
              'state_sgd': '/state_sgd.cgi?',
              'info_sgd': '/info_sgd.cgi?',
              'load_up': '/load.cgi?',
              'start_cycling': '/load.cgi?',
              'stop_cycling': '/load.cgi?',
              'comm_state': '/comm.cgi?',
              'commodity': '/commodity.cgi'            
              }

    device_type = {
        0 : "Unspecified Type",
        1 : "Water Heater - Gas",
        2 : "Water Heater - Electric",
        3 : "Water Heater - Heat Pump",
        4 : "Central AC - Heat Pump",
        5 : "Central AC - Fossil Fuel Heat",
        6 : "Central AC - Resistance Heat",
        7 : "Central AC (only)",
        8 : "Evaporative Cooler",
        9 : "Baseboard Electric Heat",
        10 : "Window AC",
        11 : "Portable Electric Heater",
        12 : "Clothes Washer",
        13 : "Clothes Dryer - Gas",
        14 : "Clothes Dryer - Electric",
        15 : "Refrigerator/Freezer",
        16 : "Freezer",
        17 : "Dishwasher",
        18 : "Microwave Oven",
        19 : "Oven - Electric",
        20 : "Oven - Gas",
        21 : "Cook Top - Electric",
        22 : "Cook Top - Gas",
        23 : "Stove - Electric",
        24 : "Stove - Gas",
        25 : "Dehumidifier",
        32 : "Fan",
        48 : "Pool Pump - Single Speed",
        49 : "Pool Pump - Variable Speed",
        50 : "Electric Hot Tub",
        64 : "Irrigation Pump",
        4096 : "Electric Vehicle",
        4097 : "Hybrid Vehicle",
        4352 : "Electric Vehicle Supply Equipment - general (SAE J1772)",
        4353 : "Electric Vehicle Supply Equipment - Level 1 (SAE J1772)",
        4354 : "Electric Vehicle Supply Equipment - Level 2 (SAE J1772)",
        4355 : "Electric Vehicle Supply Equipment - Level 3 (SAE J1772)",
        8192 : "In Premises Display",
        20480 : "Energy Manager",
        24576 : "Gateway Device"}
    
    UCMname = 'ACmodule'
    UCMip = '192.168.10.107'

    def __init__(self, config_path, **kwargs):
        super(CtaAgent, self).__init__(**kwargs)
        self._agent_id = "Cta"
        self.current_sgd_code = "-1"
        self.default_config = {"agent_id": self._agent_id}
        self.vip.config.set_default("config", self.default_config)
        self.vip.config.subscribe(self.configure, actions=["NEW", "UPDATE"], pattern="config")

    def configure(self, config_name, action, contents):
        config = self.default_config.copy()
        config.update(contents)
        # make sure config variables are valid
        try:
            self._agent_id = str(config["agent_id"])
        except ValueError as e:
            _log.error("ERROR PROCESSING CONFIGURATION: {}".format(e))

    @Core.receiver('onstart')
    def starting(self, sender, **kwargs):
        uuid = self.vip.rpc.call(CONTROL, 'install_agent_local', _load_agent_path).get(timeout=30)
        agents = self.vip.rpc.call(CONTROL, "list_agents").get(timeout=5)
        agent_id = self.retrieve_agent_identity(agents, uuid)
        message = {}
        message['message_subject'] = 'new_event'
        message['event_name'] = 'info_sgd'
        response = self.forward_UCM(json.dumps(message))
        dev_type = json.loads(response).get('Device Type', 0)
        dev_name = self.device_type.get(dev_type)
        dev_load = 100
        # TODO change dev load. make new map for it devtype->devload
        json_contents = json.dumps({'device_type': dev_name, 'device_load':dev_load, 'cta_id': self.core.agent_uuid})
        self.vip.rpc.call(CONFIGURATION_STORE, "manage_store", agent_id, 'config', json_contents, 'json')
        self.vip.rpc.call(CONTROL, "start_agent", uuid).get(timeout=5)

    def test_one_command(self, sender, **kwargs):
        self.comm_status()
        self.check_sgd_state()
        message = {}
        message['message_subject'] = 'new_event'
        message['event_name'] = 'commodity'
        response = self.forward_UCM(json.dumps(message))
        print(response)

    def check_sgd_state(self):
        # If sgd state has changed, publishes new state to local bus
        message = {}
        message['message_subject'] = 'new_event'
        message['event_name'] = 'state_sgd'
        json_message = json.dumps(message)
        str_ucm_response = self.forward_UCM(json_message)
        ucm_response = json.loads(str_ucm_response)
        if "code" in ucm_response:
            code = ucm_response.get("code")
            if code != self.current_sgd_code:
                _log.info("Old code %s, new code %s", self.current_sgd_code, code)
                self.current_sgd_code = code
                self.vip.pubsub.publish('pubsub', topic=self.create_topic('state_sgd'), headers={}, message=str_ucm_response)
            else:
                _log.info("SGD status unchanged")
        else:
            _log.info("Error: code key not in UCM response")

    @RPC.export("cta_command")
    def send_ucm_command(self, json_message):
        response = self.forward_UCM(json_message)
        self.check_sgd_state()
        return response

    def create_topic(self, parameter):
        location = ""
        topic = self._agent_id + "/" + self.UCMip + "/" + parameter + "/" + location
        return topic
     
    @Core.periodic(settings.COMM_GOOD_INTERVAL)
    def comm_status(self):
        """
        periodically sends a message to the UCM to test if the VOLTTRON-UCM connection is still good.
        If the connection is good, then the UCM will relay the channel status to its connected SGD.
        """
        # TODO Note this has a lot of repeated code from forward UCM method. consider refactoring
        mesdict = {"commstate": "good"}

        page = self.URLmap.get("comm_state", "/comm.cgi?")
        requestURL = "http://" + self.UCMip + page
        UCMrequest = urllib2.Request(requestURL)
        
        method = self.HTTPmethods.get("comm_state", "POST")
        messtr = json.dumps(mesdict)
        UCMrequest.add_data(messtr)
        UCMresponsedict = {"message_subject": "commstate_update"}
        
        now = datetime.utcnow().isoformat() + 'Z'
        if settings.DEBUGGING_LEVEL >= 2:
            print("Sending a message to test connection at {time}".format(time = now))
        topic = self.create_topic("commstate")
        try:
            result = urllib2.urlopen(UCMrequest, timeout = 10)
            HTTPcode = result.getcode()
            if HTTPcode == 200:
                UCMresponsedict["commstate"] = "good"
            elif HTTPcode == 400:
                UCMresponsedict["commstate"] = "SGD_timeout"
            else:
                UCMresponsedict["commstate"] = "ambiguous"

            print("<{name}> channel status update from {time}: {status}".format(name =self.UCMname, time = now, status = UCMresponsedict["commstate"]))
            notification = json.dumps(UCMresponsedict)
            self.vip.pubsub.publish(peer = 'pubsub', topic = topic, headers = {}, message = notification)
        except urllib2.URLError, e:
            print('an urllib2 error of type {error} occurred while sending comms test message to {ucm}'.format(error = e, ucm = self.UCMname))
            _log.error('Comm_state urllib error')
        except socket.timeout, e:
            _log.error('Comm_state time out')


    def forward_UCM(self, message):
        '''
        parses message and issues REST API CTA command
        '''
        #deserialize message string
        mesdict = json.loads(message)
        messageSubject = mesdict.get('message_subject', None)
        priority = mesdict.get("priority",0)
        
        #ignore anything posted to the topic other than notifications of new events
        if messageSubject != 'new_event':
            return json.dumps({'status' : 'Not a new event message'})
        if (priority < self.currentPriority):
            print("MESSAGE_REJECTED! new event priority is {new}, current priority is {cur}".format(new = str(priority), cur = str(self.currentPriority)))
            return json.dumps({'status': 'Message priority not high enough'})
        
        eventName = mesdict.get('event_name','normal')
        print('***NEW EVENT*** of type <{event}> for  UCM <{name}>'.format(event = eventName, name = self.UCMname))
        
        #manage priority
        if mesdict.get("event_duration", None) is not None:
            #set the current priority according to the accepted new message priority if applicable
            self.currentPriority = priority
            #set up a callback to set the priority to zero when an event has ended
            duration = mesdict.get("event_duration")
            duration = int(duration.replace("S",""))
            priorityTime = datetime.utcnow() + timedelta(seconds=duration)
            if('PrioritySched' in locals() or 'PrioritySched' in globals()):
                PrioritySched.cancel()
            
            PrioritySched = Core.schedule(priorityTime, self.priorityCallback)
            
        #get URL for request
        page = self.URLmap.get(eventName,'/load.cgi?')        
        requestURL = 'http://' + self.UCMip + page
        UCMrequest = urllib2.Request(requestURL)
        
        # determine whether to use GET, POST, or anything else if necessary
        method = self.HTTPmethods.get(eventName,'POST');
        
        if method == 'POST':
            # remove key-value pairs that aren't needed for the REST API message
            mesdict.pop('message_subject', None)
            mesdict.pop('priority', None)
            # REMEMBER TO CHECK BACK HERE WHEN THE VOLTTRON BUS MESSAGING FORMAT HAS BEEN SPECIFIED
            
            cleanmessage = json.dumps(mesdict)
            UCMrequest.add_data(cleanmessage)
            
        now = datetime.utcnow().isoformat(' ')+ 'Z'
        print('sending ' + method + ' for page ' + requestURL + ' for ' + eventName + ' event at ' + now)
        # send REST API CTA command
        try:
            result = urllib2.urlopen(UCMrequest, timeout = 10)
        except urllib2.URLError, e:
            print('an urllib2 error of type {error} occurred while sending message to {ucm}'.format(error = e, ucm = self.UCMname))
            notification = {"message_subject": "urllib2_failure"}
            return json.dumps(notification)
        except socket.timeout, e:
            #Sometimes times out once, but should work on the second time. 
            # TODO ugly approach. refactor or get bug fixed
            try:
                result = urllib2.urlopen(UCMrequest, timeout = 10)
            except urllib2.URLError, e:
                print('an urllib2 error of type {error} occurred while sending message to {ucm}'.format(error = e, ucm = self.UCMname))
                notification = {"message_subject": "urllib2_failure"}
                return json.dumps(notification)
            except socket.timeout,e:
                notification = {"message_subject": "timeout"}
                return json.dumps(notification)
        HTTPcode = result.getcode()
        UCMresponse = result.read()
        if len(UCMresponse) > 0 and method == 'GET':
            UCMresponsedict = json.loads(UCMresponse)
        else:
            UCMresponsedict = {}
        UCMresponsedict['message_subject'] = 'UCMresponse'
        UCMresponsedict['http_code'] = str(HTTPcode)
        UCMresponsestr = json.dumps(UCMresponsedict)
        # publish notification of response receipt with REST API response fields if applicable
        print('###RECEIVED A RESPONSE### relative to event #from <{name}> with HTTP code <{code}> '
              'and body message : {body}'.format(name = self.UCMname, code = HTTPcode, body = UCMresponse))
        # return 1 if successful
        return UCMresponsestr
        
    def priorityCallback(self):
        self.currentPriority = 0    
        print("Event should be over. Priority reverting to 0")

    def retrieve_agent_identity(self, agents, agent_uuid):
        for agent in agents:
            if agent.get('uuid', None) == agent_uuid:
                assert 'identity' in agent
                return agent.get('identity')
        return None
        
def main(argv=sys.argv):
    '''Main method called by the eggsecutable'''
    try:
        utils.vip_main(CtaAgent)
    except Exception as e:
        _log.exception('unhandled exception')
            
if __name__== '__main__':
    #entry point for script_from_examples
    sys.exit(main())
