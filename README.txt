                                                      Kevin Seifert - 2015 GPL

-------------------------------------------------------------------------------
SYSTEM REQUIREMENTS
-------------------------------------------------------------------------------

You'll need:

    FluidSynth (you should configure for command line first)
    Python 2.7+
    python-wxgtk2.8+

on Linux you'll also need:

    jack (and QjackCtl is recommended)


In theory this GUI can work with Windows, Mac and Linux since it's just using
fluidsynth's socket interface (over port 9800).  I use Linux as my primary OS,
however, and so far I've only tested it with: 

    xubuntu 14.04, Ubuntu Mate 16.04
    FluidSynth 1.1.6


-------------------------------------------------------------------------------
HOW TO USE THE GRAPHICAL USER INTERFACE
-------------------------------------------------------------------------------

    1. Select a folder that contains *.sf2 files. 
       Either browse for a folder or type it directly in the text box.

    2. UP/DOWN arrows will cycle through the SoundFont files.

    3. LEFT/RIGHT arrows will cycle through the instruments in each file

    4. Also, you can type a search filter while the SoundFont list has focus.

       SPACE                    is translated to a wildcard
       ESCAPE                   completely clear the search filter
       BACKSPACE/DELETE         delete the last character(s) typed

       The search box can use regular expressions as well. use --regex switch 

    5. You can navigate folders from directly inside the SoundFont list box.

       ENTER or DOUBLE-CLICK    open the folder
       select ".."              go up to the parent folder.

    6. You can set the midi channel you want to use (default = 1) 
       So, you can load 16 different fonts on 16 midi channels.

    7. Click the button "All notes off" to reset your midi controller.

    8. On the Levels tab, you can set levels for gain, reverb, and chorus.


-------------------------------------------------------------------------------
RUN THE GUI
-------------------------------------------------------------------------------

To start the GUI, just run:

    python fluidsynthgui.py


This is the only file.

-------------------------------------------------------------------------------
SOUNDFONTS
-------------------------------------------------------------------------------

The .sf2 files are not included here.  You can download them online (for free).

There are also commercial soundfonts available.



-------------------------------------------------------------------------------
TROUBLESHOOTING/CONFIGURING FLUIDSYNTH ON LINUX
-------------------------------------------------------------------------------

Before you run the GUI, it's assumed that fluidsynth is already installed and
setup.  Here's how I configured fluidsynth on xubuntu 14.04

    # you'll need the fluidsynth command line program

        sudo apt-get install fluidsynth 

    # and the jack service

        sudo apt-get install jackd qjackctl jack-tools 

    # config jack for real time

        sudo dpkg-reconfigure -p high jackd2

    # if you run `ulimit -r -l` should should see output like this:

        $ ulimit -r -l
        real-time priority              (-r) 95
        max locked memory       (kbytes, -l) unlimited

    # check that your user has perms to use rt.
    # you need to be part of the `audio` group.

    # NOTE: Group membership is only updated on login, 
    # so you need to log out and in again if you make changes.
    # to add your user to the audio group, run:

        sudo adduser  YOUR_USERNAME  audio

    # then, check the limits on the audo group.
    # edit this file with sudo:

        /etc/security/limits.conf

    # you should have these lines

        @audio   -  rtprio         99
        @audio   -  memlock        unlimited


    # then, if everything is configured correctly, you should be 
    # able to play a test midi file on the command line like this:

        fluidsynth   your_sound_font.sf2  your_midi_file.mid

    # for best results, use "Also sprach Zarathustra" as your test file. ;-)


My recommendation is to start jack first (with qjackctl), then start all your
dependent audio programs.



-------------------------------------------------------------------------------
HOW TO CONFIGURE JACK CONNECTIONS ON LINUX
-------------------------------------------------------------------------------

By default your jack connections will probably not be connected to 
fluidsynth.  These connections are similar to physical wires.  Open up 
the jack Connect tab and wire up

        Audio

            fluidsynth -> system

        Alsa

            YourMidiController -> FluidSynth-GUI

After that, you can take a snapshot of your connections and restore 
these in a startup script.  For example, using: 

    aj-snapshot jack_connections.cfg


Then start the program with a script like:

    #!/bin/bash
    
    # start the GUI
    ./fluidsynthgui.py > /tmp/fluidsynthgui.log &

    sleep 2

    # restore jack connections
    aj-snapshot -r jack_connections.cfg


-------------------------------------------------------------------------------
COMMAND LINE OPTIONS
-------------------------------------------------------------------------------

Usage:

      ./fluidsynthgui.py  [option ...]  [arg1 arg2 arg3 ...] 

Example:

      ./fluidsynthgui.py  -d /home/Music/Public/sf2/  "gain 5"

Options:

       -d sf2_dir                  the default path to your sound fonts 
       -f FluidSynth_command       override the start command 
       --regex                     allow regular expressions in search box 

       [arg1 arg2 arg3]            are executed as commands in FluidSynth


-------------------------------------------------------------------------------
FLUIDSYNTH COMMAND LINE INTERFACE 
-------------------------------------------------------------------------------

This program just runs the fluidsynth command line program, sending input, 
parsing output, the same way you would use the command line interface. 

To connect a CLI to a running fluidsynth service, you can use netcat:

   nc localhost 9800

The only significant difference between the socket interface and running
`fluidsynth` on the command line, is the socket interface does NOT have a
prompt (for example >).


-------------------------------------------------------------------------------
FUTURE MAINTENANCE
-------------------------------------------------------------------------------

If the software breaks at some point, one possible cause is syntax or Python
libraries have changed, and the code needs to be updated to use your version of
Python.

Another likely cause is the fluidsynth commands have changed (or the format
of the returned data has changed).  You can use the command line interface to
verify that the string formats are the same as referenced in the comments above
each low-level cmd() function call.

Here are all the FluidSynth command definitions used:

    echo                        Echo data back 
    load file                   Load SoundFont 
    unload id                   Unload SoundFont by ID 
    fonts                       Display the list of loaded SoundFonts
    inst font                   Print out the available instruments for the font
    select chan font bank prog  Combination of bank-select and program-change
       get var
       set var value
           synth.gain           0 - 10 
           synth.reverb.active  1 or 0
           synth.chorus.active  1 or 0
    gain value                  Set the master gain (0 < gain < 5)
    reverb [0|1|on|off]         Turn the reverb on or off
    rev_setroomsize num         Change reverb room size. 0-1
    rev_setdamp num             Change reverb damping. 0-1
    rev_setwidth num            Change reverb width. 0-1
    rev_setlevel num            Change reverb level. 0-1
    chorus [0|1|on|off]         Turn the chorus on or off
    cho_set_nr n                Use n delay lines (default 3)
    cho_set_level num           Set output level of each chorus line to num
    cho_set_speed num           Set mod speed of chorus to num (Hz)
    cho_set_depth num           Set chorus modulation depth to num (ms)
    reset                       All notes off


I split the API out from the GUI so it can be used or extended for other
projects if needed.  It's similar to the library pyfluidsynth, except the API
is using the fluidsynth socket interface instead of lower level c calls.  


-------------------------------------------------------------------------------
HELP, MY AUDIO STOPPED WORKING
-------------------------------------------------------------------------------

Occasionally, if jackd does not exit cleanly, it will prevent other audio from
playing.  This seemed to be a more frequent problem in Linux years ago, though
audio seems largely stable now.

On linux, you can stop the jackd service with the command:

    killall jackd

This will bring back all standard audio. 

