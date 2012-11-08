'''
Copyright (c) <2012> Tarek Galal <tare2.galal@gmail.com>

Permission is hereby granted, free of charge, to any person obtaining a copy of this 
software and associated documentation files (the "Software"), to deal in the Software 
without restriction, including without limitation the rights to use, copy, modify, 
merge, publish, distribute, sublicense, and/or sell copies of the Software, and to 
permit persons to whom the Software is furnished to do so, subject to the following 
conditions:

The above copyright notice and this permission notice shall be included in all 
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED, 
INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY, FITNESS FOR 
A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT 
HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION OF 
CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE 
OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.
'''

from ConnectionIO.protocoltreenode import ProtocolTreeNode
from ConnectionIO.ioexceptions import ConnectionClosedException
from ConnectionIO.connectionengine import ConnectionEngine

from Tools.debugger import Debugger
import threading, select, time
from Tools.watime import WATime
from Auth.auth import YowsupAuth
from Tools.constants import Constants
from Interfaces.Lib.LibInterface import LibMethodInterface, LibSignalInterface
import thread
from random import randrange
import socket
import hashlib
import base64



import traceback
class YowsupConnectionManager:
	
	def __init__(self):
		Debugger.attach(self)
		self.currKeyId = 1
		self.iqId = 0
		self.verbose = True
		self.state = 0
		self.lock = threading.Lock()
		self.autoPong = True
		
		self.domain = "s.whatsapp.net"
	
		#self.methodInterface = MethodInterface(authenticatedSocketConnection.getId())
		#self.signalInterface = SignalInterface(authenticatedSocketConnection.getId())
		self.readerThread = None
		
		self.methodInterface = LibMethodInterface()
		self.signalInterface = LibSignalInterface()
		self.readerThread = ReaderThread()
		self.readerThread.setSignalInterface(self.signalInterface)
		

		self.bindMethods()
	
	
	def setInterfaces(self, signalInterface, methodInterface):
		self.methodInterface = methodInterface
		self.signalInterface = signalInterface
		
		self.readerThread.setSignalInterface(self.signalInterface)
		
		self.bindMethods()
		
	def getSignalsInterface(self):
		return self.signalInterface
	
	def getMethodsInterface(self):
		return self.methodInterface

	def setAutoPong(self, autoPong):
		self.autoPong = self.readerThread.autoPong = autoPong
	
	def startReader(self):
		if self.readerThread.isAlive():
			self._d("Reader already started")
			return 0

		self._d("starting reader")
		try:
			self.readerThread.start()
			self._d("started")
		except RuntimeError:
			self._d("Reader already started before")
			self.readerThread.sendDisconnected()
			return 0
		
		return 1
	
	
	def block(self):
		self.readerThread.join()

	def bindMethods(self):
		self.methodInterface.registerCallback("getVersion", lambda: Constants.v)
		self.methodInterface.registerCallback("message_send",self.sendText)
		self.methodInterface.registerCallback("message_imageSend",self.sendImage)
		self.methodInterface.registerCallback("message_audioSend",self.sendAudio)
		self.methodInterface.registerCallback("message_videoSend",self.sendVideo)
		self.methodInterface.registerCallback("message_locationSend",self.sendLocation)
		self.methodInterface.registerCallback("message_vcardSend",self.sendVCard)

		self.methodInterface.registerCallback("message_ack",self.sendMessageReceipt)

		self.methodInterface.registerCallback("notification_ack", self.sendNotificationReceipt)
		
		self.methodInterface.registerCallback("clientconfig_send",self.sendClientConfig)

		self.methodInterface.registerCallback("delivered_ack",self.sendDeliveredReceiptAck)

		self.methodInterface.registerCallback("visible_ack",self.sendVisibleReceiptAck)

		self.methodInterface.registerCallback("ping",self.sendPing)
		self.methodInterface.registerCallback("pong",self.sendPong)

		self.methodInterface.registerCallback("typing_send",self.sendTyping)
		self.methodInterface.registerCallback("typing_paused",self.sendPaused)

		self.methodInterface.registerCallback("subject_ack",self.sendSubjectReceived)

		self.methodInterface.registerCallback("group_getInfo",self.sendGetGroupInfo)
		self.methodInterface.registerCallback("group_create",self.sendCreateGroupChat)
		self.methodInterface.registerCallback("group_addParticipants",self.sendAddParticipants)
		self.methodInterface.registerCallback("group_removeParticipants",self.sendRemoveParticipants)
		self.methodInterface.registerCallback("group_end",self.sendEndGroupChat)
		self.methodInterface.registerCallback("group_setSubject",self.sendSetGroupSubject)
		self.methodInterface.registerCallback("group_setPicture", self.sendSetPicture)
		self.methodInterface.registerCallback("group_getPicture", self.sendGetPicture)
		
		self.methodInterface.registerCallback("group_getParticipants",self.sendGetParticipants)

		self.methodInterface.registerCallback("picture_get",self.sendGetPicture)
		self.methodInterface.registerCallback("picture_getIds",self.sendGetPictureIds)

		self.methodInterface.registerCallback("contact_getProfilePicture", self.sendGetPicture)

		self.methodInterface.registerCallback("status_update",self.sendChangeStatus)

		self.methodInterface.registerCallback("presence_request",self.getLastOnline)
		#self.methodInterface.registerCallback("presence_unsubscribe",self.sendUnsubscribe)#@@TODO implement method
		self.methodInterface.registerCallback("presence_subscribe",self.sendSubscribe)
		self.methodInterface.registerCallback("presence_sendAvailableForChat",self.sendAvailableForChat)
		self.methodInterface.registerCallback("presence_sendAvailable",self.sendAvailable)
		self.methodInterface.registerCallback("presence_sendUnavailable",self.sendUnavailable)
		
		
		self.methodInterface.registerCallback("profile_setPicture", self.sendSetProfilePicture)
		self.methodInterface.registerCallback("profile_getPicture", self.sendGetProfilePicture)
		
		self.methodInterface.registerCallback("profile_setStatus", self.sendChangeStatus)

		self.methodInterface.registerCallback("disconnect", self.disconnect)
		self.methodInterface.registerCallback("ready", self.startReader)
		
		self.methodInterface.registerCallback("auth_login", self.auth )
		#self.methodInterface.registerCallback("auth_login", self.auth)


	def disconnect(self, reason=""):
		self._d("Disconnect sequence initiated")
		self._d("Sending term signal to reader thread")
		if self.readerThread.isAlive():
			self.readerThread.terminate()
			self._d("Shutting down socket")
			self.socket.close()
			self._d("Waiting for readerThread to die")
			self.readerThread.join()
		self._d("Disconnected!")
		self._d(reason)
		self.state = 0
		self.readerThread.sendDisconnected(reason)


	def getConnection(self):
		return self.socket

	def triggerEvent(self, eventName, stanza):
		if self.events.has_key(eventName) and self.events[eventName] is not None:
			self.events[eventName](stanza)

	def bindEvent(self, eventName, callback):
		if self.events.has_key(eventName):
			self.events[eventName] = callback

	##########################################################

	def _writeNode(self, node):
		if self.state == 2:
			try:
				self.out.write(node)
				return True
			except ConnectionClosedException:
				self._d("CONNECTION DOWN")
				#self.disconnect("closed")
				if self.readerThread.isAlive():
					self.readerThread.terminate()
					self.readerThread.join()
					self.readerThread.sendDisconnected("closed")
		
		return False
		
	def onDisconnected(self):
		self._d("Setting state to 0")
		self.state = 0

	def auth(self, username, password):
		self._d(">>>>>>>>                         AUTH CALLED")
		username = str(username)
		password = str(password)
		#traceback.print_stack()
		
		self.lock.acquire()
		if self.state == 0 :
		
			
			if self.readerThread.isAlive():
				raise Exception("TWO READER THREADS ON BOARD!!")
			
			self.readerThread = ReaderThread()
			self.readerThread.autoPong = self.autoPong
			self.readerThread.setSignalInterface(self.signalInterface)
			yAuth = YowsupAuth(ConnectionEngine())
			try:
				self.state = 1
				connection = yAuth.authenticate(username, password, Constants.domain, Constants.resource)
			except socket.gaierror:
				self._d("DNS ERROR")
				self.readerThread.sendDisconnected("dns")
				#self.signalInterface.send("disconnected", ("dns",))
				self.lock.release()
				self.state = 0
				
				return 0
			except socket.error:
				self._d("Socket error, connection timed out")
				self.readerThread.sendDisconnected("closed")
				#self.signalInterface.send("disconnected", ("closed",))
				self.lock.release()
				self.state = 0
				
				return 0
			except ConnectionClosedException:
				self._d("Conn closed Exception")
				self.readerThread.sendDisconnected("closed")
				#self.signalInterface.send("disconnected", ("closed",))
				self.lock.release()
				self.state = 0
				
				return 0
		
			if not connection:
				self.state = 0
				self.signalInterface.send("auth_fail", (username, "invalid"))
				self.lock.release()
				return 0
			
			self.state = 2
			
			
	
			self.socket = connection
			self.jid = self.socket.jid
			#@@TODO REPLACE PROPERLY
			self.out = self.socket.writer
			
			self.readerThread.setSocket(self.socket)
			self.readerThread.disconnectedCallback = self.onDisconnected
			self.readerThread.onPing = self.sendPong
			self.readerThread.ping = self.sendPing
			
	
			self.signalInterface.send("auth_success", (username,))
		self.lock.release()
			
		
		
		
	def sendTyping(self,jid):
		self._d("SEND TYPING TO JID")
		composing = ProtocolTreeNode("composing",{"xmlns":"http://jabber.org/protocol/chatstates"})
		message = ProtocolTreeNode("message",{"to":jid,"type":"chat"},[composing]);
		self._writeNode(message);



	def sendPaused(self,jid):
		self._d("SEND PAUSED TO JID")
		composing = ProtocolTreeNode("paused",{"xmlns":"http://jabber.org/protocol/chatstates"})
		message = ProtocolTreeNode("message",{"to":jid,"type":"chat"},[composing]);
		self._writeNode(message);



	def getSubjectMessage(self,to,msg_id,child):
		messageNode = ProtocolTreeNode("message",{"to":to,"type":"subject","id":msg_id},[child]);

		return messageNode

	def sendSubjectReceived(self,to,msg_id):
		self._d("Sending subject recv receipt")
		receivedNode = ProtocolTreeNode("received",{"xmlns": "urn:xmpp:receipts"});
		messageNode = self.getSubjectMessage(to,msg_id,receivedNode);
		self._writeNode(messageNode);



	def sendMessageReceipt(self, jid, msgId):
		self.sendReceipt(jid, "chat", msgId)

	def sendNotificationReceipt(self, jid, notificationId):
		self.sendReceipt(jid, "notification", notificationId)

	def sendReceipt(self,jid,mtype,mid):
		self._d("sending message received to "+jid+" - type:"+mtype+" - id:"+mid)
		receivedNode = ProtocolTreeNode("received",{"xmlns": "urn:xmpp:receipts"})
		messageNode = ProtocolTreeNode("message",{"to":jid,"type":mtype,"id":mid},[receivedNode]);
		self._writeNode(messageNode);


	def sendDeliveredReceiptAck(self,to,msg_id):
		self._writeNode(self.getReceiptAck(to,msg_id,"delivered"));

	def sendVisibleReceiptAck(self,to,msg_id):
		self._writeNode(self.getReceiptAck(to,msg_id,"visible"));

	def getReceiptAck(self,to,msg_id,receiptType):
		ackNode = ProtocolTreeNode("ack",{"xmlns":"urn:xmpp:receipts","type":receiptType})
		messageNode = ProtocolTreeNode("message",{"to":to,"type":"chat","id":msg_id},[ackNode]);
		return messageNode;

	def makeId(self,prefix):
		self.iqId += 1
		idx = ""
		if self.verbose:
			idx += prefix + str(self.iqId);
		else:
			idx = "%x" % self.iqId

		return idx

	def sendPing(self):

		idx = self.makeId("ping_")

		self.readerThread.requests[idx] = self.readerThread.parsePingResponse;

		pingNode = ProtocolTreeNode("ping",{"xmlns":"w:p"});
		iqNode = ProtocolTreeNode("iq",{"id":idx,"type":"get","to":self.domain},[pingNode]);
		self._writeNode(iqNode);
		return idx


	def sendPong(self,idx):
		iqNode = ProtocolTreeNode("iq",{"type":"result","to":self.domain,"id":idx})
		self._writeNode(iqNode);

	def getLastOnline(self,jid):

		if len(jid.split('-')) == 2 or jid == "Server@s.whatsapp.net": #SUPER CANCEL SUBSCRIBE TO GROUP AND SERVER
			return

		self.sendSubscribe(jid);

		self._d("presence request Initiated for %s"%(jid))
		idx = self.makeId("last_")
		self.readerThread.requests[idx] = self.readerThread.parseLastOnline;

		query = ProtocolTreeNode("query",{"xmlns":"jabber:iq:last"});
		iqNode = ProtocolTreeNode("iq",{"id":idx,"type":"get","to":jid},[query]);
		self._writeNode(iqNode)


	def sendIq(self):
		node = ProtocolTreeNode("iq",{"to":"g.us","type":"get","id":str(int(time.time()))+"-0"},None,'expired');
		self._writeNode(node);

		node = ProtocolTreeNode("iq",{"to":"s.whatsapp.net","type":"set","id":str(int(time.time()))+"-1"},None,'expired');
		self._writeNode(node);

	def sendAvailableForChat(self, pushname):
		presenceNode = ProtocolTreeNode("presence",{"name":pushname})
		self._writeNode(presenceNode);

	def sendAvailable(self):
		presenceNode = ProtocolTreeNode("presence",{"type":"available"})
		self._writeNode(presenceNode);


	def sendUnavailable(self):
		presenceNode = ProtocolTreeNode("presence",{"type":"unavailable"})
		self._writeNode(presenceNode);


	def sendSubscribe(self,to):
		presenceNode = ProtocolTreeNode("presence",{"type":"subscribe","to":to});

		self._writeNode(presenceNode);


	def mediaNode(fn):
		def wrapped(self, *args):
				mediaType = fn(self, *args)
				
				
				url = args[1]
				name = args[2]
				size = args[3]
				
				mmNode = ProtocolTreeNode("media", {"xmlns":"urn:xmpp:whatsapp:mms","type":mediaType,"file":name,"size":size,"url":url},None, args[4:][0] if args[4:] else None);
				return mmNode
			
		return wrapped
	
	def sendMessage(fn):
			def wrapped(self, *args):
				node = fn(self, *args)
				jid = args[0]
				messageNode = self.getMessageNode(jid, node)
				
				self._writeNode(messageNode);

				return messageNode.getAttributeValue("id")
			
			return wrapped
		
	def sendChangeStatus(self,status):
		self._d("updating status to: %s"%(status))
		
		bodyNode = ProtocolTreeNode("body",None,None,status.encode('utf-8'));
		messageNode = self.getMessageNode("s.us",bodyNode)
		self._writeNode(messageNode);
		
		return messageNode.getAttributeValue("id")
		
		
	
	@sendMessage
	def sendText(self,jid, content):
		return ProtocolTreeNode("body",None,None,content.encode('utf-8'));

	@sendMessage
	@mediaNode
	def sendImage(self, jid, url, name, size, preview):
		return "image"
	
	@sendMessage
	@mediaNode
	def sendVideo(self, jid, url, name, size, preview):
		return "video"
	
	@sendMessage
	@mediaNode
	def sendAudio(self, jid, url, name, size):
		return "audio"

	@sendMessage
	def sendLocation(self, jid, latitude, longitude, preview):
		self._d("sending location (" + latitude + ":" + longitude + ")")

		return ProtocolTreeNode("media", {"xmlns":"urn:xmpp:whatsapp:mms","type":"location","latitude":latitude,"longitude":longitude},None,preview)
		
	@sendMessage
	def sendVCard(self, jid, data, name):
		
		cardNode = ProtocolTreeNode("vcard",{"name":name},None,data);
		return ProtocolTreeNode("media", {"xmlns":"urn:xmpp:whatsapp:mms","type":"vcard"},[cardNode])


	def sendClientConfig(self,sound,pushID,preview,platform):
		idx = self.makeId("config_");
		configNode = ProtocolTreeNode("config",{"xmlns":"urn:xmpp:whatsapp:push","sound":sound,"id":pushID,"preview":"1" if preview else "0","platform":platform})
		iqNode = ProtocolTreeNode("iq",{"id":idx,"type":"set","to":self.domain},[configNode]);

		self._writeNode(iqNode);



	def sendGetGroupInfo(self,jid):
		self._d("getting group info for %s"%(jid))
		idx = self.makeId("get_g_info_")
		self.readerThread.requests[idx] = self.readerThread.parseGroupInfo;

		queryNode = ProtocolTreeNode("query",{"xmlns":"w:g"})
		iqNode = ProtocolTreeNode("iq",{"id":idx,"type":"get","to":jid},[queryNode])

		self._writeNode(iqNode)

	def sendCreateGroupChat(self,subject):
		self._d("creating group: %s"%(subject))
		idx = self.makeId("create_group_")
		self.readerThread.requests[idx] = self.readerThread.parseGroupCreated;

		queryNode = ProtocolTreeNode("group",{"xmlns":"w:g","action":"create","subject":subject})
		iqNode = ProtocolTreeNode("iq",{"id":idx,"type":"set","to":"g.us"},[queryNode])

		self._writeNode(iqNode)


	def sendAddParticipants(self,gjid,participants):
		self._d("opening group: %s"%(gjid))
		self._d("adding participants: %s"%(participants))
		idx = self.makeId("add_group_participants_")
		self.readerThread.requests[idx] = self.readerThread.parseAddedParticipants;
		parts = participants.split(',')
		innerNodeChildren = []
		i = 0;
		for part in parts:
			if part != "undefined":
				innerNodeChildren.append( ProtocolTreeNode("participant",{"jid":part}) )
			i = i + 1;

		queryNode = ProtocolTreeNode("add",{"xmlns":"w:g"},innerNodeChildren)
		iqNode = ProtocolTreeNode("iq",{"id":idx,"type":"set","to":gjid},[queryNode])

		self._writeNode(iqNode)


	def sendRemoveParticipants(self,gjid,participants):
		self._d("opening group: %s"%(gjid))
		self._d("removing participants: %s"%(participants))
		idx = self.makeId("remove_group_participants_")
		self.readerThread.requests[idx] = self.readerThread.parseRemovedParticipants;
		parts = participants.split(',')
		innerNodeChildren = []
		i = 0;
		for part in parts:
			if part != "undefined":
				innerNodeChildren.append( ProtocolTreeNode("participant",{"jid":part}) )
			i = i + 1;

		queryNode = ProtocolTreeNode("remove",{"xmlns":"w:g"},innerNodeChildren)
		iqNode = ProtocolTreeNode("iq",{"id":idx,"type":"set","to":gjid},[queryNode])

		self._writeNode(iqNode)


	def sendEndGroupChat(self,gjid):
		self._d("removing group: %s"%(gjid))
		idx = self.makeId("leave_group_")
		self.readerThread.requests[idx] = self.readerThread.parseGroupEnded;

		innerNodeChildren = []
		innerNodeChildren.append( ProtocolTreeNode("group",{"id":gjid}) )

		queryNode = ProtocolTreeNode("leave",{"xmlns":"w:g"},innerNodeChildren)
		iqNode = ProtocolTreeNode("iq",{"id":idx,"type":"set","to":"g.us"},[queryNode])

		self._writeNode(iqNode)

	def sendSetGroupSubject(self,gjid,subject):
		subject = subject.encode('utf-8')
		#self._d("setting group subject of " + gjid + " to " + subject)
		idx = self.makeId("set_group_subject_")
		self.readerThread.requests[idx] = self.readerThread.parseGroupSubject

		queryNode = ProtocolTreeNode("subject",{"xmlns":"w:g","value":subject})
		iqNode = ProtocolTreeNode("iq",{"id":idx,"type":"set","to":gjid},[queryNode]);

		self._writeNode(iqNode)


	def sendGetParticipants(self,jid):
		idx = self.makeId("get_participants_")
		self.readerThread.requests[idx] = self.readerThread.parseParticipants

		listNode = ProtocolTreeNode("list",{"xmlns":"w:g"})
		iqNode = ProtocolTreeNode("iq",{"id":idx,"type":"get","to":jid},[listNode]);

		self._writeNode(iqNode)


	def sendGetPicture(self,jid):
		self._d("GETTING PICTURE FROM " + jid)
		idx = self.makeId("get_picture_")

		#@@TODO, ?!
		self.readerThread.requests[idx] =  self.readerThread.parseGetPicture

		listNode = ProtocolTreeNode("picture",{"xmlns":"w:profile:picture","type":"image"})
		iqNode = ProtocolTreeNode("iq",{"id":idx,"to":jid,"type":"get"},[listNode]);

		self._writeNode(iqNode)



	def sendGetPictureIds(self,jids):
		idx = self.makeId("get_picture_ids_")
		self.readerThread.requests[idx] = self.readerThread.parseGetPictureIds

		parts = jids.split(',')
		innerNodeChildren = []
		i = 0;
		for part in parts:
			if part != "undefined":
				innerNodeChildren.append( ProtocolTreeNode("user",{"jid":part}) )
			i = i + 1;

		queryNode = ProtocolTreeNode("list",{"xmlns":"w:profile:picture"},innerNodeChildren)
		iqNode = ProtocolTreeNode("iq",{"id":idx,"type":"get"},[queryNode])

		self._writeNode(iqNode)

	
	def sendGetProfilePicture(self):
		return self.sendGetPicture(self.jid)
	
	def sendSetProfilePicture(self, filepath):
		return self.sendSetPicture(self.jid, filepath)
	
	def sendSetPicture(self, jid, imagePath):

		f = open(imagePath, 'r')
		imageData = f.read()
		imageData = bytearray(imageData)
		f.close()
		
		idx = self.makeId("set_picture_")
		self.readerThread.requests[idx] = self.readerThread.parseSetPicture

		listNode = ProtocolTreeNode("picture",{"xmlns":"w:profile:picture","type":"image"}, None, imageData)

		iqNode = ProtocolTreeNode("iq",{"id":idx,"to":jid,"type":"set"},[listNode])

		self._writeNode(iqNode)

	


	def getMessageNode(self, jid, child):
			requestNode = None;
			serverNode = ProtocolTreeNode("server",None);
			xNode = ProtocolTreeNode("x",{"xmlns":"jabber:x:event"},[serverNode]);
			childCount = (0 if requestNode is None else 1) +2;
			messageChildren = [None]*childCount;
			i = 0;
			if requestNode is not None:
				messageChildren[i] = requestNode;
				i+=1;
			#System.currentTimeMillis() / 1000L + "-"+1
			messageChildren[i] = xNode;
			i+=1;
			messageChildren[i]= child;
			i+=1;

			msgId = str(int(time.time()))+"-"+ str(self.currKeyId)
			messageNode = ProtocolTreeNode("message",{"to":jid,"type":"chat","id":msgId},messageChildren)

			self.currKeyId += 1


			return messageNode;


class ReaderThread(threading.Thread):
	def __init__(self):
		Debugger.attach(self);

		self.signalInterface = None
		#self.socket = connection
		self.terminateRequested = False
		self.disconnectedSent = False
		self.timeout = 240
		self.selectTimeout = 3
		self.requests = {};
		self.lock = threading.Lock()
		self.disconnectedCallback = None
		self.autoPong = True
		self.onPing = self.ping = None

		self.lastPongTime = int(time.time())
		super(ReaderThread,self).__init__();

		self.daemon = True
	def setSocket(self, connection):
		self.socket = connection

	def setSignalInterface(self, signalInterface):
		self.signalInterface = signalInterface

	def terminate(self):
		self._d("attempting to exit gracefully")
		self.terminateRequested = True
		

	def sendDisconnected(self, reason="noreason"):
		self._d("Sending disconnected because of %s" % reason)
		self.lock.acquire()
		if not self.disconnectedSent:
			self.disconnectedSent = True
			if self.disconnectedCallback:
				self.disconnectedCallback()
			self.lock.release()
			self.signalInterface.send("disconnected", (reason,))

	def run(self):
		self._d("Read thread startedX");
		while True:

			
			countdown = self.timeout - ((int(time.time()) - self.lastPongTime))
			
			remainder = countdown % self.selectTimeout
			countdown = countdown - remainder
					
			if countdown <= 0:
				self._d("No hope, dying!")
				self.sendDisconnected("closed")
				return
			else:
				if countdown % (self.selectTimeout*10) == 0 or countdown < 11:
					self._d("Waiting, time to die: T-%i seconds" % countdown )
					
				if self.timeout-countdown == 210 and self.ping and self.autoPong:
					self.ping()

				self.selectTimeout = 1 if countdown < 11 else 3


			try:
				ready = select.select([self.socket.reader.rawIn], [], [], self.selectTimeout)
			except:
				self._d("Error in ready")
				raise
				return
			
			if self.terminateRequested:
				return

			if ready[0]:
				try:
					node = self.socket.reader.nextTree()
				except ConnectionClosedException:
					#print traceback.format_exc()
					self._d("Socket closed, got 0 bytes!")
					#self.signalInterface.send("disconnected", ("closed",))
					self.sendDisconnected("closed")
					return

				self.lastPongTime = int(time.time());

				if node is not None:
					if ProtocolTreeNode.tagEquals(node,"iq"):
						iqType = node.getAttributeValue("type")
						idx = node.getAttributeValue("id")

						if iqType is None:
							raise Exception("iq doesn't have type")

						if iqType == "result":
							if self.requests.has_key(idx):
								self.requests[idx](node)
								del self.requests[idx]
							elif idx.startswith(self.connection.user):
								accountNode = node.getChild(0)
								ProtocolTreeNode.require(accountNode,"account")
								kind = accountNode.getAttributeValue("kind")

								if kind == "paid":
									self.connection.account_kind = 1
								elif kind == "free":
									self.connection.account_kind = 0
								else:
									self.connection.account_kind = -1

								expiration = accountNode.getAttributeValue("expiration")

								if expiration is None:
									raise Exception("no expiration")

								try:
									self.connection.expire_date = long(expiration)
								except ValueError:
									raise IOError("invalid expire date %s"%(expiration))

								self.eventHandler.onAccountChanged(self.connection.account_kind,self.connection.expire_date)
						elif iqType == "error":
							if self.requests.has_key(idx):
								self.requests[idx](node)
								del self.requests[idx]
						elif iqType == "get":
							childNode = node.getChild(0)
							if ProtocolTreeNode.tagEquals(childNode,"ping"):
								if self.autoPong:
									self.onPing(idx)
									
								self.signalInterface.send("ping", (idx,))	
							elif ProtocolTreeNode.tagEquals(childNode,"query") and jid is not None and "http://jabber.org/protocol/disco#info" == childNode.getAttributeValue("xmlns"):
								pin = childNode.getAttributeValue("pin");
								timeoutString = childNode.getAttributeValue("timeout");
								try:
									timeoutSeconds = int(timeoutString) if timeoutString is not None else None
								except ValueError:
									raise Exception("relay-iq exception parsing timeout %s "%(timeoutString))

								if pin is not None:
									self.eventHandler.onRelayRequest(pin,timeoutSeconds,idx)
						elif iqType == "set":
							childNode = node.getChild(0)
							if ProtocolTreeNode.tagEquals(childNode,"query"):
								xmlns = childNode.getAttributeValue("xmlns")

								if xmlns == "jabber:iq:roster":
									itemNodes = childNode.getAllChildren("item");
									ask = ""
									for itemNode in itemNodes:
										jid = itemNode.getAttributeValue("jid")
										subscription = itemNode.getAttributeValue("subscription")
										ask = itemNode.getAttributeValue("ask")
						else:
							raise Exception("Unkown iq type %s"%(iqType))

					elif ProtocolTreeNode.tagEquals(node,"presence"):
						xmlns = node.getAttributeValue("xmlns")
						jid = node.getAttributeValue("from")

						if (xmlns is None or xmlns == "urn:xmpp") and jid is not None:
							presenceType = node.getAttributeValue("type")
							if presenceType == "unavailable":
								self.signalInterface.send("presence_unavailable", (jid,))
							elif presenceType is None or presenceType == "available":
								self.signalInterface.send("presence_available", (jid,))

						elif xmlns == "w" and jid is not None:
							status = node.getAttributeValue("status")

							if status == "dirty":
								#categories = self.parseCategories(node); #@@TODO, send along with signal
								self._d("WILL SEND DIRTY")
								self.signalInterface.send("status_dirty")
								self._d("SENT DIRTY")

					elif ProtocolTreeNode.tagEquals(node,"message"):
						self.parseMessage(node)
					

		self._d("Reader thread terminating now!")
					
	def parseOfflineMessageStamp(self,stamp):

		watime = WATime();
		parsed = watime.parseIso(stamp)
		local = watime.utcToLocal(parsed)
		stamp = watime.datetimeToTimestamp(local)

		return stamp


	def parsePingResponse(self, node):
		idx = node.getAttributeValue("id")
		self.lastPongTime = int(time.time())
		
		

	def parseLastOnline(self,node):
		jid = node.getAttributeValue("from");
		firstChild = node.getChild(0);

		if "error" in firstChild.toString():
			return

		ProtocolTreeNode.require(firstChild,"query");
		seconds = firstChild.getAttributeValue("seconds");
		status = None
		status = firstChild.data #@@TODO discarded?

		try:
			if seconds is not None and jid is not None:
				self.signalInterface.send("presence_updated", (jid, int(seconds)))
		except:
			self._d("Ignored exception in handleLastOnline "+ sys.exc_info()[1])

	def parseGroupInfo(self,node):
		jid = node.getAttributeValue("from");
		groupNode = node.getChild(0)
		if "error code" in groupNode.toString():
			self.signalInterface.send("group_infoError",(0,)) #@@TODO replace with real error code
		else:
			ProtocolTreeNode.require(groupNode,"group")
			#gid = groupNode.getAttributeValue("id")
			owner = groupNode.getAttributeValue("owner")
			subject = groupNode.getAttributeValue("subject")
			subjectT = groupNode.getAttributeValue("s_t")
			subjectOwner = groupNode.getAttributeValue("s_o")
			creation = groupNode.getAttributeValue("creation")
		
			self.signalInterface.send("group_gotInfo",(jid, owner, subject, subjectOwner, int(subjectT),int(creation)))

	def parseAddedParticipants(self, node):
		jid = node.getAttributeValue("from");
		self.signalInterface.send("group_addParticipantsSuccess", (jid,))


	def parseRemovedParticipants(self,node): #fromm, successVector=None,failTable=None
		jid = node.getAttributeValue("from");
		self._d("handleRemovedParticipants DONE!");
		self.signalInterface.send("group_removeParticipantsSuccess", (jid,))

	def parseGroupCreated(self,node):
		jid = node.getAttributeValue("from");
		groupNode = node.getChild(0)
		
		if ProtocolTreeNode.tagEquals(groupNode,"error"):
			errorCode = groupNode.getAttributeValue("code")
			self.signalInterface.send("group_createFail", (errorCode,))
			return
		
		
		ProtocolTreeNode.require(groupNode,"group")
		group_id = groupNode.getAttributeValue("id")
		self.signalInterface.send("group_createSuccess", (jid, group_id))

	def parseGroupEnded(self,node):
		jid = node.getAttributeValue("from");
		self.signalInterface.send("group_endSuccess", (jid,))

	def parseGroupSubject(self,node):
		jid = node.getAttributeValue("from");
		self.signalInterface.send("group_setSubjectSuccess", (jid,))

	def parseParticipants(self,node):
		jid = node.getAttributeValue("from");
		children = node.getAllChildren("participant");
		jids = []
		for c in children:
			jids.append(c.getAttributeValue("jid"))

		self.signalInterface.send("group_gotParticipants", (jid, jids))

	#@@TODO PICTURE STUFF


	def createTmpFile(self, identifier ,data):
		tmpDir = "/tmp"
		
		filename = "%s/wazapp_%i_%s" % (tmpDir, randrange(0,100000) , hashlib.md5(identifier).hexdigest())
		
		tmpfile = open(filename, "w")
		tmpfile.write(data)
		tmpfile.close()

		return filename
	
	def parseGetPicture(self,node):
		jid = node.getAttributeValue("from");
		if "error code" in node.toString():
			return;

		data = node.getChild("picture").toString()
		if data is not None:
			n = data.find(">") +2
			data = data[n:]
			data = data.replace("</picture>","")

			tmp = self.createTmpFile("picture_%s" % jid, data)
			
			try:
				jid.index('-')
				self.signalInterface.send("group_gotPicture", (jid, tmp))
			except ValueError:
				self.signalInterface.send("contact_gotProfilePicture", (jid, tmp))


	def parseGetPictureIds(self,node):
		jid = node.getAttributeValue("from");
		groupNode = node.getChild("list")
		#self._d(groupNode.toString())
		children = groupNode.getAllChildren("user");
		jids = []
		for c in children:
			if c.getAttributeValue("id") is not None:
				self.signalInterface.send("contact_gotProfilePictureId", (c.getAttributeValue("jid"), c.getAttributeValue("id")))

	def parseSetPicture(self,node):
		jid = node.getAttributeValue("from");
		picNode = node.getChild("picture")
		
		try:
			jid.index('-')
			
			if picNode is None:
				self.signalInterface.send("group_setPictureError", (jid,0)) #@@TODO SEND correct error code
			else:
				self.signalInterface.send("group_setPictureSuccess", (jid,))
		except ValueError:
			if picNode is None:
				self.signalInterface.send("profile_setPictureError", (0,)) #@@TODO SEND correct error code
			else:
				self.signalInterface.send("profile_setPictureSuccess")
	
	def parseMessage(self,messageNode):


		bodyNode = messageNode.getChild("body");
		newSubject = "" if bodyNode is None else bodyNode.data;
		msgData = None
		timestamp = long(time.time()*1000)
		isGroup = False
		
		if newSubject.find("New version of WhatsApp Messenger is now available")>-1:
			self._d("Rejecting whatsapp server message")
			return #REJECT THIS FUCKING MESSAGE!


		fromAttribute = messageNode.getAttributeValue("from");

		try:
			fromAttribute.index('-')
			isGroup = True
		except:
			pass

		author = messageNode.getAttributeValue("author");
		#@@TODO reactivate blocked contacts check from client
		'''if fromAttribute is not None and fromAttribute in self.eventHandler.blockedContacts:
			self._d("CONTACT BLOCKED!")
			return

		if author is not None and author in self.eventHandler.blockedContacts:
			self._d("CONTACT BLOCKED!")
			return
		'''

		pushName = None
		notifNode = messageNode.getChild("notify")
		if notifNode is not None:
			pushName = notifNode.getAttributeValue("name");
			pushName = pushName.decode("utf8")


		msgId = messageNode.getAttributeValue("id");
		attribute_t = messageNode.getAttributeValue("t");

		typeAttribute = messageNode.getAttributeValue("type");

		if typeAttribute == "error":
			errorCode = 0;
			errorNodes = messageNode.getAllChildren("error");
			for errorNode in errorNodes:
				codeString = errorNode.getAttributeValue("code")
				try:
					errorCode = int(codeString);
				except ValueError:
					'''catch value error'''
				self.signalInterface.send("message_error", (msgId, fromAttribute, errorCode))

		elif typeAttribute == "notification":

			receiptRequested = False;
			pictureUpdated = None

			pictureUpdated = messageNode.getChild("notification").getAttributeValue("type");

			wr = None
			wr = messageNode.getChild("request").getAttributeValue("xmlns");
			if wr == "urn:xmpp:receipts":
				receiptRequested = True
				
			if pictureUpdated == "picture":
				bodyNode = messageNode.getChild("notification").getChild("set") or messageNode.getChild("notification").getChild("delete")

				if isGroup:

					self.signalInterface.send("notification_groupPictureUpdated",(bodyNode.getAttributeValue("jid"), bodyNode.getAttributeValue("author"), timestamp, msgId, receiptRequested))
				else:
					self.signalInterface.send("notification_contactProfilePictureUpdated",(bodyNode.getAttributeValue("jid"), timestamp, msgId, receiptRequested))

			else:
				addSubject = None
				removeSubject = None
				author = None

				bodyNode = messageNode.getChild("notification").getChild("add");
				if bodyNode is not None:
					addSubject = bodyNode.getAttributeValue("jid");
					author = bodyNode.getAttributeValue("author") or addSubject

				bodyNode = messageNode.getChild("notification").getChild("remove");
				if bodyNode is not None:
					removeSubject = bodyNode.getAttributeValue("jid");
					author = bodyNode.getAttributeValue("author") or removeSubject

				if addSubject is not None:
					
					self.signalInterface.send("notification_groupParticipantAdded", (fromAttribute, addSubject, author, timestamp, msgId, receiptRequested))
					
				if removeSubject is not None:
					self.signalInterface.send("notification_groupParticipantRemoved", (fromAttribute, removeSubject, author, timestamp, msgId, receiptRequested))


		elif typeAttribute == "subject":
			receiptRequested = False;
			requestNodes = messageNode.getAllChildren("request");
			for requestNode in requestNodes:
				if requestNode.getAttributeValue("xmlns") == "urn:xmpp:receipts":
					receiptRequested = True;

			bodyNode = messageNode.getChild("body");
			newSubject = None if bodyNode is None else bodyNode.data;
			
			if newSubject is not None:
				self.signalInterface.send("group_subjectReceived",(msgId, fromAttribute, author, newSubject, int(attribute_t),  receiptRequested))

		elif typeAttribute == "chat":
			wantsReceipt = False;
			messageChildren = [] if messageNode.children is None else messageNode.children

			for childNode in messageChildren:
				if ProtocolTreeNode.tagEquals(childNode,"request"):
					wantsReceipt = True;
				if ProtocolTreeNode.tagEquals(childNode,"composing"):
						self.signalInterface.send("contact_typing", (fromAttribute,))
				elif ProtocolTreeNode.tagEquals(childNode,"paused"):
						self.signalInterface.send("contact_paused",(fromAttribute,))

				elif ProtocolTreeNode.tagEquals(childNode,"media") and msgId is not None:
	
					self._d("MULTIMEDIA MESSAGE!");
					
					mediaUrl = messageNode.getChild("media").getAttributeValue("url");
					mediaType = messageNode.getChild("media").getAttributeValue("type")
					mediaSize = messageNode.getChild("media").getAttributeValue("size")
					encoding = messageNode.getChild("media").getAttributeValue("encoding")
					mediaPreview = None


					if mediaType == "image":
						mediaPreview = messageNode.getChild("media").data
						
						if encoding == "raw" and mediaPreview:
							mediaPreview = base64.b64encode(mediaPreview)

						if isGroup:
							self.signalInterface.send("group_imageReceived", (msgId, fromAttribute, author, mediaPreview, mediaUrl, mediaSize, wantsReceipt))
						else:
							self.signalInterface.send("image_received", (msgId, fromAttribute, mediaPreview, mediaUrl, mediaSize,  wantsReceipt))

					elif mediaType == "video":
						mediaPreview = messageNode.getChild("media").data
						
						if encoding == "raw" and mediaPreview:
							mediaPreview = base64.b64encode(mediaPreview)

						if isGroup:
							self.signalInterface.send("group_videoReceived", (msgId, fromAttribute, author, mediaPreview, mediaUrl, mediaSize, wantsReceipt))
						else:
							self.signalInterface.send("video_received", (msgId, fromAttribute, mediaPreview, mediaUrl, mediaSize, wantsReceipt))

					elif mediaType == "audio":
						mediaPreview = messageNode.getChild("media").data

						if isGroup:
							self.signalInterface.send("group_audioReceived", (msgId, fromAttribute, author, mediaUrl, mediaSize, wantsReceipt))
						else:
							self.signalInterface.send("audio_received", (msgId, fromAttribute, mediaUrl, mediaSize, wantsReceipt))

					elif mediaType == "location":
						mlatitude = messageNode.getChild("media").getAttributeValue("latitude")
						mlongitude = messageNode.getChild("media").getAttributeValue("longitude")
						name = messageNode.getChild("media").getAttributeValue("name")
						mediaPreview = messageNode.getChild("media").data
						
						if encoding == "raw" and mediaPreview:
							mediaPreview = base64.b64encode(mediaPreview)

						if isGroup:
							self.signalInterface.send("group_locationReceived", (msgId, fromAttribute, author, name or "", mediaPreview, mlatitude, mlongitude, wantsReceipt))
						else:
							self.signalInterface.send("location_received", (msgId, fromAttribute, name or "", mediaPreview, mlatitude, mlongitude, wantsReceipt))
		
					elif mediaType =="vcard":
						#return
						#mediaItem.preview = messageNode.getChild("media").data
						vcardData = messageNode.getChild("media").getChild("vcard").toString()
						vcardName = messageNode.getChild("media").getChild("vcard").getAttributeValue("name")
						
						if vcardData is not None:
							n = vcardData.find(">") +1
							vcardData = vcardData[n:]
							vcardData = vcardData.replace("</vcard>","")

							if isGroup:
								self.signalInterface.send("group_vcardReceived", (msgId, fromAttribute, author, vcardName, vcardData, wantsReceipt))
							else:
								self.signalInterface.send("vcard_received", (msgId, fromAttribute, vcardName, vcardData, wantsReceipt))
							
					else:
						self._d("Unknown media type")
						return

				elif ProtocolTreeNode.tagEquals(childNode,"body") and msgId is not None:
					msgData = childNode.data;
					
					#fmsg.setData({"status":0,"key":key.toString(),"content":msgdata,"type":WAXMPP.message_store.store.Message.TYPE_RECEIVED});

				elif ProtocolTreeNode.tagEquals(childNode,"received") and fromAttribute is not None and msgId is not None:

					if fromAttribute == "s.us":
						self.signalInterface.send("profile_setStatusSuccess", ("s.us", msgId,))
						return;

					#@@TODO autosend ack from client
					#print "NEW MESSAGE RECEIVED NOTIFICATION!!!"
					#self.connection.sendDeliveredReceiptAck(fromAttribute,msg_id);
					self.signalInterface.send("receipt_messageDelivered", (fromAttribute, msgId))
					
					return


				elif not (ProtocolTreeNode.tagEquals(childNode,"active")):
					if ProtocolTreeNode.tagEquals(childNode,"request"):
						wantsReceipt = True;

					elif ProtocolTreeNode.tagEquals(childNode,"notify"):
						notify_name = childNode.getAttributeValue("name");


					elif ProtocolTreeNode.tagEquals(childNode,"delay"):
						xmlns = childNode.getAttributeValue("xmlns");
						if "urn:xmpp:delay" == xmlns:
							stamp_str = childNode.getAttributeValue("stamp");
							if stamp_str is not None:
								stamp = stamp_str
								timestamp = self.parseOfflineMessageStamp(stamp)*1000;

					elif ProtocolTreeNode.tagEquals(childNode,"x"):
						xmlns = childNode.getAttributeValue("xmlns");
						if "jabber:x:event" == xmlns and msgId is not None:
							self.signalInterface.send("receipt_messageSent", (fromAttribute, msgId))
						elif "jabber:x:delay" == xmlns:
							continue; #@@TODO FORCED CONTINUE, WHAT SHOULD I DO HERE? #wtf?
							stamp_str = childNode.getAttributeValue("stamp");
							if stamp_str is not None:
								stamp = stamp_str
								timestamp = stamp;
					else:
						if ProtocolTreeNode.tagEquals(childNode,"delay") or not ProtocolTreeNode.tagEquals(childNode,"received") or msgId is None:
							continue;

							
							receipt_type = childNode.getAttributeValue("type");
							if receipt_type is None or receipt_type == "delivered":
								self.signalInterface.send("receipt_messageDelivered", (fromAttribute, msgId))
							elif receipt_type == "visible":
								self.signalInterface.send("receipt_visible", (fromAttribute, msgId))
							




			if msgData:

				if isGroup:
					self.signalInterface.send("group_messageReceived", (msgId, fromAttribute, author, msgData, timestamp, wantsReceipt))

				else:
					self.signalInterface.send("message_received", (msgId, fromAttribute, msgData, timestamp, wantsReceipt))

				##@@TODO FROM CLIENT
				'''if conversation.type == "group":
					if conversation.subject is None:
						signal = False
						self._d("GETTING GROUP INFO")
						self.connection.sendGetGroupInfo(fromAttribute)
				'''
					#if not len(conversation.getContacts()):
					#	self._d("GETTING GROUP CONTACTS")
					#	self.connection.sendGetParticipants(fromAttribute)

				'''@@TODO FROM CLIENT
				if ret is None:
					conversation.incrementNew();
					WAXMPP.message_store.pushMessage(fromAttribute,fmsg)
					fmsg.key = key
				else:
					fmsg.key = eval(ret.key)
					duplicate = True;
				'''
			
