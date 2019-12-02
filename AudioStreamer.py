#sgn

import subprocess
from time import sleep
import datetime
from threading import Thread, Lock, RLock
import csv
import json
import socket

gPlayList = []
gPListLock = RLock()
#gPathPrefix = "/home/pi/sgn/sangar/audio_streamer/"
gPathPrefix = "/home/gubuntu/sgn/smpls/py/SGNAudioSignage/audio/"

class Utils(object):
	@staticmethod
	def get_secs(hour, mins, secs):
		ret = hour * 60 * 60
		ret = ret + (mins * 60)
		ret = ret + secs
		return ret

	@staticmethod
	def is_overlapped(t1Start, t1End, t2Start, t2End):
		if t1Start <= t2Start and t1End >= t2Start:
			return True
		if t2Start <= t1Start and t2End >= t1Start:
			return True
		return False

	@staticmethod
	def send_packet(toip, port, pkt):
		sent	= 0
		sock_tx = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
		dest    = (toip, int(port))
		#print("Sending pkt to {0}".format(toip))
		try:
			sent = sock_tx.sendto(pkt, dest)
		except socket.error as e:
			print (os.strerror(e.errno))
		finally:
			sock_tx.close()
		return sent

	@staticmethod
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

class Player(object):
	def play(self, file_name, duration_mins):
		duration_secs	= duration_mins * 60
		pid = subprocess.Popen("omxplayer -o local {0}".format(gPathPrefix + file_name))
		#pid = subprocess.Popen("/home/tstone10/sgn/smpls/py/noend")
		while duration_secs > 0:
			if pid.poll() != None:	# finished playing?, then play again
				pid = subprocess.Popen("omxplayer -o local {0}".format(file_name))
				#pid = subprocess.Popen("/home/tstone10/sgn/smpls/py/noend")
				print("Play it again as remaining duration is {0} sec(s)".format(duration_secs))
			sleep(1)
			duration_secs = duration_secs - 1

		if pid.poll() == None:	# is it still playing, then kill it
			print("killing as duration is elapsed")
			pid.kill()

	def poll_playlist(self):
		global gPlayList, gPListLock
		playItem = {}
		loop = 0
		while True:
			with gPListLock:
				if len(gPlayList) > 0:
					if len(gPlayList) <= loop:		# is loop pointing to non-existent index?
						loop = len(gPlayList) - 1	# if so, pick the next greatest play item
					playItem = gPlayList[loop]

			# Password is serialized for "cmd" == "change_password". so skip if the "cmd" is not "add"
			if playItem and playItem["cmd"] == "add":
				#Check if right time to play
				playTime	= datetime.time(playItem["hour"], playItem["min"], 0)
				curHour		= datetime.datetime.now().hour
				curMins		= datetime.datetime.now().minute
				curTime		= datetime.time(curHour, curMins, 0)
				if playTime == curTime:
					self.play(playItem["file_name"], playItem["duration"])
					#print("playing {0} for duration {1}".format(playItem["file_name"], playItem["duration"]))
				playItem = {}	# who knows, this palyItem would've been removed. so make it empty

			loop = loop + 1
			sleep(1) #sleep for a second

class FileReader(object):
	def __init__(self, plist_file_name = "playlist_file.json", udp_rx_port = 4953, udp_tx_port = 4952):
		global gPlayList, gPListLock
		self.udp_rx_port	= udp_rx_port
		self.udp_tx_port	= udp_tx_port
		self.plist_file_name	= plist_file_name
		self.fileSize		= 0
		self.fileName		= "sgn.mp3"
		self.isSanityOk		= False
		self.bytesRead		= 0
		self.clientIP		= ''
		self.password		= "SGN"
		self.oneChunk		= 1024 * 16	#max UDP payload is 16K

		#	Deserialize
		try:
			playListFp	= open(self.plist_file_name, "r")	
			playListJson	= playListFp.read()
			playListFp.close()
			if len(playListJson) > 0:
				print("Playlist till now {0}" .format(playListJson))
				with gPListLock:
					gPlayList	= json.loads(playListJson)
					for playItem in gPlayList:
						if playItem["cmd"] == "change_password":
							self.password = playItem["new_password"]
		except IOError:
			print("Could not open Playlist file")

	def remove_play_item(self, play_item_name):
		global gPlayList, gPListLock
		isRemoved = False
		with gPListLock:
			for playItem in gPlayList:
				if playItem["name"] == play_item_name:
					gPlayList.remove(playItem)
					isRemoved = True
					break
		return isRemoved

	def sanity_check(self, playItem):
		global gPlayList, gPListLock
		with gPListLock:
			for item in gPlayList:
				t1Start	= Utils.get_secs(playItem["hour"], playItem["min"], 0)
				t1End	= t1Start + Utils.get_secs(0, playItem["duration"], 0)

				t2Start = Utils.get_secs(item["hour"], item["min"], 0)
				t2End	= Utils.get_secs(0, item["duration"], 0)
				if item["name"] == playItem["name"] or Utils.is_overlapped(t1Start, t1End, t2Start, t2End):
					return False;
		return True

	def add_play_item(self, playItem):
		global gPlayList, gPListLock
		with gPListLock:
			gPlayList.append(playItem)

	def get_play_list_json(self):
		global gPlayList, gPListLock
		playList = []
		with gPListLock:
			for playItem in gPlayList:
				if playItem["name"] != "password":
					playList.append(playItem)
		return json.dumps(playList)

	def serialize_play_list(self):
		global gPlayList, gPListLock
		with gPListLock:
			playListJson	= json.dumps(gPlayList)
			# print("Serializing pkt {0}".format(playListJson))
		playListFp	= open(self.plist_file_name, "w")	#Overwrite file content
		playListFp.write(playListJson)
		playListFp.close()

	def parse_packet(self, pkt):
		if self.fileSize == 0:
			print("Got packet {0}".format(pkt.decode()))
			playItem	= json.loads(pkt.decode())

			if "cmd" not in playItem.keys() or "password" not in playItem.keys():
				pkt = "Invalid Input: command or password missing"
				print(pkt)
				Utils.send_packet(self.clientIP, self.udp_tx_port, pkt.encode())
				return

			# in case if you forget the password
			if playItem["cmd"] == "get_password" :
				print("Sending current password")
				Utils.send_packet(self.clientIP, self.udp_tx_port, self.password.encode())

			if playItem["password"] != self.password:
				pkt = "Invalid password"
				print(pkt)
				Utils.send_packet(self.clientIP, self.udp_tx_port, pkt.encode())
				return

			if playItem["cmd"] == "change_password":
				self.remove_play_item(playItem["name"])
				self.password	= playItem["new_password"]
				self.add_play_item(playItem)
				self.serialize_play_list()
				pkt = "Password changed successfully"
				print(pkt)
				Utils.send_packet(self.clientIP, self.udp_tx_port, pkt.encode())

			if playItem["cmd"] == "add":
				# add - cmd is always followed by a series of packets containing the audio file
				# so set the following variables eventhough the sanity check fails
				self.fileSize	= playItem["file_size"]
				self.fileName	= playItem["file_name"]
				self.bytesRead	= 0

				self.isSanityOk = self.sanity_check(playItem)
				if self.isSanityOk:
					self.add_play_item(playItem)
					self.serialize_play_list()
					pkt = "added to playlist"
				else:
					pkt = "sanity check failed"
				print(pkt)
				Utils.send_packet(self.clientIP, self.udp_tx_port, pkt.encode())

			if playItem["cmd"] == "remove":
				if self.remove_play_item(playItem["name"]):
					self.serialize_play_list()
					pkt = "removed from playlist"
				else:
					pkt = "Item '{0}' not found".format(playItem["name"])
				print(pkt)
				Utils.send_packet(self.clientIP, self.udp_tx_port, pkt.encode())

			if playItem["cmd"] == "get_play_list":
				pkt = self.get_play_list_json()
				Utils.send_packet(self.clientIP, self.udp_tx_port, pkt.encode())

			if playItem["cmd"] == "get_ip":
				pkt = Utils.get_ip()
				Utils.send_packet(self.clientIP, self.udp_tx_port, pkt.encode())
		else:
			if self.isSanityOk:
				audio_file	= open(self.fileName, "ab")
				audio_file.write(pkt)
				audio_file.close()
			self.bytesRead	= self.bytesRead + len(pkt)
			if self.bytesRead >= self.fileSize:
				self.isSanityOk = False
				self.fileSize	= 0
				self.bytesRead	= 0
				pkt = "got the audio file"
				print(pkt)
				Utils.send_packet(self.clientIP, self.udp_tx_port, pkt.encode())

	def receive_packets(self):
		sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
		server_address = ('', int(self.udp_rx_port))
		sock.bind(server_address)

		while True:
			data, address = sock.recvfrom(self.oneChunk)
			self.clientIP = address[0]
			self.parse_packet(data)
			#print("Got pkt from {0}".format(address[0]))

if __name__ == "__main__":
	file_reader	= FileReader("playlist_file.json")
	read_thread	= Thread(target = file_reader.receive_packets)
	read_thread.start()

	media_player	= Player()
	play_thread	= Thread(target = media_player.poll_playlist)
	play_thread.start()
