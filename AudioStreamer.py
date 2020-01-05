#sgn
from omxplayer.player import OMXPlayer
from pathlib import Path
import subprocess
from time import sleep, time, localtime
import datetime
import os.path
from os import path
from threading import Thread, Lock, RLock
import csv
import json
import socket
import netifaces
from mutagen.mp3 import MP3
import logging

gPlayList = []
gPListLock = RLock()

gPlaylistPath	= "/home/pi/sgn/projs/SGNAudioSignage/"
gPathPrefix	= "/home/pi/sgn/projs/SGNAudioSignage/audio/"

#gPlaylistPath	= "/home/tstone10/sgn/smpls/py/SGNAudioSignage/"
#gPathPrefix	= "/home/tstone10/sgn/smpls/py/SGNAudioSignage/audio/"

gNetIfs	= ["eth0", "wlan0", "enp0s31f6", "wlp2s0"]
gMAX_PLAYLIST_SIZE	= 101

class SignagePlayer(object):
	def __init__(self, file_name):
		self.startSecs	= self.get_cur_time_in_secs()
		audio		= MP3(file_name)
		self.duration	= int(audio.info.length)
		#print("Started playing, start secs: {0}, duration: {1}".format(self.startSecs, self.duration))

	def get_cur_time_in_secs(self):
		curHour		= datetime.datetime.now().hour
		curMins		= datetime.datetime.now().minute
		curSecs		= datetime.datetime.now().second
		return (curHour * 60 * 60) + (curMins * 60) + curSecs

	def is_playing(self):
		curTime	= self.get_cur_time_in_secs()
		playEnd	= self.startSecs + self.duration
		return playEnd > curTime

	def quit(self):
		#print("startTime: {0}, duration: {1}, curTime: {2}".format(self.startSecs, self.duration, self.get_cur_time_in_secs()))
		self.duration	= 0
		self.bPlaying	= False

class Utils(object):
	@staticmethod
	def get_secs(hour, mins, secs):
		ret = hour * 60 * 60
		ret = ret + (mins * 60)
		ret = ret + secs
		return ret

	@staticmethod
	def get_current_time_string():
		t = localtime()
		time_string = "{}_{:02d}_{:02d}-{:02d}_{:02d}_{:02d}".format(t.tm_year, t.tm_mon, t.tm_mday, t.tm_hour, t.tm_min, t.tm_sec)
		return time_string

	@staticmethod
	def is_overlapped(t1Start, t1End, t2Start, t2End):
		# Check if t2's start is within t1's play range or vice versa
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
		#print("Sending pkt to {0}".format(pkt))
		try:
			sent = sock_tx.sendto(pkt, dest)
		except socket.error as e:
			print (os.strerror(e.errno))
		finally:
			sock_tx.close()
		return sent

	@staticmethod
	def get_ip():
		global gNetIfs
		pkt = " "
		for netif in gNetIfs:
			try:
				ifDict	= netifaces.ifaddresses(netif)
				if 2 in ifDict.keys():
					pkt = ifDict[2][0]['addr']
					#print("choosing interface {0} with ip {1}".format(netif, pkt))
					break
			except ValueError:
				#print("interface {0} is not available".format(netif) )
				pass
		return pkt

	@staticmethod
	def get_ip_obsolete():
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
	def __init__(self):
		self.my_logger	= logging.getLogger('Player')

	def play(self, file_name, duration_mins):
		global gPathPrefix
		duration_secs	= duration_mins * 60
		audio_player	= OMXPlayer(gPathPrefix + file_name)
		sleep(1)
		duration_secs = duration_secs - 1
		while duration_secs > 0:
			if not audio_player.is_playing():
				audio_player	= OMXPlayer(gPathPrefix + file_name)
				self.my_logger.info("Play it again as remaining duration is {0} sec(s)".format(duration_secs))
			sleep(1)
			duration_secs = duration_secs - 1

		if audio_player.is_playing():
			self.my_logger.info("killing as duration is elapsed")
			audio_player.quit()

	def poll_playlist(self):
		global gPlayList, gPListLock
		playItem = {}
		loop = 0
		while True:
			with gPListLock:
				if len(gPlayList) > 0:
					if len(gPlayList) <= loop:		# is loop pointing to non-existent index?
						loop = 0			# if so, start from scratch
					playItem = gPlayList[loop]
					loop = loop + 1

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
				playItem = {}	# who knows, this palyItem would've been removed by this time. so make it empty

			sleep(1) #sleep for a second

class FileReader(object):
	def __init__(self, plist_file_name = "playlist_file.json", tcp_file_port = 49500, udp_rx_port = 4953, udp_tx_port = 4952):
		global gPlayList, gPListLock
		self.udp_rx_port	= udp_rx_port
		self.udp_tx_port	= udp_tx_port
		self.tcp_file_port	= tcp_file_port
		self.plist_file_name	= plist_file_name
		self.fileSize		= 0
		self.isNoConflict	= False
		self.clientIP		= ''
		self.password		= "GuruGuha"
		self.id			= 0
		self.oneChunk		= 1024 * 16	#max UDP payload is 16K
		self.my_logger		= logging.getLogger('FReader')

		#	Deserialize
		try:
			playListFp	= open(self.plist_file_name, "r")	
			playListJson	= playListFp.read()
			playListFp.close()
			if len(playListJson) > 0:
				self.my_logger.info("Playlist till now {0}" .format(playListJson))
				with gPListLock:
					gPlayList	= json.loads(playListJson)
					for playItem in gPlayList:
						if playItem["name"] == "password":
							self.password = playItem["new_password"]
						if playItem["id"] > self.id:
							self.id = playItem["id"]
		except IOError:
			self.my_logger.info("Could not open Playlist file")

	def delete_play_item(self, playItem):
		global gPlayList, gPListLock
		with gPListLock:
			gPlayList.remove(playItem)

	def remove_play_item_by_id(self, play_item_id):
		global gPlayList, gPListLock
		isRemoved = False
		with gPListLock:
			for playItem in gPlayList:
				if playItem["id"] == play_item_id:
					gPlayList.remove(playItem)
					isRemoved = True
					self.serialize_play_list()
					break
		return isRemoved

	# Check if the given play item conflicts with existing items' time
	def is_no_conflict(self, playItem):
		global gPlayList, gPListLock
		toRemove = {}
		with gPListLock:
			for item in gPlayList:
				if item["name"] == "password":
					continue
				if item["id"] == playItem["id"]:# Skip checking with same item
					toRemove = item		# Remove it & update new time
					continue

				if item["name"] == playItem["name"]:
					return item, False
				t1Start	= Utils.get_secs(playItem["hour"], playItem["min"], 0)
				t1End	= t1Start + Utils.get_secs(0, playItem["duration"], 0)

				t2Start = Utils.get_secs(item["hour"], item["min"], 0)
				t2End	= t2Start + Utils.get_secs(0, item["duration"], 0)
				if Utils.is_overlapped(t1Start, t1End, t2Start, t2End):
					return item, False
		return toRemove, True

	def add_play_item(self, playItem):
		global gPlayList, gPListLock, gMAX_PLAYLIST_SIZE
		size_of_playlist = 0
		with gPListLock:
			size_of_playlist = len(gPlayList)
			if size_of_playlist >= gMAX_PLAYLIST_SIZE:
				return False, size_of_playlist
			gPlayList.append(playItem)
			size_of_playlist = size_of_playlist + 1
		return True, size_of_playlist

	def get_play_list(self):
		global gPlayList, gPListLock
		playList = []
		with gPListLock:
			for playItem in gPlayList:
				if playItem["name"] != "password":
					playList.append(playItem)
		return playList

	def serialize_play_list(self):
		global gPlayList, gPListLock
		with gPListLock:
			playListJson	= json.dumps(gPlayList)
			# print("Serializing pkt {0}".format(playListJson))
		playListFp	= open(self.plist_file_name, "w")	#Overwrite file content
		playListFp.write(playListJson)
		playListFp.close()

	def pack_resp(self, tag, isOk, data, desc = "null"):
		resp	= {}
		resp["tag"]	= tag
		resp["result"]	= isOk
		resp["data"]	= data
		resp["desc"]	= desc
		return json.dumps(resp)

	def parse_packet(self, pkt):
		global gPlayList, gPListLock, gMAX_PLAYLIST_SIZE

		self.my_logger.info("Got packet {0}".format(pkt.decode()))
		playItem	= json.loads(pkt.decode())

		if playItem["cmd"] == "ping":
			pkt = self.pack_resp(playItem["cmd"], "success", Utils.get_ip())
			self.my_logger.info("Sending: " + pkt)
			Utils.send_packet(self.clientIP, self.udp_tx_port, pkt.encode())
			return

		# in case if you forget the password
		if playItem["cmd"] == "get_password":
			pkt = self.pack_resp(playItem["cmd"], "success", self.password)
			self.my_logger.info("Sending: " + pkt)
			Utils.send_packet(self.clientIP, self.udp_tx_port, pkt.encode())
			return

		if playItem["cmd"] == "sanity":
			isOk	= "fail"
			if playItem["password"] == self.password:
				isOk = "success"
			pkt = self.pack_resp(playItem["cmd"], isOk, "")
			self.my_logger.info("Sending: sanity : {0}".format(isOk))
			Utils.send_packet(self.clientIP, self.udp_tx_port, pkt.encode())
			return

		if playItem["cmd"] == "change_password":
			self.remove_play_item_by_id(playItem["id"])
			self.password	= playItem["new_password"]
			self.add_play_item(playItem)
			self.serialize_play_list()
			pkt = self.pack_resp(playItem["cmd"], "success", playItem["new_password"])
			self.my_logger.info("Sending: " + pkt)
			Utils.send_packet(self.clientIP, self.udp_tx_port, pkt.encode())
			return

		if playItem["cmd"] == "add":
			desc	= ""
			isOk	= "fail"
			data	= ""
			size_of_playlist = 0
			isAdded	= False
			self.fileSize	= playItem["file_size"]
			playItem["file_name"] = playItem["file_name"].replace(" ", "_")
			item, self.isNoConflict = self.is_no_conflict(playItem)
			if self.isNoConflict:
				if bool(item):	# Remove the existing entry & add the same with new time
					self.delete_play_item(item)
				if playItem["id"] == -1:
					playItem["id"]	= self.id + 1
					desc	= "Added"
				else:
					desc	= "Updated"
				isAdded, size_of_playlist = self.add_play_item(playItem)
				if isAdded:
					self.serialize_play_list()
					if desc	== "Added":
						self.id	= self.id + 1
					isOk	= "success"
					data	= str(playItem["id"])
					if size_of_playlist == gMAX_PLAYLIST_SIZE:
						desc	+= ". Warning: Max size reached"
				else:
					desc	= "Not added. Max size reached"
					isOk	= "fail"
			else:
				desc	= "Conflicts with {0}".format(item["name"])
				isOk	= "fail"
			pkt = self.pack_resp(playItem["cmd"], isOk, data, desc)
			self.my_logger.info("Sending: " + pkt)
			Utils.send_packet(self.clientIP, self.udp_tx_port, pkt.encode())
			return

		if playItem["cmd"] == "remove":
			isOk	= "fail"
			desc	= "Item not found"
			if self.remove_play_item_by_id(playItem["id"]):
				self.serialize_play_list()
				isOk	= "success"
				desc	= "Deleted"
			pkt = self.pack_resp(playItem["cmd"], isOk, "", desc)
			self.my_logger.info("Sending: " + pkt)
			Utils.send_packet(self.clientIP, self.udp_tx_port, pkt.encode())
			return

		if playItem["cmd"] == "get_play_list":
			pkt = self.pack_resp(playItem["cmd"], "success", self.get_play_list())
			self.my_logger.info("Sending: " + pkt)
			Utils.send_packet(self.clientIP, self.udp_tx_port, pkt.encode())
			return

	def receive_tcp(self):
		global gPathPrefix
		TCP_CHUNK 	= 60 * 1024
		iFileSize	= 0
		iBytesRead	= 0
		iFileName	= ""
		audio_file	= None
		metaFile	= {}

		sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
		sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
		server_address = (Utils.get_ip(), int(self.tcp_file_port)) # connect to IP instead of localhost to avoid connection refusal
		sock.bind(server_address)
		sock.listen(1)
		while True:
			self.my_logger.info("Waiting for client...")
			connection, client_address = sock.accept()
			while True:
				data = connection.recv(TCP_CHUNK)
				if iFileSize == 0:
					metaFile = json.loads(data.decode())
					if bool(metaFile):
						iFileSize = metaFile["file_size"]
						metaFile["file_name"] = metaFile["file_name"].replace(" ", "_")
						iFileName = gPathPrefix + metaFile["file_name"]
						audio_file = open(iFileName, "wb")
						self.my_logger.info("Got file to add {0}".format(metaFile))
						connection.send("Done1".encode())
				else:
					audio_file.write(data)
					iBytesRead	= iBytesRead + len(data)
					#self.my_logger.info("File size: {0}, Read: {1}, Balance: {2}".format(iFileSize, iBytesRead, iFileSize-iBytesRead))
					if iBytesRead >= iFileSize:
						iFileSize	= 0
						iBytesRead	= 0
						audio_file.close()
						connection.send("Done2".encode())
						sleep(1)
						connection.close()
						self.my_logger.info("Done reading all bytes")
						break
				
	def receive_packets(self):
		sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
		sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
		server_address = ('', int(self.udp_rx_port))
		sock.bind(server_address)

		while True:
			data, address = sock.recvfrom(self.oneChunk)
			self.clientIP = address[0]
			self.parse_packet(data)

def setup_logging(logfile):
	root_logger = logging.getLogger('')
	root_logger.setLevel(logging.DEBUG)

	formatter = logging.Formatter('%(asctime)s %(name)s %(levelname)s %(message)s')
	fh = logging.FileHandler(logfile)
	fh.setLevel(logging.DEBUG)
	fh.setFormatter(formatter)
	root_logger.addHandler(fh)

if __name__ == "__main__":
	sleep(60)	# let all network interfaces start and settle for tcp sock to bind
	setup_logging(gPlaylistPath + "log_file_" + Utils.get_current_time_string() + ".txt")
	main_logger = logging.getLogger('MAIN')

	file_reader	= FileReader(gPlaylistPath + "playlist_file.json")
	read_thread	= Thread(target = file_reader.receive_packets)
	read_thread.start()
	main_logger.info("File reader started")

	file_thread	= Thread(target = file_reader.receive_tcp)
	file_thread.start()
	main_logger.info("TCP reader started")

	media_player	= Player()
	play_thread	= Thread(target = media_player.poll_playlist)
	play_thread.start()
	main_logger.info("Poll playlist started")
