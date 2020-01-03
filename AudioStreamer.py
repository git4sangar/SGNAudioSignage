#sgn
from omxplayer.player import OMXPlayer
from pathlib import Path
import subprocess
from time import sleep
import datetime
import os.path
from os import path
from threading import Thread, Lock, RLock
import csv
import json
import socket
import netifaces
from mutagen.mp3 import MP3

gPlayList = []
gPListLock = RLock()

gPlaylistPath	= "/home/pi/sgn/projs/SGNAudioSignage/"
gPathPrefix	= "/home/pi/sgn/projs/SGNAudioSignage/audio/"

#gPlaylistPath	= "/home/tstone10/sgn/smpls/py/SGNAudioSignage/"
#gPathPrefix	= "/home/tstone10/sgn/smpls/py/SGNAudioSignage/audio/"

gNetIfs	= ["eth0", "wlan0", "enp0s31f6", "wlp2s0"]

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
		if self.is_playing():
			print("Force stopped playing")
		else:
			print("Finished playing")
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
					print("choosing interface {0} with ip {1}".format(netif, pkt))
					break
				else:
					print("dictionary-key 2 is not available in interface {0}".format(netif))
			except ValueError:
				print("interface {0} is not available".format(netif) )
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
	def play(self, file_name, duration_mins):
		global gPathPrefix
		duration_secs	= duration_mins * 60
		audio_player	= OMXPlayer(gPathPrefix + file_name)
		sleep(1)
		duration_secs = duration_secs - 1
		while duration_secs > 0:
			if not audio_player.is_playing():
				audio_player	= OMXPlayer(gPathPrefix + file_name)
				print("Play it again as remaining duration is {0} sec(s)".format(duration_secs))
			sleep(1)
			duration_secs = duration_secs - 1

		if audio_player.is_playing():
			print("killing as duration is elapsed")
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

			loop = loop + 1
			sleep(1) #sleep for a second

class FileReader(object):
	def __init__(self, plist_file_name = "playlist_file.json", udp_file_port = 49500, udp_rx_port = 4953, udp_tx_port = 4952):
		global gPlayList, gPListLock
		self.udp_rx_port	= udp_rx_port
		self.udp_tx_port	= udp_tx_port
		self.udp_file_port	= udp_file_port
		self.plist_file_name	= plist_file_name
		self.fileSize		= 0
		self.isNoConflict	= False
		self.clientIP		= ''
		self.password		= "GuruGuha"
		self.id			= 0
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
						if playItem["name"] == "password":
							self.password = playItem["new_password"]
						if playItem["id"] > self.id:
							self.id = playItem["id"]
		except IOError:
			print("Could not open Playlist file")

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

	def conflict_check(self, playItem):
		global gPlayList, gPListLock
		toRemove = {}
		with gPListLock:
			for item in gPlayList:
				if item["name"] == "password":
					continue
				if item["id"] == playItem["id"]:
					toRemove = item
					continue

				if item["name"] == playItem["name"]:
					return item, False
				t1Start	= Utils.get_secs(playItem["hour"], playItem["min"], 0)
				t1End	= t1Start + Utils.get_secs(0, playItem["duration"], 0)

				t2Start = Utils.get_secs(item["hour"], item["min"], 0)
				t2End	= Utils.get_secs(0, item["duration"], 0)
				if Utils.is_overlapped(t1Start, t1End, t2Start, t2End):
					return item, False
		return toRemove, True

	def add_play_item(self, playItem):
		global gPlayList, gPListLock
		with gPListLock:
			gPlayList.append(playItem)

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
		global gPlayList, gPListLock

		print("Got packet {0}".format(pkt.decode()))
		playItem	= json.loads(pkt.decode())

		if playItem["cmd"] == "ping":
			pkt = self.pack_resp(playItem["cmd"], "success", Utils.get_ip())
			print("Sending: " + pkt)
			Utils.send_packet(self.clientIP, self.udp_tx_port, pkt.encode())
			return

		# in case if you forget the password
		if playItem["cmd"] == "get_password":
			pkt = self.pack_resp(playItem["cmd"], "success", self.password)
			print("Sending: " + pkt)
			Utils.send_packet(self.clientIP, self.udp_tx_port, pkt.encode())
			return

		if playItem["cmd"] == "sanity":
			isOk	= "fail"
			if playItem["password"] == self.password:
				isOk = "success"
			pkt = self.pack_resp(playItem["cmd"], isOk, "")
			print("Sending: sanity : {0}".format(isOk))
			Utils.send_packet(self.clientIP, self.udp_tx_port, pkt.encode())
			return

		if playItem["cmd"] == "change_password":
			self.remove_play_item_by_id(playItem["id"])
			self.password	= playItem["new_password"]
			self.add_play_item(playItem)
			self.serialize_play_list()
			pkt = self.pack_resp(playItem["cmd"], "success", playItem["new_password"])
			print("Sending: " + pkt)
			Utils.send_packet(self.clientIP, self.udp_tx_port, pkt.encode())
			return

		if playItem["cmd"] == "add":
			desc	= ""
			isOk	= "fail"
			data	= ""
			self.fileSize	= playItem["file_size"]
			playItem["file_name"] = playItem["file_name"].replace(" ", "_")
			item, self.isNoConflict = self.conflict_check(playItem)
			if self.isNoConflict:
				if bool(item):
					self.delete_play_item(item)
				desc = "Added" if playItem["id"] < 0 else "Updated"
				if playItem["id"] == -1:
					self.id		= self.id + 1
					playItem["id"]	= self.id
				self.add_play_item(playItem)
				self.serialize_play_list()
				isOk	= "success"
				data	= str(playItem["id"])
			else:
				desc	= "Conflicts with {0}".format(item["name"])
				isOk	= "fail"
			pkt = self.pack_resp(playItem["cmd"], isOk, data, desc)
			print("Sending: " + pkt)
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
			print("Sending: " + pkt)
			Utils.send_packet(self.clientIP, self.udp_tx_port, pkt.encode())
			return

		if playItem["cmd"] == "get_play_list":
			pkt = self.pack_resp(playItem["cmd"], "success", self.get_play_list())
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
		server_address = (Utils.get_ip(), int(self.udp_file_port))
		sock.bind(server_address)
		sock.listen(1)
		while True:
			print("Waiting for client...")
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
						print("Got file to add {0}".format(metaFile))
						connection.send("Done1".encode())
				else:
					audio_file.write(data)
					iBytesRead	= iBytesRead + len(data)
					#print("File size: {0}, Read: {1}, Balance: {2}".format(iFileSize, iBytesRead, iFileSize-iBytesRead))
					if iBytesRead >= iFileSize:
						iFileSize	= 0
						iBytesRead	= 0
						audio_file.close()
						connection.send("Done2".encode())
						sleep(1)
						connection.close()
						print("Done reading all bytes")
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

if __name__ == "__main__":
	file_reader	= FileReader(gPlaylistPath + "playlist_file.json")
	read_thread	= Thread(target = file_reader.receive_packets)
	read_thread.start()
	file_thread	= Thread(target = file_reader.receive_tcp)
	file_thread.start()

	media_player	= Player()
	play_thread	= Thread(target = media_player.poll_playlist)
	play_thread.start()
