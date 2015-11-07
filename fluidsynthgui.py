#!/usr/bin/python
#
# Kevin Seifert - GPL 2015
#
#
# This program creates a simple synthesizer interface for fluidsynth.
# This lets you easily cycle through a large set of sound fonts
# and select instruments.
#
# This program just runs the fluidsynth command line program, sending 
# input, and parsing output.  
#
#
# How to use the graphical user interface:
#     1. select a folder that contains *.sf2 files
#     2. Up/Down arrows will cycle through the soundfont files
#     3. Left/Right arrows will cycle through the instruments in each file
#     4. You can filter the sound fonts listed (search box at bottom) 
#     5. Optional: you can set the midi channel you want to use (default = 1) 
#     6. Optional: on the second tab, you can set levels for gain, reverb, 
#         and chorus.
#
#
# Command line options:
#
#    	-d sf2_dir                  the default path to your sound fonds 
#    	-f fluidsynth_command       override the start command 
#	    any additional args         are executed as commands in fluidsynth
#
#   For example:
#
#       python  fluidsynthgui.py  -d /home/Music/Public/sf2/  "gain 5"
#
# To connect a CLI to a runninng fluidsynth process, you can use netcat:
#
#    nc localhost 9800
#
#
# System Requirements:
#	jack (QjackCtl recommended)
#	fluidsynth (you should configure for command line first)
#	Python 2.7+
#	python-wxgtk2.8+
#
# Tested with: xubuntu 14.04, FluidSynth version 1.1.6
#
#
# Fluidsynth commands definitions used:
#
#   echo                        Echo data back 
#   load file                   Load SoundFont 
#   unload id                   Unload SoundFont by ID 
#   fonts                       Display the list of loaded SoundFonts
#   inst font                   Print out the available instruments for the font
#   select chan font bank prog  Combination of bank-select and program-change
#
#
# Classes defined below:
#
#	FluidSynthApi - this is the core api/application.
#	FluidSynthGui - this is the graphical interface; it wraps the api.
#

import sys 
import os 
import wx
import re
import time
import socket
import subprocess
import optparse


# API
# this api just writes/reads data to/from the command line interface
class FluidSynthApi:

	def __init__(self,options,args):
		# start fluidsynth process
		print "Init fluidsynth api..."

		# cli
		self.options = options
		self.args = args

		# memory/font management
		# we only can load 16 fonts on 16 channels.  unload the rest.
		self.fontsInUse=[-1,-1,-1,-1,-1,-1,-1,-1,-1,-1,-1,-1,-1,-1,-1,-1]
		self.activeChannel = 1 # base 1
		self.activeSoundFont = -1

		# socket io settings
		self.host='localhost'
		self.port=9800
		self.buffsize=4096
		self.readtimeout=2 # sec
		self.fluidsynth = None # the fluidsynth process

		# see `man fluidsynth` for explanation of cli options
		self.fluidsynthcmd = "fluidsynth -sli -g5 -C0 -R0"

		# arbitrary text to mark the end of stream from fluidsynth
		self.eof = "."  
		self.debug = True 

		# cli option overrides
		if ( options.fluidsynthcmd != "" ):
			self.fluidsynthcmd = options.fluidsynthcmd

		# set up/test server
		self.initFluidsynth()

		# process command line args passed to fluid synth
		if len(self.args) > 0:
			for arg in args:
				self.cmd(arg,True)


	def __del__(self):
		self.closeFluidsynth()


	# test/initialize connection to fluidsynth
	# NOTE: fluidsynth only supports one socket connection
	# push all messages to it
	def initFluidsynth(self):

		try:
			self.connect()
			# looks good
			return True

		except Exception,e:
			print "error: fluidsynth not running?"
			print "could not connect to socket: " + str(self.port)
			print e

		try:
			# try starting fluidsynth
			print "trying to start fluidsynth ..."
			print self.fluidsynthcmd
			cmd = self.fluidsynthcmd.split()
			self.fluidsynth = subprocess.Popen(cmd, shell=False, 
				stdin=subprocess.PIPE, stdout=subprocess.PIPE)

			# process should be started, try connection again
			for i in range(10):	
				try:
					self.connect()
					return True

				except Exception,e:
					print "retry ..."
					print e
					time.sleep(.5)

		except Exception,e:
			print "error: fluidsynth could not start"
			print e

		print "error: giving up"
		return False


	# cleanup
	def closeFluidsynth(self):
		self.close()
		try:
			self.fluidsynth.kill()
		except:
			print "fluidsynth will be left running"			

	# create socket connection
	# do NOT connect on every request (like HTTP)
	# fluidsynth seems to only be able to spawn a small number of total sockets 
	def connect(self):

		self.clientsocket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
		self.clientsocket.connect((self.host,self.port))
		self.clientsocket.settimeout(self.readtimeout)
		print "connected"


	# cleanup sockets when finished
	def close(self):

		self.clientsocket.shutdown(socket.SHUT_RDWR)
		self.clientsocket.close()
		print "closed"


	# send data to fluidsynth socket
	def send(self, packet):
		if self.debug:
			print "send: " + packet
		self.clientsocket.send(packet)


	# read data from fluidsynth socket
	# these packets will be small
	def read(self):
		data = ""
		# inject EOF marker into output
		# add blank line and eof marker, to tag the end of the stream
		self.send("echo \"\"\n")
		self.send("echo " + self.eof + "\n")
		try:
			i=0
			max_reads = 1000000 # avoid infinite loop
			part = ""
			while i<max_reads: 
				i+=1
				part = self.clientsocket.recv(self.buffsize)
				data += part
				#print "chunk: " + part
				# test data for boundary hit
				# NOTE: part may only contain fragment of eof 
				#for eol in [ "\n", "\r\n", "\r" ]:
				for eol in [ "\n" ]:
					eof = eol + self.eof + eol 
					pos = data.find(eof)
					if pos > -1: 
						# found end of stream
						# chop eof marker off
						data = data[0:pos]
						if self.debug:
							print "data: " + data + "\n--\n"
						return data

		except Exception, e:
			print "warn: eof not found in stream: '"+self.eof+"'" 
			print e

		if self.debug:
			print "data (timeout): " + data + "\n--\n"
		return data


	# full request/response transaction
	# nl not required
	# returns data packet (only if blocking)
	# returns True (only if non-blocking)
	def cmd(self, packet, non_blocking = False):
		data = ""
		self.send(packet+"\n")

		#if non_blocking and not self.debug: #to disable nonblocking for debug  
		if non_blocking:
			return True

		data = self.read()
		return data


	## DEPRECATED - this works and is left in as fallback option.
	## The old command line IO was switched to socket IO.
	## This function just executes the command in a basic fluidsynth cli 
	## and then reads and parses output from STDOUT pipe.
	## The only difference between CLI and socket, is CLI uses a > prompt.
	##
	## NOTE: This is a very basic version of 'Expect'.
	## For example if calling 
	##	print fluidsynth.cmd("help")
	## the function will read all output and stop at the next ">" prompt.
	## The function expects the fluid synth prompt to look like ">".
	##
	## Python bug?!  Popen readlines() does not return data.
	## And, Python doesn't support multiple Popen communicate() calls.
	## There seems to be a race condition with pipes. 
	## Overall, IMO subprocess is difficult to work with.
	##
	## Workaround: poll input with "\n" write to prevent IO blocking 
	## on each single readline().  Then, drain the padded output after 
	## the total size of the text response is known.
	##
	## The best fix probably is to use the fluidsynth socket interface.
	##
	## Other possible fixes: use pexpect, or fluidsynth python bindings
	## but, this will make the script heavier with dependencies.
	##
	#def cmd(self, cmd, readtil='>'):
	#	p=self.fluidsynth
	#	lines=''
	#	p.stdin.write(cmd + "\n" )
	#	count=0 # track \n padding
	#	while True:
	#		count += 1
	#		p.stdin.write("\n")
	#		line = p.stdout.readline()
	#		line = line.strip();
	#		if line == readtil:
	#			if lines != '':
	#				# drain \n padding 
	#				for num in range(count):
	#					p.stdout.readline()
	#				if self.debug:
	#					print lines	
	#				return lines
	#		else:
	#			lines = lines + "\n" + line


	# load sound soundfont, for example:
	#
	#> load "/home/Music/sf2/Brass 4.SF2"
	#loaded SoundFont has ID 1
	#fluidsynth: warning: No preset found on channel 9 [bank=128 prog=0]
	#> 
	def loadSoundFont(self, sf2):
		try:
			data = self.cmd('load "'+ sf2 +'"')
			ids = [int(s) for s in data.split() if s.isdigit()]	
			id = ids[-1] # return last item
			id = int(id)
			if id > -1:
				self.activeSoundFont = id
				return id

		except Exception,e:
			print "error: could not load font: " + sf2
			print e	

		return -1


	# remove soundfont from memory, for example:
	#
	#> fonts
	#ID  Name
	# 1  /home/Music/sf2/Brass 4.SF2
	#> 
	def getSoundFonts(self):
		try:
			data = self.cmd('fonts')
			ids=data.splitlines()
					
			#ids = ids[3:] # discard first 3 items (header)
			ids_clean = []
			for id in ids:
				# example:
				# '1 /home/user/sf2/Choir__Aahs_736KB.sf2'
				parts = id.split()

				try:
					if parts[0] != 'ID':
						id2=int(parts[0])
						ids_clean.append(id2)

				except Exception,e:
					print "warn: skipping font parse: " 
					print parts
					print e 

			return ids_clean

		except Exception,e:
			print "error: no fonts parsed"
			print e

		return []

 
	# remove unused soundfonts from memory, for example:
	#
	#> unload 1
	#fluidsynth: warning: No preset found on channel 0 [bank=0 prog=0]
	#> 
	def unloadSoundFonts(self):
		try:
			ids = self.getSoundFonts()
			## debug memory management
			#if self.debug:
			#	print "Fonts in use:"
			#	print self.fontsInUse
			#	print "All Fonts in memory:"
			#	print ids 

			## unload any soundfont that is not referenced
			for id in ids:
				sid=str(id)
				if id in self.fontsInUse:
					#print "font in use: " + sid
					pass
				else:
					self.cmd('unload '+ sid, True)
		except Exception,e:
			print "error: could not unload fonts"
			print e


	# list instruments in soundfont, for example:
	# 
	#> inst 1
	#000-000 Dark Violins  
	#> 
	def getInstruments(self,id):

		id = int(id)
		if id < 0:
			return []

		try:
			data = self.cmd('inst ' + str(id))
			ids = data.splitlines()
			#ids = ids[2:] # discard first two items (header)
			return ids

		except Exception,e:
			print "error: could not get instruments"
			print e

		return []


	# change voice in soundfont
	#
	# arg formats:
	#	000-000 Some Voice
	#	000-000
	#
	#note: "prog bank prog" doesn't always seem to work as expected
	#using 'select' instead
	# for example:
	#select chan sfont bank prog
	#> 
	def setInstrument(self,id):

		if id == '':
			return ''

		if self.activeSoundFont < 0:
			return ''

		try:
			parts = id.split()
			ids = parts[0].split('-')			
			chan = str(self.activeChannel-1) # base 0
			font = str(self.activeSoundFont)
			bank = ids[0]
			prog = ids[1]
			cmd = 'select '+chan+' '+font+' '+bank+' '+prog
			data = self.cmd(cmd, True)

			self.fontsInUse[int(chan)] = int(font)

			return data

		except Exception,e:
			print 'error: could not select instrument: ' + id
			print e

		return '' 


	# load soundfont, select first program voice
	# returns (id,array_of_voices)
	#
	# for example:
	#> inst 2
	#000-000 FF Brass 1
	#000-001 Orchestral Brass 1
	#000-002 Trumpets
	#000-003 Trombones
	#000-004 Trumpets+Trombones
	#000-005 RolandMcArthurBrs
	#> 
	def initSoundFont(self,sf2):
		try:
			self.unloadSoundFonts()
			id = self.loadSoundFont(sf2)
			voices = self.getInstruments(id)
			self.setInstrument(voices[0])
			return (id,voices)

		except Exception,e:
			print "error: voice did not load: " + sf2
			print e

		return (-1,[])


	# get/set config
	def setValue(self,key,value):
		value = self.cmd('set ' + key + ' ' + value, True)

	def getValue(self,key):
		value = self.cmd('get ' + key)
		values = value.split() 
		if len(values):
			return values[-1]
		else:
			return '' 

	def isTruthy(self,value):
		if value in ["true","1","on","yes"]:
			return True
		return False

	def getBoolValue(self,key):
		value = self.getValue(key)
		return self.isTruthy(value)

	def getNumValue(self,key):
		value = self.getValue(key)
		value = float(value)
		return value 

	def getIntValue(self,key):
		value = self.getValue(key)
		value = int(value)
		return value 

	# gain api
	#    gain value                Set the master gain (0 < gain < 5)
	#    get synth.gain            5.000
	def setGain(self,value):
		self.cmd('gain ' + str(value),True) # [0,5]
		self.setValue('synth.gain',str(float(value)*2)) # [0,10]

	def getGain(self):
		self.getNumValue('synth.gain') / 2

	# reverb api
	#    reverb [0|1|on|off]        Turn the reverb on or off
	#    rev_setroomsize num        Change reverb room size. 0-1
	#    rev_setdamp num            Change reverb damping. 0-1
	#    rev_setwidth num           Change reverb width. 0-1
	#    rev_setlevel num           Change reverb level. 0-1
	def getReverb(self):
		value = self.getBoolValue('synth.reverb.active')
		return value 

	def setReverb(self,boolean):
		self.cmd('reverb ' + str(int(boolean)))
		# ? not auto updated
		self.setValue('synth.reverb.active', str(int(boolean))) 
	def setReverbRoomSize(self,num):
		self.cmd('rev_setroomsize ' + str(num), True)
	def setReverbDamp(self,num):
		self.cmd('rev_setdamp ' + str(num), True)
	def setReverbWidth(self,num):
		self.cmd('rev_setwidth ' + str(num), True)
	def setReverbLevel(self,num):
		self.cmd('rev_setlevel ' + str(num), True)

	# note: no getters for reverb details	

	# chorus api
	#    cho_set_nr n               Use n delay lines (default 3)
	#    cho_set_level num          Set output level of each chorus line to num
	#    cho_set_speed num          Set mod speed of chorus to num (Hz)
	#    cho_set_depth num          Set chorus modulation depth to num (ms)
	#    chorus [0|1|on|off]        Turn the chorus on or off
	def getChorus(self):
		value = self.getBoolValue('synth.chorus.active')
		return value 

	def setChorus(self,boolean):
		self.cmd('chorus ' + str(int(boolean)))
		# ? not auto updated
		self.setValue('synth.chorus.active', str(int(boolean))) 

	def setChorusN(self,num):
		self.cmd('cho_set_nr ' + str(num), True)
	def setChorusLevel(self,num):
		self.cmd('cho_set_level ' + str(num), True)
	def setChorusSpeed(self,num):
		self.cmd('cho_set_speed ' + str(num), True)
	def setChorusDepth(self,num):
		self.cmd('cho_set_depth ' + str(num), True)


	# reset (all notes off)
	def panic(self):
		self.cmd('reset', True)


# end class


# GUI
class FluidSynthGui(wx.Frame):

	def __init__(self, parent, title, api):

		super(FluidSynthGui, self).__init__(parent, title=title, 
			size=(640, 480))
		# data
		self.fluidsynth = api 

		self.soundFontsAll = [] # everything in dir 
		self.instrumentsAll = [] # everything in dir]
		self.soundFonts = [] # filtered
		self.instruments = [] # filtered
		self.soundFontsIdx = 0
		self.instrumentsIdx = 0
		self.soundFontsFilter = "" 
	


		self.initUI()		
		self.bindEvents()		
		self.processArgs()
		self.Centre()
		self.Show() 


	# command line args
	def processArgs(self):
		options = self.fluidsynth.options

		if options.dir != "":
			self.dir = options.dir
			self.textSoundFontDir.SetValue(self.dir)
			self.refreshSoundFonts()


	def initUI(self):

		self.panel = wx.Panel(self)
		panel = self.panel

		self.notebook = wx.Notebook(panel)
		page1 = wx.Panel(self.notebook)
		page2 = wx.Panel(self.notebook)

		self.createSoundFontControls(page1)
		self.createLevelControls(page2)

		self.notebook.AddPage(page1, "Sound Fonts")
		self.notebook.AddPage(page2, "Levels")

		sizer = wx.BoxSizer()
		sizer.Add(self.notebook, 1, wx.EXPAND)
		panel.SetSizer(sizer)
		sizer.Fit(self)


	# widgets for level controls (returns sizers) ... 


	# this is the main widget for loading soundfonts
	def createSoundFontControls(self,panel):

		# ui components
		self.textSoundFontDir = wx.TextCtrl(panel)
		self.btnSoundFontDir = wx.Button(panel, label="Browse...")
		self.textfilterSoundFont = wx.TextCtrl(panel)
		self.listSoundFont = wx.ListBox(panel, choices=self.soundFonts, size=(-1,200))
		self.listInstruments = wx.ListBox(panel,choices=self.instruments,size=(-1,200))  
		self.spinChannel = wx.SpinCtrl(panel,min=1,max=16,value="1")
		self.btnPanic = wx.Button(panel, label="All notes off")

		# start layout 
		vbox = wx.BoxSizer(wx.VERTICAL)

		# row1
		row = wx.BoxSizer(wx.HORIZONTAL)
		row.Add( wx.StaticText(panel, label='Sound Font Dir') , flag=wx.ALIGN_CENTER_VERTICAL|wx.RIGHT, border=10)
		row.Add(self.textSoundFontDir, flag=wx.ALIGN_CENTER_VERTICAL, proportion=4)
		row.Add(self.btnSoundFontDir, flag=wx.ALIGN_CENTER_VERTICAL, proportion=1)

		vbox.Add(row, flag=wx.EXPAND|wx.ALL, border=5)

		# row2
		row = wx.BoxSizer(wx.HORIZONTAL)
		row.Add( wx.StaticText(panel, label='Sound Fonts') ,flag=wx.RIGHT, border=5, proportion=1)
		row.Add( wx.StaticText(panel, label='Instruments') ,flag=wx.LEFT, border=5, proportion=1)
		vbox.Add(row, flag=wx.EXPAND|wx.ALL, border=5)

		# row3
		row = wx.BoxSizer(wx.HORIZONTAL)
		row.Add(self.listSoundFont,proportion=1)
		row.Add(self.listInstruments,proportion=1)

		vbox.Add(row, flag=wx.EXPAND|wx.ALL, border=5)

		# row4
		row = wx.BoxSizer(wx.HORIZONTAL)
		row.Add(wx.StaticText(panel, label='Filter Fonts'),flag=wx.ALIGN_CENTER_VERTICAL|wx.LEFT, border=10, proportion=1)
		row.Add(self.textfilterSoundFont,flag=wx.ALIGN_CENTER_VERTICAL,proportion=2)
		row.Add(wx.StaticText(panel, label='Channel'),flag=wx.ALIGN_CENTER_VERTICAL|wx.LEFT|wx.ALIGN_RIGHT, border=10, proportion=1)
		row.Add(self.spinChannel,flag=wx.ALIGN_CENTER_VERTICAL,proportion=1)
		row.Add(self.btnPanic,flag=wx.ALIGN_CENTER_VERTICAL|wx.LEFT,border=20,proportion=1)
		vbox.Add(row, flag=wx.EXPAND|wx.ALL, border=5)

		panel.SetSizer(vbox)
		return vbox


	# widget to control master gain level
	# controls:
	# gain value                 Set the master gain (0.0 < gain < 5.0)
	def createGainControls(self,panel):

		# ui components
		slideStyle = wx.SL_VERTICAL|wx.SL_AUTOTICKS|wx.SL_LABELS|wx.SL_INVERSE

		self.sGain=wx.Slider(panel,-1,50,0,100,style=slideStyle) 

		boxlabel = "Gain" 
		flags = wx.EXPAND|wx.ALL

		box = wx.StaticBox(panel, -1, boxlabel)
		sizer = wx.StaticBoxSizer(box, wx.HORIZONTAL)

		sizer.Add(self.sGain,flag=flags, border=20)

		return sizer


	# widget to control reverb effects
	# inset panel controls:
	#reverb [0|1|on|off]        Turn the reverb on or off
	#rev_setroomsize num        Change reverb room size. 0-1
	#rev_setdamp num            Change reverb damping. 0-1
	#rev_setwidth num           Change reverb width. 0-1
	#rev_setlevel num           Change reverb level. 0-1
	def createReverbControls(self,panel):

		# ui components
		slideStyle = wx.SL_HORIZONTAL|wx.SL_AUTOTICKS|wx.SL_LABELS 

		self.cbEnableReverb = self.cb = wx.CheckBox(panel,-1,'Enabled')
		self.sReverbRoomSize=wx.Slider(panel,-1,50,0,100,style=slideStyle) 
		self.sReverbDamp=wx.Slider(panel,-1,50,0,100,style=slideStyle) 
		self.sReverbWidth=wx.Slider(panel,-1,50,0,100,style=slideStyle) 
		self.sReverbLevel=wx.Slider(panel,-1,50,0,100,style=slideStyle) 

		self.enableReverbControls(False) # off by default

		boxlabel= "Reverb"

		flags = wx.ALIGN_CENTER_VERTICAL|wx.EXPAND|wx.ALL
		sprop = 3 
		box = wx.StaticBox(panel, -1, boxlabel)
		sizer = wx.StaticBoxSizer(box, wx.VERTICAL)

		# row 1
		row = wx.BoxSizer(wx.HORIZONTAL)

		row.Add(self.cbEnableReverb,flag=flags,proportion=1)
		sizer.Add(row, 0, wx.ALL, 2)

		# row 2
		row = wx.BoxSizer(wx.HORIZONTAL)
		row.Add(wx.StaticText(panel, label='Room'),flag=flags, border=5, proportion=1)
		row.Add(self.sReverbRoomSize,flag=flags, border=5, proportion=sprop)
		sizer.Add(row, 0, wx.EXPAND|wx.ALL, 2)

		# row 3
		row = wx.BoxSizer(wx.HORIZONTAL)
		row.Add(wx.StaticText(panel, label='Damp'),flag=flags, border=5, proportion=1)
		row.Add(self.sReverbDamp,flag=flags, border=5, proportion=sprop)
		sizer.Add(row, 0, wx.EXPAND|wx.ALL, 2)

		# row 4
		row = wx.BoxSizer(wx.HORIZONTAL)
		row.Add(wx.StaticText(panel, label='Width'),flag=flags, border=5, proportion=1)
		row.Add(self.sReverbWidth,flag=flags, border=5, proportion=sprop)
		sizer.Add(row, 0, wx.EXPAND|wx.ALL, 2)

		# row 5
		row = wx.BoxSizer(wx.HORIZONTAL)
		row.Add(wx.StaticText(panel, label='Level'),flag=flags, border=5, proportion=1)
		row.Add(self.sReverbLevel,flag=flags, border=5, proportion=sprop)
		sizer.Add(row, 0, wx.EXPAND|wx.ALL, 2)

		return sizer


	# widget to control chorus effects
	# inset panel, sets values
	# cho_set_nr n               Use n delay lines (default 3). 0-99
	# cho_set_level num          Set output level of each chorus line to num. 0-1
	# cho_set_speed num          Set mod speed of chorus to num (Hz). .3-5
	# cho_set_depth num          Set chorus modulation num (ms).
	# chorus [0|1|on|off]        Turn the chorus on or off.
	def createChorusControls(self,panel):
		
		# ui components
		slideStyle = wx.SL_HORIZONTAL|wx.SL_AUTOTICKS|wx.SL_LABELS 

		self.cbEnableChorus = self.cb = wx.CheckBox(panel,-1,'Enabled')
		self.sChorusN=wx.Slider(panel,-1,50,0,99,style=slideStyle) 
		self.sChorusLevel=wx.Slider(panel,-1,50,0,100,style=slideStyle) 
		self.sChorusSpeed=wx.Slider(panel,-1,250,30,500,style=slideStyle) 
		self.sChorusDepth=wx.Slider(panel,-1,25,0,46,style=slideStyle) 

		self.enableChorusControls(False) # off by default

		boxlabel= "Chorus"

		flags = wx.ALIGN_CENTER_VERTICAL|wx.EXPAND|wx.ALL
		sprop = 3 
		box = wx.StaticBox(panel, -1, boxlabel)
		sizer = wx.StaticBoxSizer(box, wx.VERTICAL)


		# row 1
		row = wx.BoxSizer(wx.HORIZONTAL)

		row.Add(self.cbEnableChorus,flag=flags,proportion=1)
		sizer.Add(row, 0, wx.ALL, 2)

		# row 2
		row = wx.BoxSizer(wx.HORIZONTAL)
		row.Add(wx.StaticText(panel, label='N'),flag=flags, border=5, proportion=1)
		row.Add(self.sChorusN,flag=flags, border=5, proportion=sprop)
		sizer.Add(row, 0, wx.EXPAND|wx.ALL, 2)

		# row 3
		row = wx.BoxSizer(wx.HORIZONTAL)
		row.Add(wx.StaticText(panel, label='Level'),flag=flags, border=5, proportion=1)
		row.Add(self.sChorusLevel,flag=flags, border=5, proportion=sprop)
		sizer.Add(row, 0, wx.EXPAND|wx.ALL, 2)

		# row 4
		row = wx.BoxSizer(wx.HORIZONTAL)
		row.Add(wx.StaticText(panel, label='Speed'),flag=flags, border=5, proportion=1)
		row.Add(self.sChorusSpeed,flag=flags, border=5, proportion=sprop)
		sizer.Add(row, 0, wx.EXPAND|wx.ALL, 2)

		# row 5
		row = wx.BoxSizer(wx.HORIZONTAL)
		row.Add(wx.StaticText(panel, label='Depth'),flag=flags, border=5, proportion=1)
		row.Add(self.sChorusDepth,flag=flags, border=5, proportion=sprop)
		sizer.Add(row, 0, wx.EXPAND|wx.ALL, 2)

		return sizer


	# widget to control sound effects
	# gain + reverb + chorus panels
	def createLevelControls(self,panel):

		sbgain = self.createGainControls(panel)
		sbreverb = self.createReverbControls(panel)
		sbchorus = self.createChorusControls(panel)

		# start layout
		vbox = wx.BoxSizer(wx.VERTICAL)

		# row 1
		row = wx.BoxSizer(wx.HORIZONTAL)
		row.Add(sbgain, flag=wx.EXPAND|wx.ALL, proportion=1)
		row.Add(sbreverb, flag=wx.EXPAND|wx.ALL, proportion=4)
		row.Add(sbchorus, flag=wx.EXPAND|wx.ALL, proportion=4)
		vbox.Add(row, flag=wx.EXPAND|wx.ALL, border=5)

		panel.SetSizer(vbox)
		#vbox.Fit(panel)
		#panel.SetSizer(row)
		#return row
		return vbox


	# wire up controls to callbacks
	# this lists out all the controls and events
	def bindEvents(self):

		# event binding

		# sound fonts
		self.btnSoundFontDir.Bind(wx.EVT_BUTTON, self.onClickButtonBrowse, self.btnSoundFontDir)
		self.textSoundFontDir.Bind(wx.wx.EVT_KEY_UP, self.onKeyUpDirectory, self.textSoundFontDir)
		self.listSoundFont.Bind(wx.EVT_LISTBOX, self.onSelectSoundFont, self.listSoundFont)
		self.listSoundFont.Bind(wx.wx.EVT_KEY_DOWN, self.onKeyDownSoundFont, self.listSoundFont)
		self.listInstruments.Bind(wx.EVT_LISTBOX, self.onSelectInstrument,self.listInstruments)
		self.textfilterSoundFont.Bind(wx.wx.EVT_KEY_UP, self.onKeyUpFilterSoundFont,self.textfilterSoundFont)
		self.spinChannel.Bind(wx.EVT_SPINCTRL,self.onClickChannel,self.spinChannel)
		self.btnPanic.Bind(wx.EVT_BUTTON, self.onClickPanic, self.btnPanic)

		# levels 
		self.sGain.Bind(wx.EVT_SLIDER,self.onScrollGain)

		self.cbEnableReverb.Bind(wx.EVT_CHECKBOX,self.onClickEnableReverb)
		self.sReverbDamp.Bind(wx.EVT_SLIDER,self.onScrollReverbDamp)
		self.sReverbRoomSize.Bind(wx.EVT_SLIDER,self.onScrollReverbRoomSize)
		self.sReverbWidth.Bind(wx.EVT_SLIDER,self.onScrollReverbWidth)
		self.sReverbLevel.Bind(wx.EVT_SLIDER,self.onScrollReverbLevel)

		self.cbEnableChorus.Bind(wx.EVT_CHECKBOX,self.onClickEnableChorus)
		self.sChorusN.Bind(wx.EVT_SLIDER,self.onScrollChorusN)
		self.sChorusLevel.Bind(wx.EVT_SLIDER,self.onScrollChorusLevel)
		self.sChorusSpeed.Bind(wx.EVT_SLIDER,self.onScrollChorusSpeed)
		self.sChorusDepth.Bind(wx.EVT_SLIDER,self.onScrollChorusDepth)


	# define event callbacks ...

	# master gain	
	def onScrollGain(self,event):
		value = event.GetSelection()
		value *= 1/20.0 # 100 -> 5 
		self.fluidsynth.setGain(value)

	# reverb 
	def onClickEnableReverb(self,event):
		value = event.IsChecked()
		self.fluidsynth.setReverb(value)	
		self.enableReverbControls(value)

	def onScrollReverbDamp(self,event):
		value = event.GetSelection()
		value *= 1/100.0  # 100 -> 1
		self.fluidsynth.setReverbDamp(value) 

	def onScrollReverbRoomSize(self,event):
		value = event.GetSelection()
		value *= 1/100.0  # 100 -> 1
		self.fluidsynth.setReverbRoomSize(value) 

	def onScrollReverbWidth(self,event):
		value = event.GetSelection()
		value *= 1/100.0  # 100 -> 1
		self.fluidsynth.setReverbWidth(value) 

	def onScrollReverbLevel(self,event):
		value = event.GetSelection()
		value *= 1/100.0  # 100 -> 1
		self.fluidsynth.setReverbLevel(value) 


	# chorus
	def onClickEnableChorus(self,event):
		value = event.IsChecked()
		self.fluidsynth.setChorus(value)
		self.enableChorusControls(value)

	def onScrollChorusN(self,event):
		value = event.GetSelection()
		# scale: 1 -> 1
		self.fluidsynth.setChorusN(value)

	def onScrollChorusLevel(self,event):
		value = event.GetSelection()
		value *= 1/100.0 # 100 -> 1
		self.fluidsynth.setChorusLevel(value)

	def onScrollChorusSpeed(self,event):
		value = event.GetSelection()
		value *= 1/100.0 # 100 -> 1
		self.fluidsynth.setChorusSpeed(value)

	def onScrollChorusDepth(self,event):
		value = event.GetSelection()
		# scale: 1 -> 1
		self.fluidsynth.setChorusDepth(value)


	# dir change
	def onKeyUpDirectory(self, event):
		event.Skip()
		keycode = event.GetKeyCode()
		path = self.textSoundFontDir.GetValue()

		if ( os.path.isdir(path) ):
			self.dir = path
			self.refreshSoundFonts()


	def onClickButtonBrowse(self, event):
		event.Skip()
		dlg = wx.DirDialog(self, "Choose a directory:", style=wx.DD_DEFAULT_STYLE | wx.DD_NEW_DIR_BUTTON)
		if dlg.ShowModal() == wx.ID_OK:
			print 'selected: %s\n' % dlg.GetPath()
			self.dir = dlg.GetPath()
			self.textSoundFontDir.SetValue(self.dir)
			self.refreshSoundFonts()

		dlg.Destroy()


	# sound soundfont change
	def onSelectSoundFont(self, event):
		idx = event.GetSelection()
		event.Skip()
		if ( idx < 0 ):
			return
		sel = self.soundFonts[idx]
		path = self.dir + '/' + sel
		(id,instrumentsAll) = fluidsynth.initSoundFont(path)
		self.instrumentsAll = instrumentsAll
		self.instrumentsIdx = 0
		self.refreshInstruments();
		

	def onSelectInstrument(self, event):
		idx = self.listInstruments.GetSelection()
		event.Skip()

		# NOTE: idx is -1 when using the arrow keys
		if ( idx < 0 ):
			return
		self.instrumentsIdx = int(idx)
		self.loadInstrument()


	def onKeyDownSoundFont(self, event):
		keycode = event.GetKeyCode()
		event.Skip()
		if keycode == wx.WXK_LEFT:
			self.instrumentsIdx = self.incInstrument(self.instrumentsIdx,-1)
			self.loadInstrument()
			self.refreshInstruments()
		elif keycode == wx.WXK_RIGHT:
			self.instrumentsIdx = self.incInstrument(self.instrumentsIdx,1)
			self.loadInstrument()
			self.refreshInstruments()


	# filters
	def onKeyUpFilterSoundFont(self,event):
		event.Skip()
		self.refreshSoundFonts(True)


	# channel
	def onClickChannel(self,event):
		chan=self.spinChannel.GetValue()
		self.fluidsynth.activeChannel = chan	

	# reset (all notes off)
	def onClickPanic(self, event):
		self.fluidsynth.panic()


	# api ...

	# proxy
	def cmd(self,s,non_blocking=False):
		return self.fluidsynth.cmd(s,non_blocking)	

	# keep scrolling id in bounds
	def incInstrument(self,id,add=0):
		id+=add
		if ( id < 0 ):
			id = 0
		size = len(self.instruments)
		if ( id >= size ):
			id = size - 1
		return id

	# search 
	def grep(self, pattern, word_list):
		expr = re.compile(pattern, re.IGNORECASE)
		return [elem for elem in word_list if expr.search(elem)]


	def filterSoundFont(self):
		lst = self.grep(self.textfilterSoundFont.GetValue(),self.soundFontsAll);
		return sorted(lst, key=lambda s: s.lower())


	def filterInstruments(self):
		return self.instrumentsAll;

	def loadInstrument(self):
		idx = self.incInstrument( self.instrumentsIdx, 0 )
		sel = self.instruments[idx]
		#print "- select " + str(idx) + " " + sel
		self.fluidsynth.setInstrument(sel)	

	# view...

	# enable/disable fx widgets
	def enableReverbControls(self,enabled):
		self.sReverbRoomSize.Enable(enabled)
		self.sReverbDamp.Enable(enabled)
		self.sReverbWidth.Enable(enabled)
		self.sReverbLevel.Enable(enabled)

	# enable/disable fx widgets
	def enableChorusControls(self,enabled):
		self.sChorusN.Enable(enabled)
		self.sChorusLevel.Enable(enabled)
		self.sChorusSpeed.Enable(enabled)
		self.sChorusDepth.Enable(enabled)

	# draw soundfonts 
	def refreshSoundFonts(self,cache=False):
		if not cache:
			self.soundFontsAll = os.listdir(self.dir)

		self.soundFonts = self.filterSoundFont()
		self.listSoundFont.Set(self.soundFonts)

		self.instrumentsIdx = 0;
		self.refreshInstruments();


	# draw instruments
	def refreshInstruments(self):
		self.instruments = self.filterInstruments()
		self.listInstruments.Set(self.instruments)
		self.listInstruments.SetSelection(self.instrumentsIdx)

# end class


# main
if __name__ == '__main__':

	# parse cli options 
	parser = optparse.OptionParser()
	parser.add_option('-d', '--dir', action="store", dest="dir",
		help="load a sf2 directory", default="") 
	parser.add_option('-c', '--cmd', action="store", dest="fluidsynthcmd", 
		help="use a custom command to start fluidsynth server", default="") 
	options, args = parser.parse_args()

	# init api
	fluidsynth = FluidSynthApi(options,args)

	# wrap api with gui
	app = wx.App()
	FluidSynthGui(None, title='Fluid Synth Gui',api=fluidsynth)
	app.MainLoop()


# end main
