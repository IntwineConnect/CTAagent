from __future__ import absolute_import

from volttron.platform.vip.agent import Agent, Core
from volttron.platform.agent import utils
from zmq.log.handlers import TOPIC_DELIM

from datetime import datetime
import logging
import sys

import urllib2
import socket
import json

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
                   'info_request': 'GET'   
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
              'info_request': '/info_sgd.cgi?'              
              }
    
    UCMname = 'defaultname'
    UCMip = '192.168.1.3'
    
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
        
        
        print('UCMAgent waking up and subscribing to topic: CTAevent')
        self.vip.pubsub.subscribe('pubsub','CTAevent', callback=self.forward_UCM)
        
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
        #ignore anything posted to the topic other than notifications of new events
        if messageSubject != 'new_event':
            return 0
        #if the message is meant for a different UCM
        if messageTarget != self.UCMname and messageTarget != 'all':
            return 0
        
        print('UCM proxy agent for ' + self.UCMname + ' has been asked to relay a message')
        self.vip.pubsub.publish('pubsub', 'CTAevent', headers = {}, message = '{"message_subject": "initiated"}' )
        

        eventName = mesdict.get('message_type','normal')
       
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
        
        UCMresponsedict = json.loads(UCMresponse)
        UCMresponsedict['message_target'] = 'UCMresponse'
        UCMresponsedict['http_code'] = HTTPcode
        UCMresponsedict['event_uid'] = EventID
        UCMresponsestr = json.dumps(UCMresponsedict)        
        #UCMresponsestr = json.dumps(UCMresponsedict)
        
        print('received code: ' + HTTPcode)
        #publish notification of response receipt with REST API response fields if applicable
        self.vip.pubsub.publish(peer = 'pubsub', topic = 'CTAevent', headers = {}, message = UCMresponsestr )
        
        #return 1 if successful
        return 1
        
def main(argv=sys.argv):
    '''Main method called by the eggsecutable'''
    try:
        utils.vip_main(UCMAgent)
    except Exception as e:
        _log.exception('unhandled exception')
            
if __name__== '__main__':
    #entry point for script_from_examples
    sys.exit(main())