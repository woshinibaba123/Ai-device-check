"""Windows Credential Manager adapter; credentials never enter subprocess argv."""
import ctypes
from ctypes import wintypes
import shlex
import subprocess


class Credential(ctypes.Structure):
    _fields_=[('Flags',wintypes.DWORD),('Type',wintypes.DWORD),('TargetName',wintypes.LPWSTR),('Comment',wintypes.LPWSTR),('LastWritten',wintypes.FILETIME),('CredentialBlobSize',wintypes.DWORD),('CredentialBlob',ctypes.POINTER(ctypes.c_ubyte)),('Persist',wintypes.DWORD),('AttributeCount',wintypes.DWORD),('Attributes',ctypes.c_void_p),('TargetAlias',wintypes.LPWSTR),('UserName',wintypes.LPWSTR)]


def api():
    lib=ctypes.WinDLL('Advapi32.dll',use_last_error=True)
    lib.CredReadW.argtypes=[wintypes.LPCWSTR,wintypes.DWORD,wintypes.DWORD,ctypes.POINTER(ctypes.POINTER(Credential))];lib.CredReadW.restype=wintypes.BOOL
    lib.CredWriteW.argtypes=[ctypes.POINTER(Credential),wintypes.DWORD];lib.CredWriteW.restype=wintypes.BOOL
    lib.CredDeleteW.argtypes=[wintypes.LPCWSTR,wintypes.DWORD,wintypes.DWORD];lib.CredDeleteW.restype=wintypes.BOOL
    lib.CredFree.argtypes=[ctypes.c_void_p];lib.CredFree.restype=None
    return lib


def read(target):
    lib=api();pointer=ctypes.POINTER(Credential)()
    if not lib.CredReadW(target,1,0,ctypes.byref(pointer)):
        if ctypes.get_last_error()==1168:return None
        raise ValueError('无法读取 Windows 凭据管理器')
    try:return ctypes.string_at(pointer.contents.CredentialBlob,pointer.contents.CredentialBlobSize).decode('utf-8')
    finally:lib.CredFree(pointer)


def write(target,account,value):
    data=value.encode('utf-8')
    if len(data)>2560:raise ValueError('凭据内容超过 Windows 凭据管理器大小限制')
    blob=(ctypes.c_ubyte*len(data)).from_buffer_copy(data)
    credential=Credential(Type=1,TargetName=target,CredentialBlobSize=len(data),CredentialBlob=blob,Persist=2,UserName=account)
    if not api().CredWriteW(ctypes.byref(credential),0):raise ValueError('无法保存 Windows 凭据')


def delete(target):
    if not api().CredDeleteW(target,1,0) and ctypes.get_last_error()!=1168:raise ValueError('无法清除 Windows 凭据')


def run(args,data=None):
    args=shlex.split(data) if args==['-i'] else list(args)
    operation=args[0]
    def option(flag):return args[args.index(flag)+1]
    service=option('-s');account=option('-a');target=service+'/'+account
    if operation=='find-generic-password':
        value=read(target)
        return subprocess.CompletedProcess([],44 if value is None else 0,'' if value is None or '-w' not in args else value+'\n','')
    if operation=='add-generic-password':write(target,account,bytes.fromhex(option('-X')).decode('utf-8'))
    elif operation=='delete-generic-password':delete(target)
    else:raise ValueError('未知凭据操作')
    return subprocess.CompletedProcess([],0,'','')
