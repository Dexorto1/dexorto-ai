"""
Browser & Web Interaction Controller for Dexorto AI
===================================================
Provides native browser & desktop automation:
- Auto-playing songs / music via YouTube search & direct autoplay streaming
- Composing & typing messages in Web Inboxes (Gmail, WhatsApp Web, Outlook, Twitter)
- Typing and sending messages in DMs (Discord, WhatsApp, Telegram, Instagram, Slack)
- Typing text into the active browser or window using X11 keystroke simulation
- Window activation & focus switching via native X11 EWMH
"""

import sys
import os
import re
import json
import time
import urllib.request
import urllib.parse
import config
import subprocess
import threading
import ctypes
from ctypes import (
    c_int, c_uint, c_ulong, c_char_p, c_void_p, c_ubyte, c_long,
    POINTER, byref, cast, Structure, sizeof
)


class XKeyEvent(Structure):
    _fields_ = [
        ("type", c_int),
        ("serial", c_ulong),
        ("send_event", c_int),
        ("display", c_void_p),
        ("window", c_ulong),
        ("root", c_ulong),
        ("subwindow", c_ulong),
        ("time", c_ulong),
        ("x", c_int),
        ("y", c_int),
        ("x_root", c_int),
        ("y_root", c_int),
        ("state", c_uint),
        ("keycode", c_uint),
        ("same_screen", c_int),
    ]


class XClientMessageEvent(Structure):
    _fields_ = [
        ("type", c_int),
        ("serial", c_ulong),
        ("send_event", c_int),
        ("display", c_void_p),
        ("window", c_ulong),
        ("message_type", c_ulong),
        ("format", c_int),
        ("data", c_long * 5),
    ]


class XEvent(ctypes.Union):
    _fields_ = [
        ("type", c_int),
        ("xkey", XKeyEvent),
        ("xclient", XClientMessageEvent),
        ("pad", c_long * 24),
    ]


class BrowserController:
    """Manages browser interaction, song playback, DM typing & sending, and web inboxes."""

    _x11 = None
    _disp = None

    @classmethod
    def _get_x11(cls):
        """Initializes and returns X11 display connection if available."""
        if cls._disp is not None:
            return cls._x11, cls._disp

        try:
            cls._x11 = ctypes.cdll.LoadLibrary("libX11.so.6")
            cls._x11.XOpenDisplay.restype = c_void_p
            cls._x11.XOpenDisplay.argtypes = [c_char_p]
            cls._x11.XDefaultRootWindow.restype = c_ulong
            cls._x11.XDefaultRootWindow.argtypes = [c_void_p]
            cls._x11.XStringToKeysym.restype = c_ulong
            cls._x11.XStringToKeysym.argtypes = [c_char_p]
            cls._x11.XKeysymToKeycode.restype = c_ubyte
            cls._x11.XKeysymToKeycode.argtypes = [c_void_p, c_ulong]
            cls._x11.XGetInputFocus.restype = c_int
            cls._x11.XGetInputFocus.argtypes = [c_void_p, POINTER(c_ulong), POINTER(c_int)]
            cls._x11.XSendEvent.restype = c_int
            cls._x11.XSendEvent.argtypes = [c_void_p, c_ulong, c_int, c_long, c_void_p]
            cls._x11.XFlush.restype = c_int
            cls._x11.XFlush.argtypes = [c_void_p]
            cls._x11.XInternAtom.restype = c_ulong
            cls._x11.XInternAtom.argtypes = [c_void_p, c_char_p, c_int]
            cls._x11.XGetWindowProperty.restype = c_int
            cls._x11.XGetWindowProperty.argtypes = [
                c_void_p, c_ulong, c_ulong, c_long, c_long, c_int, c_ulong,
                POINTER(c_ulong), POINTER(c_int), POINTER(c_ulong), POINTER(c_ulong),
                POINTER(POINTER(c_ubyte))
            ]
            cls._x11.XFree.restype = c_int
            cls._x11.XFree.argtypes = [c_void_p]
            cls._x11.XMapRaised.restype = c_int
            cls._x11.XMapRaised.argtypes = [c_void_p, c_ulong]

            disp_env = os.environ.get("DISPLAY", ":0").encode('utf-8')
            cls._disp = cls._x11.XOpenDisplay(disp_env)
        except Exception:
            cls._x11 = None
            cls._disp = None

        return cls._x11, cls._disp

    # ─────────────────────────────────────────────────────────────
    # Window Focus & Activation (EWMH)
    # ─────────────────────────────────────────────────────────────
    @classmethod
    def focus_app_window(cls, app_query: str) -> bool:
        """
        Searches all open X11 windows for a match on app_query (e.g. 'discord',
        'telegram', 'slack', 'chrome', 'firefox', 'whatsapp') and raises it to focus.
        """
        x11, disp = cls._get_x11()
        if not x11 or not disp:
            return False

        try:
            root = x11.XDefaultRootWindow(disp)
            net_client_list = x11.XInternAtom(disp, b"_NET_CLIENT_LIST", 0)
            net_wm_name = x11.XInternAtom(disp, b"_NET_WM_NAME", 0)
            wm_name = x11.XInternAtom(disp, b"WM_NAME", 0)
            wm_class = x11.XInternAtom(disp, b"WM_CLASS", 0)
            net_active = x11.XInternAtom(disp, b"_NET_ACTIVE_WINDOW", 0)

            actual_type, actual_fmt, nitems, bytes_after = c_ulong(), c_int(), c_ulong(), c_ulong()
            prop = POINTER(c_ubyte)()

            st = x11.XGetWindowProperty(
                disp, root, net_client_list, 0, 2048, 0, 0,
                byref(actual_type), byref(actual_fmt), byref(nitems), byref(bytes_after), byref(prop)
            )
            if st != 0 or not prop:
                return False

            win_ids = cast(prop, POINTER(c_ulong))
            target_win = None
            q_lower = app_query.lower()

            for i in range(nitems.value):
                w = win_ids[i]
                # 1. Match WM_CLASS
                c_prop = POINTER(c_ubyte)()
                if x11.XGetWindowProperty(
                    disp, w, wm_class, 0, 512, 0, 0,
                    byref(c_ulong()), byref(c_int()), byref(c_ulong()), byref(c_ulong()), byref(c_prop)
                ) == 0 and c_prop:
                    cls_str = ctypes.string_at(c_prop).decode('utf-8', errors='ignore').lower()
                    x11.XFree(c_prop)
                    if q_lower in cls_str:
                        target_win = w
                        break

                # 2. Match Window Title
                for atom_n in [net_wm_name, wm_name]:
                    n_prop = POINTER(c_ubyte)()
                    if x11.XGetWindowProperty(
                        disp, w, atom_n, 0, 512, 0, 0,
                        byref(c_ulong()), byref(c_int()), byref(c_ulong()), byref(c_ulong()), byref(n_prop)
                    ) == 0 and n_prop:
                        title_str = ctypes.string_at(n_prop).decode('utf-8', errors='ignore').lower()
                        x11.XFree(n_prop)
                        if q_lower in title_str:
                            target_win = w
                            break
                if target_win:
                    break

            x11.XFree(prop)

            if target_win:
                event = XEvent()
                event.type = 33
                event.xclient.type = 33
                event.xclient.send_event = 1
                event.xclient.display = disp
                event.xclient.window = target_win
                event.xclient.message_type = net_active
                event.xclient.format = 32
                event.xclient.data[0] = 2  # Pager/Dock/App request source
                event.xclient.data[1] = 0

                mask = (1 << 20) | (1 << 19)
                x11.XSendEvent(disp, root, 0, mask, byref(event))
                x11.XMapRaised(disp, target_win)
                x11.XFlush(disp)
                print(f"[Browser] Raised and focused window matching '{app_query}' (ID: {target_win})")
                time.sleep(0.25)
                return True
        except Exception as e:
            print(f"[Browser] Window focus notice: {e}")

        return False

    # ─────────────────────────────────────────────────────────────
    # Tab Reuse Helpers (xdotool-based)
    # ─────────────────────────────────────────────────────────────
    @classmethod
    def _find_browser_tab_by_url(cls, url_pattern: str) -> bool:
        """Uses xdotool to search window titles for a pattern (e.g. 'YouTube', 'Spotify'). Returns True if found."""
        try:
            result = subprocess.run(
                ["xdotool", "search", "--name", url_pattern],
                capture_output=True, text=True, timeout=3
            )
            window_ids = result.stdout.strip().split('\n')
            return any(wid.strip() for wid in window_ids if wid.strip())
        except Exception:
            return False

    @classmethod
    def _navigate_existing_tab(cls, url_pattern: str, new_url: str) -> bool:
        """
        Finds an existing browser tab/window matching url_pattern, activates it,
        and navigates it to new_url using native X11 or TaskManager.
        Returns True if successful, False otherwise.
        """
        try:
            from assistant_tools import TaskManager
            found, win_id, title = TaskManager.focus_app_window(url_pattern)
            if not found:
                for b_name in ["brave", "firefox", "chrome", "chromium"]:
                    b_found, b_wid, b_title = TaskManager.focus_app_window(b_name)
                    if b_found and url_pattern.lower() in b_title.lower():
                        found = True
                        win_id = b_wid
                        break
            if found and win_id:
                return TaskManager.navigate_existing_tab(win_id, new_url)
        except Exception:
            pass

        # Fallback to xdotool if installed
        try:
            result = subprocess.run(
                ["xdotool", "search", "--name", url_pattern],
                capture_output=True, text=True, timeout=3
            )
            window_ids = [wid.strip() for wid in result.stdout.strip().split('\n') if wid.strip()]
            if window_ids:
                target_wid = window_ids[0]
                subprocess.run(["xdotool", "windowactivate", target_wid], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=3)
                time.sleep(0.15)
                subprocess.run(["xdotool", "key", "ctrl+l"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=2)
                time.sleep(0.15)
                subprocess.run(["xdotool", "type", "--delay", "8", new_url], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=10)
                time.sleep(0.1)
                subprocess.run(["xdotool", "key", "Return"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=2)
                print(f"[Browser] Reused existing '{url_pattern}' tab -> {new_url}")
                return True
        except Exception as e:
            print(f"[Browser] Tab reuse notice: {e}")

        return False

    # ─────────────────────────────────────────────────────────────
    # 1. Music & Song Playback in Browser
    # ─────────────────────────────────────────────────────────────
    @classmethod
    def play_song(cls, query: str, platform: str = None) -> dict:
        """
        Searches and directly plays a song in the default web browser.
        Defaults to Spotify Web (https://open.spotify.com) or YouTube if explicitly requested.
        """
        clean = re.sub(r'^(?:play|listen to|put on|start|stream)\s+', '', query.strip(), flags=re.I)
        clean = re.sub(r'\s+(?:on youtube|on spotify|song|music|video)$', '', clean, flags=re.I).strip()
        if not clean:
            clean = "top music hits"

        default_plat = getattr(config, "DEFAULT_MUSIC_PLATFORM", "spotify").lower()
        if "youtube" in query.lower():
            target_platform = "youtube"
        elif "spotify" in query.lower():
            target_platform = "spotify"
        elif platform:
            target_platform = platform.lower()
        else:
            target_platform = default_plat

        if target_platform == "spotify":
            if clean in ["top music hits", "trending songs", "music", "songs"]:
                url = "https://open.spotify.com"
            else:
                encoded = urllib.parse.quote(clean)
                url = f"https://open.spotify.com/search/{encoded}"
            print(f"🎵 [Browser] Playing on Spotify Web: {clean} ({url})")
            if not cls._navigate_existing_tab('Spotify', url):
                subprocess.Popen(["xdg-open", url], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return {"status": "playing", "platform": "spotify", "song": clean, "url": url}

        watch_url = None
        encoded = urllib.parse.quote(clean)
        search_url = f"https://www.youtube.com/results?search_query={encoded}"

        try:
            req = urllib.request.Request(
                search_url,
                headers={
                    "User-Agent": (
                        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                        "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
                    )
                }
            )
            with urllib.request.urlopen(req, timeout=3.5) as resp:
                html = resp.read().decode("utf-8", errors="ignore")
                vids = re.findall(r'/watch\?v=([a-zA-Z0-9_-]{11})', html)
                if vids:
                    vid = vids[0]
                    watch_url = f"https://www.youtube.com/watch?v={vid}&autoplay=1"
        except Exception as e:
            print(f"[Browser] YouTube fast resolve notice: {e}")

        final_url = watch_url if watch_url else search_url
        print(f"🎵 [Browser] Playing song: {clean} -> {final_url}")
        if not cls._navigate_existing_tab('YouTube', final_url):
            subprocess.Popen(["xdg-open", final_url], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

        return {
            "status": "playing",
            "platform": "youtube",
            "song": clean,
            "url": final_url,
            "direct_watch": bool(watch_url)
        }

    # ─────────────────────────────────────────────────────────────
    # 2. Inbox Messaging & Typing in Browser
    # ─────────────────────────────────────────────────────────────
    @classmethod
    def open_inbox(cls, service: str = "gmail", to: str = "", subject: str = "", message: str = "") -> dict:
        """
        Opens a Web Inbox (Gmail, WhatsApp Web, Outlook, Twitter DM)
        with recipient, subject, and the typed message body pre-filled.
        """
        svc = (service or "gmail").lower()
        msg = message or ""
        subj = subject or ""
        recipient = to or ""

        url = ""
        if "whatsapp" in svc:
            phone = re.sub(r'[^0-9+]', '', recipient)
            encoded_msg = urllib.parse.quote(msg)
            if phone:
                url = f"https://web.whatsapp.com/send?phone={phone}&text={encoded_msg}"
            else:
                url = f"https://web.whatsapp.com/send?text={encoded_msg}"

        elif "outlook" in svc or "hotmail" in svc:
            p_to = urllib.parse.quote(recipient)
            p_su = urllib.parse.quote(subj)
            p_body = urllib.parse.quote(msg)
            url = f"https://outlook.live.com/mail/0/deeplink/compose?to={p_to}&subject={p_su}&body={p_body}"

        elif "twitter" in svc or " x" in svc or svc == "x":
            encoded_msg = urllib.parse.quote(msg)
            url = f"https://twitter.com/messages/compose?text={encoded_msg}"

        else:
            params = ["view=cm", "fs=1"]
            if recipient:
                params.append(f"to={urllib.parse.quote(recipient)}")
            if subj:
                params.append(f"su={urllib.parse.quote(subj)}")
            if msg:
                params.append(f"body={urllib.parse.quote(msg)}")
            url = "https://mail.google.com/mail/?" + "&".join(params)

        print(f"✉ [Browser] Opening {svc.upper()} Inbox -> {url}")
        reused = False
        if "whatsapp" in svc:
            reused = cls._navigate_existing_tab('WhatsApp', url)
        elif "outlook" in svc or "hotmail" in svc:
            reused = cls._navigate_existing_tab('Outlook', url)
        else:
            reused = cls._navigate_existing_tab('Gmail', url) or cls._navigate_existing_tab('Mail', url)
        if not reused:
            subprocess.Popen(["xdg-open", url], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

        return {
            "status": "opened_inbox",
            "service": svc,
            "to": recipient,
            "subject": subj,
            "message": msg,
            "url": url
        }

    # ─────────────────────────────────────────────────────────────
    # 3. Direct Typing and Sending Keystrokes (X11)
    # ─────────────────────────────────────────────────────────────
    @classmethod
    def type_in_active_window(cls, text: str, press_enter: bool = False) -> bool:
        """
        Types the specified string into the currently focused window / input field.
        If press_enter is True, hits Return/Enter key after typing to send the message.
        """
        if not text:
            return False

        typed_successfully = False

        # Attempt 1: xdotool
        try:
            res = subprocess.run(
                ["xdotool", "type", "--delay", "16", text],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=5
            )
            if res.returncode == 0:
                typed_successfully = True
        except Exception:
            pass

        # Attempt 2: Native libX11 Keystroke Dispatch via ctypes
        if not typed_successfully:
            x11, disp = cls._get_x11()
            if x11 and disp:
                try:
                    focus_win = c_ulong()
                    revert_to = c_int()
                    x11.XGetInputFocus(disp, byref(focus_win), byref(revert_to))

                    if focus_win.value and focus_win.value != 1:
                        key_map = {
                            " ": b"space",
                            "\n": b"Return",
                            "\t": b"Tab",
                            "\b": b"BackSpace"
                        }

                        for ch in text:
                            key_sym_name = key_map.get(ch, ch.encode('utf-8'))
                            keysym = x11.XStringToKeysym(key_sym_name)
                            if not keysym:
                                continue

                            keycode = x11.XKeysymToKeycode(disp, keysym)
                            if not keycode:
                                continue

                            is_shift = 1 if (ch.isupper() or ch in "~!@#$%^&*()_+{}|:\"<>?") else 0

                            ev_down = XEvent()
                            ev_down.type = 2
                            ev_down.xkey.type = 2
                            ev_down.xkey.send_event = 1
                            ev_down.xkey.display = disp
                            ev_down.xkey.window = focus_win.value
                            ev_down.xkey.keycode = keycode
                            ev_down.xkey.state = is_shift

                            ev_up = XEvent()
                            ev_up.type = 3
                            ev_up.xkey.type = 3
                            ev_up.xkey.send_event = 1
                            ev_up.xkey.display = disp
                            ev_up.xkey.window = focus_win.value
                            ev_up.xkey.keycode = keycode
                            ev_up.xkey.state = is_shift

                            x11.XSendEvent(disp, focus_win.value, 1, 1, byref(ev_down))
                            x11.XSendEvent(disp, focus_win.value, 1, 2, byref(ev_up))
                            x11.XFlush(disp)
                            time.sleep(0.014)

                        typed_successfully = True
                except Exception as e:
                    print(f"[Browser] libX11 typing notice: {e}")

        # Dispatch Enter / Return key to SEND the message if requested
        if press_enter:
            time.sleep(0.18)
            # Try xdotool key Return
            try:
                subprocess.run(
                    ["xdotool", "key", "Return"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    timeout=2
                )
            except Exception:
                pass

            # Fallback native X11 Return key
            x11, disp = cls._get_x11()
            if x11 and disp:
                try:
                    focus_win = c_ulong()
                    revert_to = c_int()
                    x11.XGetInputFocus(disp, byref(focus_win), byref(revert_to))
                    if focus_win.value and focus_win.value != 1:
                        ks_enter = x11.XStringToKeysym(b"Return")
                        kc_enter = x11.XKeysymToKeycode(disp, ks_enter)
                        if kc_enter:
                            ev_d = XEvent()
                            ev_d.type = 2
                            ev_d.xkey.type = 2
                            ev_d.xkey.send_event = 1
                            ev_d.xkey.display = disp
                            ev_d.xkey.window = focus_win.value
                            ev_d.xkey.keycode = kc_enter
                            ev_d.xkey.state = 0

                            ev_u = XEvent()
                            ev_u.type = 3
                            ev_u.xkey.type = 3
                            ev_u.xkey.send_event = 1
                            ev_u.xkey.display = disp
                            ev_u.xkey.window = focus_win.value
                            ev_u.xkey.keycode = kc_enter
                            ev_u.xkey.state = 0

                            x11.XSendEvent(disp, focus_win.value, 1, 1, byref(ev_d))
                            x11.XSendEvent(disp, focus_win.value, 1, 2, byref(ev_u))
                            x11.XFlush(disp)
                except Exception:
                    pass

        action_name = "Typed & Sent (Enter)" if press_enter else "Typed"
        print(f"💬 [Browser/DM] {action_name}: '{text}'")
        return typed_successfully

    # ─────────────────────────────────────────────────────────────
    # 4. Direct Message (DM) Typing & Sending
    # ─────────────────────────────────────────────────────────────
    @classmethod
    def send_dm(cls, message: str = "", platform: str = "active", recipient: str = "", press_enter: bool = True) -> dict:
        """
        Types and sends a message into a Direct Message (DM) conversation.
        Supports opening specific recipient chats on Telegram, WhatsApp Web, Discord, Instagram, Twitter/X, Slack, Signal, or active chat.
        """
        plat = (platform or "active").lower()
        msg = (message or "").strip()
        recip = (recipient or "").strip()
        clean_user = recip.lstrip("@").strip()

        # Auto-detect platform if "active" but recipient hints at a platform or is a phone number
        if plat == "active":
            if re.match(r'^\+?[0-9]{7,15}$', recip):
                plat = "whatsapp"

        # 1. TELEGRAM: Direct Chat Deep-link & Messaging
        if "telegram" in plat:
            if clean_user:
                # tg://resolve?domain=<username> opens the specific chat in Telegram Desktop
                tg_url = f"tg://resolve?domain={clean_user}"
                web_url = f"https://t.me/{clean_user}"
                try:
                    subprocess.Popen(["xdg-open", tg_url], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                except Exception:
                    pass
                time.sleep(0.4)
                if not cls.focus_app_window("telegram"):
                    # If desktop client not running, navigate or open Web Telegram tab
                    if not cls._navigate_existing_tab("Telegram", web_url):
                        subprocess.Popen(["xdg-open", web_url], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                time.sleep(0.5)
            else:
                cls.focus_app_window("telegram") or cls._navigate_existing_tab("Telegram", "https://web.telegram.org")
                time.sleep(0.3)

            if msg:
                cls.type_in_active_window(msg, press_enter=press_enter)
            return {"status": "sent_dm", "platform": "telegram", "recipient": recip, "message": msg, "sent": press_enter}

        # 2. WHATSAPP: Direct Chat Deep-link & Messaging
        elif "whatsapp" in plat:
            clean_phone = re.sub(r'[^0-9+]', '', recip)
            if clean_phone and len(clean_phone) >= 7:
                cls.open_inbox(service="whatsapp", to=clean_phone, message=msg)
                return {"status": "opened_dm", "platform": "whatsapp", "recipient": clean_phone, "message": msg}
            elif clean_user:
                # Contact name or handle on WhatsApp Web
                if not cls.focus_app_window("whatsapp"):
                    cls.open_inbox(service="whatsapp", message=msg)
                time.sleep(0.5)
                # Search contact: WhatsApp Web shortcut to search chat '/'
                cls.type_in_active_window(f"/{clean_user}\n", press_enter=True)
                time.sleep(0.4)
                if msg:
                    cls.type_in_active_window(msg, press_enter=press_enter)
                return {"status": "sent_dm", "platform": "whatsapp", "recipient": clean_user, "message": msg, "sent": press_enter}
            else:
                if not cls.focus_app_window("whatsapp"):
                    cls.open_inbox(service="whatsapp", message=msg)
                else:
                    if msg:
                        cls.type_in_active_window(msg, press_enter=press_enter)
                return {"status": "sent_dm", "platform": "whatsapp", "message": msg, "sent": press_enter}

        # 3. INSTAGRAM: Direct Chat Deep-link & Messaging
        elif "instagram" in plat or plat == "ig":
            return cls.open_instagram_chat(username=clean_user, message=msg)

        # 4. DISCORD: Quick Switcher / User DM & Messaging
        elif "discord" in plat:
            cls.focus_app_window("discord")
            time.sleep(0.3)
            if clean_user:
                try:
                    subprocess.run(["xdotool", "key", "ctrl+k"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=2)
                except Exception:
                    pass
                time.sleep(0.25)
                cls.type_in_active_window(f"@{clean_user}\n", press_enter=True)
                time.sleep(0.35)

            if msg:
                cls.type_in_active_window(msg, press_enter=press_enter)
            return {"status": "sent_dm", "platform": "discord", "recipient": recip, "message": msg, "sent": press_enter}

        # 5. TWITTER / X
        elif "twitter" in plat or plat == "x":
            if clean_user:
                url = f"https://x.com/messages/compose?recipient_id={clean_user}" if clean_user.isdigit() else f"https://x.com/{clean_user}"
                reused = cls._navigate_existing_tab("Twitter", url) or cls._navigate_existing_tab("X", url)
                if not reused:
                    subprocess.Popen(["xdg-open", url], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                time.sleep(0.5)
            else:
                cls.focus_app_window("twitter") or cls.focus_app_window("chrome")
                time.sleep(0.3)

            if msg:
                cls.type_in_active_window(msg, press_enter=press_enter)
            return {"status": "sent_dm", "platform": "twitter", "recipient": recip, "message": msg, "sent": press_enter}

        # 6. SLACK & SIGNAL
        elif plat in ["slack", "signal"]:
            cls.focus_app_window(plat)
            time.sleep(0.3)
            if clean_user:
                try:
                    subprocess.run(["xdotool", "key", "ctrl+k"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=2)
                except Exception:
                    pass
                time.sleep(0.25)
                cls.type_in_active_window(f"{clean_user}\n", press_enter=True)
                time.sleep(0.3)

            if msg:
                cls.type_in_active_window(msg, press_enter=press_enter)
            return {"status": "sent_dm", "platform": plat, "recipient": recip, "message": msg, "sent": press_enter}

        # 7. Active / Generic Chat Window (Auto-detection & focus)
        else:
            chat_apps = ["discord", "telegram", "whatsapp", "slack", "signal", "instagram", "twitter"]
            found_chat = False
            try:
                from assistant_tools import TaskManager
                windows = TaskManager.list_open_windows()
                for app in chat_apps:
                    for w in windows:
                        if app in w.get("class", "").lower() or app in w.get("title", "").lower():
                            TaskManager.activate_window(w["id"])
                            found_chat = True
                            time.sleep(0.2)
                            break
                    if found_chat:
                        break
            except Exception:
                pass

            if msg:
                cls.type_in_active_window(msg, press_enter=press_enter)
            return {"status": "sent_dm", "platform": "active", "recipient": recip, "message": msg, "sent": press_enter}

    @classmethod
    def open_instagram_chat(cls, username: str, message: str = "") -> dict:
        """
        Searches for an Instagram user by username (e.g. '@dexorto' or 'dexorto')
        and opens their direct chat conversation directly in the browser with smart tab reuse.
        Optionally types and sends a message if provided.
        """
        clean_user = (username or "").strip()
        if "instagram.com" in clean_user:
            clean_user = re.sub(r'https?://(?:www\.)?instagram\.com/', '', clean_user).split('/')[0].split('?')[0]
        clean_user = clean_user.lstrip("@").strip().strip("/")

        if not clean_user:
            cls.focus_app_window("instagram") or cls._navigate_existing_tab("Instagram", "https://www.instagram.com/direct/inbox/?hl=en")
            return {"status": "opened_inbox", "platform": "instagram", "message": "", "text": "Opened Instagram Direct inbox, Dex."}

        # Exact user-requested format: https://www.instagram.com/(username)/?hl=en
        url = f"https://www.instagram.com/{clean_user}/?hl=en"
        print(f"📸 [Browser] Searching & Opening Instagram -> @{clean_user} ({url})")
        reused = cls._navigate_existing_tab("Instagram", url)
        if not reused:
            subprocess.Popen(["xdg-open", url], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

        time.sleep(0.7)
        if message:
            cls.type_in_active_window(message.strip(), press_enter=True)
            return {
                "status": "sent",
                "platform": "instagram",
                "username": clean_user,
                "message": message,
                "text": f"Sent message to @{clean_user} on Instagram, Dex."
            }
        else:
            return {
                "status": "opened",
                "platform": "instagram",
                "username": clean_user,
                "text": f"Opened Instagram chat with @{clean_user}, Dex."
            }

    # ─────────────────────────────────────────────────────────────
    # 5. System Menu, Volume & Media Interactions
    # ─────────────────────────────────────────────────────────────
    @classmethod
    def open_system_menu(cls) -> dict:
        """
        Opens the system application launcher / start menu (KDE Plasma, GNOME, XFCE).
        Uses native X11 Super_L key event dispatch, Alt+F1 fallback, and system launcher triggers.
        """
        dispatched = False

        # Attempt 1: Native libX11 Super_L Key Press & Release
        x11, disp = cls._get_x11()
        if x11 and disp:
            try:
                root = x11.XDefaultRootWindow(disp)
                ks_super = x11.XStringToKeysym(b"Super_L")
                kc_super = x11.XKeysymToKeycode(disp, ks_super)
                if kc_super:
                    ev_down = XEvent()
                    ev_down.type = 2  # KeyPress
                    ev_down.xkey.type = 2
                    ev_down.xkey.send_event = 1
                    ev_down.xkey.display = disp
                    ev_down.xkey.window = root
                    ev_down.xkey.keycode = kc_super
                    ev_down.xkey.state = 0

                    ev_up = XEvent()
                    ev_up.type = 3  # KeyRelease
                    ev_up.xkey.type = 3
                    ev_up.xkey.send_event = 1
                    ev_up.xkey.display = disp
                    ev_up.xkey.window = root
                    ev_up.xkey.keycode = kc_super
                    ev_up.xkey.state = 0

                    mask = (1 << 0) | (1 << 1)
                    x11.XSendEvent(disp, root, 1, mask, byref(ev_down))
                    x11.XSendEvent(disp, root, 1, mask, byref(ev_up))
                    x11.XFlush(disp)
                    dispatched = True
            except Exception as e:
                print(f"[System] X11 Super_L dispatch notice: {e}")

        # Attempt 2: xdotool key Super_L or Alt+F1
        if not dispatched:
            try:
                res = subprocess.run(["xdotool", "key", "Super_L"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=2)
                if res.returncode == 0:
                    dispatched = True
                else:
                    res2 = subprocess.run(["xdotool", "key", "alt+F1"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=2)
                    if res2.returncode == 0:
                        dispatched = True
            except Exception:
                pass

        # Attempt 3: KDE Plasma KRunner or Application Launcher via qdbus / command
        if not dispatched:
            for cmd in [
                ["qdbus", "org.kde.plasmashell", "/PlasmaShell", "org.kde.PlasmaShell.activateLauncherMenu"],
                ["krunner"],
                ["plasmawindowed", "org.kde.plasma.kickoff"],
            ]:
                try:
                    subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                    dispatched = True
                    break
                except Exception:
                    continue

        return {
            "status": "opened_menu",
            "message": "Opening system application menu, Dex.",
            "success": True
        }

    @classmethod
    def system_volume(cls, command: str = "up", level: int = None) -> dict:
        """
        Controls system audio volume (up, down, mute, unmute, set level).
        Dispatches via pactl, amixer, or native X11 XF86Audio keys.
        """
        cmd = (command or "up").lower().strip()
        done = False
        if level is not None:
            msg = f"Volume set to {int(level)}%, Dex."
        elif cmd in ["up", "increase", "raise", "badhao"]:
            msg = "Volume increased, Dex."
        elif cmd in ["down", "decrease", "lower", "kam karo", "kam"]:
            msg = "Volume decreased, Dex."
        elif cmd in ["mute", "silent", "shant"]:
            msg = "System audio muted, Dex."
        elif cmd in ["unmute"]:
            msg = "System audio unmuted, Dex."
        else:
            msg = "Adjusted system volume, Dex."

        if level is not None:
            pct = max(0, min(100, int(level)))
            try:
                subprocess.run(["pactl", "set-sink-volume", "@DEFAULT_SINK@", f"{pct}%"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=2)
                done = True
                msg = f"Volume set to {pct}%, Dex."
            except Exception:
                try:
                    subprocess.run(["amixer", "-D", "pulse", "sset", "Master", f"{pct}%"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=2)
                    done = True
                    msg = f"Volume set to {pct}%, Dex."
                except Exception:
                    pass
        elif cmd in ["up", "increase", "raise", "badhao"]:
            try:
                subprocess.run(["pactl", "set-sink-volume", "@DEFAULT_SINK@", "+10%"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=2)
                done = True
                msg = "Volume increased, Dex."
            except Exception:
                try:
                    subprocess.run(["amixer", "-D", "pulse", "sset", "Master", "10%+"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=2)
                    done = True
                    msg = "Volume increased, Dex."
                except Exception:
                    pass
        elif cmd in ["down", "decrease", "lower", "kam karo", "kam"]:
            try:
                subprocess.run(["pactl", "set-sink-volume", "@DEFAULT_SINK@", "-10%"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=2)
                done = True
                msg = "Volume decreased, Dex."
            except Exception:
                try:
                    subprocess.run(["amixer", "-D", "pulse", "sset", "Master", "10%-"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=2)
                    done = True
                    msg = "Volume decreased, Dex."
                except Exception:
                    pass
        elif cmd in ["mute", "silent", "shant"]:
            try:
                subprocess.run(["pactl", "set-sink-mute", "@DEFAULT_SINK@", "1"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=2)
                done = True
                msg = "System audio muted, Dex."
            except Exception:
                try:
                    subprocess.run(["amixer", "-D", "pulse", "sset", "Master", "mute"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=2)
                    done = True
                    msg = "System audio muted, Dex."
                except Exception:
                    pass
        elif cmd in ["unmute"]:
            try:
                subprocess.run(["pactl", "set-sink-mute", "@DEFAULT_SINK@", "0"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=2)
                done = True
                msg = "System audio unmuted, Dex."
            except Exception:
                try:
                    subprocess.run(["amixer", "-D", "pulse", "sset", "Master", "unmute"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=2)
                    done = True
                    msg = "System audio unmuted, Dex."
                except Exception:
                    pass

        # Native X11 Fallback via Media Keys
        if not done:
            x11, disp = cls._get_x11()
            key_name = b"XF86AudioRaiseVolume" if "up" in cmd else (b"XF86AudioLowerVolume" if "down" in cmd else b"XF86AudioMute")
            if x11 and disp:
                try:
                    root = x11.XDefaultRootWindow(disp)
                    ks = x11.XStringToKeysym(key_name)
                    kc = x11.XKeysymToKeycode(disp, ks)
                    if kc:
                        ev_d = XEvent()
                        ev_d.type = 2
                        ev_d.xkey.type = 2
                        ev_d.xkey.send_event = 1
                        ev_d.xkey.display = disp
                        ev_d.xkey.window = root
                        ev_d.xkey.keycode = kc
                        ev_u = XEvent()
                        ev_u.type = 3
                        ev_u.xkey.type = 3
                        ev_u.xkey.send_event = 1
                        ev_u.xkey.display = disp
                        ev_u.xkey.window = root
                        ev_u.xkey.keycode = kc
                        x11.XSendEvent(disp, root, 1, (1 << 0) | (1 << 1), byref(ev_d))
                        x11.XSendEvent(disp, root, 1, (1 << 0) | (1 << 1), byref(ev_u))
                        x11.XFlush(disp)
                        done = True
                except Exception:
                    pass

        return {"status": "volume_adjusted", "command": cmd, "message": msg, "success": True}

    @classmethod
    def media_control(cls, command: str = "play_pause") -> dict:
        """
        Controls media playback across browser and desktop players (play/pause, next, prev, stop).
        Uses playerctl, native X11 XF86Audio keys, or xdotool.
        """
        cmd = (command or "play_pause").lower().strip()
        done = False
        msg = "Playback updated, Dex."

        playerctl_cmd = "play-pause"
        if cmd in ["play", "resume", "chalao"]:
            playerctl_cmd = "play"
            msg = "Resuming playback, Dex."
        elif cmd in ["pause", "stop", "roko", "band karo"]:
            playerctl_cmd = "pause"
            msg = "Paused playback, Dex."
        elif cmd in ["next", "skip", "agla"]:
            playerctl_cmd = "next"
            msg = "Playing next track, Dex."
        elif cmd in ["prev", "previous", "pichhla"]:
            playerctl_cmd = "previous"
            msg = "Playing previous track, Dex."
        else:
            playerctl_cmd = "play-pause"
            msg = "Toggled playback, Dex."

        # 1. Primary: playerctl (controls all active MPRIS media players)
        try:
            res = subprocess.run(["playerctl", playerctl_cmd], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=2)
            if res.returncode == 0:
                done = True
        except Exception:
            pass

        # 2. Secondary: D-Bus MPRIS direct method calls for Spotify, browsers, VLC, MPV
        if not done:
            mpris_method = "PlayPause"
            if playerctl_cmd == "play":
                mpris_method = "Play"
            elif playerctl_cmd == "pause":
                mpris_method = "Pause"
            elif playerctl_cmd == "stop":
                mpris_method = "Stop"
            elif playerctl_cmd == "next":
                mpris_method = "Next"
            elif playerctl_cmd == "previous":
                mpris_method = "Previous"

            for target in ["spotify", "vlc", "firefox", "chromium", "brave", "google-chrome", "mpv", "audacious"]:
                try:
                    p = subprocess.run([
                        "dbus-send", "--type=method_call",
                        f"--dest=org.mpris.MediaPlayer2.{target}",
                        "/org/mpris/MediaPlayer2",
                        f"org.mpris.MediaPlayer2.Player.{mpris_method}"
                    ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=1)
                    if p.returncode == 0:
                        done = True
                        break
                except Exception:
                    continue

        # 3. Tertiary: xdotool multimedia key emission
        if not done:
            xdotool_keys = {
                "play": "XF86AudioPlay",
                "pause": "XF86AudioPlay",
                "play-pause": "XF86AudioPlay",
                "next": "XF86AudioNext",
                "previous": "XF86AudioPrev",
                "stop": "XF86AudioStop"
            }
            k = xdotool_keys.get(playerctl_cmd, "XF86AudioPlay")
            try:
                p = subprocess.run(["xdotool", "key", k], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=1)
                if p.returncode == 0:
                    done = True
            except Exception:
                pass

        # 4. Quaternary: Native X11 XSendEvent to Root Window
        if not done:
            key_map = {
                "play": b"XF86AudioPlay",
                "pause": b"XF86AudioPlay",
                "play-pause": b"XF86AudioPlay",
                "next": b"XF86AudioNext",
                "previous": b"XF86AudioPrev",
                "stop": b"XF86AudioStop"
            }
            key_name = key_map.get(playerctl_cmd, b"XF86AudioPlay")
            x11, disp = cls._get_x11()
            if x11 and disp:
                try:
                    root = x11.XDefaultRootWindow(disp)
                    ks = x11.XStringToKeysym(key_name)
                    kc = x11.XKeysymToKeycode(disp, ks)
                    if kc:
                        ev_d = XEvent()
                        ev_d.type = 2
                        ev_d.xkey.type = 2
                        ev_d.xkey.send_event = 1
                        ev_d.xkey.display = disp
                        ev_d.xkey.window = root
                        ev_d.xkey.keycode = kc
                        ev_u = XEvent()
                        ev_u.type = 3
                        ev_u.xkey.type = 3
                        ev_u.xkey.send_event = 1
                        ev_u.xkey.display = disp
                        ev_u.xkey.window = root
                        ev_u.xkey.keycode = kc
                        x11.XSendEvent(disp, root, 1, (1 << 0) | (1 << 1), byref(ev_d))
                        x11.XSendEvent(disp, root, 1, (1 << 0) | (1 << 1), byref(ev_u))
                        x11.XFlush(disp)
                        done = True
                except Exception:
                    pass

        return {"status": "media_controlled", "command": cmd, "message": msg, "success": True}

    # ─────────────────────────────────────────────────────────────
    # 6. Dedicated Gmail Feature & Browser Tab Reuse
    # ─────────────────────────────────────────────────────────────
    @classmethod
    def manage_gmail(cls, action: str = "inbox", query: str = "", to: str = "", subject: str = "", message: str = "") -> dict:
        """
        Manages Gmail interaction: opens inbox, unread emails, compose with to/subject/body, or search.
        Reuses existing Gmail browser tabs to prevent duplicate tabs.
        """
        act = (action or "inbox").lower().strip()
        site_name = "Gmail"

        if act == "unread":
            url = "https://mail.google.com/mail/u/0/#search/is%3Aunread"
            reply_msg = "Opening your unread emails in Gmail, Dex."
        elif act in ["compose", "write", "new"]:
            encoded_to = urllib.parse.quote(to or "")
            encoded_su = urllib.parse.quote(subject or "")
            encoded_body = urllib.parse.quote(message or "")
            url = f"https://mail.google.com/mail/?view=cm&fs=1&to={encoded_to}&su={encoded_su}&body={encoded_body}"
            dest = f" to {to}" if to else ""
            reply_msg = f"Composing new Gmail message{dest}, Dex."
        elif act in ["search", "find"]:
            q_enc = urllib.parse.quote(query or "")
            url = f"https://mail.google.com/mail/u/0/#search/{q_enc}"
            reply_msg = f"Searching Gmail for '{query}', Dex."
        else: # "inbox"
            url = "https://mail.google.com"
            reply_msg = "Opening your Gmail inbox, Dex."

        # Check if Gmail tab is already open using TabManager
        try:
            from assistant_tools import TaskManager
            found, win_id, title = TaskManager.focus_app_window(site_name)
            if not found:
                for b_name in ["brave", "firefox", "chrome", "chromium"]:
                    b_found, b_wid, b_title = TaskManager.focus_app_window(b_name)
                    if b_found and site_name.lower() in b_title.lower():
                        found = True
                        win_id = b_wid
                        break

            if found and win_id:
                TaskManager.navigate_existing_tab(win_id, url)
                return {"status": "navigated_existing", "action": act, "url": url, "message": reply_msg}
        except Exception:
            pass

        subprocess.Popen(["xdg-open", url], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return {"status": "opened_new", "action": act, "url": url, "message": reply_msg}

    # ─────────────────────────────────────────────────────────────
    # 7. Unified Browser & System Interaction Tools
    # ─────────────────────────────────────────────────────────────
    @classmethod
    def browser_action(cls, action: str, url: str = "", song: str = "", platform: str = "spotify", query: str = "", command: str = "") -> dict:
        """
        Unified tool to interact with the browser: playing music (Spotify default),
        navigating websites with tab reuse, media controls, web searching, and scrolling.
        """
        act = (action or "play_music").lower().strip()
        if act in ["play_music", "play_song", "music"]:
            target_song = song or query or command or "top music hits"
            cls.play_song(target_song, platform=platform)
            return {"status": "success", "action": "play_music", "message": f"Playing {target_song} on {platform.capitalize()}, Dex."}
        elif act in ["open_url", "navigate", "open"]:
            target_url = url or query
            if target_url:
                if not target_url.startswith(("http://", "https://")):
                    target_url = "https://" + target_url
                parsed = urllib.parse.urlparse(target_url)
                site = (parsed.hostname or target_url).replace("www.", "").split(".")[0].capitalize()
                cls._navigate_existing_tab(site, target_url)
                return {"status": "success", "action": "open_url", "message": f"Navigating to {site}, Dex."}
            return {"status": "error", "message": "No URL provided."}
        elif act in ["media_control", "media", "playback"]:
            return cls.media_control(command or query or "play_pause")
        elif act in ["search", "search_web"]:
            q_enc = urllib.parse.quote(query or command or "")
            target_url = f"https://www.google.com/search?q={q_enc}"
            subprocess.Popen(["xdg-open", target_url], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return {"status": "success", "action": "search", "message": f"Searching web for '{query or command}', Dex."}
        elif act in ["scroll_down", "down"]:
            cls.type_in_active_window("", press_enter=False)
            try:
                subprocess.run(["xdotool", "key", "Page_Down"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=2)
            except Exception:
                pass
            return {"status": "success", "action": "scroll_down", "message": "Scrolled down, Dex."}
        elif act in ["scroll_up", "up"]:
            try:
                subprocess.run(["xdotool", "key", "Page_Up"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=2)
            except Exception:
                pass
            return {"status": "success", "action": "scroll_up", "message": "Scrolled up, Dex."}
        return {"status": "error", "message": f"Unknown browser action '{action}', Dex."}

    @classmethod
    def system_action(cls, action: str, command: str = "", app_name: str = "", volume_level: int = None) -> dict:
        """
        Unified tool to interact with the desktop system: opening start/application menu,
        controlling system volume, controlling media playback, locking screen, opening settings.
        """
        act = (action or "open_menu").lower().strip()
        if act in ["open_menu", "menu", "start_menu"]:
            return cls.open_system_menu()
        elif act in ["volume", "sound", "audio"]:
            return cls.system_volume(command=command, level=volume_level)
        elif act in ["media", "media_control", "playback"]:
            return cls.media_control(command=command)
        elif act in ["lock_screen", "lock"]:
            for lock_cmd in [["loginctl", "lock-session"], ["xdg-screensaver", "lock"], ["qdbus", "org.freedesktop.ScreenSaver", "/ScreenSaver", "Lock"]]:
                try:
                    subprocess.Popen(lock_cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                    break
                except Exception:
                    continue
            return {"status": "success", "action": "lock_screen", "message": "Screen locked, Dex."}
        elif act in ["settings", "system_settings"]:
            for s_cmd in ["systemsettings5", "systemsettings", "gnome-control-center"]:
                try:
                    subprocess.Popen([s_cmd], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                    return {"status": "success", "action": "settings", "message": "Opening system settings, Dex."}
                except Exception:
                    continue
            return {"status": "error", "message": "Could not open system settings."}
        elif act in ["open_app", "launch"]:
            from assistant_tools import ToolExecutor
            msg = ToolExecutor.execute_tool("open_app", {"app_name": app_name or command})
            return {"status": "success", "action": "open_app", "message": msg}
        return {"status": "error", "message": f"Unknown system action '{action}', Dex."}

    # ─────────────────────────────────────────────────────────────
    # 8. Command Router & Natural Language Intent Parser
    # ─────────────────────────────────────────────────────────────
    @classmethod
    def execute_action(cls, action_data: dict) -> bool:
        """Executes a parsed action dictionary."""
        action = action_data.get("action", "")
        cmd = action_data.get("command", "")

        # 1. Direct Message (DM) Type & Send
        if action in ["send_dm", "type_and_send"] or (action == "browser" and cmd in ["send_dm", "dm"]):
            message = (
                action_data.get("message") or
                action_data.get("text") or
                action_data.get("body") or ""
            )
            platform = action_data.get("platform") or action_data.get("inbox") or "active"
            recipient = action_data.get("recipient") or action_data.get("to") or ""
            press_enter = action_data.get("press_enter", True)
            if message:
                cls.send_dm(message=message, platform=platform, recipient=recipient, press_enter=press_enter)
                return True

        # 2. Browser Action (Unified)
        elif action == "browser_action":
            cls.browser_action(
                action=action_data.get("browser_action") or action_data.get("action_type") or "play_music",
                url=action_data.get("url", ""),
                song=action_data.get("song", ""),
                platform=action_data.get("platform", "spotify"),
                query=action_data.get("query", ""),
                command=action_data.get("command", "")
            )
            return True

        # 3. System Action (Unified)
        elif action == "system_action":
            cls.system_action(
                action=action_data.get("system_action") or action_data.get("action_type") or "open_menu",
                command=action_data.get("command", ""),
                app_name=action_data.get("app_name", ""),
                volume_level=action_data.get("volume_level")
            )
            return True

        # 4. Open System Menu
        elif action in ["open_menu", "open_system_menu", "system_menu"]:
            cls.open_system_menu()
            return True

        # 5. System Volume
        elif action in ["system_volume", "volume"]:
            cls.system_volume(command=cmd or action_data.get("direction", "up"), level=action_data.get("level"))
            return True

        # 6. Media Control
        elif action in ["media_control", "media_playback"]:
            cls.media_control(command=cmd or action_data.get("direction", "play_pause"))
            return True

        # 7. Dedicated Gmail
        elif action in ["manage_gmail", "gmail"]:
            cls.manage_gmail(
                action=action_data.get("gmail_action", "inbox"),
                query=action_data.get("query", ""),
                to=action_data.get("to", ""),
                subject=action_data.get("subject", ""),
                message=action_data.get("message", "")
            )
            return True

        # 8. Play Music / Song
        elif action == "play_music" or (action == "browser" and cmd == "play_song"):
            song = (
                action_data.get("song") or
                action_data.get("query") or
                action_data.get("target") or
                action_data.get("title") or ""
            )
            platform = action_data.get("platform") or getattr(config, "DEFAULT_MUSIC_PLATFORM", "spotify")
            if song:
                cls.play_song(song, platform=platform)
                return True

        # 9. Compose / Inbox Messaging (Draft/Compose URL)
        elif action in ["compose_message", "inbox"] or (action == "browser" and cmd in ["open_inbox", "compose"]):
            service = (
                action_data.get("inbox") or
                action_data.get("service") or
                action_data.get("platform") or "gmail"
            )
            to = action_data.get("to") or action_data.get("recipient") or ""
            subject = action_data.get("subject") or action_data.get("title") or ""
            message = (
                action_data.get("message") or
                action_data.get("body") or
                action_data.get("text") or ""
            )
            cls.open_inbox(service=service, to=to, subject=subject, message=message)
            return True

        # 10. Direct Typing (No Enter)
        elif action == "type_text" or (action == "browser" and cmd in ["type", "type_text"]):
            text = action_data.get("text") or action_data.get("message") or ""
            if text:
                cls.type_in_active_window(text, press_enter=False)
                return True

        # 11. Open URL / Page
        elif action == "open_url" or (action == "browser" and cmd == "open"):
            url = action_data.get("target") or action_data.get("url") or ""
            if url:
                reused = False
                try:
                    parsed = urllib.parse.urlparse(url)
                    domain = parsed.hostname or ""
                    domain_parts = domain.replace("www.", "").split(".")
                    if domain_parts:
                        site_name = domain_parts[0].capitalize()
                        reused = cls._navigate_existing_tab(site_name, url)
                except Exception:
                    pass
                if not reused:
                    subprocess.Popen(["xdg-open", url], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                return True

        return False

    @classmethod
    def handle_natural_intent(cls, user_query: str) -> bool:
        """Parses natural language intent for DMs, songs, inboxes, system menu, volume, and media."""
        q = user_query.strip()
        low = q.lower()

        # 0a. Check Open System Menu Intent
        # Examples: "open menu", "start menu", "open start menu", "menu kholo", "system menu"
        if re.search(r'\b(?:open|show|launch)?\s*(?:the\s+)?(?:system|application|start|kde|plasma)?\s*menu\b', low) or (
            any(w in low for w in ["start menu", "app menu", "menu kholo", "system menu"])
        ):
            cls.open_system_menu()
            return True

        # 0b. Check System Volume Intent
        if re.search(r'\b(?:volume|sound|audio|awaaz)\s*(?:up|down|mute|unmute|badhao|kam|raise|lower)\b', low) or (
            any(w in low for w in ["volume up", "volume down", "volume badhao", "volume kam karo", "mute karo", "unmute karo"])
        ):
            cmd = "up" if any(w in low for w in ["up", "raise", "badhao", "increase"]) else (
                "down" if any(w in low for w in ["down", "lower", "kam", "decrease"]) else (
                    "mute" if "mute" in low else "unmute"
                )
            )
            cls.system_volume(command=cmd)
            return True

        # 0c. Check Media Playback Control Intent
        if re.search(r'\b(?:pause|resume|stop|next|previous)\s+(?:music|song|playback|track|video)\b', low) or (
            low in ["pause music", "stop music", "next song", "resume music", "next track", "previous track", "pause", "resume"]
        ):
            cmd = "pause" if any(w in low for w in ["pause", "stop", "roko"]) else (
                "next" if any(w in low for w in ["next", "agla", "skip"]) else (
                    "previous" if any(w in low for w in ["prev", "previous", "pichhla"]) else "play"
                )
            )
            cls.media_control(command=cmd)
            return True

        # 0d. Check Gmail Intent
        if re.search(r'\b(?:open|check|show)\s+(?:gmail|unread\s+email|unread\s+emails|email\s+inbox|my\s+emails?)\b', low) or (
            "check gmail" in low or "unread email" in low
        ):
            act = "unread" if "unread" in low else "inbox"
            cls.manage_gmail(action=act)
            return True

        # 1. Check DM Type & Send Intent
        # Examples: "type and send message in dms: hello", "send dm on discord saying ...", "send in chat: ...", "chat me bhejo"
        dm_keywords = ["dm", "dms", "direct message", "chat", "discord", "telegram", "slack", "whatsapp", "instagram"]
        is_dm_intent = (
            ("dm" in low or "dms" in low or "chat" in low) and any(w in low for w in ["type", "send", "write", "bhejo"])
        ) or (
            "type and send" in low or "send in chat" in low or "send to chat" in low or "chat me" in low or "chat mein" in low
        ) or (
            any(app in low for app in ["discord", "telegram", "slack", "whatsapp", "instagram"]) and any(w in low for w in ["saying", "send", "type", "bhejo"])
        )

        if is_dm_intent:
            platform = "active"
            for p in ["discord", "whatsapp", "telegram", "instagram", "slack", "twitter"]:
                if p in low:
                    platform = p
                    break

            recipient = ""
            m_to = re.search(r'\b(?:to|ko)\s+([a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+|\+?[0-9]{7,15}|\w+)', q, re.I)
            if m_to and m_to.group(1).lower() not in ["dm", "dms", "chat", "inbox", "discord", "whatsapp", "telegram", "slack", "saying", "message", "me", "mein"]:
                recipient = m_to.group(1)

            msg = ""
            m_say = re.search(r'\b(?:saying|bolkar|likhkar)\s*[:]?\s*(.+)$', q, re.I)
            if m_say:
                msg = m_say.group(1).strip('"\' ')
            else:
                m_colon = re.search(r':\s*(.+)$', q)
                if m_colon:
                    msg = m_colon.group(1).strip('"\' ')
                else:
                    msg = re.sub(
                        r'^(?:type\s+and\s+send|send|type|bhejo)?\s*(?:[a-zA-Z0-9_]+\s+ko)?\s*(?:a\s+)?(?:message|text)?\s*(?:in\s+dm|in\s+dms|in\s+chat|to\s+dm|to\s+chat|on\s+discord|on\s+telegram|on\s+whatsapp|chat\s+me|chat\s+mein)?\s*(?:bhejo)?\s*',
                        '', q, flags=re.I
                    ).strip('"\' ')

            if msg:
                cls.send_dm(message=msg, platform=platform, recipient=recipient, press_enter=True)
                return True

        # 2. Check Music / Song Intent
        if re.search(r'\b(?:play|listen to|put on)\s+(.+)', low, re.I):
            song_match = re.search(r'\b(?:play|listen to|put on)\s+(?:a\s+)?(?:song\s+)?(.+)', q, re.I)
            if song_match:
                song = song_match.group(1).strip()
                if song and not any(k in song.lower() for k in ["game", "video game", "football", "cricket"]):
                    cls.play_song(song)
                    return True

        # 3. Check Web Inbox Compose Intent
        inbox_keywords = ["inbox", "gmail", "email", "mail", "whatsapp", "outlook"]
        if any(k in low for k in inbox_keywords) and any(w in low for w in ["type", "send", "compose", "write", "message"]):
            svc = "gmail"
            if "whatsapp" in low:
                svc = "whatsapp"
            elif "outlook" in low or "hotmail" in low:
                svc = "outlook"

            to = ""
            m_to = re.search(r'\bto\s+([a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+|\+?[0-9]{7,15}|\w+)', q, re.I)
            if m_to and m_to.group(1).lower() not in ["inbox", "gmail", "whatsapp", "outlook", "saying", "message", "email"]:
                to = m_to.group(1)

            subject = ""
            m_su = re.search(r'\bsubject\s+(.*?)(?=\s+(?:and\s+)?(?:body|message|saying)\b|$)', q, re.I)
            if m_su:
                subject = m_su.group(1).strip('"\' ')

            body = ""
            m_say = re.search(r'\bsaying\s*[:]?\s*(.+)$', q, re.I)
            if m_say:
                body = m_say.group(1).strip('"\' ')
            else:
                m_body = re.search(r'\b(?:body|message)\s*[:]?\s*(.+)$', q, re.I)
                if m_body:
                    body = m_body.group(1).strip('"\' ')
                else:
                    body = re.sub(
                        r'^(?:type|send|write|compose)\s+(?:a\s+)?(?:message|text|email)?\s*(?:in\s+inbox|to\s+inbox|in\s+whatsapp|in\s+gmail)?\s*',
                        '', q, flags=re.I
                    ).strip('"\' ')

            cls.open_inbox(service=svc, to=to, subject=subject, message=body)
            return True

        # 4. Check Pure Type Text Intent (without Enter)
        type_match = re.search(r'\btype\s+(?:this|text|message)?\s*[:]?\s*["\']?(.+?)["\']?$', q, re.I)
        if type_match:
            text_to_type = type_match.group(1).strip('"\' ')
            if text_to_type:
                cls.type_in_active_window(text_to_type, press_enter=False)
                return True

        return False
