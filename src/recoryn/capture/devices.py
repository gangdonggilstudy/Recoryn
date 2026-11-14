"""Experimental Windows MMDevice/WASAPI ABI, loaded only on explicit calls.

ABI checked against Microsoft Windows SDK 10.0.22621.0 mmdeviceapi.h,
audioclient.h, mmreg.h and functiondiscoverykeys_devpkey.h. Primary references:
https://learn.microsoft.com/windows/win32/api/mmdeviceapi/
https://learn.microsoft.com/windows/win32/api/audioclient/
https://learn.microsoft.com/windows/win32/api/mmreg/ns-mmreg-waveformatextensible
Enumeration never activates IAudioClient or starts a stream. Probe activates an
audio client only on explicit request, queries its format, then releases it.
Actual capture is experimental until physical Windows device testing is done.
"""

from __future__ import annotations

import ctypes as ct
import struct
import sys
from dataclasses import dataclass
from threading import get_ident
from typing import Any
from uuid import UUID

from recoryn.domain import AudioFormat, ValidationError

_HRESULT = ct.c_int32
_DWORD = ct.c_uint32
_UINT = ct.c_uint32
_PTR = ct.c_void_p
_CALL = getattr(ct, "WINFUNCTYPE", ct.CFUNCTYPE)


class WasapiError(RuntimeError):
    """Safe stable error code; never displays arbitrary backend exception text."""

    def __init__(self, code: str, hresult: int | None = None) -> None:
        self.code = code
        self.hresult = hresult
        super().__init__(code)


def _check(result: int) -> None:
    unsigned = result & 0xFFFFFFFF
    if unsigned & 0x80000000:
        code = {
            0x88890004: "DEVICE_UNAVAILABLE",
            0x80070005: "DEVICE_ACCESS_DENIED",
            0x88890010: "AUDIO_SERVICE_UNAVAILABLE",
        }.get(unsigned, "NATIVE_CALL_FAILED")
        raise WasapiError(code, unsigned)


class _GUID(ct.Structure):
    _fields_ = [
        ("Data1", ct.c_uint32),
        ("Data2", ct.c_uint16),
        ("Data3", ct.c_uint16),
        ("Data4", ct.c_uint8 * 8),
    ]

    @classmethod
    def parse(cls, text: str) -> _GUID:
        return cls.from_buffer_copy(UUID(text).bytes_le)


class _WaveFormatEx(ct.Structure):
    _pack_ = 1
    _fields_ = [
        ("wFormatTag", ct.c_uint16),
        ("nChannels", ct.c_uint16),
        ("nSamplesPerSec", ct.c_uint32),
        ("nAvgBytesPerSec", ct.c_uint32),
        ("nBlockAlign", ct.c_uint16),
        ("wBitsPerSample", ct.c_uint16),
        ("cbSize", ct.c_uint16),
    ]


class _PropertyKey(ct.Structure):
    _fields_ = [("fmtid", _GUID), ("pid", ct.c_uint32)]


class _PropertyValue(ct.Union):
    _fields_ = [("pointer", _PTR), ("storage", ct.c_uint64 * (2 if ct.sizeof(_PTR) == 8 else 1))]


class _PropVariant(ct.Structure):
    _fields_ = [
        ("vt", ct.c_uint16),
        ("reserved1", ct.c_uint16),
        ("reserved2", ct.c_uint16),
        ("reserved3", ct.c_uint16),
        ("value", _PropertyValue),
    ]


_CLSID_ENUMERATOR = _GUID.parse("BCDE0395-E52F-467C-8E3D-C4579291692E")
_IID_ENUMERATOR = _GUID.parse("A95664D2-9614-4F35-A746-DE8DB63617E6")
_IID_AUDIO_CLIENT = _GUID.parse("1CB9AD4C-DBFA-4C32-B178-C2F568A703B2")
_IID_CAPTURE_CLIENT = _GUID.parse("C8ADBD64-E71E-48A0-A4DE-185C395CD317")
_IID_ENDPOINT = _GUID.parse("1BE09788-6894-4089-8586-9A2A6C265AC5")
_FRIENDLY_NAME = _PropertyKey(_GUID.parse("A45C254E-DF1C-4EFD-8020-67D146A850E0"), 14)


def _invoke(
    pointer: ct.c_void_p,
    index: int,
    argtypes: tuple[Any, ...],
    *args: Any,
    result_type: Any = _HRESULT,
) -> int:
    """Call a COM slot with explicit Windows-width arguments and stdcall ABI."""
    if not pointer.value:
        raise WasapiError("NULL_INTERFACE")
    table = ct.cast(pointer, ct.POINTER(ct.POINTER(_PTR))).contents
    address = table[index]
    if not address:
        raise WasapiError("NULL_METHOD")
    method = _CALL(result_type, _PTR, *argtypes)(address)
    return int(method(pointer, *args))


def _release(pointer: ct.c_void_p) -> None:
    if pointer.value:
        _invoke(pointer, 2, (), result_type=ct.c_uint32)  # IUnknown::Release returns ULONG.
        pointer.value = None


@dataclass(frozen=True, slots=True)
class DeviceInfo:
    device_id: str
    name: str
    flow: str
    default: bool

    def __post_init__(self) -> None:
        _device_id(self.device_id)
        if not isinstance(self.name, str) or not self.name or len(self.name) > 4096:
            raise ValidationError("invalid device name")
        if self.flow not in ("capture", "render") or type(self.default) is not bool:
            raise ValidationError("invalid device flow/default")


def _device_id(value: str) -> None:
    if not isinstance(value, str) or not value or "\0" in value or len(value) > 4096:
        raise ValidationError("invalid endpoint ID")


@dataclass(frozen=True, slots=True)
class NativeFormat:
    """OS format plus metadata absent from the original core AudioFormat DTO."""

    audio_format: AudioFormat
    valid_bits: int
    channel_mask: int | None = None
    raw: bytes = b""

    def __post_init__(self) -> None:
        if not isinstance(self.audio_format, AudioFormat):
            raise ValidationError("invalid native format")
        bits = self.audio_format.frame_bytes * 8 // self.audio_format.channels
        if type(self.valid_bits) is not int or not 0 < self.valid_bits <= bits:
            raise ValidationError("invalid valid bits")
        if self.audio_format.sample_type == "f32le" and self.valid_bits != 32:
            raise ValidationError("invalid float precision")
        if self.channel_mask is not None and (
            type(self.channel_mask) is not int or not 0 <= self.channel_mask <= 0xFFFFFFFF
        ):
            raise ValidationError("invalid channel mask")
        if type(self.raw) is not bytes:
            raise ValidationError("invalid native format bytes")

    def metadata(self) -> dict[str, object]:
        return {
            "format": self.audio_format.to_dict(),
            "valid_bits": self.valid_bits,
            "container_bits": self.audio_format.frame_bytes * 8 // self.audio_format.channels,
            "channel_mask": self.channel_mask,
            "experimental": True,
        }


def _parse_wave_format(raw: bytes) -> NativeFormat:
    if len(raw) < 18 or len(raw) > 4096:
        raise WasapiError("UNSUPPORTED_FORMAT")
    tag, channels, rate, average, alignment, bits, extra = struct.unpack_from("<HHIIHHH", raw)
    if len(raw) != 18 + extra:
        raise WasapiError("UNSUPPORTED_FORMAT")
    valid, mask = bits, None
    if tag == 0xFFFE:
        if extra < 22:
            raise WasapiError("UNSUPPORTED_FORMAT")
        valid, channel_mask = struct.unpack_from("<HI", raw, 18)
        mask = channel_mask or None
        subformat = UUID(bytes_le=raw[24:40])
        if subformat == UUID("00000001-0000-0010-8000-00aa00389b71"):
            tag = 1
        elif subformat == UUID("00000003-0000-0010-8000-00aa00389b71"):
            tag = 3
        else:
            raise WasapiError("UNSUPPORTED_FORMAT")
    sample = {(1, 16): "s16le", (1, 24): "s24le", (1, 32): "s32le", (3, 32): "f32le"}.get(
        (tag, bits)
    )
    if sample is None:
        raise WasapiError("UNSUPPORTED_FORMAT")
    try:
        format = AudioFormat(rate, channels, sample)
        if alignment != format.frame_bytes or average != rate * alignment:
            raise ValidationError("invalid PCM alignment")
        if mask is not None and mask.bit_count() != channels:
            raise ValidationError("channel mask mismatch")
        return NativeFormat(format, valid, mask, raw)
    except ValidationError:
        raise WasapiError("UNSUPPORTED_FORMAT") from None


class _WinAPI:
    """Apartment ownership and system DLL calls; constructed inside explicit work."""

    def __init__(self) -> None:
        self.ole32: Any = None
        self.kernel32: Any = None
        self._owns_com = False
        self._owner: int | None = None
        self._frequency = 0

    def __enter__(self) -> _WinAPI:
        if sys.platform != "win32":
            raise WasapiError("UNSUPPORTED_PLATFORM")
        if sys.getwindowsversion().major < 10:
            raise WasapiError("UNSUPPORTED_WINDOWS")
        loader = ct.WinDLL
        self.ole32 = loader("ole32", use_last_error=True)
        self.kernel32 = loader("kernel32", use_last_error=True)
        self.ole32.CoInitializeEx.argtypes = [_PTR, _DWORD]
        self.ole32.CoInitializeEx.restype = _HRESULT
        self.ole32.CoUninitialize.argtypes = []
        self.ole32.CoUninitialize.restype = None
        self.ole32.CoCreateInstance.argtypes = [_PTR, _PTR, _DWORD, _PTR, _PTR]
        self.ole32.CoCreateInstance.restype = _HRESULT
        self.ole32.CoTaskMemFree.argtypes = [_PTR]
        self.ole32.CoTaskMemFree.restype = None
        self.ole32.PropVariantClear.argtypes = [ct.POINTER(_PropVariant)]
        self.ole32.PropVariantClear.restype = _HRESULT
        for name in ("QueryPerformanceCounter", "QueryPerformanceFrequency"):
            function = getattr(self.kernel32, name)
            function.argtypes = [ct.POINTER(ct.c_int64)]
            function.restype = ct.c_int32
        result = int(self.ole32.CoInitializeEx(None, 0))
        # Enumeration on an existing STA may use that apartment without owning
        # an initialization count. A new capture thread always initializes MTA.
        if result & 0xFFFFFFFF != 0x80010106:  # RPC_E_CHANGED_MODE
            _check(result)
            self._owns_com = True  # Includes S_FALSE; must balance that count.
        self._owner = get_ident()
        frequency = ct.c_int64()
        if not self.kernel32.QueryPerformanceFrequency(ct.byref(frequency)) or frequency.value <= 0:
            self.__exit__()
            raise WasapiError("CLOCK_UNAVAILABLE")
        self._frequency = frequency.value
        return self

    def __exit__(self, *args: object) -> None:
        if self._owns_com:
            self.ole32.CoUninitialize()
            self._owns_com = False

    def now_ns(self) -> int:
        if self._owner != get_ident():
            raise WasapiError("THREAD_VIOLATION")
        value = ct.c_int64()
        if not self.kernel32.QueryPerformanceCounter(ct.byref(value)):
            raise WasapiError("CLOCK_UNAVAILABLE")
        return value.value * 1_000_000_000 // self._frequency

    def enumerator(self) -> ct.c_void_p:
        pointer = _PTR()
        _check(
            int(
                self.ole32.CoCreateInstance(
                    ct.byref(_CLSID_ENUMERATOR),
                    None,
                    23,
                    ct.byref(_IID_ENUMERATOR),
                    ct.byref(pointer),
                )
            )
        )
        return pointer


def _endpoint_id(api: _WinAPI, device: ct.c_void_p) -> str:
    name = _PTR()
    try:
        _check(_invoke(device, 5, (_PTR,), ct.byref(name)))
        if not name.value:
            raise WasapiError("INVALID_DEVICE_ID")
        result = ct.wstring_at(name)
        _device_id(result)
        return result
    finally:
        if name.value:
            api.ole32.CoTaskMemFree(name)


def _friendly_name(api: _WinAPI, device: ct.c_void_p, fallback: str) -> str:
    properties = _PTR()
    value = _PropVariant()
    try:
        _check(_invoke(device, 4, (_DWORD, _PTR), 0, ct.byref(properties)))
        _check(_invoke(properties, 5, (_PTR, _PTR), ct.byref(_FRIENDLY_NAME), ct.byref(value)))
        if value.vt == 31 and value.value.pointer:
            name = ct.wstring_at(value.value.pointer)
            if name and len(name) <= 4096:
                return name
        return fallback
    except WasapiError:
        return fallback
    finally:
        api.ole32.PropVariantClear(ct.byref(value))
        _release(properties)


def _get_device(enumerator: ct.c_void_p, device_id: str) -> ct.c_void_p:
    _device_id(device_id)
    pointer = _PTR()
    _check(_invoke(enumerator, 5, (ct.c_wchar_p, _PTR), device_id, ct.byref(pointer)))
    return pointer


def _activate_client(device: ct.c_void_p, *, loopback: bool) -> ct.c_void_p:
    endpoint, flow = _PTR(), ct.c_int32()
    try:
        _check(_invoke(device, 0, (_PTR, _PTR), ct.byref(_IID_ENDPOINT), ct.byref(endpoint)))
        _check(_invoke(endpoint, 3, (_PTR,), ct.byref(flow)))
        if flow.value != (0 if loopback else 1):
            raise WasapiError("INVALID_DEVICE_FLOW")
    finally:
        _release(endpoint)
    client = _PTR()
    _check(
        _invoke(
            device,
            3,
            (_PTR, _DWORD, _PTR, _PTR),
            ct.byref(_IID_AUDIO_CLIENT),
            23,
            None,
            ct.byref(client),
        )
    )
    return client


def _mix_format(api: _WinAPI, client: ct.c_void_p) -> NativeFormat:
    pointer = _PTR()
    try:
        _check(_invoke(client, 8, (_PTR,), ct.byref(pointer)))
        if not pointer.value:
            raise WasapiError("UNSUPPORTED_FORMAT")
        header = ct.string_at(pointer, 18)
        extra = struct.unpack_from("<H", header, 16)[0]
        if extra > 4096 - 18:
            raise WasapiError("UNSUPPORTED_FORMAT")
        return _parse_wave_format(ct.string_at(pointer, 18 + extra))
    finally:
        if pointer.value:
            api.ole32.CoTaskMemFree(pointer)


def _probe_native(device_id: str, *, loopback: bool) -> NativeFormat:
    with _WinAPI() as api:
        enumerator, device, client = _PTR(), _PTR(), _PTR()
        try:
            enumerator = api.enumerator()
            device = _get_device(enumerator, device_id)
            client = _activate_client(device, loopback=loopback)
            return _mix_format(api, client)
        finally:
            _release(client)
            _release(device)
            _release(enumerator)


def probe_device(device_id: str, *, loopback: bool = False) -> AudioFormat:
    """Explicit format query; never Initialize/Start or read an audio packet."""
    _device_id(device_id)
    if type(loopback) is not bool:
        raise ValidationError("loopback must be bool")
    return _probe_native(device_id, loopback=loopback).audio_format


def list_devices() -> list[DeviceInfo]:
    """List active endpoints using read-only MMDevice and property-store calls."""
    result: list[DeviceInfo] = []
    with _WinAPI() as api:
        enumerator = api.enumerator()
        try:
            for flow in (0, 1):
                default, collection = _PTR(), _PTR()
                default_id: str | None = None
                try:
                    status = _invoke(
                        enumerator, 4, (ct.c_int32, ct.c_int32, _PTR), flow, 1, ct.byref(default)
                    )  # eMultimedia
                    if status & 0xFFFFFFFF == 0x80070490:  # ERROR_NOT_FOUND: no default endpoint.
                        default_id = None
                    else:
                        _check(status)
                        default_id = _endpoint_id(api, default)
                    _check(
                        _invoke(
                            enumerator, 3, (ct.c_int32, _DWORD, _PTR), flow, 1, ct.byref(collection)
                        )
                    )  # DEVICE_STATE_ACTIVE
                    count = _UINT()
                    _check(_invoke(collection, 3, (_PTR,), ct.byref(count)))
                    if count.value > 4096:
                        raise WasapiError("DEVICE_LIMIT_EXCEEDED")
                    for index in range(count.value):
                        device = _PTR()
                        try:
                            _check(_invoke(collection, 4, (_UINT, _PTR), index, ct.byref(device)))
                            identity = _endpoint_id(api, device)
                            result.append(
                                DeviceInfo(
                                    identity,
                                    _friendly_name(api, device, identity),
                                    "render" if flow == 0 else "capture",
                                    identity == default_id,
                                )
                            )
                        finally:
                            _release(device)
                finally:
                    _release(default)
                    _release(collection)
        finally:
            _release(enumerator)
    return result
