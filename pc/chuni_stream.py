"""把 CHUNITHM 的游戏画面推到 iPad 上方，触摸板留在屏幕下方。

iPad App 本身是 TCP 服务端（端口 24864），输入桥接端自己占一条连接。
本脚本再连一条，只负责发视频；输入桥接端完全不用改：

    0xFF + 4 字节大端长度 + b"VID" + JPEG

原来的短包（首字节 = 长度，LED 是 99）保持不动，所以旧桥接端仍能工作。
连上后先发一个 4 字节的 "NOP\\0" 短包，满足 App 的握手读取。

    python chuni_stream.py --usb                 # USB，转发 127.0.0.1:24865
    python chuni_stream.py --host 192.168.1.20   # Wi-Fi 直连 iPad
    python chuni_stream.py --width 960 --fps 30  # 画质/帧率调低
"""

import argparse
import asyncio
import ctypes
import io
import logging
import msvcrt
import os
import socket
import struct
import sys
import tempfile
import threading
import time
from ctypes import wintypes

from PIL import Image, ImageGrab

try:
    import numpy as np
except ImportError:
    np = None

try:
    import cv2
except ImportError:
    cv2 = None

try:
    import dxcam
except ImportError:
    dxcam = None

ASPECT = 16.0 / 9.0
MAX_BYTES = 400000

user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)


def _dpi_aware():
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:
        try:
            user32.SetProcessDPIAware()
        except Exception:
            pass


if sys.platform == "win32":
    _dpi_aware()


class _PROCESSENTRY32W(ctypes.Structure):
    _fields_ = [
        ("dwSize", wintypes.DWORD),
        ("cntUsage", wintypes.DWORD),
        ("th32ProcessID", wintypes.DWORD),
        ("th32DefaultHeapID", ctypes.c_size_t),
        ("th32ModuleID", wintypes.DWORD),
        ("cntThreads", wintypes.DWORD),
        ("th32ParentProcessID", wintypes.DWORD),
        ("pcPriClassBase", ctypes.c_long),
        ("dwFlags", wintypes.DWORD),
        ("szExeFile", wintypes.WCHAR * 260),
    ]


class _RECT(ctypes.Structure):
    _fields_ = [("left", wintypes.LONG), ("top", wintypes.LONG),
                ("right", wintypes.LONG), ("bottom", wintypes.LONG)]


class _POINT(ctypes.Structure):
    _fields_ = [("x", wintypes.LONG), ("y", wintypes.LONG)]


class _BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [
        ("biSize", wintypes.DWORD),
        ("biWidth", wintypes.LONG),
        ("biHeight", wintypes.LONG),
        ("biPlanes", wintypes.WORD),
        ("biBitCount", wintypes.WORD),
        ("biCompression", wintypes.DWORD),
        ("biSizeImage", wintypes.DWORD),
        ("biXPelsPerMeter", wintypes.LONG),
        ("biYPelsPerMeter", wintypes.LONG),
        ("biClrUsed", wintypes.DWORD),
        ("biClrImportant", wintypes.DWORD),
    ]


class _BITMAPINFO(ctypes.Structure):
    _fields_ = [("bmiHeader", _BITMAPINFOHEADER),
                ("bmiColors", wintypes.DWORD * 3)]


kernel32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
kernel32.Process32FirstW.argtypes = (wintypes.HANDLE, ctypes.POINTER(_PROCESSENTRY32W))
kernel32.Process32NextW.argtypes = (wintypes.HANDLE, ctypes.POINTER(_PROCESSENTRY32W))
kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
user32.EnumWindows.argtypes = (
    ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM), wintypes.LPARAM)
user32.GetDC.restype = wintypes.HDC
user32.GetDC.argtypes = (wintypes.HWND,)
user32.ReleaseDC.argtypes = (wintypes.HWND, wintypes.HDC)
gdi32.CreateCompatibleDC.restype = wintypes.HDC
gdi32.CreateCompatibleDC.argtypes = (wintypes.HDC,)
gdi32.CreateDIBSection.restype = wintypes.HBITMAP
gdi32.CreateDIBSection.argtypes = (
    wintypes.HDC, ctypes.POINTER(_BITMAPINFO), wintypes.UINT,
    ctypes.POINTER(ctypes.c_void_p), wintypes.HANDLE, wintypes.DWORD)
gdi32.SelectObject.argtypes = (wintypes.HDC, wintypes.HGDIOBJ)
gdi32.DeleteObject.argtypes = (wintypes.HGDIOBJ,)
gdi32.DeleteDC.argtypes = (wintypes.HDC,)
gdi32.StretchBlt.argtypes = (
    wintypes.HDC, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
    wintypes.HDC, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, wintypes.DWORD)
gdi32.SetStretchBltMode.argtypes = (wintypes.HDC, ctypes.c_int)
gdi32.SetBrushOrgEx.argtypes = (wintypes.HDC, ctypes.c_int, ctypes.c_int,
                                ctypes.POINTER(_POINT))


def pids_of(exe_name):
    pids = set()
    snap = kernel32.CreateToolhelp32Snapshot(0x2, 0)
    if not snap or snap == ctypes.c_void_p(-1).value:
        return pids
    entry = _PROCESSENTRY32W()
    entry.dwSize = ctypes.sizeof(entry)
    try:
        ok = kernel32.Process32FirstW(snap, ctypes.byref(entry))
        while ok:
            if entry.szExeFile.lower() == exe_name.lower():
                pids.add(entry.th32ProcessID)
            ok = kernel32.Process32NextW(snap, ctypes.byref(entry))
    finally:
        kernel32.CloseHandle(snap)
    return pids


def find_game_window(exe_name):
    pids = pids_of(exe_name)
    if not pids:
        return None
    best = []

    def visit(hwnd, _):
        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if pid.value not in pids:
            return True
        if not user32.IsWindowVisible(hwnd) or user32.IsIconic(hwnd):
            return True
        rect = _RECT()
        if not user32.GetClientRect(hwnd, ctypes.byref(rect)):
            return True
        width = rect.right - rect.left
        height = rect.bottom - rect.top
        if width >= 320 and height >= 180:
            best.append((width * height, hwnd))
        return True

    user32.EnumWindows(
        ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)(visit), 0)
    return max(best)[1] if best else None


def client_box(hwnd):
    rect = _RECT()
    if not user32.GetClientRect(hwnd, ctypes.byref(rect)):
        return None
    origin = _POINT(0, 0)
    if not user32.ClientToScreen(hwnd, ctypes.byref(origin)):
        return None
    width = rect.right - rect.left
    height = rect.bottom - rect.top
    if width < 320 or height < 180:
        return None
    return (origin.x, origin.y, origin.x + width, origin.y + height)


def crop_aspect(box, aspect):
    left, top, right, bottom = box
    width = right - left
    height = bottom - top
    if width / height > aspect:
        new_width = int(round(height * aspect))
        left += (width - new_width) // 2
        width = new_width
    else:
        new_height = int(round(width / aspect))
        top += (height - new_height) // 2
        height = new_height
    return (left, top, left + width, top + height)


class GdiGrabber:
    """StretchBlt straight into a DIB at the output size."""

    SRCCOPY = 0x00CC0020
    HALFTONE = 4

    def __init__(self, width, height):
        self.width = width
        self.height = height
        self.ok = False
        self.screen_dc = user32.GetDC(None)
        self.mem_dc = gdi32.CreateCompatibleDC(self.screen_dc)
        header = _BITMAPINFOHEADER()
        header.biSize = ctypes.sizeof(_BITMAPINFOHEADER)
        header.biWidth = width
        header.biHeight = -height
        header.biPlanes = 1
        header.biBitCount = 32
        header.biCompression = 0
        info = _BITMAPINFO()
        info.bmiHeader = header
        self.bits = ctypes.c_void_p()
        self.bitmap = gdi32.CreateDIBSection(
            self.mem_dc, ctypes.byref(info), 0, ctypes.byref(self.bits), None, 0)
        if not self.bitmap:
            return
        gdi32.SelectObject(self.mem_dc, self.bitmap)
        gdi32.SetStretchBltMode(self.mem_dc, self.HALFTONE)
        gdi32.SetBrushOrgEx(self.mem_dc, 0, 0, None)
        self.ok = bool(self.screen_dc and self.mem_dc and self.bits)

    def grab(self, box):
        if not self.ok:
            return None
        left, top, right, bottom = box
        if right <= left or bottom <= top:
            return None
        if not gdi32.StretchBlt(self.mem_dc, 0, 0, self.width, self.height,
                                self.screen_dc, left, top, right - left, bottom - top,
                                self.SRCCOPY):
            return None
        data = ctypes.string_at(self.bits, self.width * self.height * 4)
        return Image.frombuffer("RGB", (self.width, self.height), data,
                                "raw", "BGRX", 0, 1)

    def close(self):
        try:
            if self.bitmap:
                gdi32.DeleteObject(self.bitmap)
            if self.mem_dc:
                gdi32.DeleteDC(self.mem_dc)
            if self.screen_dc:
                user32.ReleaseDC(None, self.screen_dc)
        except Exception:
            pass
        self.ok = False


class Capture:
    def __init__(self, exe_name, width, quality, use_camera, log):
        self.exe_name = exe_name
        self.width = width
        self.quality = quality
        self.use_camera = use_camera
        self.log = log
        self.hwnd = None
        self.camera = None
        self.gdi = None
        self.size = None
        self.last_warn = 0.0
        self._open_camera()

    def _open_camera(self):
        if not self.use_camera:
            self.log("按参数使用 GDI 抓屏")
            return
        if dxcam is None or np is None:
            self.log("没有 dxcam, 用 GDI 抓屏")
            return
        try:
            self.camera = dxcam.create(output_color="BGR")
            self.log("桌面复制抓屏 (dxcam)")
        except Exception as error:
            self.log(f"桌面复制不可用 ({error}), 用 GDI 抓屏")
            self.camera = None

    def _warn(self, text):
        if time.time() - self.last_warn > 5:
            self.last_warn = time.time()
            self.log(text)

    def _window(self):
        if self.hwnd and user32.IsWindow(self.hwnd) and not user32.IsIconic(self.hwnd):
            return self.hwnd
        self.hwnd = find_game_window(self.exe_name)
        return self.hwnd

    def _target(self, box):
        width = self.width or (box[2] - box[0])
        width -= width % 2
        height = int(round(width / ASPECT))
        height -= height % 2
        return width, height

    def grab(self):
        hwnd = self._window()
        if not hwnd:
            self._warn(f"等待 {self.exe_name} 窗口")
            return None
        box = client_box(hwnd)
        if not box:
            self._warn("游戏窗口最小化或太小")
            return None
        crop = crop_aspect(box, ASPECT)
        size = self._target(crop)
        if size != self.size:
            self.size = size
            self.log(f"抓取区域 {crop} -> {size[0]}x{size[1]}")
        if self.camera is not None:
            try:
                frame = self.camera.grab(region=crop)
            except Exception as error:
                self.log(f"桌面复制抓帧失败 ({error}), 改用 GDI")
                self.camera = None
                frame = None
            if frame is not None:
                if cv2 is not None and tuple(frame.shape[1::-1]) != size:
                    frame = cv2.resize(frame, size, interpolation=cv2.INTER_AREA)
                return self._encode(frame)
            if self.camera is not None:
                return None  # 画面没变化，iPad 保持上一帧
        if self.gdi is None or (self.gdi.width, self.gdi.height) != size:
            if self.gdi is not None:
                self.gdi.close()
            self.gdi = GdiGrabber(*size)
            if not self.gdi.ok:
                self._warn("GDI 抓屏不可用")
                return None
        image = self.gdi.grab(crop)
        if image is None:
            return None
        return self._encode(image)

    def _encode(self, image):
        quality = self.quality
        while True:
            if cv2 is not None and np is not None and isinstance(image, np.ndarray):
                ok, buffer = cv2.imencode(
                    ".jpg", image, [int(cv2.IMWRITE_JPEG_QUALITY), quality])
                data = buffer.tobytes() if ok else b""
            else:
                if isinstance(image, np.ndarray):
                    image = Image.fromarray(image[:, :, ::-1])
                buffer = io.BytesIO()
                image.save(buffer, "JPEG", quality=quality, optimize=False)
                data = buffer.getvalue()
            if len(data) <= MAX_BYTES or quality <= 20:
                return data if data and len(data) <= MAX_BYTES + 1000 else None
            quality -= 5

    def close(self):
        if self.gdi is not None:
            self.gdi.close()
            self.gdi = None
        camera, self.camera = self.camera, None
        if camera is not None:
            try:
                camera.stop()
            except Exception:
                pass


class UsbForward(threading.Thread):
    """127.0.0.1:local_port -> iPad:device_port over usbmux."""

    def __init__(self, local_port, device_port, udid=None, log=print):
        super().__init__(daemon=True)
        self.local_port = local_port
        self.device_port = device_port
        self.udid = udid
        self.log = log
        self.running = True
        self._last_wait = 0.0

    def run(self):
        logging.getLogger("pymobiledevice3.tcp_forwarder").setLevel(logging.CRITICAL)
        while self.running:
            try:
                asyncio.run(self._session())
            except Exception as error:
                self.log(f"USB 转发异常: {error}")
                time.sleep(2)

    async def _session(self):
        from pymobiledevice3 import usbmux
        from pymobiledevice3.tcp_forwarder import UsbmuxTcpForwarder

        try:
            devices = await usbmux.list_devices()
        except Exception as error:
            self.log(f"连不上 usbmuxd: {error} (需要 Apple Devices/iTunes 保持运行)")
            await asyncio.sleep(3)
            return
        devices = [device for device in devices if device.is_usb]
        if self.udid:
            devices = [device for device in devices if device.matches_udid(self.udid)]
        if not devices:
            if time.time() - self._last_wait > 15:
                self._last_wait = time.time()
                self.log("没找到 USB 连接的 iPad: 换数据线、解锁并点「信任此电脑」")
            await asyncio.sleep(3)
            return
        device = devices[0]
        self.log(f"USB 转发 127.0.0.1:{self.local_port} -> iPad {device.serial}:{self.device_port}")
        forwarder = UsbmuxTcpForwarder(device.serial, self.device_port, self.local_port)
        task = asyncio.create_task(forwarder.start())
        try:
            while self.running:
                await asyncio.sleep(1)
                if task.done():
                    break
        finally:
            forwarder.stop()
            try:
                await asyncio.wait_for(task, timeout=3)
            except Exception:
                task.cancel()


class Sender:
    def __init__(self, host, port, capture, fps, log):
        self.host = host
        self.port = port
        self.capture = capture
        self.interval = 1.0 / max(1, fps)
        self.log = log
        self.sock = None
        self.running = True
        self.frames = 0
        self.bytes = 0
        self.last_report = time.time()

    def _connect(self):
        while self.running:
            try:
                sock = socket.create_connection((self.host, self.port), timeout=2)
            except OSError:
                time.sleep(1)
                continue
            sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            sock.settimeout(5)
            try:
                # 满足 App 的 1 字节长度握手；NOP 包会被忽略。
                sock.sendall(b"\x04NOP\x00")
            except OSError:
                try:
                    sock.close()
                except OSError:
                    pass
                time.sleep(1)
                continue
            self.sock = sock
            self.frames = 0
            self.bytes = 0
            self.last_report = time.time()
            self.log(f"已连接 {self.host}:{self.port}，开始推送画面")
            threading.Thread(target=self._drain, args=(sock,), daemon=True).start()
            return True
        return False

    def _drain(self, sock):
        # App 会把触摸包广播给所有连接，这里读掉丢弃，避免接收缓冲区堆满。
        try:
            while self.running:
                if not sock.recv(4096):
                    break
        except OSError:
            pass
        try:
            sock.close()
        except OSError:
            pass
        if self.sock is sock:
            self.sock = None

    def run(self):
        while self.running:
            if self.sock is None and not self._connect():
                return
            started = time.perf_counter()
            data = self.capture.grab()
            if data and self.sock is not None:
                packet = b"\xff" + struct.pack(">I", len(data) + 3) + b"VID" + data
                try:
                    self.sock.sendall(packet)
                except OSError:
                    self.log("连接断开，重连中")
                    try:
                        self.sock.close()
                    except OSError:
                        pass
                    self.sock = None
                    time.sleep(1)
                    continue
                self.frames += 1
                self.bytes += len(data)
            if time.time() - self.last_report >= 5:
                spent = time.time() - self.last_report
                size = self.capture.size or (0, 0)
                self.log(f"画面 {size[0]}x{size[1]}  {self.frames / spent:.1f} fps  "
                         f"{self.bytes / max(1, self.frames) / 1024:.0f} KB/帧")
                self.last_report = time.time()
                self.frames = 0
                self.bytes = 0
            delay = self.interval - (time.perf_counter() - started)
            if delay > 0:
                time.sleep(delay)


def acquire_single_instance(log):
    # 第二份会再连一条视频 socket，还会和 USB 转发抢 24865 端口。
    path = os.path.join(tempfile.gettempdir(), "chuni_stream.lock")
    handle = open(path, "w")
    try:
        msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
    except OSError:
        handle.close()
        log("串流已经在运行，本次启动跳过（关掉旧窗口才能重开）")
        return None
    return handle


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--exe", default="chusanApp.exe", help="游戏进程名")
    parser.add_argument("--usb", action="store_true", help="走 USB 转发（默认；给了 --host 时用它强制回到 USB）")
    parser.add_argument("--host", default=None, help="iPad 的 IP；留空走 USB 转发")
    parser.add_argument("--port", type=int, default=24864, help="App 监听端口")
    parser.add_argument("--local-port", type=int, default=24865, help="USB 转发本机端口")
    parser.add_argument("--udid", default=None, help="有多台 iPad 时指定")
    parser.add_argument("--width", type=int, default=1280, help="推流宽度，0 = 窗口原宽")
    parser.add_argument("--fps", type=int, default=30)
    parser.add_argument("--quality", type=int, default=65)
    parser.add_argument("--gdi", action="store_true", help="跳过桌面复制，直接用 GDI")
    args = parser.parse_args()

    log = lambda text: print(time.strftime("%H:%M:%S"), text, flush=True)

    lock = acquire_single_instance(log)
    if lock is None:
        return 0

    if args.host and not args.usb:
        host = args.host
    else:
        try:
            import pymobiledevice3  # noqa: F401
        except ImportError:
            log("缺少 pymobiledevice3：先运行  python -m pip install pymobiledevice3")
            log("或者改用 Wi-Fi： python chuni_stream.py --host <iPad 的 IP>")
            return 1
        forward = UsbForward(args.local_port, args.port, args.udid, log)
        forward.start()
        host = "127.0.0.1"

    capture = Capture(args.exe, args.width, args.quality, not args.gdi, log)
    sender = Sender(host, args.port if args.host else args.local_port, capture, args.fps, log)
    try:
        sender.run()
    except KeyboardInterrupt:
        pass
    finally:
        capture.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
