# -*- coding: utf-8 -*-

# Copyright (C) 2011 Chris Dekter
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.

X_RECORD_INTERFACE = "XRecord"
ATSPI_INTERFACE = "AT-SPI"

INTERFACES = [X_RECORD_INTERFACE, ATSPI_INTERFACE]
CURRENT_INTERFACE = None

# Key codes enumeration
class Key:

    LEFT = "<left>"
    RIGHT = "<right>"
    UP = "<up>"
    DOWN = "<down>"
    BACKSPACE = "<backspace>"
    TAB = "<tab>"
    ENTER = "<enter>"
    SCROLL_LOCK = "<scroll_lock>"
    PRINT_SCREEN = "<print_screen>"
    PAUSE = "<pause>"
    MENU = "<menu>"
    
    # Modifier keys
    CONTROL = "<ctrl>"
    ALT = "<alt>"
    ALT_GR = "<alt_gr>"
    SHIFT = "<shift>"
    SUPER = "<super>"
    HYPER = "<hyper>"
    CAPSLOCK = "<capslock>"
    NUMLOCK = "<numlock>"
    META = "<meta>"
    
    F1 = "<f1>"
    F2 = "<f2>"
    F3 = "<f3>"
    F4 = "<f4>"
    F5 = "<f5>"
    F6 = "<f6>"
    F7 = "<f7>"
    F8 = "<f8>"
    F9 = "<f9>"
    F10 = "<f10>"
    F11 = "<f11>"
    F12 = "<f12>"
    
    # Other
    ESCAPE = "<escape>"
    INSERT = "<insert>"
    DELETE = "<delete>"
    HOME = "<home>"
    END = "<end>"
    PAGE_UP = "<page_up>"
    PAGE_DOWN = "<page_down>"

    # Numpad
    NP_INSERT = "<np_insert>"
    NP_DELETE = "<np_delete>"
    NP_HOME = "<np_home>"
    NP_END = "<np_end>"
    NP_PAGE_UP = "<np_page_up>"
    NP_PAGE_DOWN = "<np_page_down>"
    NP_LEFT = "<np_left>"
    NP_RIGHT = "<np_right>"
    NP_UP = "<np_up>"
    NP_DOWN = "<np_down>"
    NP_DIVIDE = "<np_divide>"
    NP_MULTIPLY = "<np_multiply>"
    NP_ADD = "<np_add>"
    NP_SUBTRACT = "<np_subtract>"
    NP_5 = "<np_5>"

    @classmethod
    def is_key(klass, keyString):
        # Key strings must be treated as case insensitive - always convert to lowercase
        # before doing any comparisons
        return keyString.lower() in klass.__dict__.values() or keyString.startswith("<code")

import datetime, time, threading, Queue, re, logging

_logger = logging.getLogger("iomediator")

MODIFIERS = [Key.CONTROL, Key.ALT, Key.ALT_GR, Key.SHIFT, Key.SUPER, Key.HYPER, Key.META, Key.CAPSLOCK, Key.NUMLOCK]
HELD_MODIFIERS = [Key.CONTROL, Key.ALT, Key.SUPER, Key.SHIFT, Key.HYPER, Key.META]
NAVIGATION_KEYS = [Key.LEFT, Key.RIGHT, Key.UP, Key.DOWN, Key.BACKSPACE, Key.HOME, Key.END, Key.PAGE_UP, Key.PAGE_DOWN]

#KEY_SPLIT_RE = re.compile("(<.+?>\+{0,1})", re.UNICODE)
KEY_SPLIT_RE = re.compile("(<[^<>]+>\+?)", re.UNICODE)
SEND_LOCK = threading.Lock()

from interface import *
from configmanager import *

class IoMediator(threading.Thread):
    """
    The IoMediator is responsible for tracking the state of modifier keys and
    interfacing with the various Interface classes to obtain the correct
    characters to pass to the expansion service. 
    
    This class must not store or maintain any configuration details.
    """
    
    # List of targets interested in receiving keypress, hotkey and mouse events
    listeners = []
    
    def __init__(self, service):
        threading.Thread.__init__(self, name="KeypressHandler-thread")
        self.queue = Queue.Queue()
        self.listeners.append(service)
        self.interfaceType = ConfigManager.SETTINGS[INTERFACE_TYPE]
        
        # Modifier tracking
        self.modifiers = {
                          Key.CONTROL : False,
                          Key.ALT : False,
                          Key.ALT_GR: False,
                          Key.SHIFT : False,
                          Key.SUPER : False,
                          Key.HYPER : False,
                          Key.META  : False,
                          Key.CAPSLOCK : False,
                          Key.NUMLOCK : False
                          }
        
        if self.interfaceType == X_RECORD_INTERFACE:
            self.interface = XRecordInterface(self, service.app)
        elif self.interfaceType == X_EVDEV_INTERFACE:
            self.interface = EvDevInterface(self, service.app)    
        else:
            self.interface = AtSpiInterface(self, service.app)

        global CURRENT_INTERFACE
        CURRENT_INTERFACE = self.interface
        
    def shutdown(self):
        self.interface.cancel()
        self.queue.put_nowait((None, None, None))
        self.join()

    # Callback methods for Interfaces ----

    def set_modifier_state(self, modifier, state):
        _logger.debug("Set modifier %s to %r", modifier, state)
        self.modifiers[modifier] = state
    
    def handle_modifier_down(self, modifier):
        """
        Updates the state of the given modifier key to 'pressed'
        """
        _logger.debug("%s pressed", modifier)
        if modifier in (Key.CAPSLOCK, Key.NUMLOCK):
            if self.modifiers[modifier]:
                self.modifiers[modifier] = False
            else:
                self.modifiers[modifier] = True
        else:
            self.modifiers[modifier] = True
        
    def handle_modifier_up(self, modifier):
        """
        Updates the state of the given modifier key to 'released'.
        """
        _logger.debug("%s released", modifier)
        # Caps and num lock are handled on key down only
        if not modifier in (Key.CAPSLOCK, Key.NUMLOCK):
            self.modifiers[modifier] = False
    
    def handle_keypress(self, keyCode, windowName, windowClass):
        """
        Looks up the character for the given key code, applying any 
        modifiers currently in effect, and passes it to the expansion service.
        """
        self.queue.put_nowait((keyCode, windowName, windowClass))
        
    def run(self):
        while True:
            keyCode, windowName, windowClass = self.queue.get()
            if keyCode is None and windowName is None:
                break
            
            numLock = self.modifiers[Key.NUMLOCK]
            modifiers = self.__getModifiersOn()
            shifted = self.modifiers[Key.CAPSLOCK] ^ self.modifiers[Key.SHIFT]
            key = self.interface.lookup_string(keyCode, shifted, numLock, self.modifiers[Key.ALT_GR])
            rawKey = self.interface.lookup_string(keyCode, False, False, False)
            
            for target in self.listeners:
                target.handle_keypress(rawKey, modifiers, key, windowName, windowClass)                
                
            self.queue.task_done()
            
    def handle_mouse_click(self, rootX, rootY, relX, relY, button, windowInfo):
        for target in self.listeners:
            target.handle_mouseclick(rootX, rootY, relX, relY, button, windowInfo)
        
    # Methods for expansion service ----

    def send_string(self, string):
        """
        Sends the given string for output.
        """
        if len(string) == 0:
            return

        k = Key()
        
        string = string.replace('\n', "<enter>")
        string = string.replace('\t', "<tab>")
        
        _logger.debug("Send via event interface")
        self.__clearModifiers()
        modifiers = []            
        for section in KEY_SPLIT_RE.split(string):
            if len(section) > 0:
                if k.is_key(section[:-1]) and section[-1] == '+' and section[:-1] in MODIFIERS:
                    # Section is a modifier application (modifier followed by '+')
                    modifiers.append(section[:-1])
                    
                else:
                    if len(modifiers) > 0:
                        # Modifiers ready for application - send modified key
                        if k.is_key(section):
                            self.interface.send_modified_key(section, modifiers)
                            modifiers = []
                        else:
                            self.interface.send_modified_key(section[0], modifiers)
                            if len(section) > 1:
                                self.interface.send_string(section[1:])
                            modifiers = []
                    else:
                        # Normal string/key operation                    
                        if k.is_key(section):
                            self.interface.send_key(section)
                        else:
                            self.interface.send_string(section)
                            
        self.__reapplyModifiers()
        
    def paste_string(self, string, pasteCommand):
        if len(string) > 0:
            _logger.debug("Send via clipboard")
            self.interface.send_string_clipboard(string, pasteCommand)
        
    def remove_string(self, string):
        backspaces = -1 # Start from -1 to discount the backspace already pressed by the user
        k = Key()
        
        for section in KEY_SPLIT_RE.split(string):
            if k.is_key(section):
                backspaces += 1
            else:
                backspaces += len(section)
                
        self.send_backspace(backspaces)
        
    def send_key(self, keyName):
        keyName = keyName.replace('\n', "<enter>")
        self.interface.send_key(keyName)
        
    def press_key(self, keyName):
        keyName = keyName.replace('\n', "<enter>")
        self.interface.fake_keydown(keyName)
        
    def release_key(self, keyName):
        keyName = keyName.replace('\n', "<enter>")
        self.interface.fake_keyup(keyName)                

    def fake_keypress(self, keyName):
        keyName = keyName.replace('\n', "<enter>")
        self.interface.fake_keypress(keyName)

    def send_left(self, count):
        """
        Sends the given number of left key presses.
        """
        for i in range(count):
            self.interface.send_key(Key.LEFT)
        
    def send_right(self, count):
        for i in range(count):
            self.interface.send_key(Key.RIGHT)
    
    def send_up(self, count):
        """
        Sends the given number of up key presses.
        """        
        for i in range(count):
            self.interface.send_key(Key.UP)
        
    def send_backspace(self, count):
        """
        Sends the given number of backspace key presses.
        """
        for i in range(count):
            self.interface.send_key(Key.BACKSPACE)
        
    def send_mouse_click(self, x, y, button, relative):
        self.interface.send_mouse_click(x, y, button, relative)
        
    def send_mouse_click_relative(self, x, y, button):
        self.interface.send_mouse_click_relative(x, y, button)
            
    def flush(self):
        self.interface.flush()
        
    # Utility methods ----
    
    def __clearModifiers(self):
        self.releasedModifiers = []
        
        for modifier in self.modifiers.keys():
            if self.modifiers[modifier] and not modifier in (Key.CAPSLOCK, Key.NUMLOCK):
                self.releasedModifiers.append(modifier)
                self.interface.release_key(modifier)
        
    def __reapplyModifiers(self):
        for modifier in self.releasedModifiers:
            self.interface.press_key(modifier)
            
    def __getModifiersOn(self):
        modifiers = []
        for modifier in HELD_MODIFIERS:
            if self.modifiers[modifier]:
                modifiers.append(modifier)
        
        modifiers.sort()
        return modifiers

class Waiter:
    """
    Waits for a specified event to occur
    """
    
    def __init__(self, rawKey, modifiers, button, timeOut):
        IoMediator.listeners.append(self)
        self.rawKey = rawKey
        self.modifiers = modifiers
        self.button = button
        self.event = threading.Event()
        self.timeOut = timeOut
        
        if modifiers is not None:
            self.modifiers.sort()

    def wait(self):
        self.event.wait(self.timeOut)
        
    def handle_keypress(self, rawKey, modifiers, key, *args):
        if rawKey == self.rawKey and modifiers == self.modifiers:
            IoMediator.listeners.remove(self)
            self.event.set()
    
    def handle_mouseclick(self, rootX, rootY, relX, relY, button, windowInfo):
        if button == self.button:
            self.event.set()
            
        
class KeyGrabber:
    """
    Keygrabber used by the hotkey settings dialog to grab the key pressed
    """
    
    def __init__(self, parent):
        self.targetParent = parent
    
    def start(self):
        # In QT version, sometimes the mouseclick event arrives before we finish initialising
        # sleep slightly to prevent this
        time.sleep(0.1)
        IoMediator.listeners.append(self)
        CURRENT_INTERFACE.grab_keyboard()
                 
    def handle_keypress(self, rawKey, modifiers, key, *args):
        if not rawKey in MODIFIERS:
            IoMediator.listeners.remove(self)
            self.targetParent.set_key(rawKey, modifiers)
            CURRENT_INTERFACE.ungrab_keyboard()
    
    def handle_mouseclick(self, rootX, rootY, relX, relY, button, windowInfo):
        IoMediator.listeners.remove(self)
        CURRENT_INTERFACE.ungrab_keyboard()
        self.targetParent.cancel_grab()

class Recorder(KeyGrabber):
    """
    Recorder used by the record macro functionality
    """
    
    def __init__(self, parent):
        KeyGrabber.__init__(self, parent)
        self.insideKeys = False
        
    def start(self, delay):
        time.sleep(0.1)
        IoMediator.listeners.append(self)
        self.targetParent.start_record()
        self.startTime = time.time()
        self.delay = delay
        self.delayFinished = False
        
    def start_withgrab(self):
        time.sleep(0.1)
        IoMediator.listeners.append(self)
        self.targetParent.start_record()
        self.startTime = time.time()
        self.delay = 0
        self.delayFinished = True
        CURRENT_INTERFACE.grab_keyboard()
        
    
    def stop(self):
        if self in IoMediator.listeners:
            IoMediator.listeners.remove(self)
            if self.insideKeys:
                self.targetParent.end_key_sequence()
            self.insideKeys = False
            
    def stop_withgrab(self):
        CURRENT_INTERFACE.ungrab_keyboard()
        if self in IoMediator.listeners:
            IoMediator.listeners.remove(self)
            if self.insideKeys:
                self.targetParent.end_key_sequence()
            self.insideKeys = False        
        
    def set_record_keyboard(self, doIt):
        self.recordKeyboard = doIt

    def set_record_mouse(self, doIt):
        self.recordMouse = doIt
        
    def __delayPassed(self):
        if not self.delayFinished:
            now = time.time()
            delta = datetime.datetime.utcfromtimestamp(now - self.startTime)
            self.delayFinished = (delta.second > self.delay)
            
        return self.delayFinished
                
    def handle_keypress(self, rawKey, modifiers, key, *args):
        if self.recordKeyboard and self.__delayPassed():
            if not self.insideKeys:
                self.insideKeys = True
                self.targetParent.start_key_sequence()
                
            modifierCount = len(modifiers)
            
            if modifierCount > 1 or (modifierCount == 1 and Key.SHIFT not in modifiers) or \
                    (Key.SHIFT in modifiers and len(rawKey) > 1):
                self.targetParent.append_hotkey(rawKey, modifiers)
                
            elif not key in MODIFIERS:
                self.targetParent.append_key(key)
        
    def handle_mouseclick(self, rootX, rootY, relX, relY, button, windowInfo):
        if self.recordMouse and self.__delayPassed():
            if self.insideKeys:
                self.insideKeys = False
                self.targetParent.end_key_sequence()
                
            self.targetParent.append_mouseclick(relX, relY, button, windowInfo[0])


class WindowGrabber:

    def __init__(self, dialog):
        self.dialog = dialog

    def start(self):
        time.sleep(0.1)
        IoMediator.listeners.append(self)

    def handle_keypress(self, rawKey, modifiers, key, *args):
        pass

    def handle_mouseclick(self, rootX, rootY, relX, relY, button, windowInfo):
        IoMediator.listeners.remove(self)
        self.dialog.receive_window_info(windowInfo)

