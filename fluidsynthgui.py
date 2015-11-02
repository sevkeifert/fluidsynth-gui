#!/usr/bin/python
#
# Kevin Seifert - GPL 2005
#
# This program creates a simple synthesizer interface for fluidsynth.
# This lets you easily cycle through a large set of sound fonts
# and select instruments.
#
# This program just runs the fluidsynth command line program, sending 
# input, and parsing output.  
#
# How to use:
#     1. select a folder that contains *.sf2 files
#     2. Up/Down arrows will cycle through the soundfont files
#     3. Left/Right arrows will cycle through the instruments in each file
#     4. You can filter the sound fonts listed (search box at bottom) 
#     5. Optional: you can set the midi channel you want to use (default = 1) 
#
# Command line options:
#     1. cmd1|cmd2                pipe-delimited fluidsynth commands (can be "")
#     2. path_to_sf2_dir          the default path to your sound fonds 
#
#     For example:
#         python  fluidsynthgui.py  "gain 5"  /home/Music/Public/sf2/
#
# System Requirements
#	jack/QjackCtl	
#	fluidsynth (you should configure for command line first)
#	Python 2.7+
#	python-wxgtk2.8+
#
# Tested with: xubuntu 14.04, FluidSynth version 1.1.6
#
# Expected Fluidsynth command definitions:
#
#   select chan font bank prog  Combination of bank-select and program-change
#   quit                        Quit the synthesizer
#   load file                   Load SoundFont 
#   unload id                   Unload SoundFont by ID 
#   fonts                       Display the list of loaded SoundFonts
#   inst font                   Print out the available instruments for the font
#   gain value                  Set the master gain (0 < gain < 5)

import sys 
import os 
import wx
import re
import subprocess


# API
# this api just writes/reads data to/from the command line interface
class FluidSynthApi:

	def __init__(self):
		# start fluidsynth process
		print "Init fluidsynth..."
		self.fluidsynth = subprocess.Popen(['fluidsynth'], shell=False, stdin=subprocess.PIPE, stdout=subprocess.PIPE)

		# memory/font management
		# we only can load 16 fonts on 16 channels.  unload the rest.
		self.fontsInUse = [-1,-1,-1,-1,-1,-1,-1,-1,-1,-1,-1,-1,-1,-1,-1,-1]
		self.activeChannel = 1 # base 1
		self.activeSoundFont = -1

		self.debug = True

	# execute command in fluidsynth and read output.
	#
	# NOTES: This is a very basic version of 'Expect'.
	# For example if calling 
	#	print fluidsynth.cmd("help")
	# the function will read all output and stop at the next ">" prompt.
	# The function expects the fluid synth prompt to look like ">".
	#
	# Python bug?!  Popen readlines() does not return data.
	# And, Python doesn't support multiple Popen communicate() calls.
	# There seems to be a race condition with pipes. 
	# Overall, IMO subprocess is difficult to work with.
	#
	# Workaround: I'll poll input with "\n" write to prevent IO blocking 
	# on single readline().  Then, I'll drain the output after I know 
	# the total size of the text response.
	#
	# Other possible fixes: use pexpect, or fluidsynth python bindings
	# but, this will make the script heavier with dependencies.
	def cmd(self, cmd, readtil='>'):

		p=self.fluidsynth

		lines=''
		p.stdin.write(cmd + "\n" )
		count=0 # track \n padding

		while True:
			count += 1
			p.stdin.write("\n")
			line = p.stdout.readline()
			line = line.strip();

			if line == readtil:
				if lines != '':
					# drain \n padding 
					for num in range(1,count):
						p.stdout.readline()
					if self.debug:
						print lines	
					return lines
			else:
				lines = lines + "\n" + line

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
			self.activeSoundFont = id
			return id
		except:
			print "error: did not complete loading font: " + sf2
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
					
			ids = ids[3:] # discard first 3 items (header)
			ids_clean = []
			for id in ids:
				# example:
				# '1 /home/user/sf2/Choir__Aahs_736KB.sf2'
				parts = id.split()

				try:
					id2=int(parts[0])
					ids_clean.append(id2)
				except:
					print "error: skip font parse: " + parts
			return ids_clean
		except:
			print "error: no fonts parsed"

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
					self.cmd('unload '+ sid )
		except:
			print "error: could not unload fonts"

	# list instruments in soundfont, for example:
	# 
	#> inst 1
	#000-000 Dark Violins  
	#> 
	def getInstruments(self,id):
		try:
			data = self.cmd('inst ' + str(id))
			ids = data.splitlines()
			return ids[2:] # discard first two items (header)
		except:
			print "error: could not get instruments"
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
		try:
			parts = id.split()
			ids = parts[0].split('-')			
			chan = str(self.activeChannel-1) # base 0
			font = str(self.activeSoundFont)
			bank = ids[0]
			prog = ids[1]
			cmd = 'select '+chan+' '+font+' '+bank+' '+prog
			data = self.cmd(cmd)

			self.fontsInUse[int(chan)] = int(font)

			return data
		except:
			print 'error: could not select instrument: ' + id
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
		except:
			print "error: voice did not load: " + sf2

		return (-1,[])


# GUI
class FluidSynthGui(wx.Frame):
  
	def __init__(self, parent, title, api):
		super(FluidSynthGui, self).__init__(parent, title=title, 
			size=(640, 350))
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
		self.args()
		self.Centre()
		self.Show() 


	# command line args
	#	cmd1 | cmd2 cmd3
	# 	soundfont dir
	def args(self):

		# init fluidsynth
		if len(sys.argv) > 1:
			cmds = sys.argv[1].split("|")
			for cmd in cmds:	
				print self.fluidsynth.cmd(cmd)

		# init soundfonts dir
		if len(sys.argv) > 2:
			self.dir = sys.argv[2]
			self.textSoundFontDir.SetValue(self.dir)
			self.refreshSoundFonts()

	def initUI(self):

		# user interface 	

		# ui components 
		panel = wx.Panel(self)
		self.textSoundFontDir = wx.TextCtrl(panel)
		self.btnSfDir = wx.Button(panel, label="Browse...")
		self.textfilterSoundFont = wx.TextCtrl(panel)
		self.listSoundFont = wx.ListBox(panel, choices=self.soundFonts, size=(-1,200))
		self.listInstruments = wx.ListBox(panel,choices=self.instruments,size=(-1,200))  
		self.spinChannel = wx.SpinCtrl(panel,min=1,max=16,initial=1)

		# start layout 
		vbox = wx.BoxSizer(wx.VERTICAL)

		# row1
		row = wx.BoxSizer(wx.HORIZONTAL)
		row.Add( wx.StaticText(panel, label='Sound Font Dir') , flag=wx.ALIGN_CENTER_VERTICAL|wx.RIGHT, border=10)
		row.Add(self.textSoundFontDir, flag=wx.ALIGN_CENTER_VERTICAL, proportion=4)
		row.Add(self.btnSfDir, flag=wx.ALIGN_CENTER_VERTICAL, proportion=1)

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
		row.Add(self.textfilterSoundFont,flag=wx.ALIGN_CENTER_VERTICAL,proportion=4)
		row.Add(wx.StaticText(panel, label='Channel'),flag=wx.ALIGN_CENTER_VERTICAL|wx.LEFT, border=10, proportion=1)
		row.Add(self.spinChannel,flag=wx.ALIGN_CENTER_VERTICAL,proportion=1)

		vbox.Add(row, flag=wx.EXPAND|wx.ALL, border=5)

		# event binding

		self.btnSfDir.Bind(wx.EVT_BUTTON, self.clickButtonBrowse, self.btnSfDir)
		self.textSoundFontDir.Bind(wx.wx.EVT_KEY_UP, self.keyUpDirectory, self.textSoundFontDir)
		self.listSoundFont.Bind(wx.EVT_LISTBOX, self.selectSoundFont, self.listSoundFont)
		self.listSoundFont.Bind(wx.wx.EVT_KEY_DOWN, self.keyDownSoundFont, self.listSoundFont)
		self.listInstruments.Bind(wx.EVT_LISTBOX, self.selectInstrument,self.listInstruments)
		self.textfilterSoundFont.Bind(wx.wx.EVT_KEY_UP, self.keyUpFilterSoundFont,self.textfilterSoundFont)
		self.spinChannel.Bind(wx.EVT_SPINCTRL,self.clickChannel,self.spinChannel)

		# pack
		panel.SetSizer(vbox)


	# event handlers

	# dir
	def keyUpDirectory(self, event):
		event.Skip()
		keycode = event.GetKeyCode()
		path = self.textSoundFontDir.GetValue()

		if ( os.path.isdir(path) ):
			self.dir = path
			self.refreshSoundFonts()

	# set self.dir
	def clickButtonBrowse(self, event):
		event.Skip()
		dlg = wx.DirDialog(self, "Choose a directory:", style=wx.DD_DEFAULT_STYLE | wx.DD_NEW_DIR_BUTTON)
		if dlg.ShowModal() == wx.ID_OK:
			print 'selected: %s\n' % dlg.GetPath()
			self.dir = dlg.GetPath()
			self.textSoundFontDir.SetValue(self.dir)
			self.refreshSoundFonts()

		dlg.Destroy()
		

	# sound soundfont change
	def selectSoundFont(self, event):
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
		
	def selectInstrument(self, event):
		idx = self.listInstruments.GetSelection()
		event.Skip()

		# NOTE: idx is -1 when using the arrow keys
		if ( idx < 0 ):
			return
		self.instrumentsIdx = int(idx)
		self.loadInstrument()

	def keyDownSoundFont(self, event):
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

	# keep scrolling id in bounds
	def incInstrument(self,id,add=0):
		id+=add
		if ( id < 0 ):
			id = 0
		size = len(self.instruments)
		if ( id >= size ):
			id = size - 1
		return id

	# filters
	def keyUpFilterSoundFont(self,event):
		event.Skip()
		self.refreshSoundFonts(True)

	# channel
	def clickChannel(self,event):
		chan=self.spinChannel.GetValue()
		self.fluidsynth.activeChannel = chan	

	# api 
	def grep(self, pattern, word_list):
	    expr = re.compile(pattern, re.IGNORECASE)
	    return [elem for elem in word_list if expr.match(elem)]

	def filterSoundFont(self):
		lst = self.grep(self.textfilterSoundFont.GetValue(),self.soundFontsAll);
		return sorted(lst, key=lambda s: s.lower())

	def filterInstruments(self):
		return self.instrumentsAll;

	def refreshSoundFonts(self,cache=False):
		if not cache:
			self.soundFontsAll = os.listdir(self.dir)

		self.soundFonts = self.filterSoundFont()
		self.listSoundFont.Set(self.soundFonts)

		self.instrumentsIdx = 0;
		self.refreshInstruments();

	# instrument
	def refreshInstruments(self):
		self.instruments = self.filterInstruments()
		self.listInstruments.Set(self.instruments)
		self.listInstruments.SetSelection(self.instrumentsIdx)

	def loadInstrument(self):
		idx = self.incInstrument( self.instrumentsIdx, 0 )
		sel = self.instruments[idx]
		print "- select " + str(idx) + " " + sel
		self.fluidsynth.setInstrument(sel)	


# main

if __name__ == '__main__':
  
	app = wx.App()
	fluidsynth = FluidSynthApi()
	FluidSynthGui(None, title='Fluid Synth Gui',api=fluidsynth)
	app.MainLoop()

