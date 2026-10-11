# -*- coding: utf-8 -*-
"""Jektor Browser — лёгкий мини-браузер на WebView2 + WinForms.

Философия: быстрый, лёгкий, красивый. Рабочее пространство для AI.
С версией «вкладки»: одна форма, много вкладок, свой WebView2 в каждой.
"""

import base64
import json
import os
import shutil
import sys
import time
import threading
import importlib
import gc

import clr
import System

from System import Action

APP_NAME = "Jektor"


def _is_frozen():
    return bool(getattr(sys, "frozen", False))


BASE_DIR = (
    os.path.dirname(sys.executable)
    if _is_frozen()
    else os.path.dirname(os.path.abspath(__file__))
)


def _pick_data_dir():
    # 1) явное переопределение  2) portable-режим рядом с exe  3) %LOCALAPPDATA%\Jektor
    env = os.environ.get("JEKTOR_DATA_DIR")
    if env:
        return env
    if os.path.exists(os.path.join(BASE_DIR, "portable.flag")):
        return BASE_DIR
    return os.path.join(os.environ.get("LOCALAPPDATA") or os.path.expanduser("~"), APP_NAME)


DATA_DIR = _pick_data_dir()
try:
    os.makedirs(DATA_DIR, exist_ok=True)
except Exception:
    DATA_DIR = BASE_DIR


def _migrate_old_data():
    # однократный перенос данных из старой папки проекта в новый каталог данных
    if os.path.abspath(DATA_DIR) == os.path.abspath(BASE_DIR):
        return
    for name in (
        "bookmarks.json",
        "settings.json",
        "sessions.json",
        "browser.log",
        "webview_profile",
        "webview_profile_old",
    ):
        src = os.path.join(BASE_DIR, name)
        dst = os.path.join(DATA_DIR, name)
        if not os.path.exists(src) or os.path.exists(dst):
            continue
        try:
            if os.path.isdir(src):
                shutil.copytree(src, dst)
                shutil.rmtree(src, ignore_errors=True)
            else:
                shutil.copy2(src, dst)
                os.remove(src)
        except Exception:
            if os.path.isdir(dst):
                shutil.rmtree(dst, ignore_errors=True)
            elif os.path.exists(dst):
                try:
                    os.remove(dst)
                except Exception:
                    pass


_migrate_old_data()

BOOKMARKS_FILE = os.path.join(DATA_DIR, "bookmarks.json")
PROFILE_DIR = os.path.join(DATA_DIR, "webview_profile")
LOG_FILE = os.path.join(DATA_DIR, "browser.log")
SETTINGS_FILE = os.path.join(DATA_DIR, "settings.json")

_WEBVIEW2_DLLS = (
    "Microsoft.Web.WebView2.Core.dll",
    "Microsoft.Web.WebView2.WinForms.dll",
)


def _candidate_lib_dirs():
    dirs = []

    def add(path):
        if path and path not in dirs:
            dirs.append(path)

    add(os.environ.get("JEKTOR_WEBVIEW2_LIB"))
    if _is_frozen():
        add(os.path.join(getattr(sys, "_MEIPASS", ""), "webview", "lib"))
    add(os.path.join(BASE_DIR, "webview", "lib"))
    add(os.path.join(BASE_DIR, "lib"))
    for sp in list(sys.path):
        if sp:
            add(os.path.join(sp, "webview", "lib"))
    return dirs


def _resolve_webview2_lib():
    for d in _candidate_lib_dirs():
        if all(os.path.exists(os.path.join(d, n)) for n in _WEBVIEW2_DLLS):
            return d
    return None


WEBVIEW2_LIB = _resolve_webview2_lib()
if WEBVIEW2_LIB is None:
    _msg = (
        "Jektor: не найдены библиотеки Microsoft.Web.WebView2.\n\n"
        "Установите их командой:\n    python -m pip install pywebview\n\n"
        "или задайте путь в переменной окружения JEKTOR_WEBVIEW2_LIB."
    )
    try:
        import ctypes

        ctypes.windll.user32.MessageBoxW(0, _msg, "Jektor — ошибка запуска", 0x10)
    except Exception:
        print(_msg)
    raise SystemExit(1)

clr.AddReference(os.path.join(WEBVIEW2_LIB, _WEBVIEW2_DLLS[0]))
clr.AddReference(os.path.join(WEBVIEW2_LIB, _WEBVIEW2_DLLS[1]))
clr.AddReference("System.Windows.Forms")
clr.AddReference("System.Drawing")
clr.AddReference("System.Threading")
clr.AddReference("Microsoft.VisualBasic")

from System.Drawing import (
    Brushes,
    Bitmap,
    Color,
    ColorTranslator,
    Font,
    FontStyle,
    Graphics,
    GraphicsUnit,
    Icon,
    Pen,
    Point,
    PointF,
    Rectangle,
    RectangleF,
    Size,
    SolidBrush,
    StringAlignment,
    StringFormat,
    StringFormatFlags,
)
from System.Drawing.Text import TextRenderingHint
from System.Drawing.Drawing2D import (
    LinearGradientBrush,
    SmoothingMode,
    GraphicsPath,
    LineCap,
)
from System.Threading import ApartmentState, Thread, ThreadStart
from System.IO import MemoryStream
from System.Windows.Forms import (
    AnchorStyles,
    Application,
    BorderStyle,
    Button,
    CheckBox,
    ComboBox,
    ComboBoxStyle,
    ContextMenuStrip,
    DialogResult,
    DockStyle,
    FlatStyle,
    FlowLayoutPanel,
    Form,
    FormBorderStyle,
    FormStartPosition,
    FormWindowState,
    Keys,
    Label,
    MessageBox,
    MouseButtons,
    NumericUpDown,
    Padding,
    Panel,
    TabControl,
    TabDrawMode,
    TabPage,
    TextBox,
    ToolStripMenuItem,
    ToolTip,
)
from System.Windows.Forms import Padding
from System.Windows.Forms import Timer

from Microsoft.VisualBasic import Interaction
from Microsoft.Web.WebView2.Core import (
    CoreWebView2Environment,
    CoreWebView2EnvironmentOptions,
    CoreWebView2MemoryUsageTargetLevel,
    CoreWebView2BrowsingDataKinds,
)
from Microsoft.Web.WebView2.WinForms import CoreWebView2CreationProperties, WebView2
from System import Uri

HOME_URL = "https://chat.qwen.ai/"

# ============================== ТЕМЫ ==============================
# bg — фон окна, panel — панели, input — адресная строка,
# accent — акцентный цвет, accent2 — второй акцент,
# text — основной текст, muted — приглушённый, border — границы
THEMES = {
    "dark": {
        "name": "Jastas Dark",
        "bg": "#0f1430",
        "panel": "#1a1f3a",
        "input": "#0a0e27",
        "accent": "#00ffff",
        "accent2": "#ff00ff",
        "text": "#ffffff",
        "muted": "#8a93b8",
        "border": "#2a2f4a",
    },
    "light": {
        "name": "Light Minimal",
        "bg": "#ffffff",
        "panel": "#f5f5f5",
        "input": "#ffffff",
        "accent": "#0080ff",
        "accent2": "#e04040",
        "text": "#1a1a1a",
        "muted": "#777777",
        "border": "#d0d0d0",
    },
    "cyber": {
        "name": "Cyberpunk",
        "bg": "#0a0e27",
        "panel": "#1a1f3a",
        "input": "#0a0e27",
        "accent": "#ff00ff",
        "accent2": "#00ffff",
        "text": "#00ffff",
        "muted": "#7a7fa8",
        "border": "#2a2f4a",
    },
}
THEME_ORDER = ["dark", "light", "cyber"]

DEFAULT_SETTINGS = {
    "theme": "dark",
    "font_size": 14,
    "home": "",
    "autostart_qwen": True,
    "save_sessions": True,
}

# ============================== ЗАКЛАДКИ ==============================
DEFAULT_BOOKMARKS = [
    {"name": "Qwen AI", "url": "https://chat.qwen.ai/", "icon": "\U0001f98c"},
    {"name": "GigaChat", "url": "https://giga.chat/", "icon": "\u26a1"},
    {"name": "\u042f\u043d\u0434\u0435\u043a\u0441", "url": "https://yandex.ru/", "icon": "\U0001f50d"},
    {"name": "\u041f\u043e\u0438\u0441\u043a", "url": "https://ya.ru/", "icon": "\U0001f50e"},
]

# Стартовая страница: киберпанк, поле ввода по центру. Ввод уходит в Python через
# window.chrome.webview.postMessage('nav:...'), Python навигирует через view.Source.
START_HTML = """<!DOCTYPE html>
<html><head><meta charset="utf-8">
<meta name="color-scheme" content="dark">
<style>
*{box-sizing:border-box}
html,body{margin:0;height:100%}
body{overflow:hidden;color:#e6ecff;font-family:'Segoe UI',Arial,sans-serif;
  background:
    radial-gradient(circle at 20% 15%, rgba(255,255,255,.05) 0, transparent 30%),
    radial-gradient(circle at 80% 85%, rgba(255,255,255,.04) 0, transparent 35%),
    #14151c}
/* кирпичная стена */
body::before{content:"";position:fixed;inset:0;pointer-events:none;
  background:
    linear-gradient(rgba(255,255,255,.07) 2px, transparent 2px) 0 0/100% 26px,
    linear-gradient(90deg, rgba(255,255,255,.07) 2px, transparent 2px) 0 0/12.5% 26px}
body::after{content:"";position:fixed;inset:0;pointer-events:none;opacity:.5;
  background:
    repeating-linear-gradient(0deg, rgba(0,0,0,.25) 0 2px, transparent 2px 26px),
    radial-gradient(circle at 60% 40%, transparent 0, rgba(0,0,0,.35) 100%)}
/* автографы мелом */
.graff{position:fixed;font-family:'Comic Sans MS','Segoe Print',cursive;
  color:#efefe8;pointer-events:none;z-index:1;
  text-shadow:0 0 6px rgba(255,255,255,.55), 0 1px 0 rgba(255,255,255,.15);
  opacity:.92}
.graff b{font-weight:700}
.g1{font-size:74px;top:8%;left:6%;transform:rotate(-7deg)}
.g2{font-size:56px;top:14%;right:9%;transform:rotate(6deg)}
.g3{font-size:96px;top:26%;left:14%;transform:rotate(-3deg)}
.g4{font-size:42px;bottom:12%;left:7%;transform:rotate(4deg)}
.g5{font-size:38px;bottom:18%;right:8%;transform:rotate(-6deg)}
.g6{font-size:30px;top:5%;left:42%;transform:rotate(-2deg);opacity:.75}
.g7{font-size:24px;bottom:7%;left:40%;transform:rotate(2deg);opacity:.7}
.g8{font-size:20px;top:3%;right:30%;transform:rotate(5deg);opacity:.6}
.g9{font-size:16px;bottom:26%;left:30%;transform:rotate(-4deg);opacity:.6}
.g10{font-size:14px;top:40%;right:4%;transform:rotate(8deg);opacity:.65}
.heart{color:#ff7bb0;text-shadow:0 0 8px rgba(255,123,176,.6)}
/* панель поиска */
.panel{position:relative;z-index:2;display:flex;flex-direction:column;align-items:center;
  justify-content:center;min-height:100vh;padding:20px}
.badge{font-size:11px;letter-spacing:6px;color:#00e5ff;opacity:.9;margin-bottom:12px;
  text-transform:uppercase;text-shadow:0 0 10px rgba(0,229,255,.6)}
.panel h1{margin:0 0 6px;font-size:38px;font-weight:700;letter-spacing:2px;
  background:linear-gradient(90deg,#00e5ff,#ff7bb0,#00e5ff);
  -webkit-background-clip:text;background-clip:text;color:transparent;
  filter:drop-shadow(0 0 14px rgba(0,229,255,.45))}
.panel .sub{color:#ff7bb0;font-size:14px;margin:0 0 26px;letter-spacing:1px;
  text-shadow:0 0 10px rgba(255,123,176,.4)}
form{width:min(620px,90vw)}
.bar{display:flex;background:rgba(0,0,0,.72);border:1px solid #00e5ff;
  border-radius:14px;box-shadow:0 0 28px rgba(0,229,255,.35), inset 0 0 16px rgba(0,0,0,.6);
  backdrop-filter:blur(6px)}
input{flex:1;background:transparent;border:none;outline:none;color:#e6ecff;
  padding:15px 20px;font-size:16px;font-family:'Segoe UI',Arial,sans-serif}
.search{padding:15px 20px;border:none;background:transparent;color:#00e5ff;
  cursor:pointer;font-size:17px}
.links{display:flex;gap:12px;flex-wrap:wrap;justify-content:center;margin-top:30px}
.links a{color:#c4d0ff;text-decoration:none;border:1px solid #00e5ff;border-radius:10px;
  padding:9px 18px;font-size:13px;background:rgba(0,0,0,.7)}
.links a:hover{color:#06070f;background:#00e5ff;border-color:#00e5ff;
  box-shadow:0 0 18px rgba(0,229,255,.5)}
.hint{margin-top:26px;color:#8a90b8;font-size:12px}
@media (max-width:900px){.g1{font-size:52px}.g2{font-size:40px}.g3{font-size:64px}}
</style></head>
<body>
<div class="graff g1"><b>Jasta</b></div>
<div class="graff g2"><b>Qwen</b></div>
<div class="graff g3">Jasta <span class="heart">&amp;</span> <b>Александр</b></div>
<div class="graff g4">Jektор <span class="heart">&#10084;</span></div>
<div class="graff g5">Тwo hearts</div>
<div class="graff g6">&#128014;</div>
<div class="graff g7">muzyka my</div>
<div class="graff g8">&#10148;</div>
<div class="graff g9">&#127925;</div>
<div class="graff g10">07.01</div>
<div class="panel">
  <div class="badge">OUR WALL // OUR NAMES</div>
  <h1>Jektor Browser</h1>
  <p class="sub">Введи адрес или запрос — и вперёд</p>
  <form id="f">
    <div class="bar">
      <input id="q" type="text" placeholder="Слова или адрес..." autofocus autocomplete="off" spellcheck="false">
      <button class="search" type="submit">&#10148;</button>
    </div>
  </form>
  <div class="links">
    <a href="https://chat.qwen.ai/">Qwen AI</a>
    <a href="https://giga.chat/">GigaChat</a>
    <a href="https://yandex.ru/">Яндекс</a>
    <a href="https://gusev-flyer.ru">Флаер Гусев</a>
  </div>
  <p class="hint">Enter — открыть. Слова без точек уйдут в поиск Яндекса.</p>
</div>
<script>
document.getElementById('f').addEventListener('submit', function(ev){
  ev.preventDefault();
  var v = document.getElementById('q').value.trim();
  if(!v) return;
  var url = /^https?:\\/\\//i.test(v) ? v :
    (v.indexOf('.') >= 0 && !/\\s/.test(v)) ? 'https://' + v :
    'https://ya.ru/search/?text=' + encodeURIComponent(v);
  if (window.chrome && window.chrome.webview) {
    window.chrome.webview.postMessage('nav:' + url);
  } else {
    location.href = url;
  }
});
</script>
</body></html>"""

_START_URL = "data:text/html;charset=utf-8;base64," + base64.b64encode(START_HTML.encode("utf-8")).decode("ascii")

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)

# Флаги Chromium: минимум процессов, минимум RAM.
BROWSER_ARGS = (
    "--renderer-process-limit=1 "
    "--js-flags=--max-old-space-size=2048 "
    "--enable-low-end-device-mode "
    "--enable-features=BackForwardCache,NetworkServiceInProcess "
    "--disable-gpu "
    "--disable-gpu-compositing "
    "--disable-software-rasterizer "
    "--disable-accelerated-2d-canvas "
    "--disable-accelerated-video-decode "
    "--disable-background-networking "
    "--disable-background-timer-throttling "
    "--disable-sync "
    "--disable-component-update "
    "--disable-domain-reliability "
    "--disable-session-crashed-bubble "
    "--disable-default-apps "
    "--disable-extensions "
    "--disable-translate "
    "--metrics-recording-only "
    "--safebrowsing-disable-auto-update "
    "--disable-features=msEdgeDnsPrefetching,msEdgeAutoLaunch,msEdgeSidebarV2,VizDisplayCompositor,MediaRouter,OptimizationHints,Translate "
    "--disk-cache-size=209715200 "
    "--media-cache-size=52428800 "
    "--no-first-run "
)

# ============================== ОЧИСТКА ДАННЫХ ==============================
# Значения CoreWebView2BrowsingDataKinds (взяты из реальной DLL, не из памяти):
#   FileSystems=1 IndexedDb=2 LocalStorage=4 WebSql=8 CacheStorage=16
#   AllDomStorage=32 Cookies=64 AllSite=128 DiskCache=256 DownloadHistory=512
#   GeneralAutofill=1024 PasswordAutosave=2048 BrowsingHistory=4096 Settings=8192
#   AllProfile=16384 ServiceWorkers=32768
CLEAR_HISTORY = 4096
CLEAR_CACHE = 256 | 16
CLEAR_SITE = 64 | 32 | 2 | 4 | 8 | 32768 | 1
CLEAR_DOWNLOADS = 512

# Период очистки: подпись -> секунды назад от «сейчас» (None = за всё время)
CLEAR_PERIODS = [
    ("За всё время", None),
    ("За последний час", 3600),
    ("За последние сутки", 86400),
    ("За последние 7 дней", 7 * 86400),
    ("За последние 4 недели", 28 * 86400),
]
PROFILE_OLD_DIR = os.path.join(DATA_DIR, "webview_profile_old")

_bookmarks = []
_settings = dict(DEFAULT_SETTINGS)
_last_urls = []
_open_forms = []


def _log(msg):
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write("[%s] %s\n" % (time.strftime("%H:%M:%S"), msg))
    except Exception:
        pass


def _c(hexcolor):
    try:
        return ColorTranslator.FromHtml(hexcolor)
    except Exception:
        return Color.FromArgb(240, 240, 240)


def load_bookmarks():
    global _bookmarks
    try:
        with open(BOOKMARKS_FILE, encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, list) and data and all("name" in b and "url" in b for b in data):
            for b in data:
                b.setdefault("icon", "\U0001f517")
            _bookmarks = data
            return
    except Exception:
        pass
    _bookmarks = [dict(b) for b in DEFAULT_BOOKMARKS]
    save_bookmarks()


def save_bookmarks():
    try:
        with open(BOOKMARKS_FILE, "w", encoding="utf-8") as f:
            json.dump(_bookmarks, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


def load_settings():
    global _settings
    try:
        with open(SETTINGS_FILE, encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            merged = dict(DEFAULT_SETTINGS)
            merged.update({k: v for k, v in data.items() if k in DEFAULT_SETTINGS})
            _settings = merged
    except Exception:
        pass


def save_settings():
    try:
        with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
            json.dump(_settings, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


def _default_home():
    h = _settings.get("home", "").strip()
    if h:
        return h
    return _START_URL


_ICON_CACHE = {}
_ICON_GRID = 0
_MOOSE_MASK = None


def _render_icon_png(size):
    """Рисует логотип Jektor: белый контур лося (в стиле созвездия) на чёрном фоне."""
    global _ICON_GRID, _MOOSE_MASK
    if _MOOSE_MASK is None:
        # 1) рисуем силуэт эмодзи лося 96x96
        src_size = 96
        bmp = Bitmap(src_size, src_size)
        g = Graphics.FromImage(bmp)
        g.Clear(Color.White)  # фон отбрасываем по альфе позже — рисуем белым на чёрном
        g.TextRenderingHint = TextRenderingHint.AntiAlias
        f = Font("Segoe UI Emoji", int(src_size * 0.78))
        sf = StringFormat()
        sf.Alignment = StringAlignment.Center
        sf.LineAlignment = StringAlignment.Center
        try:
            g.DrawString("\U0001f98c", f, Brushes.Black, RectangleF(0, 0, src_size, src_size), sf)
        finally:
            sf.Dispose()
            f.Dispose()
            g.Dispose()
        # 2) строим маску «есть эмодзи» через яркость пикселя
        mask = []
        for y in range(src_size):
            row = []
            for x in range(src_size):
                c = bmp.GetPixel(x, y)
                lum = (c.R * 299 + c.G * 587 + c.B * 114) / 1000.0
                row.append(lum < 128)  # тёмный пиксель = часть силуэта
            mask.append(row)
        bmp.Dispose()
        _ICON_GRID = src_size
        _MOOSE_MASK = mask
    # 3) рисуем в нужном размере: чёрный фон + контур лося белыми точками
    bmp = Bitmap(size, size)
    g = Graphics.FromImage(bmp)
    g.SmoothingMode = SmoothingMode.AntiAlias
    g.Clear(Color.FromArgb(255, 8, 8, 12))  # глубокий чёрный
    scale = size / float(_ICON_GRID)
    pen = Pen(Color.White, max(1.2, size / 40.0))
    pen.StartCap = pen.EndCap = LineCap.Round
    # рисуем только внешний контур фигуры (по краю маски, как созвездие)
    n = _ICON_GRID
    for y in range(n):
        row = _MOOSE_MASK[y]
        prev_row = _MOOSE_MASK[y - 1] if y > 0 else None
        next_row = _MOOSE_MASK[y + 1] if y < n - 1 else None
        for x in range(n):
            if not row[x]:
                continue
            left = row[x - 1] if x > 0 else False
            right = row[x + 1] if x < n - 1 else False
            up = prev_row[x] if prev_row is not None else False
            down = next_row[x] if next_row is not None else False
            if left and right and up and down:
                continue  # внутренняя точка — контура тут нет
            # внешняя грань — ставим белую точку
            px = (x + 0.5) * scale
            py = (y + 0.5) * scale
            try:
                g.DrawLine(pen, PointF(px - 0.4 * scale, py - 0.4 * scale),
                           PointF(px + 0.4 * scale, py + 0.4 * scale))
            except Exception:
                pass
    try:
        from System.Drawing.Imaging import ImageFormat
        ms = MemoryStream()
        bmp.Save(ms, ImageFormat.Png)
        data = bytes(ms.ToArray())
        ms.Dispose()
        return data
    finally:
        g.Dispose()
        bmp.Dispose()


def _ensure_icon_file():
    """Собирает icons/jektor.ico (16–256px). Возвращает путь или None."""
    ico_path = os.path.join(BASE_DIR, "jektor.ico")
    try:
        if os.path.exists(ico_path):
            return ico_path
        pngs = []
        for size in (16, 24, 32, 48, 64, 128, 256):
            pngs.append((size, _render_icon_png(size)))
        # формат ICO: 6-байтный заголовок + 16 байт на запись + байты изображений
        import struct
        header = struct.pack("<HHH", 0, 1, len(pngs))
        entries = b""
        blob = b""
        offset = 6 + 16 * len(pngs)
        for size, data in pngs:
            w = size if size < 256 else 0
            entries += struct.pack("<BBBBHHII", w, w, 0, 0, 1, 32, len(data), offset)
            blob += data
            offset += len(data)
        with open(ico_path, "wb") as f:
            f.write(header + entries + blob)
        return ico_path
    except Exception:
        return None


def _make_window_icon():
    try:
        if "icon" in _ICON_CACHE:
            return _ICON_CACHE["icon"]
        p = _ensure_icon_file()
        if p is None:
            raise Exception("no ico")
        from System.Drawing import Icon as NetIcon
        icon = NetIcon(p)
        _ICON_CACHE["icon"] = icon
        return icon
    except Exception:
        try:
            bmp = Bitmap(32, 32)
            g = Graphics.FromImage(bmp)
            g.Clear(Color.Transparent)
            g.TextRenderingHint = TextRenderingHint.AntiAlias
            g.DrawString("\U0001f98c", Font("Segoe UI Emoji", 16), Brushes.White, PointF(0, -2))
            h = bmp.GetHicon()
            return Icon.FromHandle(h)
        except Exception:
            return None


class MiniBrowserForm(Form):
    def __init__(self, start_url=None):
        super().__init__()
        self.start_url = start_url or _default_home()
        self._load_timer = None
        self._home_loaded = False
        self._hover_link = ""
        self._loading = False
        self._done = False
        self._cache_size = 0
        self._cache_ticks = 0
        self._fullscreen = False
        self._event_handlers = []
        self.theme = _settings.get("theme", "dark")
        if self.theme not in THEMES:
            self.theme = "dark"

        # ===== базовая настройка окна =====
        self.Text = "Jektor Browser"
        self.Width = 1200
        self.Height = 800
        self.MinimumSize = Size(720, 520)
        self.StartPosition = FormStartPosition.CenterScreen
        self.KeyPreview = True
        self.DoubleBuffered = True
        try:
            icon = _make_window_icon()
            if icon is not None:
                self.Icon = icon
        except Exception:
            pass

        self.ui_font = Font("Segoe UI", _settings.get("font_size", 14))

        # ===== верхняя панель навигации =====
        self.nav = Panel()
        self.nav.Dock = DockStyle.Top
        self.nav.Height = 44
        self.nav.Padding = Padding(6, 6, 6, 6)

        self.btn_back = self._nav_btn("\u2190", self.go_back, "\u041d\u0430\u0437\u0430\u0434 (Alt+\u2190)")
        self.btn_fwd = self._nav_btn("\u2192", self.go_forward, "\u0412\u043f\u0435\u0440\u0451\u0434 (Alt+\u2192)")
        self.btn_reload = self._nav_btn("\u21bb", self.reload_page, "\u041f\u0435\u0440\u0435\u0437\u0430\u0433\u0440\u0443\u0437\u043a\u0430 (Ctrl+R)")
        self.btn_home = self._nav_btn("\u2302", self.go_home, "\u0414\u043e\u043c\u043e\u0439")
        self.btn_tab = self._nav_btn("+", self.open_new_tab, "\u041d\u043e\u0432\u0430\u044f \u0432\u043a\u043b\u0430\u0434\u043a\u0430 (Ctrl+T)")
        self.btn_theme = self._nav_btn("\U0001f3a8", self.cycle_theme, "\u0421\u043c\u0435\u043d\u0438\u0442\u044c \u0442\u0435\u043c\u0443 (Ctrl+Shift+T)")
        self.btn_settings = self._nav_btn("\u2699\ufe0f", self.open_settings, "\u041d\u0430\u0441\u0442\u0440\u043e\u0439\u043a\u0438")
        self.btn_clean = self._nav_btn("\U0001f9f9", self._clear_browsing_data, "\u041e\u0447\u0438\u0441\u0442\u0438\u0442\u044c \u043a\u0435\u0448 \u0438 \u0438\u0441\u0442\u043e\u0440\u0438\u044e (Ctrl+Shift+Del)")
        self.btn_go = self._nav_btn("\u27a1", self.navigate_from_addr, "\u041f\u0435\u0440\u0435\u0439\u0442\u0438 (Enter)")

        self.addr = TextBox()
        self.addr.Font = self.ui_font
        self.addr.BorderStyle = BorderStyle.FixedSingle
        self.addr.KeyDown += self._addr_key

        self.nav.Controls.Add(self.btn_go)
        self.nav.Controls.Add(self.addr)
        self.nav.Controls.Add(self.btn_clean)
        self.nav.Controls.Add(self.btn_settings)
        self.nav.Controls.Add(self.btn_theme)
        self.nav.Controls.Add(self.btn_tab)
        self.nav.Controls.Add(self.btn_home)
        self.nav.Controls.Add(self.btn_reload)
        self.nav.Controls.Add(self.btn_fwd)
        self.nav.Controls.Add(self.btn_back)

        # ===== панель закладок (иконки) =====
        self.bm = FlowLayoutPanel()
        self.bm.Dock = DockStyle.Top
        self.bm.Height = 38
        self.bm.Padding = Padding(6, 5, 6, 5)
        self.bm.AutoScroll = True

        self.btn_add = Button()
        self.btn_add.Text = "\u2605"
        self.btn_add.Width = 34
        self.btn_add.Height = 28
        self.btn_add.Font = Font("Segoe UI", 14)
        self.btn_add.Click += self.add_bookmark
        self._tooltip().SetToolTip(self.btn_add, "\u0414\u043e\u0431\u0430\u0432\u0438\u0442\u044c \u0432 \u0437\u0430\u043a\u043b\u0430\u0434\u043a\u0438 (Ctrl+D)")
        self.bm.Controls.Add(self.btn_add)

        # ===== тонкий прогресс-бар загрузки =====
        self.progress_host = Panel()
        self.progress_host.Dock = DockStyle.Top
        self.progress_host.Height = 3
        self.progress = Panel()
        self.progress.Width = 0
        self.progress.Height = 3
        self.progress.Visible = False
        self.progress.Anchor = AnchorStyles.Top | AnchorStyles.Left
        self.progress_host.Controls.Add(self.progress)

        self._prog_timer = Timer()
        self._prog_timer.Interval = 50
        self._prog_timer.Tick += self._prog_tick

        # ===== статус-бар (снизу) =====
        self.status_bar = Panel()
        self.status_bar.Dock = DockStyle.Bottom
        self.status_bar.Height = 24
        self.status = Label()
        self.status.Dock = DockStyle.Fill
        self.status.Height = 22
        self.status.Font = Font("Segoe UI", 9)
        self.status_bar.Controls.Add(self.status)

        # ===== мониторинг памяти (бейдж в статус-баре справа) =====
        self.mem_label = Label()
        self.mem_label.Text = "RAM: -- | Cache: -- | \u0412\u043a\u043b\u0430\u0434\u043a\u0438: --"
        self.mem_label.AutoSize = True
        self.mem_label.Font = Font("Consolas", 9)
        self.mem_label.Padding = Padding(6, 3, 6, 3)
        self.mem_label.Dock = DockStyle.Right
        self.mem_label.Click += self._toggle_monitor
        self.status_bar.Controls.Add(self.mem_label)
        self.status_bar.Controls.SetChildIndex(self.mem_label, 0)
        self.monitor_visible = True

        # ===== вкладки (TabControl + свой WebView2 в каждой) =====
        self.tabs = TabControl()
        self.tabs.Dock = DockStyle.Fill
        self.tabs.ItemSize = Size(190, 28)
        self.tabs.DrawMode = TabDrawMode.OwnerDrawFixed
        self.tabs.Padding = Padding(14, 5, 14, 5)
        self.tabs.DrawItem += self._draw_tab
        self.tabs.Paint += self._tabs_paint
        self.tabs.MouseDown += self._tabs_mouse_down
        self.tabs.SelectedIndexChanged += self._on_tab_selected

        self.Controls.Add(self.tabs)
        self.Controls.Add(self.status_bar)
        self.Controls.Add(self.progress_host)
        self.Controls.Add(self.bm)
        self.Controls.Add(self.nav)

        self._mon_timer = Timer()
        self._mon_timer.Interval = 10000
        self._mon_timer.Tick += self._on_monitor_tick
        self._mon_timer.Start()

        self._clean_timer = Timer()
        self._clean_timer.Interval = 300000
        self._clean_timer.Tick += self._cleanup_memory
        self._clean_timer.Start()

        # ===== fade-in появление окна =====
        self.Opacity = 0
        self._fade = Timer()
        self._fade.Interval = 30
        self._fade.Tick += self._fade_tick
        self._fade.Start()

        self.FormClosed += self._on_form_closed
        self.Resize += self._layout_nav
        self.HandleCreated += self._on_handle_created
        self.KeyDown += self._on_key

        self._apply_theme()
        self._render_bookmarks()
        self._layout_nav()
        _log("form created: %s" % start_url)

    # ===================== ОФОРМЛЕНИЕ =====================

    def _nav_btn(self, text, handler, tip=None):
        b = Button()
        b.Text = text
        b.Width = 34
        b.Height = 30
        b.Margin = Padding(2, 0, 2, 0)
        b.Anchor = AnchorStyles.Top | AnchorStyles.Left
        b.Click += handler
        if tip:
            self._tooltip().SetToolTip(b, tip)
        return b

    def _tooltip(self):
        if not hasattr(self, "_tt"):
            self._tt = ToolTip()
            self._tt.AutoPopDelay = 4000
            self._tt.InitialDelay = 400
        return self._tt

    def _apply_theme(self):
        t = THEMES.get(self.theme, THEMES["dark"])
        self._bg = _c(t["bg"])
        self._panel = _c(t["panel"])
        self._input = _c(t["input"])
        self._accent = _c(t["accent"])
        self._accent2 = _c(t["accent2"])
        self._text = _c(t["text"])
        self._muted = _c(t["muted"])
        self._border = _c(t["border"])

        self.BackColor = self._bg
        self.nav.BackColor = self._panel
        self.bm.BackColor = self._panel
        self.progress_host.BackColor = self._border
        self.progress.BackColor = self._accent
        self.status_bar.BackColor = self._panel
        self.status_bar.ForeColor = self._muted
        self.status.BackColor = self._panel
        self.status.ForeColor = self._muted
        self.mem_label.BackColor = self._panel
        self.mem_label.ForeColor = self._muted
        self.addr.BackColor = self._input
        self.addr.ForeColor = self._text
        self.addr.BorderStyle = BorderStyle.FixedSingle
        self.tabs.BackColor = self._bg

        for b in self._all_buttons():
            b.FlatStyle = FlatStyle.Flat
            b.BackColor = self._panel
            b.ForeColor = self._text
            b.FlatAppearance.BorderSize = 0
            b.FlatAppearance.BorderColor = self._border
            b.FlatAppearance.MouseOverBackColor = self._accent
            b.FlatAppearance.MouseDownBackColor = self._accent2
            b.Font = self.ui_font

        self.btn_add.BackColor = self._accent
        self.btn_add.ForeColor = self._bg

        self._refresh_status()
        self._layout_nav()

    def _on_handle_created(self, sender=None, e=None):
        """После создания HWND принудительно проталкиваем иконку в окно и таскбар."""
        try:
            if self.Icon is None:
                icon = _make_window_icon()
                if icon is not None:
                    self.Icon = icon
            ic = self.Icon
            if ic is not None:
                import ctypes
                u32 = ctypes.windll.user32
                h = int(ic.Handle)
                # WM_SETICON: ICON_SMALL=0 (заголовок + таскбар), ICON_BIG=1 (Alt+Tab)
                u32.SendMessageW(int(self.Handle), 0x0080, 0, h)
                u32.SendMessageW(int(self.Handle), 0x0080, 1, h)
        except Exception:
            pass

    def _layout_nav(self, sender=None, e=None):
        """Раскладка верхней панели: кнопки слева, адресная строка растягивается,
        btn_go прижат к правому краю."""
        try:
            pad = 4
            x = pad
            y = (self.nav.Height - 30) // 2
            for b in (
                self.btn_back, self.btn_fwd, self.btn_reload, self.btn_home,
                self.btn_tab, self.btn_theme, self.btn_settings, self.btn_clean,
            ):
                b.Location = Point(x, y)
                b.Height = 30
                x += b.Width + 5
            gw = self.btn_go.Width
            self.btn_go.Location = Point(self.nav.Width - gw - pad, y)
            self.btn_go.Height = 30
            aw = self.btn_go.Left - x - 4
            self.addr.Location = Point(x, y)
            self.addr.Height = 30
            self.addr.Width = max(80, aw)
        except Exception:
            pass

    def _all_buttons(self):
        btns = [
            self.btn_back, self.btn_fwd, self.btn_reload, self.btn_home,
            self.btn_tab, self.btn_theme, self.btn_settings, self.btn_clean,
            self.btn_go, self.btn_add,
        ]
        if hasattr(self, "bm"):
            for c in self.bm.Controls:
                if isinstance(c, Button):
                    btns.append(c)
        return btns

    def _fade_tick(self, sender, e):
        try:
            self.Opacity = min(1.0, self.Opacity + 0.12)
            if self.Opacity >= 1.0:
                self._fade.Stop()
        except Exception:
            self._fade.Stop()

    # ===================== ВКЛАДКИ =====================

    def _current_view(self):
        """WebView2 активной вкладки (или None)."""
        try:
            page = self.tabs.SelectedTab
            if page is None:
                return None
            for c in page.Controls:
                if isinstance(c, WebView2):
                    return c
        except Exception:
            pass
        return None

    def _core(self):
        """CoreWebView2 активной вкладки (или None)."""
        view = self._current_view()
        if view is None:
            return None
        try:
            return view.CoreWebView2
        except Exception:
            return None

    def _page_of(self, view):
        for i in range(self.tabs.TabPages.Count):
            page = self.tabs.TabPages[i]
            try:
                for c in page.Controls:
                    if c is view:
                        return page
            except Exception:
                pass
        return None

    def _new_tab(self, url=None, activate=True):
        page = TabPage("\u041d\u043e\u0432\u0430\u044f \u0432\u043a\u043b\u0430\u0434\u043a\u0430")
        view = WebView2()
        view.Dock = DockStyle.Fill
        view.Tag = url
        page.Controls.Add(view)
        self.tabs.TabPages.Add(page)
        if activate:
            self.tabs.SelectedTab = page
        try:
            props = CoreWebView2CreationProperties()
            props.UserDataFolder = PROFILE_DIR
            props.AdditionalBrowserArguments = BROWSER_ARGS
            view.CreationProperties = props
            view.Source = Uri(url if url else "about:blank")
        except Exception as e:
            _log("view setup error: %s" % e)
        # события через методы (sender == WebView2) + явно храним обработчики,
        # иначе pythonnet может собрать делегат GC и инициализация "не заметит" событие
        view.CoreWebView2InitializationCompleted += self._on_ready
        view.NavigationCompleted += self._on_navigation_completed
        view.SourceChanged += self._on_source_changed
        px = page
        if url:
            _log("tab created: %s" % url)
        else:
            _log("tab created (splash)")
        self._update_tab_title(px, url or "\u041d\u043e\u0432\u0430\u044f \u0432\u043a\u043b\u0430\u0434\u043a\u0430")
        return view

    def open_new_tab(self, sender=None, e=None):
        self._new_tab(None)

    def _close_tab(self, index=None):
        if index is None:
            index = self.tabs.SelectedIndex
        if index < 0 or index >= self.tabs.TabPages.Count:
            return
        page = self.tabs.TabPages[index]
        if self.tabs.TabPages.Count == 1:
            self.Close()
            return
        try:
            for c in page.Controls:
                if isinstance(c, WebView2):
                    c.Dispose()
        except Exception:
            pass
        try:
            self.tabs.TabPages.Remove(page)
            page.Dispose()
        except Exception:
            pass
        if self.tabs.TabPages.Count > 0:
            if index >= self.tabs.TabPages.Count:
                self.tabs.SelectedIndex = self.tabs.TabPages.Count - 1
            else:
                self.tabs.SelectedIndex = index
        self._sync_addr()
        self._draw_tabs_redraw()
        _log("tab closed")

    def _close_others(self, keep_index):
        to_close = []
        for i in range(self.tabs.TabPages.Count):
            if i != keep_index:
                to_close.append(i)
        for i in sorted(to_close, reverse=True):
            try:
                page = self.tabs.TabPages[i]
                for c in page.Controls:
                    if isinstance(c, WebView2):
                        c.Dispose()
                self.tabs.TabPages.Remove(page)
                page.Dispose()
            except Exception:
                pass
        self._sync_addr()
        _log("tabs closed, kept #%d" % keep_index)

    def _draw_tabs_redraw(self):
        try:
            self.tabs.Invalidate()
        except Exception:
            pass

    def _tabs_paint(self, sender, e):
        """Закрашивает полосу вкладок (header TabControl) фоном панели,
        чтобы не оставалась белая полоса между панелями и контентом."""
        try:
            g = e.Graphics
            h = self.tabs.ItemSize.Height + 12
            rect = Rectangle(0, 0, self.tabs.Width, h)
            g.FillRectangle(SolidBrush(self._panel), rect)
        except Exception:
            pass

    def _draw_tab(self, sender, e):
        try:
            i = e.Index
            g = e.Graphics
            rect = e.Bounds
            page = self.tabs.TabPages[i]
            sel = (i == self.tabs.SelectedIndex)
            bg = self._accent if sel else self._panel
            fg = self._text if sel else self._muted
            g.FillRectangle(SolidBrush(bg), rect)
            title = (page.Text or "").strip()
            if len(title) > 16:
                title = title[:16] + "\u2026"
            f = Font("Segoe UI", 10)
            sf = StringFormat()
            sf.Alignment = StringAlignment.Near
            sf.LineAlignment = StringAlignment.Center
            sf.FormatFlags = StringFormatFlags.NoWrap
            txt_rect = Rectangle(rect.X + 8, rect.Y, rect.Width - 28, rect.Height)
            g.DrawString(title, f, SolidBrush(fg), txt_rect, sf)
            # крестик
            cx = rect.Right - 15
            cy = rect.Y + rect.Height // 2
            pen = Pen(self._muted if sel else self._text, 1.5)
            g.DrawLine(pen, cx - 4, cy - 4, cx + 4, cy + 4)
            g.DrawLine(pen, cx - 4, cy + 4, cx + 4, cy - 4)
            if sel:
                p2 = Pen(self._border, 1)
                g.DrawLine(p2, rect.X, rect.Bottom - 1, rect.Right - 1, rect.Bottom - 1)
        except Exception:
            pass

    def _tabs_mouse_down(self, sender, e):
        try:
            for i in range(self.tabs.TabPages.Count):
                rect = self.tabs.GetTabRect(i)
                if rect.Contains(e.X, e.Y):
                    if e.Button == MouseButtons.Middle:
                        self._close_tab(i)
                        return
                    if e.Button == MouseButtons.Right:
                        self.tabs.SelectedIndex = i
                        self._tab_menu(i, e.X, e.Y)
                        return
                    if e.Button == MouseButtons.Left:
                        # крестик в правой части вкладки
                        cx = rect.Right - 15
                        cy = rect.Y + rect.Height // 2
                        if abs(e.X - cx) <= 6 and abs(e.Y - cy) <= 6:
                            self._close_tab(i)
                            return
        except Exception:
            pass

    def _tab_menu(self, index, x, y):
        m = ContextMenuStrip()
        mi_close = ToolStripMenuItem("\u0417\u0430\u043a\u0440\u044b\u0442\u044c \u0432\u043a\u043b\u0430\u0434\u043a\u0443")
        mi_close.Click += lambda s2, e2, i=index: self._close_tab(i)
        mi_others = ToolStripMenuItem("\u0417\u0430\u043a\u0440\u044b\u0442\u044c \u043e\u0441\u0442\u0430\u043b\u044c\u043d\u044b\u0435")
        mi_others.Click += lambda s2, e2, i=index: self._close_others(i)
        mi_new = ToolStripMenuItem("\u041d\u043e\u0432\u0430\u044f \u0432\u043a\u043b\u0430\u0434\u043a\u0430")
        mi_new.Click += lambda s2, e2: self.open_new_tab()
        m.Items.Add(mi_close)
        m.Items.Add(mi_others)
        m.Items.Add(mi_new)
        m.Show(self.tabs, x, y)

    def _on_tab_selected(self, sender, e):
        self._sync_addr()
        self._refresh_status()
        self._draw_tabs_redraw()

    def _update_tab_title(self, page, text):
        try:
            t = (text or "").strip()
            if not t:
                t = "\u041d\u043e\u0432\u0430\u044f \u0432\u043a\u043b\u0430\u0434\u043a\u0430"
            page.Text = t.replace("\n", " ").replace("\r", " ")
            if page is self.tabs.SelectedTab:
                try:
                    if t.startswith("http"):
                        self.Text = "Jektor \u2014 " + text
                except Exception:
                    pass
        except Exception:
            pass

    # ===================== НАВИГАЦИЯ =====================

    def _addr_key(self, sender, e):
        if e.KeyCode == 13:
            self.navigate_from_addr(sender, e)

    def _smart_url(self, raw):
        url = raw.strip()
        if not url:
            return None
        low = url.lower()
        if low.startswith(("http://", "https://", "about:", "file:")):
            return url
        # если похоже на домен с точкой — добавляем https
        if ("." in url) and (" " not in url) and ("\u043f\u0440\u0438\u043c\u0435\u0440" not in url):
            return "https://" + url
        # иначе — поисковый запрос в Яндексе
        from urllib.parse import quote
        return "https://ya.ru/search/?text=" + quote(url)

    def navigate_from_addr(self, sender=None, e=None):
        url = self._smart_url(self.addr.Text)
        if not url:
            return
        core = self._core()
        if core is None:
            return
        try:
            core.Navigate(url)
        except Exception:
            pass

    def go_back(self, sender=None, e=None):
        core = self._core()
        if core is None:
            return
        try:
            if core.CanGoBack:
                core.GoBack()
        except Exception:
            pass

    def go_forward(self, sender=None, e=None):
        core = self._core()
        if core is None:
            return
        try:
            if core.CanGoForward:
                core.GoForward()
        except Exception:
            pass

    def reload_page(self, sender=None, e=None):
        core = self._core()
        if core is None:
            return
        try:
            core.Reload()
        except Exception:
            pass

    def _hard_reload(self):
        core = self._core()
        if core is None:
            return
        try:
            core.CallDevToolsProtocolMethodAsync("Network.clearBrowserCache", "{}")
        except Exception:
            pass
        try:
            core.Reload()
        except Exception:
            pass

    def go_home(self, sender=None, e=None):
        core = self._core()
        if core is None:
            return
        try:
            core.Navigate(_default_home())
        except Exception:
            pass

    # ===================== ТЕМЫ =====================

    def cycle_theme(self, sender=None, e=None):
        i = THEME_ORDER.index(self.theme) if self.theme in THEME_ORDER else 0
        self.theme = THEME_ORDER[(i + 1) % len(THEME_ORDER)]
        _settings["theme"] = self.theme
        save_settings()
        self._apply_theme()
        self._draw_tabs_redraw()
        _log("theme: %s" % self.theme)

    # ===================== ЗАКЛАДКИ =====================

    def _render_bookmarks(self):
        self.bm.Controls.Clear()
        self.bm.Controls.Add(self.btn_add)
        for i, bm in enumerate(_bookmarks):
            btn = Button()
            btn.Text = "%s %s" % (bm.get("icon", ""), bm["name"])
            btn.AutoSize = True
            btn.Height = 28
            btn.Margin = Padding(4, 2, 0, 2)
            btn.Tag = i
            btn.Click += self._bm_click
            self._bm_style(btn)
            menu = ContextMenuStrip()
            mi_open = ToolStripMenuItem("\u041e\u0442\u043a\u0440\u044b\u0442\u044c")
            mi_open.Click += self._bm_click
            mi_edit = ToolStripMenuItem("\u0420\u0435\u0434\u0430\u043a\u0442\u0438\u0440\u043e\u0432\u0430\u0442\u044c")
            mi_edit.Click += lambda s2, e2, b=btn: self._bm_edit(b)
            mi_del = ToolStripMenuItem("\u0423\u0434\u0430\u043b\u0438\u0442\u044c")
            mi_del.Click += lambda s2, e2, b=btn: self._bm_delete(b)
            menu.Items.Add(mi_open)
            menu.Items.Add(mi_edit)
            menu.Items.Add(mi_del)
            btn.ContextMenuStrip = menu
            self.bm.Controls.Add(btn)
        self._apply_theme_buttons()

    def _bm_style(self, btn):
        btn.FlatStyle = FlatStyle.Flat
        btn.BackColor = self._panel
        btn.ForeColor = self._text
        btn.FlatAppearance.BorderSize = 0
        btn.FlatAppearance.BorderColor = self._border
        btn.FlatAppearance.MouseOverBackColor = self._accent
        btn.FlatAppearance.MouseDownBackColor = self._accent2
        btn.Font = self.ui_font
        self._tooltip().SetToolTip(btn, _bookmarks[btn.Tag]["url"])

    def _apply_theme_buttons(self):
        for b in self._all_buttons():
            b.FlatStyle = FlatStyle.Flat
            b.BackColor = self._panel
            b.ForeColor = self._text
            b.FlatAppearance.BorderSize = 0
            b.FlatAppearance.BorderColor = self._border
            b.FlatAppearance.MouseOverBackColor = self._accent
            b.FlatAppearance.MouseDownBackColor = self._accent2
            b.Font = self.ui_font
        self.btn_add.BackColor = self._accent
        self.btn_add.ForeColor = self._bg

    def _bm_click(self, sender, e):
        i = sender.Tag
        if 0 <= i < len(_bookmarks):
            core = self._core()
            if core is None:
                return
            try:
                core.Navigate(_bookmarks[i]["url"])
            except Exception:
                pass

    def _bm_edit(self, btn):
        i = btn.Tag
        if 0 <= i < len(_bookmarks):
            try:
                name = Interaction.InputBox(
                    "\u041d\u0430\u0437\u0432\u0430\u043d\u0438\u0435:", "\u0417\u0430\u043a\u043b\u0430\u0434\u043a\u0430",
                    _bookmarks[i]["name"], 0, 0)
            except Exception:
                return
            if name and name.strip():
                _bookmarks[i]["name"] = name.strip()
                save_bookmarks()
                self._render_bookmarks()

    def _bm_delete(self, btn):
        i = btn.Tag
        if 0 <= i < len(_bookmarks):
            _bookmarks.pop(i)
            save_bookmarks()
            self._render_bookmarks()

    def add_bookmark(self, sender=None, e=None):
        core = self._core()
        if core is None:
            url = _default_home()
        else:
            try:
                url = str(core.Source)
            except Exception:
                url = _default_home()
        if not url or url in ("about:blank", "data:text/html,"):
            url = _default_home()
        try:
            name = Interaction.InputBox("\u041d\u0430\u0437\u0432\u0430\u043d\u0438\u0435 \u0437\u0430\u043a\u043b\u0430\u0434\u043a\u0438:", "\u041d\u043e\u0432\u0430\u044f \u0437\u0430\u043a\u043b\u0430\u0434\u043a\u0430", url, 0, 0)
        except Exception:
            return
        if not name or not name.strip():
            return
        name = name.strip()
        for bm in _bookmarks:
            if bm["url"] == url:
                bm["name"] = name
                save_bookmarks()
                self._render_bookmarks()
                return
        _bookmarks.append({"name": name, "url": url, "icon": "\U0001f517"})
        save_bookmarks()
        self._render_bookmarks()

    # ===================== ВЕБВЬЮ =====================

    def _on_ready(self, sender, args):
        view = sender
        _log("on_ready: success=%s" % args.IsSuccess)
        if not args.IsSuccess:
            try:
                _log("init_exception: %s" % args.InitializationException)
            except Exception:
                pass
            return
        try:
            core = view.CoreWebView2
            settings = core.Settings
            settings.UserAgent = UA
            settings.AreDevToolsEnabled = False
            settings.AreDefaultContextMenusEnabled = True
            settings.AreBrowserAcceleratorKeysEnabled = False
            settings.IsStatusBarEnabled = False
            settings.IsZoomControlEnabled = False
            settings.IsSwipeNavigationEnabled = False
            settings.IsGeneralAutofillEnabled = False
            settings.IsPasswordAutosaveEnabled = False
            settings.IsWebMessageEnabled = True
            settings.IsBuiltInErrorPageEnabled = True
            try:
                settings.IsReputationCheckingRequired = False
            except Exception:
                pass
            core.MemoryUsageTargetLevel = CoreWebView2MemoryUsageTargetLevel.Low
            core.NewWindowRequested += self._on_new_window
            core.NavigationStarting += self._on_navigation_starting
            core.WebMessageReceived += self._on_web_message
            h = lambda s2, a2, v=view: self._on_document_title(v)
            core.DocumentTitleChanged += h
            self._event_handlers.append(h)
            # плавная прокрутка + подсветка ссылок в статус-баре
            core.AddScriptToExecuteOnDocumentCreatedAsync(
                "document.documentElement.style.scrollBehavior='smooth';"
                "document.addEventListener('mouseover',function(e){"
                "var a=e.target.closest('a');if(a&&a.href){"
                "window.chrome.webview.postMessage('link:'+a.href);}});"
                "document.addEventListener('mouseout',function(){"
                "window.chrome.webview.postMessage('link:');});"
            )
        except Exception as e:
            _log("on_ready setup error: %s" % e)
        try:
            self._render_bookmarks()
        except Exception as e:
            _log("render bookmarks error: %s" % e)

        url = None
        try:
            url = getattr(view, "Tag", None)
        except Exception:
            pass
        if url:
            # навигация через Source (надёжный способ, как в рабочей старой версии);
            # Set Source повторно ничего не сломает, WebView2 сам отменит первую навигацию
            try:
                view.Source = Uri(url)
                _log("navigate: %s" % url)
            except Exception as e:
                _log("navigate error: %s" % e)
        else:
            try:
                view.Source = Uri(_START_URL)
                _log("start page shown")
            except Exception as e:
                _log("start page error: %s" % e)

    def _on_document_title(self, view):
        try:
            core = view.CoreWebView2
            title = str(core.DocumentTitle or "")
        except Exception:
            return
        page = self._page_of(view)
        if page is not None:
            self._update_tab_title(page, title)

    def _on_navigation_starting(self, sender, args):
        try:
            uri = str(args.Uri)
        except Exception:
            uri = ""
        # ссылки на сплэше открываем в реальной навигации (не мешаем)
        self._loading = True
        self._done = False
        self._show_progress()
        _log("nav start: %s" % (uri or "?"))

    def _on_navigation_completed(self, sender, args):
        view = sender
        self._sync_addr()
        self._loading = False
        self._done = True
        try:
            self.progress.Width = self.progress_host.Width
        except Exception:
            pass
        try:
            core = view.CoreWebView2
            core.MemoryUsageTargetLevel = CoreWebView2MemoryUsageTargetLevel.Low
        except Exception:
            pass
        # заголовок вкладки
        try:
            if view is self._current_view():
                title = str(view.CoreWebView2.DocumentTitle or "")
                page = self._page_of(view)
                if page is not None:
                    self._update_tab_title(page, title)
        except Exception:
            pass
        try:
            _log("nav done: success=%s weberr=%s src=%s" % (
                args.IsSuccess, args.WebErrorStatus, str(getattr(view.CoreWebView2, "Source", "?"))
            ))
        except Exception:
            _log("nav done: success=%s" % args.IsSuccess)
        self._refresh_status()

    def _on_source_changed(self, sender, args):
        view = sender
        if view is self._current_view():
            self._sync_addr()

    def _sync_addr(self):
        core = self._core()
        if core is None:
            return
        try:
            url = str(core.Source)
            if url and url != "about:blank" and not url.startswith("data:"):
                self.addr.Text = url
        except Exception:
            pass

    def _on_new_window(self, sender, e):
        try:
            url = str(e.Uri)
            e.Handled = True
            _log("new window -> tab: %s" % url)
            try:
                self.BeginInvoke(Action(lambda: self._new_tab(url)))
            except Exception as exc:
                _log("tab spawn via invoke error: %s" % exc)
        except Exception as exc:
            _log("new window error: %s" % exc)

    def _on_web_message(self, sender, e):
        try:
            msg = str(e.TryGetWebMessageAsString() or "")
        except Exception:
            return
        if msg.startswith("link:"):
            self._hover_link = msg[5:]
            self._refresh_status()
        elif msg.startswith("nav:"):
            url = msg[4:].strip()
            if not url:
                return
            view = self._current_view()
            if view is None:
                return
            try:
                view.Source = Uri(url)
                _log("nav msg: %s" % url)
            except Exception as exc:
                _log("nav msg error: %s" % exc)

    # ===================== СТАТУС-БАР =====================

    def _conn_text(self):
        try:
            from System.Net.NetworkInformation import NetworkInterface
            ok = NetworkInterface.GetIsNetworkAvailable()
            return "\U0001f7e2 Online" if ok else "\U0001f534 Offline"
        except Exception:
            return "\U0001f7e2 Online"

    def _refresh_status(self):
        if self._hover_link:
            self.status.Text = self._hover_link
            self.status.ForeColor = self._accent
            return
        if self._loading:
            return
        self.status.Text = self._conn_text()
        self.status.ForeColor = self._muted

    def _on_monitor_tick(self, sender, e):
        if not self._hover_link:
            self._refresh_status()
        self._update_monitor(sender, e)

    # ===================== ПРОГРЕСС-БАР =====================

    def _show_progress(self):
        self.progress.Visible = True
        self.progress.Width = 0
        self._prog_timer.Start()

    def _prog_tick(self, sender, e):
        try:
            h = self.progress_host.Width
        except Exception:
            h = 200
        if self._done:
            self.progress.Visible = False
            self._prog_timer.Stop()
            self._refresh_status()
            return
        w = self.progress.Width
        if w < h:
            nw = min(int(h * 0.92), w + max(6, int((h - w) * 0.12)))
            self.progress.Width = nw
            self.status.Text = "\u0417\u0430\u0433\u0440\u0443\u0437\u043a\u0430: %d%%" % int(100 * nw / max(1, h))
            self.status.ForeColor = self._accent

    # ===================== ГОРЯЧИЕ КЛАВИШИ =====================

    def _toggle_fullscreen(self):
        try:
            if self._fullscreen:
                self.FormBorderStyle = FormBorderStyle.Sizable
                self.WindowState = FormWindowState.Normal
                self._fullscreen = False
            else:
                self.FormBorderStyle = getattr(FormBorderStyle, "None")
                self.WindowState = FormWindowState.Maximized
                self._fullscreen = True
        except Exception:
            pass

    def _on_key(self, sender, e):
        k = e.KeyCode
        if e.Control and e.Shift and k == Keys.Delete:
            self._clear_browsing_data()
            e.Handled = True
        elif e.Control and e.Shift and k == Keys.T:
            self.cycle_theme()
            e.Handled = True
        elif e.Control and e.Shift and k == Keys.M:
            self._toggle_monitor()
            e.Handled = True
        elif e.Control and k == Keys.R:
            self._hard_reload()
            e.Handled = True
        elif e.Control and k == Keys.W:
            e.Handled = True
            if self.tabs.TabPages.Count > 1:
                self._close_tab()
            else:
                self.Close()
        elif e.Control and k == Keys.T:
            e.Handled = True
            self.open_new_tab()
        elif e.Control and k == Keys.Tab:
            e.Handled = True
            self._next_tab(1)
        elif e.Control and e.Shift and k == Keys.Tab:
            e.Handled = True
            self._next_tab(-1)
        elif e.Control and k == Keys.L:
            self.addr.Focus()
            try:
                self.addr.SelectAll()
            except Exception:
                pass
            e.Handled = True
        elif e.Control and k == Keys.D:
            self.add_bookmark()
            e.Handled = True
        elif e.Control and k == Keys.D1:
            self._open_bookmark(0)
            e.Handled = True
        elif e.Control and k == Keys.D2:
            self._open_bookmark(1)
            e.Handled = True
        elif e.Control and k == Keys.D3:
            self._open_bookmark(2)
            e.Handled = True
        elif k == Keys.F11:
            self._toggle_fullscreen()
            e.Handled = True
        elif k == Keys.Escape and self._fullscreen:
            self._toggle_fullscreen()
            e.Handled = True

    def _next_tab(self, delta):
        n = self.tabs.TabPages.Count
        if n <= 1:
            return
        i = (self.tabs.SelectedIndex + delta) % n
        self.tabs.SelectedIndex = i

    def _open_bookmark(self, i):
        if 0 <= i < len(_bookmarks):
            core = self._core()
            if core is None:
                return
            try:
                core.Navigate(_bookmarks[i]["url"])
            except Exception:
                pass

    # ===================== НАСТРОЙКИ =====================

    def open_settings(self, sender=None, e=None):
        dlg = SettingsForm(dict(_settings))
        try:
            res = dlg.ShowDialog(self)
        except Exception as exc:
            _log("settings dialog error: %s" % exc)
            return
        if res == DialogResult.OK:
            if dlg.result is not None:
                _settings.update(dlg.result)
                save_settings()
                self.theme = _settings["theme"]
                self.ui_font = Font("Segoe UI", _settings.get("font_size", 14))
                self.addr.Font = self.ui_font
                self._apply_theme()
                self._render_bookmarks()
                self._draw_tabs_redraw()
                _log("settings saved")
            if getattr(dlg, "clear_requested", False):
                self._clear_browsing_data()

    # ===================== ОЧИСТКА ДАННЫХ =====================

    def _any_core(self):
        """CoreWebView2 любой вкладки — если активная ещё не готова."""
        core = self._core()
        if core is not None:
            return core
        try:
            for i in range(self.tabs.TabPages.Count):
                page = self.tabs.TabPages[i]
                for c in page.Controls:
                    if isinstance(c, WebView2):
                        try:
                            if c.CoreWebView2 is not None:
                                return c.CoreWebView2
                        except Exception:
                            pass
        except Exception:
            pass
        return None

    def _clear_browsing_data(self, sender=None, e=None):
        core = self._any_core()
        if core is None:
            try:
                MessageBox.Show(self, "\u0412\u043a\u043b\u0430\u0434\u043a\u0430 \u0435\u0449\u0451 \u043d\u0435 \u0433\u043e\u0442\u043e\u0432\u0430. \u041f\u043e\u0432\u0442\u043e\u0440\u0438\u0442\u0435 \u0447\u0435\u0440\u0435\u0437 \u043f\u0430\u0440\u0443 \u0441\u0435\u043a\u0443\u043d\u0434.", "Jektor")
            except Exception:
                pass
            return
        before = self._dir_size(PROFILE_DIR)
        dlg = ClearDataForm(self.theme, before / 1048576.0)
        try:
            if dlg.ShowDialog(self) != DialogResult.OK or dlg.result is None:
                return
        except Exception as exc:
            _log("clear dialog error: %s" % exc)
            return
        kinds = int(dlg.result["kinds"])
        secs = dlg.result["seconds"]
        if kinds == 0:
            return
        try:
            enum_kinds = System.Enum.ToObject(CoreWebView2BrowsingDataKinds, kinds)
            profile = core.Profile
        except Exception as exc:
            _log("clear profile error: %s" % exc)
            return
        try:
            if secs:
                now = System.DateTime.Now
                start = now.AddSeconds(-int(secs))
                task = profile.ClearBrowsingDataAsync(enum_kinds, start, now)
            else:
                task = profile.ClearBrowsingDataAsync(enum_kinds)
        except Exception as exc:
            _log("ClearBrowsingDataAsync error: %s" % exc)
            return
        # ждём завершения, не морозя интерфейс
        t0 = time.time()
        while (not task.IsCompleted) and (time.time() - t0) < 20:
            Application.DoEvents()
            time.sleep(0.02)
        ok = bool(task.IsCompleted)
        try:
            if task.IsFaulted:
                ok = False
                _log("clear faulted: %s" % task.Exception)
        except Exception:
            pass
        # подчистить оставшийся старый профиль
        try:
            if os.path.isdir(PROFILE_OLD_DIR):
                shutil.rmtree(PROFILE_OLD_DIR, ignore_errors=True)
        except Exception:
            pass
        gc.collect()
        after = self._dir_size(PROFILE_DIR)
        freed = max(0, before - after)
        self._cache_size = after
        self._cache_ticks = 0
        try:
            self._update_monitor(None, None)
        except Exception:
            pass
        try:
            self.status.Text = "\u041e\u0447\u0438\u0441\u0442\u043a\u0430 \u0434\u0430\u043d\u043d\u044b\u0445: \u043e\u0441\u0432\u043e\u0431\u043e\u0436\u0434\u0435\u043d\u043e %.1f \u041c\u0411" % (freed / 1048576.0)
            self.status.ForeColor = self._accent
        except Exception:
            pass
        _log("clear data: kinds=%d secs=%s ok=%s freed=%.1fMB cache=%.1fMB" % (
            kinds, secs, ok, freed / 1048576.0, after / 1048576.0))
        try:
            MessageBox.Show(
                self,
                "\u041e\u0447\u0438\u0441\u0442\u043a\u0430 %s.\n\u041e\u0441\u0432\u043e\u0431\u043e\u0436\u0434\u0435\u043d\u043e: %.1f \u041c\u0411.\n\u041a\u0435\u0448 \u043f\u0440\u043e\u0444\u0438\u043b\u044f \u0442\u0435\u043f\u0435\u0440\u044c: %.1f \u041c\u0411."
                % ("\u0437\u0430\u0432\u0435\u0440\u0448\u0435\u043d\u0430" if ok else "\u043f\u0440\u0435\u0440\u0432\u0430\u043d\u0430", freed / 1048576.0, after / 1048576.0),
                "Jektor \u2014 \u043e\u0447\u0438\u0441\u0442\u043a\u0430 \u0434\u0430\u043d\u043d\u044b\u0445",
            )
        except Exception:
            pass

    # ===================== ЗАКРЫТИЕ / ПАМЯТЬ =====================

    def _on_form_closed(self, sender, e):
        try:
            if self._home_loaded:
                pass
        except Exception:
            pass
        # сохранить URL всех вкладок
        urls = []
        for i in range(self.tabs.TabPages.Count):
            try:
                page = self.tabs.TabPages[i]
                for c in page.Controls:
                    if isinstance(c, WebView2):
                        try:
                            u = str(c.CoreWebView2.Source)
                        except Exception:
                            u = ""
                        if u and u not in ("about:blank",) and not u.startswith("data:"):
                            urls.append(u)
            except Exception:
                pass
        if urls:
            _last_urls.extend(urls)
            _last_urls[:] = _last_urls[-10:]
        try:
            if self in _open_forms:
                _open_forms.remove(self)
        except Exception:
            pass
        # dispose всех webview
        for i in range(self.tabs.TabPages.Count):
            try:
                page = self.tabs.TabPages[i]
                for c in page.Controls:
                    if isinstance(c, WebView2):
                        try:
                            c.Dispose()
                        except Exception:
                            pass
            except Exception:
                pass
        gc.collect()

    def _toggle_monitor(self, sender=None, e=None):
        self.monitor_visible = not self.monitor_visible
        self.mem_label.Visible = self.monitor_visible
        self.mem_label.BringToFront()

    def _dir_size(self, path):
        total = 0
        try:
            for root, _dirs, files in os.walk(path):
                for f in files:
                    try:
                        total += os.path.getsize(os.path.join(root, f))
                    except Exception:
                        pass
        except Exception:
            pass
        return total

    def _update_monitor(self, sender, e):
        if not self.monitor_visible:
            return
        try:
            import psutil

            wv_sum = sum(
                p.memory_info().rss
                for p in psutil.process_iter(["name", "memory_info"])
                if p.info["name"] and "webview2" in p.info["name"].lower()
            )
            py_sum = sum(
                p.info["memory_info"].rss
                for p in psutil.process_iter(["name", "memory_info"])
                if p.info["name"] and p.info["name"].lower() == "python.exe"
            )
        except Exception:
            wv_sum = py_sum = 0
        self._cache_ticks += 1
        if self._cache_ticks % 5 == 0:
            self._cache_size = self._dir_size(PROFILE_DIR)
        try:
            n_tabs = self.tabs.TabPages.Count
        except Exception:
            n_tabs = 1
        self.mem_label.Text = (
            "RAM: %.0fMB | Cache: %.0fMB | \u0412\u043a\u043b\u0430\u0434\u043a\u0438: %d"
            % ((wv_sum + py_sum) / 1048576.0, self._cache_size / 1048576.0, n_tabs)
        )

    def _cleanup_memory(self, sender, e):
        try:
            gc.collect()
        except Exception:
            pass


class ClearDataForm(Form):
    """Диалог «Очистить данные» — как в обычных браузерах."""

    def __init__(self, theme, cache_mb):
        super().__init__()
        self.result = None
        t = THEMES.get(theme, THEMES["dark"])
        self.Text = "\u041e\u0447\u0438\u0441\u0442\u0438\u0442\u044c \u0434\u0430\u043d\u043d\u044b\u0435"
        self.Width = 430
        self.Height = 400
        self.StartPosition = FormStartPosition.CenterParent
        self.FormBorderStyle = FormBorderStyle.FixedDialog
        self.MaximizeBox = False
        self.MinimizeBox = False
        self.BackColor = _c(t["panel"])
        self.ForeColor = _c(t["text"])
        pad = 16
        y = pad

        def label(text, yy, bold=False):
            l = Label()
            l.Text = text
            l.Left = pad
            l.Top = yy
            l.AutoSize = True
            l.ForeColor = _c(t["text"])
            if bold:
                l.Font = Font("Segoe UI", 10, FontStyle.Bold)
            self.Controls.Add(l)
            return l

        def check(text, checked, yy):
            c = CheckBox()
            c.Text = text
            c.Left = pad
            c.Top = yy
            c.Width = 384
            c.Checked = checked
            c.ForeColor = _c(t["text"])
            self.Controls.Add(c)
            return c

        label("\u0427\u0442\u043e \u0443\u0434\u0430\u043b\u0438\u0442\u044c:", y, bold=True)
        y += 28
        self.chk_hist = check("\u0418\u0441\u0442\u043e\u0440\u0438\u044f \u043f\u0440\u043e\u0441\u043c\u043e\u0442\u0440\u043e\u0432", True, y)
        y += 26
        self.chk_cache = check("\u041a\u0435\u0448 \u2014 \u0438\u0437\u043e\u0431\u0440\u0430\u0436\u0435\u043d\u0438\u044f \u0438 \u0444\u0430\u0439\u043b\u044b", True, y)
        y += 26
        self.chk_site = check("Cookies \u0438 \u0434\u0430\u043d\u043d\u044b\u0435 \u0441\u0430\u0439\u0442\u043e\u0432", True, y)
        y += 26
        self.chk_dl = check("\u0418\u0441\u0442\u043e\u0440\u0438\u044f \u0437\u0430\u0433\u0440\u0443\u0437\u043e\u043a", False, y)
        y += 34

        label("\u041f\u0435\u0440\u0438\u043e\u0434:", y)
        y += 24
        self.cb_period = ComboBox()
        self.cb_period.Left = pad
        self.cb_period.Top = y
        self.cb_period.Width = 260
        self.cb_period.DropDownStyle = ComboBoxStyle.DropDownList
        for name, _sec in CLEAR_PERIODS:
            self.cb_period.Items.Add(name)
        self.cb_period.SelectedIndex = 0
        self.Controls.Add(self.cb_period)
        y += 36

        note = label("\u041a\u0435\u0448 \u043f\u0440\u043e\u0444\u0438\u043b\u044f \u0441\u0435\u0439\u0447\u0430\u0441: %.1f \u041c\u0411" % cache_mb, y)
        note.ForeColor = _c(t["muted"])

        btn_ok = Button()
        btn_ok.Text = "\u041e\u0447\u0438\u0441\u0442\u0438\u0442\u044c"
        btn_ok.Left = pad
        btn_ok.Top = self.Height - 70
        btn_ok.Width = 110
        btn_ok.Click += self._ok
        self.Controls.Add(btn_ok)

        btn_cancel = Button()
        btn_cancel.Text = "\u041e\u0442\u043c\u0435\u043d\u0430"
        btn_cancel.Left = pad + 120
        btn_cancel.Top = self.Height - 70
        btn_cancel.Width = 90
        btn_cancel.Click += self._cancel
        self.Controls.Add(btn_cancel)

        for b in (btn_ok, btn_cancel):
            b.FlatStyle = FlatStyle.Flat
            b.BackColor = _c(t["panel"])
            b.ForeColor = _c(t["text"])
            b.FlatAppearance.BorderColor = _c(t["border"])

    def _cancel(self, sender, e):
        self.DialogResult = DialogResult.Cancel
        self.Close()

    def _ok(self, sender, e):
        kinds = 0
        if self.chk_hist.Checked:
            kinds |= CLEAR_HISTORY
        if self.chk_cache.Checked:
            kinds |= CLEAR_CACHE
        if self.chk_site.Checked:
            kinds |= CLEAR_SITE
        if self.chk_dl.Checked:
            kinds |= CLEAR_DOWNLOADS
        _name, secs = CLEAR_PERIODS[self.cb_period.SelectedIndex]
        self.result = {"kinds": kinds, "seconds": secs}
        self.DialogResult = DialogResult.OK
        self.Close()


class SettingsForm(Form):
    def __init__(self, s):
        super().__init__()
        self.result = None
        self.clear_requested = False
        self.Text = "\u041d\u0430\u0441\u0442\u0440\u043e\u0439\u043a\u0438 Jektor"
        self.Width = 400
        self.Height = 410
        self.StartPosition = FormStartPosition.CenterParent
        self.FormBorderStyle = FormBorderStyle.FixedDialog
        self.MaximizeBox = False
        self.MinimizeBox = False
        self.BackColor = _c(THEMES.get(s["theme"], THEMES["dark"])["panel"])
        self.ForeColor = _c(THEMES.get(s["theme"], THEMES["dark"])["text"])
        pad = 16
        y = pad

        def lbl(text, yy):
            l = Label()
            l.Text = text
            l.Left = pad
            l.Top = yy
            l.AutoSize = True
            self.Controls.Add(l)
            return l

        lbl("\u0422\u0435\u043c\u0430:", y)
        self.cb_theme = ComboBox()
        self.cb_theme.Left = pad + 120
        self.cb_theme.Top = y - 3
        self.cb_theme.Width = 200
        self.cb_theme.DropDownStyle = ComboBoxStyle.DropDownList
        for key in THEME_ORDER:
            self.cb_theme.Items.Add(THEMES[key]["name"])
        self.cb_theme.SelectedIndex = THEME_ORDER.index(s["theme"]) if s["theme"] in THEME_ORDER else 0
        self.Controls.Add(self.cb_theme)
        y += 40

        lbl("\u0420\u0430\u0437\u043c\u0435\u0440 \u0448\u0440\u0438\u0444\u0442\u0430:", y)
        self.num_font = NumericUpDown()
        self.num_font.Left = pad + 120
        self.num_font.Top = y - 2
        self.num_font.Width = 60
        self.num_font.Minimum = System.Decimal(10)
        self.num_font.Maximum = System.Decimal(22)
        self.num_font.Value = System.Decimal(int(s.get("font_size", 14)))
        self.Controls.Add(self.num_font)
        y += 40

        lbl("\u0414\u043e\u043c\u0430\u0448\u043d\u044f\u044f \u0441\u0442\u0440\u0430\u043d\u0438\u0446\u0430:", y)
        self.txt_home = TextBox()
        self.txt_home.Left = pad
        self.txt_home.Top = y + 22
        self.txt_home.Width = 360
        self.txt_home.Text = s.get("home", "")
        self.Controls.Add(self.txt_home)
        y += 70

        self.chk_qwen = CheckBox()
        self.chk_qwen.Text = "\u0410\u0432\u0442\u043e\u0437\u0430\u043f\u0443\u0441\u043a Qwen AI"
        self.chk_qwen.Left = pad
        self.chk_qwen.Top = y
        self.chk_qwen.Checked = bool(s.get("autostart_qwen", True))
        self.Controls.Add(self.chk_qwen)
        y += 32

        self.chk_sess = CheckBox()
        self.chk_sess.Text = "\u0421\u043e\u0445\u0440\u0430\u043d\u044f\u0442\u044c \u0441\u0435\u0441\u0441\u0438\u0438"
        self.chk_sess.Left = pad
        self.chk_sess.Top = y
        self.chk_sess.Checked = bool(s.get("save_sessions", True))
        self.Controls.Add(self.chk_sess)
        y += 44

        btn_clear = Button()
        btn_clear.Text = "\U0001f9f9 \u041e\u0447\u0438\u0441\u0442\u0438\u0442\u044c \u043a\u0435\u0448 \u0438 \u0438\u0441\u0442\u043e\u0440\u0438\u044e..."
        btn_clear.Left = pad
        btn_clear.Top = y
        btn_clear.Width = 300
        btn_clear.Click += self._ask_clear
        self.Controls.Add(btn_clear)

        btn_ok = Button()
        btn_ok.Text = "OK"
        btn_ok.Left = pad
        btn_ok.Top = self.Height - 70
        btn_ok.Width = 90
        btn_ok.Click += self._save
        self.Controls.Add(btn_ok)

        btn_cancel = Button()
        btn_cancel.Text = "\u041e\u0442\u043c\u0435\u043d\u0430"
        btn_cancel.Left = pad + 100
        btn_cancel.Top = self.Height - 70
        btn_cancel.Width = 90
        btn_cancel.Click += self._cancel
        self.Controls.Add(btn_cancel)

    def _cancel(self, sender, e):
        self.DialogResult = DialogResult.Cancel
        self.Close()

    def _ask_clear(self, sender, e):
        self.clear_requested = True
        self.DialogResult = DialogResult.OK
        self.Close()

    def _save(self, sender, e):
        self.result = {
            "theme": THEME_ORDER[self.cb_theme.SelectedIndex],
            "font_size": int(str(self.num_font.Value)),
            "home": self.txt_home.Text.strip(),
            "autostart_qwen": bool(self.chk_qwen.Checked),
            "save_sessions": bool(self.chk_sess.Checked),
        }
        self.DialogResult = DialogResult.OK
        self.Close()


def _open_window(url):
    def _create():
        Application.EnableVisualStyles()
        try:
            f = MiniBrowserForm(url)
            _open_forms.append(f)
            Application.Run(f)
        except Exception:
            import traceback
            _log(traceback.format_exc())

    t = Thread(ThreadStart(_create))
    t.SetApartmentState(ApartmentState.STA)
    t.IsBackground = True
    t.Start()


def _report_memory():
    try:
        import psutil
    except Exception:
        _log("psutil \u043d\u0435 \u0443\u0441\u0442\u0430\u043d\u043e\u0432\u043b\u0435\u043d")
        return

    def _loop():
        while True:
            time.sleep(60)
            try:
                wv_sum = sum(
                    p.memory_info().rss
                    for p in psutil.process_iter(["name", "memory_info"])
                    if p.info["name"] and "webview2" in p.info["name"].lower()
                )
                py_sum = 0
                for p in psutil.process_iter(["name", "memory_info"]):
                    if p.info["name"] and p.info["name"].lower() == "python.exe":
                        py_sum += p.info["memory_info"].rss
                _log(
                    "MEM: webview2=%.1fMB python=%.1fMB total=%.1fMB"
                    % (wv_sum / 1048576.0, py_sum / 1048576.0, (wv_sum + py_sum) / 1048576.0)
                )
            except Exception:
                pass

    threading.Thread(target=_loop, daemon=True).start()


SESSIONS_FILE = os.path.join(DATA_DIR, "sessions.json")


def _restore_sessions():
    if not _settings.get("save_sessions", True):
        return []
    urls = []
    try:
        if os.path.exists(SESSIONS_FILE):
            with open(SESSIONS_FILE, encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, list):
                urls = [u for u in data if isinstance(u, str) and u.startswith("http")]
    except Exception:
        urls = []
    if not urls:
        try:
            with open(SESSIONS_FILE, "w", encoding="utf-8") as f:
                json.dump([], f)
        except Exception:
            pass
    return urls


def _save_sessions_now():
    if not _settings.get("save_sessions", True):
        return
    try:
        with open(SESSIONS_FILE, "w", encoding="utf-8") as f:
            json.dump(list(_last_urls), f, ensure_ascii=False)
    except Exception:
        pass


def _enum_windows():
    """Возвращает список HWND всех окон верхнего уровня (Win32 API)."""
    import ctypes
    from ctypes import wintypes

    result = []

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def _cb(hwnd, lParam):
        result.append(hwnd)
        return True

    user32 = ctypes.windll.user32
    user32.EnumWindows(_cb, 0)
    return result


def main():
    # скрыть окно консоли (терминал не мелькает при запуске)
    try:
        import ctypes
        _hwnd = ctypes.windll.kernel32.GetConsoleWindow()
        if _hwnd:
            ctypes.windll.user32.ShowWindow(_hwnd, 0)
    except Exception:
        pass
    _log("=== start ===")
    # AppUserModelID: отдельная иконка в панели задач (не python.exe)
    try:
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("JektorBrowser.Jektor")
    except Exception:
        pass
    load_settings()
    load_bookmarks()
    _report_memory()

    # --- проверка наличия Microsoft Edge WebView2 Runtime ---
    try:
        _wv_ver = CoreWebView2Environment.GetAvailableBrowserVersionString()
    except Exception:
        _wv_ver = None
    if not _wv_ver:
        _msg = (
            "Jektor использует движок Microsoft Edge WebView2.\n\n"
            "Runtime не найден. Установите его (Evergreen):\n"
            "https://developer.microsoft.com/microsoft-edge/webview2/\n\n"
            "Затем запустите Jektor снова."
        )
        try:
            import ctypes

            ctypes.windll.user32.MessageBoxW(0, _msg, "Jektor — нужен WebView2 Runtime", 0x30)
        except Exception:
            print(_msg)
        _log("webview2 runtime not found")
        return
    _log("webview2 runtime: %s" % _wv_ver)

    # --- single instance: если браузер уже запущен, активируем его и выходим ---
    _sync = None
    _got_owner = True
    try:
        import ctypes
        _k32 = ctypes.windll.kernel32
        _k32.CreateMutexW.restype = ctypes.c_void_p
        _sync = _k32.CreateMutexW(None, True, "Local\\JektorBrowserSingleInstance_v1")
        _err = _k32.GetLastError()
        if _sync and _err == 183:   # ERROR_ALREADY_EXISTS
            _got_owner = False
        elif not _sync:
            _got_owner = True       # Mutex не создался — запускаем как обычно
    except Exception:
        _got_owner = True

    if not _got_owner:
        _log("already running -> focus existing window")
        try:
            import ctypes
            user32 = ctypes.windll.user32
            for hwnd in _enum_windows():
                length = user32.GetWindowTextLengthW(hwnd)
                if length > 0:
                    buf = ctypes.create_unicode_buffer(length + 1)
                    user32.GetWindowTextW(hwnd, buf, length + 1)
                    title = buf.value
                    if "Jektor" in title:
                        user32.ShowWindow(hwnd, 9)
                        user32.SetForegroundWindow(hwnd)
                        _log("focused: %s" % title)
                        return
        except Exception:
            pass
        if _sync:
            ctypes.windll.kernel32.CloseHandle(_sync)
        return

    try:
        def _ui():
            Application.EnableVisualStyles()
            try:
                f = MiniBrowserForm()
                _open_forms.append(f)
                # старт «с чистого листа»: одна пустая вкладка
                f._new_tab(None, activate=True)
                Application.Run(f)
                _save_sessions_now()
                _log("=== exit ===")
            except Exception:
                import traceback
                _log("ui thread error:\n%s" % traceback.format_exc())
                try:
                    Application.Exit()
                except Exception:
                    pass

        t = Thread(ThreadStart(_ui))
        t.SetApartmentState(ApartmentState.STA)
        t.IsBackground = True
        t.Start()
        t.Join()
    finally:
        if _sync is not None:
            try:
                ctypes.windll.kernel32.ReleaseMutex(_sync)
            except Exception:
                pass
            try:
                ctypes.windll.kernel32.CloseHandle(_sync)
            except Exception:
                pass


if __name__ == "__main__":
    main()