"""Store Supabase writer credentials under the current Windows account."""

import ctypes
import json
import os
from ctypes import wintypes
from pathlib import Path
from tempfile import NamedTemporaryFile


def credential_path(project):
    return Path.home() / ".smart-door" / "writers" / (project.removeprefix("https://") + ".dpapi")


def transform(data, *, protect):
    class Blob(ctypes.Structure):
        _fields_ = [("size", wintypes.DWORD), ("data", ctypes.c_void_p)]

    storage = ctypes.create_string_buffer(data)
    source = Blob(len(data), ctypes.addressof(storage))
    result = Blob()
    crypt = ctypes.WinDLL("crypt32", use_last_error=True)
    operation = crypt.CryptProtectData if protect else crypt.CryptUnprotectData
    operation.argtypes = (
        ctypes.POINTER(Blob), ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p,
        ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(Blob),
    )
    operation.restype = wintypes.BOOL
    free = ctypes.WinDLL("kernel32").LocalFree
    free.argtypes = (ctypes.c_void_p,)
    free.restype = ctypes.c_void_p
    try:
        ui_forbidden = 1
        if not operation(ctypes.byref(source), None, None, None, None, ui_forbidden, ctypes.byref(result)):
            raise ctypes.WinError(ctypes.get_last_error())
        return ctypes.string_at(result.data, result.size)
    finally:
        if result.data:
            ctypes.memset(result.data, 0, result.size)
            free(result.data)
        ctypes.memset(storage, 0, len(storage))


def read_writer(project):
    if os.name != "nt":
        return "", ""
    try:
        data = credential_path(project).read_bytes()
    except FileNotFoundError:
        return "", ""
    payload = json.loads(transform(data, protect=False))
    if (not isinstance(payload, dict) or payload.get("project") != project
            or not isinstance(payload.get("email"), str) or not isinstance(payload.get("password"), str)):
        raise ValueError("Invalid saved writer credentials.")
    return payload["email"], payload["password"]


def save_writer(project, email, password):
    data = json.dumps({"project": project, "email": email, "password": password}).encode("utf-8")
    encrypted = transform(data, protect=True)
    path = credential_path(project)
    path.parent.mkdir(parents=True, exist_ok=True)
    with NamedTemporaryFile(dir=path.parent, delete=False) as file:
        staged = Path(file.name)
        try:
            file.write(encrypted)
            file.close()
            staged.replace(path)
        finally:
            staged.unlink(missing_ok=True)
