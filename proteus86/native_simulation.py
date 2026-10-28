"""PID-scoped Win32 adapters for the verified Proteus 8.6 build.

The bounded status-widget approach is adapted from the MIT upstream simulation
research (see THIRD_PARTY.md and _codec/LICENSE); offsets below were verified on
this 8.6 binary, not borrowed from 8.16. No simulator memory is modified. List
control messages use only a separately allocated IPC buffer, never the clipboard.
"""
import ctypes as c
from ctypes import wintypes as w
import hashlib
from pathlib import Path
import struct

from ._codec import proteus_native as native

CORE_SHA256 = 'aaab209aabfadba4df1615caeadd6d7e654cc050fcd5463392ab7b35bbc78776'
u,k = native.u,native.k
u.GetWindowLongW.argtypes,u.GetWindowLongW.restype = (w.HWND,c.c_int),w.LONG
u.SendMessageTimeoutW.argtypes = (w.HWND,w.UINT,w.WPARAM,w.LPARAM,w.UINT,w.UINT,c.POINTER(c.c_size_t))
u.SendMessageTimeoutW.restype = w.LPARAM
k.ReadProcessMemory.argtypes = (w.HANDLE,c.c_void_p,c.c_void_p,c.c_size_t,c.POINTER(c.c_size_t))
k.WriteProcessMemory.argtypes = (w.HANDLE,c.c_void_p,c.c_void_p,c.c_size_t,c.POINTER(c.c_size_t))
k.VirtualAllocEx.argtypes,k.VirtualAllocEx.restype = (w.HANDLE,c.c_void_p,c.c_size_t,w.DWORD,w.DWORD),c.c_void_p
k.VirtualFreeEx.argtypes = (w.HANDLE,c.c_void_p,c.c_size_t,w.DWORD)


def owned(pid,hwnd):
    actual=w.DWORD()
    u.GetWindowThreadProcessId(hwnd,c.byref(actual))
    if actual.value!=pid:
        raise RuntimeError('Window no longer belongs to this Proteus session')


def message(pid,hwnd,code,wp=0,lp=0):
    owned(pid,hwnd)
    result=c.c_size_t()
    if not u.SendMessageTimeoutW(hwnd,code,wp,lp,2,3000,c.byref(result)):
        raise RuntimeError('Proteus control message failed or timed out')
    return result.value


def read(process,pointer,size):
    if not pointer or not 0<size<=65536:
        raise RuntimeError('Invalid bounded native read')
    buffer=c.create_string_buffer(size);got=c.c_size_t()
    if not k.ReadProcessMemory(process,pointer,buffer,size,c.byref(got)) or got.value!=size:
        raise RuntimeError('Could not read the owned Proteus control')
    return buffer.raw


class StatusReader:
    def __init__(self,session):
        self.session=session
        executable=Path(session.process.args[0])
        if hashlib.sha256((executable.parent/'WINCORE.DLL').read_bytes()).hexdigest()!=CORE_SHA256:
            raise NotImplementedError('Simulation state requires the verified Proteus 8.6 WINCORE build')
        with executable.open('rb') as stream:
            header=stream.read(64)
            if header[:2]!=b'MZ':raise RuntimeError('Invalid native executable')
            stream.seek(struct.unpack_from('<I',header,60)[0]);pe=stream.read(6)
        if pe!=b'PE\0\0\x4c\x01':raise NotImplementedError('Only the verified 32-bit PDS build is supported')

    def _widget(self, window):
        bars=[row for row in window['children'] if row['control_id']==3 and row['cls']=='LX_APPLN_NoDC']
        bound=getattr(self,'_status_widget',None)
        if bound is None:
            if len(bars)!=1:raise RuntimeError('Unrecognized Proteus status widget before main-bar binding')
            self._status_widget=(window['hwnd'],bars[0]['hwnd'])
            bound=self._status_widget
        if bound[0]!=window['hwnd']:
            raise RuntimeError('Owned main window changed; reopen the simulation session')
        matches=[row for row in bars if row['hwnd']==bound[1]]
        if len(matches)!=1:
            raise RuntimeError('Verified main status widget changed; reopen the simulation session')
        # Opening the VSM debugger adds another id=3 widget. Keep only the
        # initially unambiguous identity; never pick the first of two bars or
        # cache status/time. Ownership and native pointer guards run every read.
        owned(self.session.pid,matches[0]['hwnd'])
        return matches[0]

    def text(self,window):
        bar=self._widget(window)
        process=k.OpenProcess(0x410,False,self.session.pid)
        if not process:raise c.WinError(c.get_last_error())
        try:
            pointer=u.GetWindowLongW(bar['hwnd'],0)&0xffffffff
            if struct.unpack('<I',read(process,pointer+4,4))[0]!=bar['hwnd']:
                raise RuntimeError('Native status owner check failed')
            strings=[]
            for address in struct.unpack('<II',read(process,pointer+0x24c,8)):
                raw=read(process,address,256) if address else b'\0'
                if b'\0' not in raw:raise RuntimeError('Unrecognized bounded status string')
                strings.append(raw.split(b'\0',1)[0].decode('cp1252',errors='replace'))
            return strings
        finally:k.CloseHandle(process)


def _log_window_description(pid,hwnd):
    """Recheck a log candidate's live identity, not EnumChildWindows ordering."""
    owned(pid,hwnd)
    size=u.GetWindowTextLengthW(hwnd)
    if not 0<=size<=2048:raise RuntimeError('Native log window title exceeds the read limit')
    title=c.create_unicode_buffer(size+1);cls=c.create_unicode_buffer(256)
    u.GetWindowTextW(hwnd,title,len(title))
    if not u.GetClassNameW(hwnd,cls,len(cls)):
        raise RuntimeError('Native log window disappeared during identification')
    result=dict(hwnd=hwnd,title=title.value,cls=cls.value,control_id=u.GetDlgCtrlID(hwnd))
    owned(pid,hwnd)
    return result


def _log_parent_chain(pid,hwnd,main):
    """A bounded, PID-checked real GetParent chain, including both endpoints."""
    u.GetParent.argtypes,u.GetParent.restype=(w.HWND,),w.HWND
    result=[];seen=set()
    for _ in range(64):
        if not hwnd:return None
        if hwnd in seen:raise RuntimeError('Native log parent chain contains a cycle')
        seen.add(hwnd);result.append(_log_window_description(pid,hwnd))
        if hwnd==main:return result
        hwnd=u.GetParent(hwnd)
    raise RuntimeError('Native log parent chain exceeds the verified depth limit')


def find_log_control(session,window,*,include_dialogs=True):
    """Locate the verified debugger log or custom-class Simulation Log window.

    Simulation construction retains its WINCORE/PE build check. This helper adds
    live PID, exact control signatures, real parent chains and uniqueness checks;
    a flat EnumChildWindows result never establishes parentage. It does not
    activate windows, invoke menus or select an arbitrary list in the process.
    """
    if session.process.poll() is not None:raise RuntimeError('Owned Proteus process exited before log read')
    if session.process.pid!=session.pid:raise RuntimeError('Owned Proteus process identity changed before log read')
    main=window['hwnd'];owned(session.pid,main)
    windows=native.windows(session.pid)
    mains=[row for row in windows if row['hwnd']==main]
    if len(mains)!=1:raise RuntimeError('Owned Proteus main window changed before log read')
    signature=lambda row:(row['cls'],row['title'],row['control_id'])
    live_main=_log_window_description(session.pid,main)
    if live_main['cls']!='LX_APPLN_DClkNoDC' or live_main['control_id']!=0:
        raise RuntimeError('Unrecognized Proteus main window profile for log read')
    candidates={}
    for row in mains[0]['children']:
        if row['cls']!='SysListView32' or row['control_id']!=1:continue
        chain=_log_parent_chain(session.pid,row['hwnd'],main)
        if (chain is not None and len(chain)==4
                and signature(chain[0])==('SysListView32','',1)
                and signature(chain[1])==('LX_APPLN_DClkNoDC','Log Window',0)
                and signature(chain[2])==('LX_APPLN_DClkNoDC','VSM Debugger',101)):
            candidates[row['hwnd']]=dict(chain[0],log_profile='vsm_debugger')
    if include_dialogs:
        for log_window in windows:
            expected=('LX_APPLN_DClkNoDC','Simulation Log',0)
            if signature(log_window)!=expected:continue
            chain=_log_parent_chain(session.pid,log_window['hwnd'],main)
            if chain is None or signature(chain[0])!=expected:continue
            lists=[child for child in log_window['children']
                   if signature(child)==('SysListView32','',1)]
            for row in lists:
                child_chain=_log_parent_chain(session.pid,row['hwnd'],main)
                # This is the custom-class window actually observed on 8.6,
                # not an assumed standard #32770 dialog. Require its exact
                # list signature and real direct-child/owned-main chain.
                if (child_chain is not None and len(child_chain)==3
                        and signature(child_chain[0])==('SysListView32','',1)
                        and child_chain[1]['hwnd']==log_window['hwnd']):
                    candidates[row['hwnd']]=dict(child_chain[0],log_profile='simulation_log_window')
    if len(candidates)>1:
        raise RuntimeError('Ambiguous native simulation log controls; refusing to choose a list')
    return next(iter(candidates.values()),None)


def list_rows(pid,hwnd,*,columns=2,limit=10000):
    """Read a standard 32-bit list control through documented Win32 messages."""
    owned(pid,hwnd)
    if u.GetWindowLongW(hwnd,-16)&0x1000:
        raise NotImplementedError('Owner-data log controls are unsupported')
    count=message(pid,hwnd,0x1004)
    if not 0<=count<=limit:raise RuntimeError('Native list exceeds the read limit')
    process=k.OpenProcess(0x438,False,pid)
    if not process:raise c.WinError(c.get_last_error())
    remote=k.VirtualAllocEx(process,None,8256,0x3000,4)
    if not remote:
        k.CloseHandle(process);raise c.WinError(c.get_last_error())
    uncertain=False
    def send(code,wp=0,lp=0):
        nonlocal uncertain
        try:return message(pid,hwnd,code,wp,lp)
        except RuntimeError:
            # A timed-out window thread may still be using its IPC pointer.
            # Keep this small buffer alive until this owned process exits.
            uncertain=True
            raise
    try:
        if remote+8256>2**32:raise RuntimeError('IPC buffer is outside the 32-bit control range')
        result=[]
        for index in range(count):
            fields=[]
            image=None
            for column in range(columns):
                header=struct.pack('<5I',3,index,column,0,0)+struct.pack('<Ii',remote+64,4096)+bytes(36)
                wrote=c.c_size_t();buffer=c.create_string_buffer(header)
                if not k.WriteProcessMemory(process,remote,buffer,len(header),c.byref(wrote)) or wrote.value!=len(header):
                    raise RuntimeError('Could not write the allocated IPC buffer')
                length=send(0x1073,index,remote)  # LVM_GETITEMTEXTW
                if length>=4095:raise RuntimeError('Native log entry exceeds the read limit')
                fields.append(read(process,remote+64,(length+1)*2).decode('utf-16-le').split('\0',1)[0])
                if column==0 and send(0x104b,0,remote):  # LVM_GETITEMW, image
                    image=struct.unpack_from('<i',read(process,remote,64),28)[0]
            result.append(dict(text=fields[0],source=fields[1] if columns>1 else '',image=image))
        return result
    finally:
        if not uncertain:k.VirtualFreeEx(process,remote,0,0x8000)
        k.CloseHandle(process)
