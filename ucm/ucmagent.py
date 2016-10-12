from __future__ import absolute_import

from volttron.platform.vip.agent import Agent, Core
from volttron.platform.agent import utils
from zmq.log.handlers import TOPIC_DELIM

from datetime import datetime
from . import settings
import logging
import sys

import urllib2
import socket
import json
from pip._vendor.distlib.locators import Page

utils.setup_logging()
_log = logging.getLogger(__name__)

class UCMAgent(Agent):
    
    HTTPmethods = {'shed' : 'POST',
                   'normal': 'POST',
                   'grid_emergency': 'POST',
                   'critical_peak': 'POST',
                   'cur_price': 'POST',
                   'next_price': 'POST',
                   'time_remaining': 'POST',
                   'time_sync': 'POST',
                   'query_op_state': 'GET',
                   'info_request': 'GET',
                   'comm_state': 'POST' 
                   }
    URLmap = {'shed': '/load.cgi?',
              'normal': '/load.cgi?',
              'grid_emergency': '/load.cgi?',
              'critical_peak': '/load.cgi?',
              'cur_price': '/price.cgi?',
              'next_price': '/price.cgi?',
              'time_remaining': '/price.cgi?',
              'time_sync': '/time.cgi?',
              'query_op_state': '/state_sgd.cgi?',
              'info_request': '/info_sgd.cgi?',
              'comm_state': '/comm.cgi?'            
              }
    
    UCMname = 'defaultname'
    UCMip = '192.168.1.116'
    
    def __init__(self,config_path, **kwargs):
        super(UCMAgent, self).__init__(**kwargs)
        self.config = utils.load_config(config_path)
        self._agent_id = self.config['agentid']
        
        
    @Core.receiver("onstart")
    def starting(self, sender, **kwargs):
        '''
        subscribes to the ADRdecision TOPIC_DELIM
        '''
        _log.info(self.config['message'])
        self._agent_id=self.config['agentid']
        
        
        print('!!!HELLO!!! UCMAgent <{name}> starting up and subscribing to topic: CTAevent'.format(name = self.UCMname))
        self.vip.pubsub.subscribe('pubsub','CTAevent', callback=self.forward_UCM)
     
    @Core.periodic(settings.COMM_GOOD_INTERVAL)
    def comm_status(self):
        '''
        periodically sends a message to the UCM to test if the VOLTTRON-UCM connection is still good.
        If the connection is good, then the UCM will relay the channel status to its connected SGD.
        '''
        mesdict = {"commstate": "good"}
        
        page = self.URLmap.get("comm_state", "/comm.cgi?")
        requestURL = "http://" + self.UCMip + page
        UCMrequest = urllib2.Request(requestURL)
        
        method = self.HTTPmethods.get("comm_state", "POST")
        messtr = json.dumps(mesdict)
        UCMrequest.add_data(messtr)
        
        UCMresponsedict = {"message_subject": "commstate_update"}
        UCMresponsedict["message_target"] = self.UCMname
        try:
            result = urllib2.urlopen(UCMrequest, timeout = 10)
        except urllib2.URLError, e:
            print('an urllib2 error of type {error} occurred while sending comms test message to {ucm}'.format(error = e, ucm = self.UCMname))
            HTTPcode = 'no_response'
            UCMresponsedict["message_target"] = self.UCMname
            UCMresponsedict["commstate"] = "UCM_timeout"
            notification = json.dumps(UCMresponsedict)
            self.vip.pubsub.publish(peer = 'pubsub', topic = 'CTAevent', headers = {}, message = notification )
            return 0
        
        HTTPcode = result.getcode()
        
        if HTTPcode == 200:
            UCMresponsedict["commstate"] = "good"
        elif HTTPcode == 400:
            UCMresponsedict["commstate"] = "SGD_timeout"
        else:
            UCMresponsedict["commstate"] = "ambiguous"
             
        print("<{name}> channel status update: {status}".format(name =self.UCMname, status = UCMresponsedict["commstate"]))
        notification = json.dumps(UCMresponsedict)
        self.vip.pubsub.publish(peer = 'pubsub', topic = 'CTAevent', headers = {}, message = notification)
        

        
    def forward_UCM(self, peer, sender, bus, topic, headers, message):
        '''
        parses message and issues REST API CTA command
        '''
        print(message)
        #deserialize message string
        mesdict = json.loads(message)
        
        messageSubject = mesdict.get('message_subject', None)
        eventID = mesdict.get('event_uid',None)
        messageTarget = mesdict.get('message_target', 'all')
        ADRstartTime = mesdict.get('ADR_start_time', 'now')
        
        #ignore anything posted to the topic other than notifications of new events
        if messageSubject != 'new_event':
            return 0
        #ignore if the message is meant for a different UCM
        if (self.checkForName(messageTarget) == False) and (messageTarget != 'all'):
            return 0
        #If the message is meant to be sent later ignore it for now. The message delay agent resubmit it when it's time to send
        if (ADRstartTime != 'now'):
            return 0
        
        eventName = mesdict.get('message_type','normal')
        
        print('***NEW EVENT*** of type <{event}> for  UCM <{name}>'.format(event = eventName, name = self.UCMname))
        notification = '{"message_subject": "initiated", "event_uid": "' + eventID + '"}'
        self.vip.pubsub.publish('pubsub', 'CTAevent', headers = {}, message = notification )
        
        
       
        #get URL for request
        page = self.URLmap.get(eventName,'/load.cgi?')        
        requestURL = 'http://' + self.UCMip + page
        UCMrequest = urllib2.Request(requestURL)
        
        #determine whether to use GET, POST, or anything else if necessary
        method = self.HTTPmethods.get(eventName,'POST');
        
        if method == 'POST':
            #remove key-value pairs that aren't needed for the REST API message
            mesdict.pop('message_subject', None)
            mesdict.pop('message_target', None)
            mesdict.pop('event_uid', None)
            mesdict.pop('message_type', None)
            mesdict.pop('ADR_start_time', None)
            # REMEMBER TO CHECK BACK HERE WHEN THE VOLTTRON BUS MESSAGING FORMAT HAS BEEN SPECIFIED
            
            cleanmessage = json.dumps(mesdict)
            UCMrequest.add_data(cleanmessage)
            
        now = datetime.utcnow().isoformat(' ')+ 'Z'
        print('sending ' + method + ' for page ' + requestURL + ' for ' + eventName + ' event at ' + now)
        #send REST API CTA command
        try:
            result = urllib2.urlopen(UCMrequest, timeout = 10)
        except urllib2.URLError, e:
            print('an urllib2 error of type {error} occurred while sending message to {ucm}'.format(error = e, ucm = self.UCMname))
            HTTPcode = 'no_response'
            notification = '{"message_subject": "urllib2_failure", "event_UID": "' + eventID + '" }'
            self.vip.pubsub.publish(peer = 'pubsub', topic = 'CTAevent', headers = {}, message = notification )
            return 0

            
        
        HTTPcode = result.getcode()
        UCMresponse = result.read()
        print(UCMresponse)
        if len(UCMresponse) > 0 and method == 'GET':
            UCMresponsedict = json.loads(UCMresponse)
        else:
            UCMresponsedict = {}
        
        UCMresponsedict['message_subject'] = 'UCMresponse'
        UCMresponsedict['http_code'] = str(HTTPcode)
        UCMresponsedict['event_uid'] = eventID
        UCMresponsestr = json.dumps(UCMresponsedict)
                    
        #UCMresponsestr = json.dumps(UCMresponsedict)
        
        print('received code: ' + str(HTTPcode))
        #publish notification of response receipt with REST API response fields if applicable
        self.vip.pubsub.publish(peer = 'pubsub', topic = 'CTAevent', headers = {}, message = UCMresponsestr )
        print('###RECEIVED A RESPONSE### relative to event #{event} from <{name}> with HTTP code <{code}> and body message : {body}'.format(event = eventID, name = self.UCMname, code = HTTPcode, body = UCMresponse))
        #return 1 if successful
        return 1
        
    #the message_target can be either the name of a single device or an array of names    
    def checkForName(self,names):
        if type(names) is list: 
            for name in names:
                if name == self.UCMname:
                    return True
            return False
        elif type(names) is str:
            if names == self.UCMname:
                return True
            else:
                return False
        elif type(names) is unicode:
            if names == self.UCMname:
                return True
            else:
                return False
        
def main(argv=sys.argv):
    '''Main method called by the eggsecutable'''
    try:
        utils.vip_main(UCMAgent)
    except Exception as e:
        _log.exception('unhandled exception')
            
if __name__== '__main__':
    #entry point for script_from_examples
    sys.exit(main())