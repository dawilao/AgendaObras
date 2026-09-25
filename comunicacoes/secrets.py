"""Segredo local protegido pelo Windows para o usuário atual (DPAPI)."""
import ctypes
import os
from ctypes import wintypes
from pathlib import Path

PREFIX = b'AGENDA_DPAPI_V1\n'


def _crypt(data, decrypt=False):
    if os.name != 'nt':
        raise OSError('Este segredo está protegido pelo Windows. Configure uma credencial no servidor de destino.')
    class Blob(ctypes.Structure):
        _fields_ = [('size', wintypes.DWORD), ('data', ctypes.POINTER(ctypes.c_ubyte))]
    buffer = ctypes.create_string_buffer(data)
    source = Blob(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ubyte)))
    result = Blob()
    crypt = ctypes.WinDLL('crypt32', use_last_error=True)
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.LocalFree.argtypes = [ctypes.c_void_p]
    kernel.LocalFree.restype = ctypes.c_void_p
    if decrypt:
        fn = crypt.CryptUnprotectData
        fn.argtypes = [ctypes.POINTER(Blob), ctypes.c_void_p, ctypes.c_void_p,
                       ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(Blob)]
        fn.restype = wintypes.BOOL
        ok = fn(ctypes.byref(source), None, None, None, None, 1, ctypes.byref(result))
    else:
        fn = crypt.CryptProtectData
        fn.argtypes = [ctypes.POINTER(Blob), wintypes.LPCWSTR, ctypes.c_void_p,
                       ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(Blob)]
        fn.restype = wintypes.BOOL
        ok = fn(ctypes.byref(source), 'AgendaObras IMAP', None, None, None, 1, ctypes.byref(result))
    if not ok:
        raise OSError('Não foi possível acessar a credencial protegida pelo Windows.')
    try:
        return ctypes.string_at(result.data, result.size)
    finally:
        kernel.LocalFree(ctypes.cast(result.data, ctypes.c_void_p))


def save_windows_secret(path, password):
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    encrypted = PREFIX + _crypt(password.encode('utf-8'))
    temp = target.with_suffix('.tmp')
    temp.write_bytes(encrypted)
    temp.replace(target)


def read_secret(path):
    data = Path(path).read_bytes()
    if data.startswith(PREFIX):
        return _crypt(data[len(PREFIX):], decrypt=True).decode('utf-8')
    return data.decode('utf-8').rstrip('\r\n')
