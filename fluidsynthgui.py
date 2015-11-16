#!/usr/bin/python
#
# Kevin Seifert - GPL 2015
#
# This program creates a simple synthesizer interface for FluidSynth.
# This interface lets you easily search or cycle through a large set of 
# sound fonts and select instruments.
#
# See README.txt for more details.
#
# Classes defined below:
#
#	FluidSynthApi - this is the core api that interfaces with fluidsynth
#                   using the socket api.
#	FluidSynthGui - the graphical interface wraps the api and saves the state
#                   of the application on shutdown.
# 
# Note on whitespace: 
#    I'm using tabs (\t) for indentation, with my tab width set at 4 spaces.

import sys 
import os 
import wx
import re
import time
import socket
import subprocess
import traceback
import optparse
import signal
import json


# API
# this is the api that writes data to and read data from the command line interface.
# this communicates with fluidsynth over the socket 9800.
class FluidSynthApi:

	def __init__(self,options,args):

		print('init FluidSynth api...')

		# cli
		self.options = options         # key/value pairs.
		self.args = args               # bare args.

		# memory/font management
		# note: we will only load at most 16 fonts on the 16 channels. 
		#       all other fonts will be unloaded from memory.
		self.fontFilesLoaded={}        # font_id: font_file.
		self.fontsInUse=[-1] * 16      # font_id. position is channel.
		self.instrumentsInUse=['']*16  # instrument_name. position is channel.
		self.selectedChannel = 1       # 1-based. all new instruments load here.
		self.activeChannel = 1         # 1-based. last used channel.
		self.activeSoundFontId = -1    # last font loaded.
		self.activeSoundFontFile = ''  # last SoundFont loaded.
		self.activeInstrument = ''     # last instrument loaded.

		# socket io settings
		self.host='localhost'          # fluidsynth hostname.
		self.port=9800                 # fluidsynth socket port.
		self.buffersize=4096           # buffer size for socket.
		self.readtimeout=5             # read timeout in seconds (blocking IO only).
		self.fluidsynth = None         # the fluidsynth system process.
		self.eof = '.'                 # arbitrary text to mark the end of stream.
		self.debug = True              # enable verbose logging to stdout.

		# see `man fluidsynth` for explanation of cli options
		#
		# -C, --chorus
		#    Turn the chorus on or off [0|1|yes|no, default = on]
		# -i, --no-shell
		#    Don't read commands from the shell [default = yes]
		# -g, --gain
		#    Set the master gain [0 < gain < 10, default = 0.2]
		# -j, --connect-jack-outputs
		#    Attempt to connect the jack outputs to the physical ports
		# -p, --portname=[label]
		#    Set MIDI port name (alsa_seq, coremidi drivers)
		# -s, --server
		#    Start FluidSynth as a server process
		# -R, --reverb
		#    Turn the reverb on or off [0|1|yes|no, default = on]

		self.fluidsynthCmd = 'fluidsynth -sli -g5 -C0 -R0 -pFluidSynth-GUI'


		# cli option overrides
		if ( options.fluidsynthCmd != '' ):
			self.fluidsynthCmd = options.fluidsynthCmd

		# set up/test server
		self.initFluidSynth()

		# process command line args passed to fluid synth
		if len(self.args) > 0:
			for arg in args:
				self.cmd(arg,True)


	def __del__(self):
		self.closeFluidSynth()


	# test/initialize connection to fluidsynth
	def initFluidSynth(self):

		try:
			self.connect()
			# looks good
			return True

		except Exception as e:
			print('error: FluidSynth not running?')
			print('could not connect to socket: ' + str(self.port))
			print(e)

		try:
			# try starting fluidsynth command line process
			print('trying to start fluidsynth ...')
			print(self.fluidsynthCmd)
			cmd = self.fluidsynthCmd.split()
			self.fluidsynth = subprocess.Popen(cmd, shell=False, 
				stdin=subprocess.PIPE, stdout=subprocess.PIPE)

			# process should be started, try connection again
			for i in range(10):	
				try:
					self.connect()
					return True

				except Exception as e:
					print(e)
					print('retry ...')
					time.sleep(.5)

		except Exception as e:
			print('error: fluidsynth could not start')
			print(e)

		print('error: giving up. :(')
		print('you may try stopping any fluidsynth that is currently running.')
		print('for example, on linux:')
		print('    killall fluidsynth')
		print('    killall -s 9 fluidsynth')
		return False


	# cleanup
	def closeFluidSynth(self):
		self.close()
		try:
			self.fluidsynth.kill()
		except:
			print('fluidsynth will be left running')


	# create socket connection
	# NOTE: do NOT connect on every request (like HTTP).
	# fluidsynth seems to only be able to spawn a small number of total sockets.
	# reuse the same socket connection for all io, or you will run out of 
	# fluidsynth threads.
	def connect(self):

		self.clientsocket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
		self.clientsocket.connect((self.host,self.port))
		self.clientsocket.settimeout(self.readtimeout)
		print('connected to port: ' + str(self.port))


	# cleanup sockets when finished
	def close(self):

		self.clientsocket.shutdown(socket.SHUT_RDWR)
		self.clientsocket.close()
		print('closed')


	# send data to fluidsynth socket
	def send(self, packet):
		if self.debug:
			print('send: '+ packet)
		self.clientsocket.send(packet)


	# read data from fluidsynth socket
	# these packets will be small
	def read(self):
		data = ''
		# inject EOF marker into output
		# add blank line and eof marker, to tag the end of the stream
		self.send('echo ""\n')
		self.send('echo ' + self.eof + '\n')
		try:
			i=0
			max_reads = 1000000 # avoid infinite loop
			part = ''
			while i<max_reads: 
				i+=1
				part = self.clientsocket.recv(self.buffersize)
				data += part
				#print 'chunk: ' + part
				# test data for boundary hit
				# NOTE: part may only contain fragment of eof 
				for eol in [ '\n' ]:
					eof = eol + self.eof + eol 
					pos = data.find(eof)
					if pos > -1: 
						# found end of stream
						# chop eof marker off
						data = data[0:pos]
						if self.debug:
							print('data: ' + data + '\n--\n')
						return data

		except Exception as e:
			print('warn: eof not found in stream: "'+self.eof+'"') 
			print(e)

		if self.debug:
			print('data (timeout): ' + data + '\n--\n')
		return data


	# full request/response transaction
	# the end of line '\n' char is not required.
	# NOTE: non-blocking mode is MUCH faster.  
	# always use non-blocking unless you actually need to read the response.
	#   returns: data packet (only if blocking)
	#   returns: True (only if non-blocking)
	def cmd(self, packet, non_blocking = False):
		data = ''
		self.send(packet+'\n')

		#if non_blocking and not self.debug: #to disable nonblocking for debug  
		if non_blocking:
			return True

		data = self.read()
		return data


	## DEPRECATED - this works and is left in as fallback option.
	## Instead of connecting with a socket, you can also connect to the cli directly.
	## This is a very basic version of 'Expect'.
	## the function will read all output and stop at the next '>' prompt.
	## NOTE: non_blocking IO was not implemented.
	##
	## Python bug?!  Popen readlines() does not return data.
	## And, Python doesn't support multiple Popen communicate() calls.
	## There seems to be a race condition with pipes. 
	## Overall, IMO subprocess is difficult to work with.
	## Workaround: poll input with '\n' write to prevent IO blocking 
	## on each single readline().  Then, drain the padded output after 
	## the total size of the text response is known.
	##
	#def cmd(self, cmd):
	#	readtil = '>'
	#	p=self.fluidsynth
	#	lines=''
	#	p.stdin.write(cmd + '\n' )
	#	count=0 # track \n padding
	#	while True:
	#		count += 1
	#		p.stdin.write('\n')
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
	#			lines = lines + '\n' + line


	# getter/setter for fluidsynth config
	def setValue(self,key,value):
		value = self.cmd('set ' + key + ' ' + value, True)

	def getValue(self,key):
		value = self.cmd('get ' + key)
		values = value.split() 
		if len(values):
			return values[-1]
		else:
			return '' 


	# parser utils
	def isTruthy(self,value):
		value = value.lower()
		if value in ['true','1','on','yes']:
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


	# channel control
	def setSelectedChannel(self,channel):
		self.selectedChannel = int(channel)

	def getSelectedChannel(self):
		return self.selectedChannel

	# 0-based for fluidsynth
	def getSelectedChannel0(self):
		return self.selectedChannel-1


	# return last known font and instrument on a channel
	# note: channel is 1-based
	# return: (font_file, instrument_name)
	def getFontInstrumentFromChannel(self,channel):

		try:
			chan0 = channel-1 # to 0 based
			font_id = self.fontsInUse[chan0] 
			font = self.fontFilesLoaded[font_id]
			instrument = self.instrumentsInUse[chan0]
			return (font, instrument)
		except Exception as e:
			print('error: could not find font, instrument on channel '+str(channel))
			print(e)

		return ('','')


	# lookup fluidsynth's font id from a path (if loaded)
	# returns int
	def getSoundFontIdFromPath(self, path):
		for key, value in self.fontFilesLoaded.iteritems():
			if value == path:
				return int(key)
		return -1


	# load sound soundfont, for example:
	#
	#> load "/home/Music/sf2/Brass 4.SF2"
	#loaded SoundFont has ID 1
	#fluidsynth: warning: No preset found on channel 9 [bank=128 prog=0]
	#> 
	def loadSoundFont(self, sf2Filename):

		try:
			# try cache
			id = self.getSoundFontIdFromPath(sf2Filename)

			if id < 0:
				# cache miss	
				data = self.cmd('load "'+ sf2Filename +'"')

				# parse sound font id
				ids = [int(s) for s in data.split() if s.isdigit()]	
				if len(ids) > 0:
					id = ids[-1] # return last item
					id = int(id)

			self.fontFilesLoaded[id] = sf2Filename # store mapping id->file
			self.activeSoundFontId = id
			self.activeSoundFontFile = sf2Filename
			return id

		except Exception as e:
			print('error: could not load font: ' + sf2Filename)
			print(e)	

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
					
			#ids = ids[3:] # cli only: discard first 3 items (header)
			ids_clean = []
			for id in ids:
				# example:
				# '1 /home/user/sf2/Choir__Aahs_736KB.sf2'
				parts = id.split()

				try:
					if parts[0] != 'ID':
						id2=int(parts[0])
						ids_clean.append(id2)

				except Exception as e:
					print('warn: skipping font parse:')
					print(parts)
					print(e) 

			return ids_clean

		except Exception as e:
			print('error: no fonts parsed')
			print(e)

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
			#	print('Fonts in use:')
			#	print(self.fontsInUse)
			#	print('All Fonts in memory:')
			#	print(ids)

			## unload any soundfont that is not referenced
			for id in ids:
				sid=str(id)
				if id in self.fontsInUse:
					#print 'font in use: ' + sid
					pass
				else:
					self.cmd('unload '+ sid, True)
					del self.fontFilesLoaded[id]

		except Exception as e:
			print('error: could not unload fonts')
			print(e)


	# list instruments in soundfont, for example:
	# 
	#> inst 1
	#000-000 Dark Violins  
	#> 
	def getInstruments(self,fontId):

		fontId = int(fontId)
		if fontId < 0:
			return []

		try:
			data = self.cmd('inst ' + str(fontId))
			ids = data.splitlines()
			#ids = map(lambda s: s.strip(' '), ids)
			#ids = ids[2:] # cli only: discard first two items (header)
			return ids

		except Exception as e:
			print('error: could not get instruments')
			print(e)

		return []


	# change voice in soundfont
	#
	# arg formats:
	#	000-000 Some Voice
	#	000-000
	#
	#note: 'prog bank prog' doesn't always seem to work as expected
	#using 'select' instead
	# for example:
	#select chan sfont bank prog
	#> 
	def setInstrument(self,instrumentName):

		if instrumentName == '':
			raise Exception('instrument name cannot be blank')

		if self.activeSoundFontId < 0:
			return ''

		try:
			parts = instrumentName.split()
			ids = parts[0].split('-')			
			chan0 = str(self.getSelectedChannel0()) # convert base 0
			font = str(self.activeSoundFontId)
			bank = ids[0]
			prog = ids[1]
			cmd = 'select '+chan0+' '+font+' '+bank+' '+prog
			data = self.cmd(cmd, True)

			self.activeInstrument = instrumentName
			self.fontsInUse[int(chan0)] = int(font)
			self.instrumentsInUse[int(chan0)] = instrumentName 
			self.activeChannel = self.getSelectedChannel()

			return data

		except Exception as e:
			print('error: could not select instrument: '+instrumentName)
			print(e)

		return False 


	# load soundfont, select first program voice
	# returns (id,array_of_voices)
	def initSoundFont(self,sf2):
		try:
			self.unloadSoundFonts()
			id = self.loadSoundFont(sf2)
			if id > -1:
				voices = self.getInstruments(id)
				self.setInstrument(voices[0])
				return (id,voices)

		except Exception as e:
			print('error: font and instrument did not load: '+sf2)
			print(e)

		return (-1,[])


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
		self.cmd('reverb ' + str(int(boolean)),True)
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
		self.cmd('chorus ' + str(int(boolean)),True)
		# ? not auto updated
		self.setValue('synth.chorus.active', str(int(boolean))) 

	def setChorusNR(self,num):
		self.cmd('cho_set_nr ' + str(num), True)
	def setChorusLevel(self,num):
		self.cmd('cho_set_level ' + str(num), True)
	def setChorusSpeed(self,num):
		self.cmd('cho_set_speed ' + str(num), True)
	def setChorusDepth(self,num):
		self.cmd('cho_set_depth ' + str(num), True)

	# note: no getters for chorus details	


	# reset (all notes off)
	def panic(self):
		self.cmd('reset', True)


# end class


# GUI
#
# Expected order of events
#
#	1. load dir
#	2. optional: filter list of fonts
#	3. optional: change selected channel 
# 	4. load sound font
# 	5. load instruments
#	6. select instrument
#	7. adjust levels 
#
# the gui manages all persistence of the interface.
# anything in self.data will be written to:
#    ~/.fluidsynth-gui/data.json
class FluidSynthGui(wx.Frame):

	def __init__(self, parent, title, api):

		super(FluidSynthGui, self).__init__(parent, title=title, size=(640, 480))

		self.fluidsynth = api    # the fluidsynth socket api 

		self.soundFontsAll = []  # all files in dir.  only filenames, not full paths.
		self.soundFonts = []     # filtered version of soundFontsAll
		self.instrumentsAll = [] # everything in current SoundFont.
		self.instruments = []    # filtered version of instrumentsAll.
		self.instrumentsIdx = 0  # pointer to currently selected instrument in list.
		self.dir = ''            # the current working dir.
		self.regex = False       # use regular expressions in search filter? 
		self.lastSelectedPath='' # to preserve selected dir/font when possible.
		self.parentDir = '..'    # text for option to navigate up one dir.
	
		# persistent data
		self.data = {}           # anything in this dict will be persisitent
		self.dataDir = os.path.expanduser('~') + '/.fluidsynth-gui' # prefs dir
		self.dataFile = self.dataDir + '/data.json' # save gui state to this file

		# what components will be persistent?
		# anything in this list will be automatically serialized
		self.saveUiState = [
				'textSoundFontDir',
				'textFilterSoundFont',
				'spinChannel',
				'sGain',
				'cbEnableReverb',
				'sReverbDamp',
				'sReverbRoomSize',
				'sReverbWidth',
				'sReverbLevel',
				'cbEnableChorus',
				'sChorusNR',
				'sChorusLevel',
				'sChorusSpeed',
				'sChorusDepth',
				'textSoundFontDir',
				'textFilterSoundFont',
				'spinChannel',
		]

		# attributes of fluidsynth api that will be preserved
		self.saveFluidSynthState = [
				'fontsInUse',
				'instrumentsInUse',
				'fontFilesLoaded',
				'selectedChannel',
				'activeInstrument',
				'activeChannel',
				'activeSoundFontId',
				'activeSoundFontFile',
		]


		# init
		self.initUI()                  # create widgets.
		self.bindEvents()              # bind ui widgets to callback event handlers.
		self.loadDataFile()            # load last state of GUI from file.
		self.applyPreferenceSnapshot() # restore last state of GUI.
		self.processArgs()             # cli overrides saved state.

		# show
		self.Centre()
		self.Show() 


	###########################################################################
	# persistence/data utilities ...
	###########################################################################

	# process command line args
	def processArgs(self):
		options = self.fluidsynth.options

		if options.dir != '':
			self.dir = options.dir
			self.textSoundFontDir.SetValue(self.dir)
			self.refreshSoundFontList(resetInstruments=True)

		self.regex = options.regex


	# getter/setter for persistent data
	def getData(self,key,default=''):
		if key in self.data:
			return self.data[key]
		return default	
	def setData(self,key,value):
		self.data[key] = value
	def unsetData(self,key):
		del self.data[key]


	# create persistent data storage, so GUI can restore last state
	# Everything in self.data will get serialized as a json file
	# and will be written to ~/.fluidsynth-gui/
	def storeDataFile(self):
		try:
			if not os.path.exists(self.dataDir):
				print('create preference dir ' + self.dataDir)
				os.makedirs(self.dataDir)	
			data = json.dumps(self.data)
			f = open(self.dataFile, 'w+')
			print('save preferences to ' + self.dataFile)
			f.write(data)
			f.close()
		except Exception as e:
			print('no preference file saved: '+self.dataFile)
			print(e)


	# restore persistent data
	def loadDataFile(self):
		try:
			print('read preferences from ' + self.dataFile)
			f = open(self.dataFile, 'r')
			data = f.read()
			f.close()
			self.data = json.loads(data)
		except Exception as e:
			print('no preference file loaded: ' + self.dataFile)
			print(e)


	# serialize GUI/api state to self.data
	def takePreferenceSnapshot(self):

		try:	
			# save ui widget properties
			# all objects in list should have a GetValue() function
			for prop in self.saveUiState: 
				try:
					obj = getattr(self, prop)
					if hasattr(obj, 'GetValue'):
						getvalue = getattr(obj, 'GetValue')
						if callable(getvalue):
							self.setData(prop,getvalue())
						else:
							print('error: '+prop+' does not have GetValue()')
				except Exception as e2:
					print(e2)
					print('remove property causing error: ' + prop)
					self.unsetData(prop)

			# save api properties
			for prop in self.saveFluidSynthState: 
				try:
					obj = getattr(self.fluidsynth, prop)
					self.setData(prop,obj)
				except Exception as e2:
					print(e2)
					print('remove property causing error: ' + prop)
					self.unsetData(prop)

			# avoid leaving spaces in search filter
			search = self.getData('textFilterSoundFont').strip(' \t\n\r') 
			self.setData('textFilterSoundFont',search)

		except Exception as e:
			print('error: could not take snapshot of preferences')
			print(e)
		

	# retore state of GUI/api to last snapshot
	def applyPreferenceSnapshot(self):

		try:	
			# restore ui widget properties
			# all objects in list has a GetValue() function
			for prop in self.saveUiState: 
				obj = getattr(self, prop)
				if hasattr(obj, 'SetValue'):
					setvalue = getattr(obj, 'SetValue')
					if callable(setvalue):
						setvalue(self.getData(prop))
					else:
						print('error: ' + prop + 'does not have SetValue()')

			# trigger change on all level controls to sync api
			self.onScrollGain()
			self.onClickEnableReverb()
			self.onClickEnableChorus()

			# restore core api properties manually...

			# restore last dir, will restore filtered view
			path = self.getData('textSoundFontDir')			
			print('restore dir path: ' + path)
			self.changeDir(path,giveFocus=True)

			# restore last fonts in memory
			# note: font ids will change on reloading
			fontsInUse = self.getData('fontsInUse')	 # overall map 
			fontFilesLoaded = self.getData('fontFilesLoaded')			
			instrumentsInUse = self.getData('instrumentsInUse')	
			selectedChannel = self.getData('selectedChannel') # base 1
			activeChannel = self.getData('activeChannel') # base 1
			activeSoundFontFile = self.getData('activeSoundFontFile')
			activeInstrument = self.getData('activeInstrument')

			# restore inactive fonts 
			print('restore inactive fonts...')
			for idx, oldFontId in enumerate(fontsInUse):

				if oldFontId == -1: # not in use
					continue

				channel = idx+1 # 1-based
				font = fontFilesLoaded[str(oldFontId)]
				instrument = instrumentsInUse[idx]

				print('found ')
				print('	channel: ' + str(channel))
				print('	font: ' + font)
				print('	instrument: ' + instrument)
				print('--')

				if font == '':
					print('error: missing font data')
					continue

				if instrument == '':
					print('error: missing instrument data')
					continue

				if channel == activeChannel and font == activeSoundFontFile and instrument == activeInstrument:
					print('found primary font')
					continue

				self.fluidsynth.setSelectedChannel(channel)
				self.fluidsynth.loadSoundFont(font)
				self.fluidsynth.setInstrument(instrument)

			# restore primary active channel
			# note: ignoring last selectedChannel if it was unused.
			print('restore active channel: ' + str(activeChannel))
			self.fluidsynth.setSelectedChannel(activeChannel)

			# restore primary font
			if activeSoundFontFile != '':
				self.setSoundFont(activeSoundFontFile)

			# restore primary instrument
			if activeInstrument != '':
				self.setInstrumentByName(activeInstrument)

		except Exception as e:
			print('error: could not restore snapshot of preferences')
			print(e)
			traceback.print_exc()


	###########################################################################
	# widgets for level controls (returns sizers) ... 
	###########################################################################

	# create all gui elements
	def initUI(self):

		self.panel = wx.Panel(self)
		panel = self.panel

		self.notebook = wx.Notebook(panel)
		page1 = wx.Panel(self.notebook)
		page2 = wx.Panel(self.notebook)

		self.createSoundFontControls(page1)
		self.createLevelControls(page2)

		self.notebook.AddPage(page1, 'Sound Fonts')
		self.notebook.AddPage(page2, 'Levels')

		sizer = wx.BoxSizer()
		sizer.Add(self.notebook, 1, wx.EXPAND)
		panel.SetSizer(sizer)
		sizer.Fit(self)


	# this is the main widget for loading soundfonts
	def createSoundFontControls(self,panel):

		# ui components
		self.textSoundFontDir = wx.TextCtrl(panel)
		self.btnSoundFontDir = wx.Button(panel, label='Browse...')
		self.textFilterSoundFont = wx.TextCtrl(panel)
		self.listSoundFont = wx.ListBox(panel, choices=self.soundFonts, size=(-1,200))
		self.listInstruments = wx.ListBox(panel,choices=self.instruments,size=(-1,200))  
		self.spinChannel = wx.SpinCtrl(panel,min=1,max=16,value='1')
		self.btnPanic = wx.Button(panel, label='All notes off')

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
		row.Add(self.textFilterSoundFont,flag=wx.ALIGN_CENTER_VERTICAL,proportion=2)
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

		boxlabel = 'Gain' 
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

		boxlabel= 'Reverb'

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
		self.sChorusNR=wx.Slider(panel,-1,50,0,99,style=slideStyle) 
		self.sChorusLevel=wx.Slider(panel,-1,50,0,100,style=slideStyle) 
		self.sChorusSpeed=wx.Slider(panel,-1,250,30,500,style=slideStyle) 
		self.sChorusDepth=wx.Slider(panel,-1,25,0,46,style=slideStyle) 

		self.enableChorusControls(False) # off by default

		boxlabel= 'Chorus'

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
		row.Add(self.sChorusNR,flag=flags, border=5, proportion=sprop)
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
		return vbox


	# wire up controls to callbacks.
	# note: this lists out all controls and events in one place.
	def bindEvents(self):

		# sound font page
		self.btnSoundFontDir.Bind(wx.EVT_BUTTON, self.onClickButtonBrowse, self.btnSoundFontDir)
		self.textSoundFontDir.Bind(wx.wx.EVT_KEY_UP, self.onKeyUpDirectory, self.textSoundFontDir)
		self.listSoundFont.Bind(wx.EVT_LISTBOX, self.onSelectSoundFont, self.listSoundFont)
		self.listSoundFont.Bind(wx.EVT_LISTBOX_DCLICK, self.onDblClickSoundFont, self.listSoundFont)
		self.listSoundFont.Bind(wx.wx.EVT_CHAR, self.onKeyDownSoundFont, self.listSoundFont)
		self.listInstruments.Bind(wx.EVT_LISTBOX, self.onSelectInstrument,self.listInstruments)
		self.listInstruments.Bind(wx.wx.EVT_CHAR, self.onKeyDownInstrument, self.listInstruments)
		self.textFilterSoundFont.Bind(wx.wx.EVT_KEY_UP, self.onKeyUpFilterSoundFont,self.textFilterSoundFont)
		self.spinChannel.Bind(wx.EVT_SPINCTRL,self.onClickChannel,self.spinChannel)
		self.btnPanic.Bind(wx.EVT_BUTTON, self.onClickPanic, self.btnPanic)

		# levels page 
		self.sGain.Bind(wx.EVT_SLIDER,self.onScrollGain)

		self.cbEnableReverb.Bind(wx.EVT_CHECKBOX,self.onClickEnableReverb)
		self.sReverbDamp.Bind(wx.EVT_SLIDER,self.onScrollReverbDamp)
		self.sReverbRoomSize.Bind(wx.EVT_SLIDER,self.onScrollReverbRoomSize)
		self.sReverbWidth.Bind(wx.EVT_SLIDER,self.onScrollReverbWidth)
		self.sReverbLevel.Bind(wx.EVT_SLIDER,self.onScrollReverbLevel)

		self.cbEnableChorus.Bind(wx.EVT_CHECKBOX,self.onClickEnableChorus)
		self.sChorusNR.Bind(wx.EVT_SLIDER,self.onScrollChorusNR)
		self.sChorusLevel.Bind(wx.EVT_SLIDER,self.onScrollChorusLevel)
		self.sChorusSpeed.Bind(wx.EVT_SLIDER,self.onScrollChorusSpeed)
		self.sChorusDepth.Bind(wx.EVT_SLIDER,self.onScrollChorusDepth)

		self.Bind(wx.EVT_CLOSE, self.onClose)


	###########################################################################
	# define event handlers ...
	# most of these can be called directly (event=None)
	###########################################################################


	# dir change
	def onKeyUpDirectory(self, event=None):
		# must be key up to read full text from input
		#keycode = event.GetKeyCode()
		path = self.textSoundFontDir.GetValue()
		self.changeDir(path,clearSearchFilter=True) # keep focus if typing
		if event != None:
			event.Skip()


	def onClickButtonBrowse(self, event):
		dlg = wx.DirDialog(self, 'Choose a directory:', style=wx.DD_DEFAULT_STYLE | wx.DD_NEW_DIR_BUTTON)
		dlg.SetPath(self.dir)
		path = None
		if dlg.ShowModal() == wx.ID_OK:
			print('selected: ' + dlg.GetPath())
			path = dlg.GetPath()

		dlg.Destroy()

		if path != None:
			self.textSoundFontDir.SetValue(path)
			self.changeDir(path,clearSearchFilter=True,giveFocus=True)

		event.Skip()


	# sound soundfont change
	def onSelectSoundFont(self, event=None):

		path = self.getSelectedSoundFontFile()

		if path == None or path == '':
			return  # nothing to do

		self.lastSelectedPath = path 

		# if user selected a file, automatically try to open the file as sf2
		if not os.path.isdir(path):
			self.clearInstrumentList()
			self.setSoundFont(path)
		
		if event != None:
			event.Skip()


	# allow changing directory if shown in sound font listing
	def onDblClickSoundFont(self, event=None):

		path = self.getSelectedSoundFontFile()
		self.lastSelectedPath = path 

		if os.path.isdir(path):
			# open directories
			self.clearInstrumentList()
			self.changeDir(path,clearSearchFilter=True,giveFocus=True)
		
		if event != None:
			event.Skip()


	def onSelectInstrument(self, event=None):
		idx = self.listInstruments.GetSelection()
		# NOTE: idx is -1 when using the arrow keys
		if ( idx < 0 ):
			return

		self.setInstrumentByIdx(idx)
		#self.refreshInstrumentList(0); # no draw needed 

		if event != None:
			event.Skip()


	# shared bindings
	def onKeyDownListBoxes(self, event):
		keycode = event.GetKeyCode()
		if keycode in [ wx.WXK_LEFT, wx.WXK_NUMPAD_LEFT ]:
			self.incInstrument(-1)
		elif keycode in [ wx.WXK_RIGHT, wx.WXK_NUMPAD_RIGHT ]:
			self.incInstrument(1)
		elif keycode == wx.WXK_ESCAPE:
			self.clearSearchFilter(refreshSoundFontList=True)

		event.Skip()


	# key navigation on sound font list
	# note: EVT_CHAR contains translated char 
	def onKeyDownSoundFont(self, event):

		keycode = event.GetKeyCode()
		path = self.getSelectedSoundFontFile()

		self.onKeyDownListBoxes(event)

		if keycode == wx.WXK_RETURN: 
			if path != None and os.path.isdir(path):
				# navigate to the new dir
				self.changeDir(path,clearSearchFilter=True,giveFocus=True)
				self.lastSelectedPath = path 

		elif keycode in [ wx.WXK_BACK, wx.WXK_DELETE ]: 
			# backspace for search filter
			try:
				search = self.textFilterSoundFont.GetValue()
				if len(search) > 0:
					# remove last char
					search = search[:-1]
					self.textFilterSoundFont.SetValue(search)
					self.onKeyUpFilterSoundFont()
			except Exception as e:
				print(e)
				pass

		elif keycode >= 32 and keycode <= 126:

			# user supplied some type of printable ascii data.  
			# update search filter
			a = '' 
			try:
				a = chr(keycode)
				search = self.textFilterSoundFont.GetValue()
				search += a
				self.textFilterSoundFont.SetValue(search)
				self.onKeyUpFilterSoundFont()
			except Exception as e:
				print(e)
				pass

		event.Skip()


	# key navigation on instrument list
	def onKeyDownInstrument(self, event):
		self.onKeyDownListBoxes(event)
		event.Skip()


	# search filter changed. does not require event input
	# clear input on ESC 
	def onKeyUpFilterSoundFont(self, event=None):

		keycode = -1
		pos = -1
		giveFocus = False

		if event != None:
			keycode = event.GetKeyCode()

			if keycode == wx.WXK_ESCAPE:
				self.clearSearchFilter(refreshSoundFontList=True)

			# up/down in text input?  user is trying to change sound font. 
			# transfer focus back to sound font listing.
			# text box is mostly intended just for visual feedback and editing.
			elif keycode in [ wx.WXK_UP, wx.WXK_NUMPAD_UP ]:
				idx = self.listSoundFont.GetSelection()
				if idx > 0:
					pos = idx - 1
				giveFocus = True	

			elif keycode in [ wx.WXK_DOWN, wx.WXK_NUMPAD_DOWN]:
				size = self.listSoundFont.GetCount()
				idx = self.listSoundFont.GetSelection()
				if idx < size - 1:
					pos = idx + 1
				giveFocus = True	

		self.refreshSoundFontList()

		if pos != -1: 
			self.setSoundFontByIdx(pos)

		if giveFocus:
			self.listSoundFont.SetFocus()

		if event != None:
			event.Skip()


	# channel change
	def onClickChannel(self,event):

		#self.changeDir('.',clearSearchFilter=True)
		self.clearSearchFilter()
		self.clearInstrumentList()
		self.refreshSoundFontList()

		channel = self.spinChannel.GetValue()
		self.fluidsynth.selectedChannel = channel

		# try to restore last known font/instrument on this channel
		(font,instrument)=self.fluidsynth.getFontInstrumentFromChannel(channel)

		if font != '':
			dirname = os.path.dirname(font)
			self.changeDir(dirname)
			self.setSoundFont(font)	
		else:
			self.listSoundFont.SetSelection(-1)	

		if instrument != '':
			self.setInstrumentByName(instrument)	
		else:
			self.refreshInstrumentList(-1)	


	# reset (all notes off)
	def onClickPanic(self, event):
		self.fluidsynth.panic()


	# master gain	
	def onScrollGain(self,event=None):
		value = self.sGain.GetValue()
		value *= 1/20.0 # 100 -> 5 
		self.fluidsynth.setGain(value)


	# reverb 
	def onClickEnableReverb(self,event=None):
		value = self.cbEnableReverb.GetValue()
		self.fluidsynth.setReverb(value)	
		self.enableReverbControls(value)

		# sync api to sliders
		if value:
			self.onScrollReverbDamp()
			self.onScrollReverbRoomSize()
			self.onScrollReverbWidth()
			self.onScrollReverbLevel()


	def onScrollReverbDamp(self,event=None):
		value = self.sReverbDamp.GetValue()
		value *= 1/100.0  # 100 -> 1
		self.fluidsynth.setReverbDamp(value) 


	def onScrollReverbRoomSize(self,event=None):
		value = self.sReverbRoomSize.GetValue()
		value *= 1/100.0  # 100 -> 1
		self.fluidsynth.setReverbRoomSize(value) 


	def onScrollReverbWidth(self,event=None):
		value = self.sReverbWidth.GetValue()
		value *= 1/100.0  # 100 -> 1
		self.fluidsynth.setReverbWidth(value) 


	def onScrollReverbLevel(self,event=None):
		value = self.sReverbLevel.GetValue()
		value *= 1/100.0  # 100 -> 1
		self.fluidsynth.setReverbLevel(value) 


	# chorus change
	def onClickEnableChorus(self,event=None):
		value = self.cbEnableChorus.GetValue()
		self.fluidsynth.setChorus(value)
		self.enableChorusControls(value)

		# sync api to sliders
		if value:
			self.onScrollChorusNR()
			self.onScrollChorusLevel()
			self.onScrollChorusSpeed()
			self.onScrollChorusDepth()


	def onScrollChorusNR(self,event=None):
		value = self.sChorusNR.GetValue()
		# scale: 1 -> 1
		self.fluidsynth.setChorusNR(value)


	def onScrollChorusLevel(self,event=None):
		value = self.sChorusLevel.GetValue()
		value *= 1/100.0 # 100 -> 1
		self.fluidsynth.setChorusLevel(value)


	def onScrollChorusSpeed(self,event=None):
		value = self.sChorusSpeed.GetValue()
		value *= 1/100.0 # 100 -> 1
		self.fluidsynth.setChorusSpeed(value)


	def onScrollChorusDepth(self,event=None):
		value = self.sChorusDepth.GetValue()
		# scale: 1 -> 1
		self.fluidsynth.setChorusDepth(value)


	# on shutdown
	def onClose(self,event=None):
		self.takePreferenceSnapshot()
		self.storeDataFile() # store GUI state, will restore on load
		if event != None:
			event.Skip() # continue shutdown


	###########################################################################
	# api ...
	###########################################################################

	# load new dir
	# pass in None for refresh
	def changeDir(self, path, clearSearchFilter=False, giveFocus=False):

		path = os.path.realpath(path) # cannonical form
		if not os.path.isdir(path):
			print('info: not a directory: ' + path)
			return

		if self.dir == path:
			# no change.  we're already there
			return

		if path != None:
			self.dir = path

		if clearSearchFilter:
			self.clearSearchFilter()

		# get files
		allFiles = os.listdir(self.dir)
		# exclude dot files
		allFiles = [x for x in allFiles if not x.startswith('.')]	
		self.soundFontsAll = allFiles 

		self.refreshSoundFontList(giveFocus=giveFocus,resetInstruments=True)

		if giveFocus:
			# update text input and transfer focus to font list
			if path != self.textSoundFontDir.GetValue():
				self.textSoundFontDir.SetValue(path) 


	# getters/setters for font and instrument
	# idx is the position in the select list (if in bounds)

	# what sound font is at list position?  
	# this returns the full path to the file.
	def getSoundFontFileFromIdx(self,idx):
		try:
			if idx > -1:
				selected = self.soundFonts[idx]
				path = self.dir + '/' + selected
				return path
		except Exception as e:
			print(e)
		return ''


	# what is the list index for a given font name?  
	# the arg may be the full path or just font filename.sf2
	# may return -1 if not found
	def getIdxFromSoundFontName(self,path):
		try:
			if path == self.parentDir:
				return 0
			fontName = os.path.basename(path) 
			idx = self.soundFonts.index(fontName)
			return idx
		except Exception as e:
			print(e)
		return -1	
		

	# what sound font is actively selected?
	# this returns the full path to the file.
	def getSelectedSoundFontFile(self):
		try:
			idx = self.listSoundFont.GetSelection()
			if idx > -1:
				return self.getSoundFontFileFromIdx(idx)

		except Exception as e:
			print(e)
		return ''


	# what is the list index for a given intrument name? 
	# may return -1 if not found
	def getIdxFromInstrumentName(self,value):
		try:
			idx = self.instruments.index(value)
			return idx
		except Exception as e:
			print(e)
		return -1	


	# what is the instrumetn name for a given list index?
	def getInstrumentFromIdx(self,idx):
		if idx > -1:
			instrumentName = self.instruments[idx]
			return instrumentName
		return ''


	# what instrument is currently selected?
	def getSelectedInstrument(self):
		idx = self.listSoundFont.GetSelection()
		return self.getInstrumentFromIdx(idx)


	# change soundfont in fluid synth 
	def setSoundFont(self, path):

		if path == '' or path == None:
			return -1 # nothing to do 

		self.lastSelectedPath = path # save selection

		if os.path.isdir(path):
			return -1 # not a sf2 file. don't try to load 

		# assume sf2 file, try to load
		(id,instrumentsAll) = fluidsynth.initSoundFont(path)
		if id == -1:
			instrumentsAll = ['Error: could not load as .sf2 file']

		self.instrumentsAll = instrumentsAll
		self.instruments = self.filterInstruments()

		# visually select font in list only if needed
		selIdx = self.getIdxFromSoundFontName(path)
		if id != -1 and selIdx != -1 and selIdx != self.listSoundFont.GetSelection():
			self.listSoundFont.SetSelection(selIdx)

		#self.setInstrumentByIdx(0) # already initalized
		self.refreshInstrumentList(0);
		return id


	# allow setting sound font by list index
	def setSoundFontByIdx(self, idx):
		try:
			path = self.getSoundFontFileFromIdx(idx)
			self.listSoundFont.Select(-1)
			#self.listSoundFont.Focus(-1)
			id =  self.setSoundFont(path)
			return id
		except Exception as e:
			print('error: could not set sound font by idx: ' + str(idx))
			print(e)
		return -1

		
	# change the instrument in fluidsynth
	# this does NOT redraw the list of all instruments
	# like setInstrumentByName but accepts a named instrument, for example:
	#    000-000 Dark Violins  
	# expects: setSoundFont is called first 
	def setInstrumentByName(self,instrumentName):

		if instrumentName == '':
			print('warn: no instrument name')
			return False # nothing to do

		idx = self.instrumentsIdx
		try:
			idx = self.getIdxFromInstrumentName(instrumentName)
			self.instrumentsIdx = idx
		except:
			print('error: did not resolve name->id for setInstrumentByName')
			print('    for name: "' + instrumentName + '"')

		# visually select instrument in list if needed
		if idx != self.listInstruments.GetSelection():
			#self.listInstruments.SetSelection(idx)
			self.listInstruments.SetSelection(idx)

		return self.fluidsynth.setInstrument(instrumentName)	


	# like setInstrumentByName, but set instrument by list box index.
	# expects: setSoundFont should be called first
	def setInstrumentByIdx(self,selectedIdx=None):
		if selectedIdx != None:
			idx = self.incInstrumentIdx( selectedIdx, 0 )
			self.instrumentsIdx = idx

		instrumentName = self.getInstrumentFromIdx(self.instrumentsIdx)
		return self.setInstrumentByName(instrumentName)	


	# refresh list of soundfonts
	def refreshSoundFontList(self, resetInstruments=False, giveFocus=False):

		# preserve previous selection if possible
		oldValue = self.lastSelectedPath # last known dir or font

		self.soundFonts = self.filterSoundFont() # apply search filter
		self.soundFonts.insert(0, self.parentDir) # add up-dir option
		self.listSoundFont.Set(self.soundFonts)

		idx = self.getIdxFromSoundFontName(oldValue) 
		if idx < 0:
			idx = 0 # could not restore old selection. default to first item

		self.listSoundFont.SetSelection(idx)

		if resetInstruments:
			self.refreshInstrumentList(0);
		
		#if giveFocus and len(self.soundFonts):
		if giveFocus:
			self.listSoundFont.SetFocus()


	# increment scrolling index, keep index in bounds
	def incInstrumentIdx(self,id,add=0):
		id+=add
		if ( id < 0 ):
			id = 0
		size = len(self.instruments)
		if ( id >= size ):
			id = size - 1
		return id


	# manually move active instrument pointer in list
	def incInstrument(self,direction):
			idx = self.incInstrumentIdx(self.instrumentsIdx,direction)
			self.setInstrumentByIdx(idx)
			#self.refreshInstrumentList()


	# refresh entire list of instruments  
	# this is always drawn from cache
	# expects: setSoundFont should be called first
	def refreshInstrumentList(self,selectedIdx=None):
		if selectedIdx != None: 
			self.instrumentsIdx = selectedIdx
		self.listInstruments.Set(self.instruments)
		self.listInstruments.SetSelection(self.instrumentsIdx)


	# search 
	def grep(self, pattern, word_list):
		expr = re.compile(pattern, re.IGNORECASE)
		return [elem for elem in word_list if expr.search(elem)]


	# apply search filter
	def filterSoundFont(self):
		pattern = self.textFilterSoundFont.GetValue()

		# whitespace may be confusing since it won't show up in search box
		# by default all space will be a wildcard 
		# clean up trailing, duplicate spaces
		pattern = pattern.strip(' \t\n\r') 
		pattern = re.sub('  +', ' ', pattern)

		# disable regex searches by default, unless turned on via cli switch
		if self.regex:
			pattern = pattern.replace(' ','.*')
		else:
			pattern = re.escape(pattern)
			pattern = pattern.replace('\\ ','.*')
		
		lst = self.grep(pattern,self.soundFontsAll);
		return sorted(lst, key=lambda s: s.lower())


	# possible enhancement: add search filter for instruments
	# currently there is no search filter 
	# since 99% of the soundfonts I use have less than 10 instruments
	def filterInstruments(self):
		return self.instrumentsAll;


	# remove all instruments from listing
	def clearInstrumentList(self):
		self.instruments = [] 
		self.instrumentsAll = [] 
		self.refreshInstrumentList()	


	# remove filter, force refresh of file listing
	def clearSearchFilter(self,refreshSoundFontList=False):
		self.textFilterSoundFont.SetValue('') 
		if refreshSoundFontList:
			self.refreshSoundFontList()


	# enable/disable fx widgets
	def enableReverbControls(self,enabled):
		self.sReverbRoomSize.Enable(enabled)
		self.sReverbDamp.Enable(enabled)
		self.sReverbWidth.Enable(enabled)
		self.sReverbLevel.Enable(enabled)


	# enable/disable fx widgets
	def enableChorusControls(self,enabled):
		self.sChorusNR.Enable(enabled)
		self.sChorusLevel.Enable(enabled)
		self.sChorusSpeed.Enable(enabled)
		self.sChorusDepth.Enable(enabled)


# end class


# main
if __name__ == '__main__':

	try:
		# parse cli options 
		parser = optparse.OptionParser()
		parser.add_option('-d', '--dir', action='store', dest='dir',
			help='load a sf2 directory', default='') 
		parser.add_option('-c', '--cmd', action='store', dest='fluidsynthCmd', 
			help='use a custom command to start FluidSynth server', default='') 
		parser.add_option('--regex', action='store_true', dest='regex', 
			help='allow regex patterns in search filter') 
		options, args = parser.parse_args()

		# init api
		fluidsynth = FluidSynthApi(options,args)

		# wrap api with gui
		app = wx.App(clearSigInt=True)
		gui = FluidSynthGui(None, title='FluidSynth Gui v1.0',api=fluidsynth)
		app.MainLoop()

	except Exception as e:
		print('exiting...')
		print(e)
		traceback.print_exc()

# end main


