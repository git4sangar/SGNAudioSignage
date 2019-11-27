#sgn

import json
import socket
import os
from time import sleep
from threading import Thread, Lock, RLock

class FileSender(object):
	def __init__(self, file_name = "test.mp3", udp_tx_port = 4953):
		self.oneChunk	= 1024 * 16
		self.file_name	= file_name
		self.file_size	= os.path.getsize(file_name)
		self.udp_tx_port= udp_tx_port

	def pack_meta_data(self, start_hour, start_min, duration):
		myDict	= {}
		myDict["cmd"]	= "remove"
		myDict["name"]	= "Coffee Break"
		myDict["hour"]	= start_hour
		myDict["min"]	= start_min
		myDict["duration"] = duration
		myDict["file_name"] = self.file_name + "_read"
		myDict["file_size"] = self.file_size
		return json.dumps(myDict)

	def pack_file(self, offset):
		with open(self.file_name, 'rb') as fp:
			fp.seek(offset)
			chunk = fp.read(self.oneChunk)
			fp.close()
			return len(chunk), chunk

	def send_packet(self, toip, pkt):
		sent	= 0
		sock_tx = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
		dest    = (toip, int(self.udp_tx_port))
		try:
			sent = sock_tx.sendto(pkt, dest)
		except socket.error as e:
			print (os.strerror(e.errno))
		finally:
			sock_tx.close()
		return sent

def get_ip():
	s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
	try:
		# doesn't even have to be reachable
		s.connect(('10.255.255.255', 1))
		IP = s.getsockname()[0]
	except:
		IP = '127.0.0.1'
	finally:
		s.close()
	return IP

def receive_packets():
	sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
	server_address = ('', 4952)
	sock.bind(server_address)

	while True:
		data, address = sock.recvfrom(1024*16)
		print("Got - {0}".format(data.decode()))

if __name__ == "__main__":
	read_thread	= Thread(target = receive_packets)
	read_thread.start()

	file_sender	= FileSender("audio_file_01.mp3")
	meta_data_json	= file_sender.pack_meta_data(10, 30, 60)
	print(meta_data_json)
	bytes_sent	= file_sender.send_packet(get_ip(), meta_data_json.encode())
	print("No of bytes sent is {0}" .format(bytes_sent))
'''
	bytes_read	= 0
	current_size	= 0
	chunks_read	= 0
	while bytes_read < file_sender.file_size:
		current_size, chunk = file_sender.pack_file(bytes_read)
		chunks_read = chunks_read + 1
		bytes_read = current_size + bytes_read
		bytes_sent	= file_sender.send_packet(get_ip(), chunk)
		sleep(0.01)
	print("Sent {0} chunks of toal size {1}".format(chunks_read, bytes_read))
'''

