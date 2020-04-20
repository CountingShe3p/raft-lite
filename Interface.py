import zmq
import multiprocessing
import Queue
import time

from MessageProtocol import MessageType

class Talker(multiprocessing.Process):
	def __init__(self, identity):
		super(Talker, self).__init__()

		# Port to talk from
		self.port = identity['address']

		# Backoff amounts
		self.initial_backoff = 1.0
		self.operation_backoff = 0.01

		# Place to store outgoing messages
		self.messages = multiprocessing.Queue()

		# Signals
		self._ready_event = multiprocessing.Event()
		self._stop_event = multiprocessing.Event()

	def stop(self):
		self._stop_event.set()

	def run(self):
		# All of the zmq initialization has to be in the same function for some reason
		context = zmq.Context()
		pub_socket = context.socket(zmq.PUB)
		while True:
			try:
				pub_socket.bind("tcp://127.0.0.1:%s" % self.port)
				break
			except zmq.ZMQError:
				time.sleep(0.1)

		# Need to backoff to give the connections time to initizalize
		time.sleep(self.initial_backoff)

		# Signal that you're ready
		self._ready_event.set()

		while not self._stop_event.is_set():
			try:
				pub_socket.send_json(self.messages.get_nowait())
			except Queue.Empty:
				pass
			time.sleep(self.operation_backoff)
		
		pub_socket.unbind("tcp://127.0.0.1:%s" % self.port)
		pub_socket.close()

	def send_message(self, msg):
		self.messages.put(msg)
	
	def wait_until_ready(self):
		while not self._ready_event.is_set():
			time.sleep(0.1)
		return True

class Listener(multiprocessing.Process):
	def __init__(self, port_list, identity):
		super(Listener, self).__init__()

		# List of ports to subscribe to
		self.port_list = port_list
		self.identity = identity

		# Backoff amounts
		self.initial_backoff = 1.0
		self.operation_backoff = 0.01

		# Place to store incoming messages
		self.messages = multiprocessing.Queue()
		self.leader_messages = multiprocessing.Queue()

		# Signals
		self._stop_event = multiprocessing.Event()

	def stop(self):
		self._stop_event.set()

	def run(self):
		# All of the zmq initialization has to be in the same function for some reason
		context = zmq.Context()
		sub_sock = context.socket(zmq.SUB)
		sub_sock.setsockopt(zmq.SUBSCRIBE, '')
		for p in [self.port_list[n]['port'] for n in self.port_list]:
			sub_sock.connect("tcp://127.0.0.1:%s" % p)

		# Need to backoff to give the connections time to initizalize
		time.sleep(self.initial_backoff)
		
		# Use this to add new connections
		next_port = max([int(self.port_list[n]['port']) for n in self.port_list]) + 1

		while not self._stop_event.is_set():
			try:
				msg = sub_sock.recv_json(zmq.NOBLOCK)	
				# Check if this message is a heartbeat from someone else. If it is then they are the leader so empty the leader queue.
				if ((msg['type'] == MessageType.Heartbeat) and (msg['sender'] != self.identity['address'])):
					try:
						while True:
							self.leader_messages.get_nowait()
					except Queue.Empty:
						pass
				if ((msg['receiver'] == self.identity['address']) or (msg['receiver'] is None)):
					self.messages.put(msg)
			except zmq.Again:
				pass

			time.sleep(self.operation_backoff)
		
		sub_sock.close()
	
	def get_message(self):
		# If there's nothing in the queue Queue.Empty will be thrown
		try:
			msg = self.messages.get_nowait()
		except Queue.Empty:
			return None
		return msg

	def get_leader_message(self):
		# If there's nothing in the queue Queue.Empty will be thrown
		try:
			msg = self.leader_messages.get_nowait()
		except Queue.Empty:
			return None
		return msg