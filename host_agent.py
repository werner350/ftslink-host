"""
FTS Link Host — run on the computer you want to let someone control.

Shows a small window with a 6-character code. Give the code to the person
helping you; they open ftslink.com, enter it, and can see and control this
computer. Close the window to end the session instantly.

Packaged into a standalone Mac .app / Windows .exe via PyInstaller (see
.github/workflows/build.yml) so recipients need nothing installed.
"""

import asyncio
import json
import queue
import threading
import time
import tkinter as tk
import urllib.request

import numpy as np
import websockets
from aiortc import (
    RTCConfiguration,
    RTCIceServer,
    RTCPeerConnection,
    RTCSessionDescription,
)
from aiortc.mediastreams import VideoStreamTrack
from aiortc.sdp import candidate_from_sdp
from av import VideoFrame

SERVER = "ftslink.com"
SIGNAL_URL = f"wss://{SERVER}"
ICE_URL = f"https://{SERVER}/ice.json"
FPS = 15

# GUI <- worker communication
gui_q: "queue.Queue[tuple]" = queue.Queue()
stop_flag = threading.Event()


def gui(kind, value=""):
    gui_q.put((kind, value))


# --------------------------------------------------------------------------
def get_ice_servers():
    try:
        with urllib.request.urlopen(ICE_URL, timeout=10) as r:
            data = json.loads(r.read().decode())
        out = []
        for s in data:
            out.append(RTCIceServer(urls=s["urls"], username=s.get("username"),
                                    credential=s.get("credential")))
        return out
    except Exception:
        return [RTCIceServer(urls="stun:stun.l.google.com:19302")]


class ScreenTrack(VideoStreamTrack):
    def __init__(self):
        super().__init__()
        import mss
        self._sct = mss.mss()
        self._mon = self._sct.monitors[1]
        self.width = self._mon["width"]
        self.height = self._mon["height"]
        self._interval = 1.0 / FPS
        self._last = 0.0

    async def recv(self):
        pts, time_base = await self.next_timestamp()
        wait = self._interval - (time.time() - self._last)
        if wait > 0:
            await asyncio.sleep(wait)
        self._last = time.time()
        img = np.asarray(self._sct.grab(self._mon))
        frame = VideoFrame.from_ndarray(img[:, :, :3], format="bgr24")
        frame.pts = pts
        frame.time_base = time_base
        return frame


class Injector:
    def __init__(self, w, h):
        from pynput.keyboard import Controller as KB, Key
        from pynput.mouse import Button, Controller as MC
        self._Button = Button
        self.mouse = MC()
        self.kb = KB()
        self.w, self.h = w, h
        self.SPECIAL = {
            "Enter": Key.enter, "Escape": Key.esc, "Backspace": Key.backspace,
            "Tab": Key.tab, " ": Key.space, "ArrowLeft": Key.left,
            "ArrowRight": Key.right, "ArrowUp": Key.up, "ArrowDown": Key.down,
            "Shift": Key.shift, "Control": Key.ctrl, "Alt": Key.alt,
            "Meta": Key.cmd, "CapsLock": Key.caps_lock, "Delete": Key.delete,
            "Home": Key.home, "End": Key.end, "PageUp": Key.page_up,
            "PageDown": Key.page_down, "Insert": Key.insert, "F1": Key.f1,
            "F2": Key.f2, "F3": Key.f3, "F4": Key.f4, "F5": Key.f5, "F6": Key.f6,
            "F7": Key.f7, "F8": Key.f8, "F9": Key.f9, "F10": Key.f10,
            "F11": Key.f11, "F12": Key.f12,
        }
        self.BTN = {"left": Button.left, "right": Button.right, "middle": Button.middle}

    def _px(self, x, y):
        return int(x * self.w), int(y * self.h)

    def _key(self, name):
        if name in self.SPECIAL:
            return self.SPECIAL[name]
        return name if len(name) == 1 else None

    def handle(self, ev):
        t = ev.get("t")
        if t == "move":
            self.mouse.position = self._px(ev["x"], ev["y"])
        elif t == "down":
            self.mouse.position = self._px(ev["x"], ev["y"])
            self.mouse.press(self.BTN.get(ev.get("button"), self._Button.left))
        elif t == "up":
            self.mouse.position = self._px(ev["x"], ev["y"])
            self.mouse.release(self.BTN.get(ev.get("button"), self._Button.left))
        elif t == "scroll":
            self.mouse.scroll(ev.get("dx", 0), ev.get("dy", 0))
        elif t == "key":
            k = self._key(ev.get("key", ""))
            if k is not None:
                (self.kb.press if ev.get("down") else self.kb.release)(k)


async def add_ice(pc, data):
    if not data or not data.get("candidate"):
        return
    try:
        cand = candidate_from_sdp(data["candidate"].split(":", 1)[1])
        cand.sdpMid = data.get("sdpMid")
        cand.sdpMLineIndex = data.get("sdpMLineIndex")
        await pc.addIceCandidate(cand)
    except Exception:
        pass


async def run_session():
    pc = RTCPeerConnection(RTCConfiguration(iceServers=get_ice_servers()))
    try:
        async with websockets.connect(SIGNAL_URL, max_size=None) as ws:
            await ws.send(json.dumps({"type": "create-room"}))
            async for raw in ws:
                if stop_flag.is_set():
                    break
                msg = json.loads(raw)
                t = msg.get("type")
                if t == "room-created":
                    gui("code", msg["room"])
                    gui("status", "Waiting for someone to connect…")
                elif t == "peer-joined":
                    gui("status", "Connecting…")
                    track = ScreenTrack()
                    inj = Injector(track.width, track.height)
                    pc.addTrack(track)
                    dc = pc.createDataChannel("input")

                    @dc.on("message")
                    def on_msg(message):
                        try:
                            inj.handle(json.loads(message))
                        except Exception:
                            pass

                    offer = await pc.createOffer()
                    await pc.setLocalDescription(offer)
                    await ws.send(json.dumps({"type": "offer", "data": {
                        "sdp": pc.localDescription.sdp,
                        "type": pc.localDescription.type}}))
                    gui("status", "● Live — your screen is shared and controllable")
                elif t == "answer":
                    await pc.setRemoteDescription(RTCSessionDescription(
                        sdp=msg["data"]["sdp"], type=msg["data"]["type"]))
                elif t == "ice":
                    await add_ice(pc, msg.get("data"))
                elif t in ("peer-left", "bye"):
                    gui("status", "Disconnected. You can close this window.")
                    break
                elif t == "error":
                    gui("status", "Error: " + str(msg.get("message")))
    except Exception as e:  # noqa: BLE001
        gui("status", "Connection error: " + str(e))
    finally:
        await pc.close()


def worker():
    try:
        asyncio.run(run_session())
    except Exception as e:  # noqa: BLE001
        gui("status", "Error: " + str(e))


# --------------------------------------------------------------------------
# GUI (main thread)
# --------------------------------------------------------------------------
def main():
    root = tk.Tk()
    root.title("FTS Link Host")
    root.configure(bg="#0f1115")
    root.geometry("420x300")
    # NOTE: do NOT call root.resizable(False, False) — on Windows a fixed-size
    # Tk window cannot be restored with a single taskbar click (only via
    # right-click > Restore). Keeping it resizable fixes that; minsize keeps
    # it from shrinking too small.
    root.minsize(420, 300)

    # Make a single taskbar click reliably bring the window back to the front.
    def _on_map(_evt=None):
        try:
            root.deiconify()
            root.lift()
        except Exception:
            pass
    root.bind("<Map>", _on_map)

    tk.Label(root, text="FTS Link", fg="#ffffff", bg="#0f1115",
             font=("Helvetica", 20, "bold")).pack(pady=(22, 0))
    tk.Label(root, text="Let someone help you with this computer",
             fg="#9aa0a6", bg="#0f1115", font=("Helvetica", 11)).pack()

    tk.Label(root, text="Give this code to the person helping you:",
             fg="#9aa0a6", bg="#0f1115", font=("Helvetica", 11)).pack(pady=(22, 4))
    code_label = tk.Label(root, text="······", fg="#3b82f6", bg="#0f1115",
                          font=("Courier", 34, "bold"))
    code_label.pack()

    status_label = tk.Label(root, text="Connecting to ftslink.com…", fg="#e8eaed",
                            bg="#0f1115", font=("Helvetica", 11), wraplength=380)
    status_label.pack(pady=(18, 0))

    def stop():
        stop_flag.set()
        root.destroy()

    tk.Button(root, text="End session", command=stop).pack(pady=18)
    root.protocol("WM_DELETE_WINDOW", stop)

    threading.Thread(target=worker, daemon=True).start()

    def poll():
        try:
            while True:
                kind, val = gui_q.get_nowait()
                if kind == "code":
                    code_label.config(text=val)
                elif kind == "status":
                    status_label.config(text=val)
        except queue.Empty:
            pass
        if not stop_flag.is_set():
            root.after(150, poll)

    root.after(150, poll)
    root.mainloop()


if __name__ == "__main__":
    main()
