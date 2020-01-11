#sgn
from omxplayer.player import OMXPlayer
from omxplayer import keys as Keys 
from pathlib import Path
import subprocess
from time import sleep, time, localtime
from os import path
from threading import Thread, Lock, RLock
import json
import socket
import netifaces
import logging

gPlayList = []
gPListLock = RLock()

gPlaylistPath	= "/home/pi/sgn/projs/SGNMoviePlayer/"
gPathPrefix	= "/home/pi/sgn/projs/SGNMoviePlayer/movies/"

#gPlaylistPath	= "/home/tstone10/sgn/smpls/py/SGNAudioSignage/"
#gPathPrefix	= "/home/tstone10/sgn/smpls/py/SGNAudioSignage/audio/"

gNetIfs	= ["eth0", "wlan0", "enp0s31f6", "wlp2s0"]

class Utils(object):
	@staticmethod
	def get_current_time_string():
		t = localtime()
		time_string = "{}_{:02d}_{:02d}-{:02d}_{:02d}_{:02d}".format(t.tm_year, t.tm_mon, t.tm_mday, t.tm_hour, t.tm_min, t.tm_sec)
		return time_string

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

class FileReader(object):
	def __init__(self, plist_file_name = "playlist_file.json", udp_rx_port = 10001, udp_tx_port = 10002):
		global gPlayList, gPListLock
		self.udp_rx_port	= udp_rx_port
		self.udp_tx_port	= udp_tx_port
		self.plist_file_name	= plist_file_name
		self.clientIP		= ''
		self.chosen_id		= -1 
		self.oneChunk		= 1024 * 16	#max UDP payload is 16K
		self.my_logger		= logging.getLogger('FReader')
		self.video_player	= None
		self.isMuted    	= False 

		#	Deserialize
		try:
			playListFp	= open(self.plist_file_name, "r")	
			playListJson	= playListFp.read()
			playListFp.close()
			if len(playListJson) > 0:
				self.my_logger.info("Playlist till now {0}" .format(playListJson))
				with gPListLock:
					gPlayList	= json.loads(playListJson)
		except IOError:
			self.my_logger.info("Could not open Playlist file")

	def get_play_list(self):
		global gPlayList, gPListLock
		playList = []
		with gPListLock:
			for playItem in gPlayList:
				playList.append(playItem)
		return playList

	def pack_resp(self, tag, isOk, data, desc = "null"):
		resp	= {}
		resp["tag"]	= tag
		resp["result"]	= isOk
		resp["data"]	= data
		resp["desc"]	= desc
		return json.dumps(resp)

	def get_file_for_id(self, id):
		global gPlayList, gPListLock
		file_name = ""
		with gPListLock:
			for playItem in gPlayList:
				if id == playItem["id"]:
					file_name = playItem["file_name"]
					break
		return file_name

	def parse_packet(self, pkt):
		global gPlayList, gPListLock

		self.my_logger.info("Got packet {0}".format(pkt.decode()))
		playItem	= json.loads(pkt.decode())

		if playItem["cmd"] == "ping":
			pkt = self.pack_resp(playItem["cmd"], "success", Utils.get_ip())
			self.my_logger.info("Sending: " + pkt)
			Utils.send_packet(self.clientIP, self.udp_tx_port, pkt.encode())

		elif playItem["cmd"] == "get_play_list":
			pkt = self.pack_resp(playItem["cmd"], "success", self.get_play_list())
			self.my_logger.info("Sending: " + pkt)
			Utils.send_packet(self.clientIP, self.udp_tx_port, pkt.encode())

		elif playItem["cmd"] == "choose":
			self.chosen_id	= playItem["id"]
			if bool(self.video_player):
				data1 = "playing"
			else:
				data1 = ""
			pkt = self.pack_resp("choose", "success", data1)
			self.my_logger.info("Sending: " + pkt)
			Utils.send_packet(self.clientIP, self.udp_tx_port, pkt.encode())

		elif self.chosen_id == -1:
			pkt = self.pack_resp("stopped", "success", "null")
			Utils.send_packet(self.clientIP, self.udp_tx_port, pkt.encode())
			return
 
		elif playItem["cmd"] == "play":
			file_to_play		= self.get_file_for_id(self.chosen_id)
			self.my_logger.info("file to play: {0}".format(file_to_play))
			if bool(self.video_player):
				self.video_player.pause()
				self.video_player.play()
			else:
				self.video_player = OMXPlayer(file_to_play, args=['-o', 'hdmi'])

		elif playItem["cmd"] == "pause" and bool(self.video_player):
			self.video_player.pause()

		elif playItem["cmd"] == "vol_up" and bool(self.video_player):
                        if self.isMuted:
                                self.video_player.unmute()
                                self.isMuted = False
                                self.video_player.action(Keys.INCREASE_VOLUME)

		elif playItem["cmd"] == "vol_down" and bool(self.video_player):
                        if self.isMuted:
                                self.video_player.unmute()
                                self.isMuted = False
                                self.video_player.action(Keys.DECREASE_VOLUME)

		elif playItem["cmd"] == "mute" and bool(self.video_player):
                        if not self.isMuted:
                                self.video_player.mute()
                                self.isMuted = True 

		elif playItem["cmd"] == "fast_fwd" and bool(self.video_player):
			#self.video_player.action(Keys.FAST_FORWARD)
                        pos = self.video_player.position()
                        pos = pos + 5
                        self.video_player.seek(pos)
			#self.video_player.action(Keys.FAST_FORWARD)

		elif playItem["cmd"] == "fast_rev" and bool(self.video_player):
                        pos = self.video_player.position()
                        pos = pos - 5
                        self.video_player.seek(pos)
			#self.video_player.action(Keys.REWIND)

		elif playItem["cmd"] == "stop" and bool(self.video_player):
			self.video_player.stop()
			self.chosen_id	= -1 
			self.video_player = None
			self.isMuted    = False

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
	fh.setLevel(logging.INFO)
	fh.setFormatter(formatter)
	root_logger.addHandler(fh)

if __name__ == "__main__":
	setup_logging(gPlaylistPath + "log_file_" + Utils.get_current_time_string() + ".txt")
	main_logger = logging.getLogger('MAIN')

	file_reader	= FileReader(gPlaylistPath + "playlist_file.json")
	read_thread	= Thread(target = file_reader.receive_packets)
	read_thread.start()
	main_logger.info("File reader started")
