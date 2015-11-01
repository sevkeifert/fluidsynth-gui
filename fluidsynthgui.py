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
#     4. You can filter the sound fonts with the filter (bottom) 
#
# Command line options:
#     1. fluidsynth_cmd1 | fluidsynth_cmd2	
#     2. path_to_sf2_dir
#
# System Requirements
#	jack/QjackCtl	
#	fluidsynth (you should configure for command line first)
#	Python 2.7
#	wxpython
#
# Tested with: xubuntu 12.04, FluidSynth version 1.1.6

import sys 
import os 
import wx
import re
import subprocess

class FluidSynthApi:

	def __init__(self):
		print "Init fluidsynth..."
		# start fluidsynth process
		self.fluidsynth = subprocess.Popen(['fluidsynth'], shell=False, stdin=subprocess.PIPE, stdout=subprocess.PIPE)

	# execute command in fluidsynth and read output
	#
	# NOTE: This is a very basic version of 'Expect'
	# The function expects the fluid synth prompt to look like ">"
	# Example: 
	#	print cmd("help")
	# Function will read all outupt and stop at the next ">" prompt
	def cmd(self, cmd,readtil='>'):

		p=self.fluidsynth
		print "- cmd: " + cmd

		lines=''
		p.stdin.write(cmd + "\n" )
		count=0

		# ?!  readlines() does not return data.
		# Seems to be a race condition with pipes.
		# Python doesn't seem to support multiple Popen communicate()
		# So, pad input with "\n" to prevent IO blocking on 1 read.
		# Possible fixes: use pexpect, or fluidsynth python bindings
		# but, this will make the script heavier with dependencies.

		while True:

			count += 1
			p.stdin.write("\n")
			line = p.stdout.readline()
			line = line.strip();

			if line == readtil:
				if lines != '':
					# drain padding 
					for num in range(1,count):
						p.stdout.readline()
						
					return lines
			else:
				lines = lines + "\n" + line


	# load sound font, for example:
	#
	#> load "/home/Music/sf2/Brass 4.SF2"
	#loaded SoundFont has ID 1
	#fluidsynth: warning: No preset found on channel 9 [bank=128 prog=0]
	def loadSoundFont(self, sf2):
		try:
			data = self.cmd('load "'+ sf2 +'"')
			ids = [int(s) for s in data.split() if s.isdigit()]	
			id = ids[-1]
			return id
		except:
			return -1



	# remove font from memory, for example:
	#
	#> fonts
	#ID  Name
	# 1  /home/kevins/Music/sf2/Brass 4.SF2
	def getSoundFonts(self):
		try:
			data = self.cmd('fonts')
			ids=data.splitlines()
					
			ids = ids[3:]
			ids_clean = []
			for id in ids:
				# example:
				# '1 /home/user/sf2/Choir__Aahs_736KB.sf2'
				parts = id.split()
				id2=parts[0]	
				#name=parts[0]	
				ids_clean.append(id2)
			return ids_clean
		except:
			print "no fonts parsed"


	# remove font from memory, for example:
	#
	#> unload 1
	#fluidsynth: warning: No preset found on channel 0 [bank=0 prog=0]
	def unloadSoundFonts(self):
		try:
			ids = self.getSoundFonts()
			for id in ids:
				self.cmd('unload "'+ id +'"')
		except:
			print "could not unload fonts"

	# list instruments in sound fon, for example:
	def getInstruments(self,id):
		
		try:
			data = self.cmd('inst ' + str(id))
			ids = data.splitlines()
			return ids[2:]
		except:
			return []

	# change voice in soundfon, for example:
	#
	# takes arg formats
	#	000-000 Some Voice
	#	000-000
	def setProgram(self,id):
		try:
			parts = id.split()			
			ids = parts[0].split('-')			
			data = self.cmd('prog '+ids[0]+' '+ids[1])
			return data
		except:
			return 'error'


	# load font, select first program voice
	# returns (id,array_of_voices)
	#
	#> inst 2
	#000-000 FF Brass 1
	#000-001 Orchestral Brass 1
	#000-002 Trumpets
	#000-003 Trombones
	#000-004 Trumpets+Trombones
	#000-005 RolandMcArthurBrs
	def initSoundFont(self,sf2):
		try:
			self.unloadSoundFonts()
			id = self.loadSoundFont(sf2)
			voices = self.getInstruments(id)
			self.setProgram(voices[0])
			return (id,voices)
		except:
			print "Voice did not load: " + sf2

		return (-1,[])



# GUI
class FluidSynthGui(wx.Frame):
  
	def __init__(self, parent, title, api):
		super(FluidSynthGui, self).__init__(parent, title=title, 
			size=(640, 350))
		# data
		self.fluidsynth = api 
		#self.fluidsynthActiveData = (-1,[])  # inst id, voices

		self.soundFontsAll = [] # everything in dir 
		self.instrumentsAll = [] # everything in dir]
		self.soundFonts = [] # filtered
		self.instruments = [] # filtered
		self.soundFontsIdx = 0
		self.instrumentsIdx = 0
		self.soundFontsFilter = "" 
		#self.instrumentsFilter = "" 
	
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

		# ui vars 
		panel = wx.Panel(self)
		self.textSoundFontDir = wx.TextCtrl(panel)
		self.btnSfDir = wx.Button(panel, label="Browse...")
		self.textfilterSoundFont = wx.TextCtrl(panel)
		#self.textfilterInstruments = wx.TextCtrl(panel)
		self.listSf = wx.ListBox(panel, choices=self.soundFonts, size=(-1,200))  
		self.listInst = wx.ListBox(panel, choices=self.instruments, size=(-1,200))  

		# start layout 
		#font = wx.SystemSettings_GetFont(wx.SYS_SYSTEM_FONT)
		#font.SetPointSize(9)
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
		row.Add(self.listSf,proportion=1)
		row.Add(self.listInst,proportion=1)

		vbox.Add(row, flag=wx.EXPAND|wx.ALL, border=5)

		# row3
		row = wx.BoxSizer(wx.HORIZONTAL)
		row.Add(wx.StaticText(panel, label='Filter Fonts'),flag=wx.LEFT, border=10, proportion=1)
		row.Add(self.textfilterSoundFont,proportion=4)
		#row.Add(wx.StaticText(panel, label='filter *'),flag=wx.LEFT, border=10, proportion=1)
		#row.Add(self.textfilterInstruments,proportion=4)

		vbox.Add(row, flag=wx.EXPAND|wx.ALL, border=5)

		# event binding

		self.btnSfDir.Bind(wx.EVT_BUTTON, self.clickButtonBrowse, self.btnSfDir)
        	self.textSoundFontDir.Bind(wx.wx.EVT_KEY_UP, self.keyUpDirectory, self.textSoundFontDir)

        	self.listSf.Bind(wx.EVT_LISTBOX, self.selectSoundFont, self.listSf)
        	self.listSf.Bind(wx.wx.EVT_KEY_DOWN, self.keyDownSoundFont, self.listSf)

        	self.listInst.Bind(wx.EVT_LISTBOX, self.selectInstrument,self.listInst)

        	self.textfilterSoundFont.Bind(wx.wx.EVT_KEY_UP, self.keyUpFilterSoundFont,self.textfilterSoundFont)
        	#self.textfilterInstruments.Bind(wx.wx.EVT_KEY_UP, self.keyUpfilterInstrumentsrument)


		# pack
		panel.SetSizer(vbox)


	# event handlers

	# dir
	def keyUpDirectory(self, event):
		event.Skip()
		keycode = event.GetKeyCode()
		path = self.textSoundFontDir.GetValue()
		#print path

		if ( os.path.isdir(path) ):
			self.dir = path
			self.refreshSoundFonts()
			#print "dir exists" 

	# set self.dir
	def clickButtonBrowse(self, event):
		event.Skip()
		dlg = wx.DirDialog(self, "Choose a directory:", style=wx.DD_DEFAULT_STYLE | wx.DD_NEW_DIR_BUTTON)
		if dlg.ShowModal() == wx.ID_OK:
			#self.SetStatusText('You selected: %s\n' % dlg.GetPath())
			print 'selected: %s\n' % dlg.GetPath()
			self.dir = dlg.GetPath()
			self.textSoundFontDir.SetValue(self.dir)
			self.refreshSoundFonts()

		dlg.Destroy()
		

	# filters
	def keyUpFilterSoundFont(self,event):
		event.Skip()
		self.refreshSoundFonts(True)

	def keyUpfilterInstrumentsrument(self,event):
		event.Skip()
		self.instrumentsIdx = 0
		self.refreshInstruments()

	# sound font change
	def selectSoundFont(self, event):
		idx = event.GetSelection()
		event.Skip()
		#print 'event idx: ' + str(idx)
		if ( idx < 0 ):
			return
		sel = self.soundFonts[idx]
		path = self.dir + '/' + sel
		(id,instrumentsAll) = fluidsynth.initSoundFont(path)
		self.instrumentsAll = instrumentsAll
		#self.fluidsynthActiveData = (id, instrumentsAll)	
		self.instrumentsIdx = 0
		self.refreshInstruments();
		
	def selectInstrument(self, event):
		idx = self.listInst.GetSelection()
		event.Skip()
		#print "selecvted"
		#print idx

		# NOTE: idx is -1 when using the arrow keys
		if ( idx < 0 ):
			return
		self.instrumentsIdx = int(idx)
		self.loadInstrument()

	def keyDownSoundFont(self, event):
		keycode = event.GetKeyCode()
		event.Skip()
		#print keycode
		if keycode == wx.WXK_LEFT:
			self.instrumentsIdx = self.incrementInst(self.instrumentsIdx,-1)
			self.loadInstrument()
			self.refreshInstruments()
		elif keycode == wx.WXK_RIGHT:
			self.instrumentsIdx = self.incrementInst(self.instrumentsIdx,1)
			self.loadInstrument()
			self.refreshInstruments()

	# keep scrolling id in bounds
	def incrementInst(self,id,add=0):
		id+=add
		#try:
		if ( id < 0 ):
			id = 0
		size = len(self.instruments)
		if ( id >= size ):
			id = size - 1
		return id
		#except:
		#	return 0

	# api 
	def grep(self, pattern, word_list):
	    expr = re.compile(pattern, re.IGNORECASE)
	    return [elem for elem in word_list if expr.match(elem)]

	def filterSoundFont(self):
		return self.grep(self.textfilterSoundFont.GetValue(),self.soundFontsAll);

	def filterInstruments(self):
		return self.instrumentsAll;
#		return self.grep(self.textfilterInstruments.GetValue(),self.instrumentsAll);

	def refreshSoundFonts(self,cache=False):
		if not cache:
			self.soundFontsAll = os.listdir(self.dir)
			#print "All files:" 
			#print self.soundFontsAll

		self.soundFonts = self.filterSoundFont()
		#print "filtered list:" 
		#print self.soundFonts
		self.listSf.Set(self.soundFonts)

		self.instrumentsIdx = 0;
		self.refreshInstruments();

	# instrument
	def refreshInstruments(self):
		#self.instrumentsAll = self.fluidsynth.getInstruments()
		self.instruments = self.filterInstruments()
		self.listInst.Set(self.instruments)
		self.listInst.SetSelection(self.instrumentsIdx)

	def loadInstrument(self):
		idx = self.incrementInst( self.instrumentsIdx, 0 )
		sel = self.instruments[idx]
		print "- select " + str(idx) + " " + sel
		#print "selected inst: " + sel 
		self.fluidsynth.setProgram(sel)	


# main

if __name__ == '__main__':
  
	app = wx.App()
	fluidsynth = FluidSynthApi()
	FluidSynthGui(None, title='Fluid Synth Gui',api=fluidsynth)
	app.MainLoop()

