"""Tarjetas de la consola interactiva del README (`$ ssh alexis@umb`).

neofetch, man, history, sudo, visitas.log, la pantalla CONTINUE? y el
código Konami. Las llama scripts/generate.py y comparten con él las
utilerías y las fuentes retro.
"""
from __future__ import annotations

import datetime as dt
import json
import re
import unicodedata
import urllib.request
from pathlib import Path

from generate import (ANIM_CSS, ARCADE, MESES, PIXEL, PIXEL_FILE, RETRO_CSS, VT, VT_FILE, card,
                      font_advance, font_face, sprite, svg, t, wrap)

ROOT = Path(__file__).resolve().parent.parent
GUESTBOOK = ROOT / "assets" / "guestbook.json"
GUESTBOOK_SHOWN = 6
GUESTBOOK_MAX_LEN = 60

VTF = f"font-family=\"'{VT}',monospace\""
PXF = f"font-family=\"'{PIXEL}',monospace\""
W, PAD = 880, 32
FS, LH = 22, 26  # tamaño y alto de línea del texto VT323
RED = {"dark": "#ff7b72", "light": "#cf222e"}

# Tux, la mascota de Linux (original de Larry Ewing, lewing@isc.tamu.edu, hecho con GIMP), en píxeles.
TUX = [
    "......KKKK......",
    ".....KKKKKK.....",
    "....KKKKKKKK....",
    "....KWWKKWWK....",
    "....KWKKKKWK....",
    ".....KOOOOK.....",
    "....KKKOOKKK....",
    "...KKKWWWWKKK...",
    "..KKKWWWWWWKKK..",
    "..KKWWWWWWWWKK..",
    ".KKKWWWWWWWWKKK.",
    ".KKKWWWWWWWWKKK.",
    ".KKKWWWWWWWWKKK.",
    ".KKKWWWWWWWWKKK.",
    "..KKWWWWWWWWKK..",
    "..KKKWWWWWWKKK..",
    "...OOOKKKKOOO...",
    "..OOOOO..OOOOO..",
    "..OOOO....OOOO..",
]
TUX_COLORS = {"K": "#0b0b0b", "W": "#ffffff", "O": "#f5a623"}
HEART = [".##.##.", "#######", "#######", ".#####.", "..###..", "...#..."]
TERM_COLORS = ["#21262d", "#ff5f56", "#3fb950", "#ffbd2e", "#58a6ff", "#d2a8ff", "#39c5cf", "#e6edf3"]

CONSOLE_CSS = (
    ".cd{opacity:0;animation:cd 10s steps(1) infinite}@keyframes cd{0%{opacity:1}10%{opacity:0}}"
    "@media (prefers-reduced-motion:reduce){.cd{animation:none}.cd:last-of-type{opacity:1}}"
)


# ------------------------------------------------------------- datos ---

def fetch_commits(user: str, token: str | None, n: int = 5) -> list[dict]:
    """Últimos commits públicos del usuario: el commit cabeza de cada push público reciente (máximo 90 días)."""
    headers = {"User-Agent": "profile-generator", "Accept": "application/vnd.github+json"}
    if token:
        headers["Authorization"] = f"bearer {token}"

    def get(url: str):
        with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=30) as resp:
            return json.load(resp)

    try:
        events = get(f"https://api.github.com/users/{user}/events/public?per_page=100")
    except (OSError, ValueError) as exc:
        print(f"  (sin historial: {exc})")
        return []
    commits, seen = [], set()
    for ev in events:
        if ev.get("type") != "PushEvent" or not ev.get("public", True):
            continue
        repo, head = ev["repo"]["name"], ev["payload"].get("head")
        if not head or head in seen:
            continue
        seen.add(head)
        try:
            c = get(f"https://api.github.com/repos/{repo}/commits/{head}")["commit"]
        except (OSError, ValueError, KeyError):
            continue
        if (c.get("author") or {}).get("name") == "github-actions[bot]":
            continue
        message = (c.get("message") or "").splitlines()[0].strip() if c.get("message") else ""
        if message:
            commits.append({"message": message, "repo": repo,
                            "date": (c.get("author") or {}).get("date") or ev["created_at"]})
        if len(commits) == n + 3:  # unos de sobra: los eventos no siempre llegan en orden
            break
    # Como en `history | tail`: el más viejo arriba, el más reciente abajo.
    return sorted(commits, key=lambda c: c["date"])[-n:]


def load_guestbook() -> list[dict]:
    if not GUESTBOOK.exists():
        return []
    entries = json.loads(GUESTBOOK.read_text(encoding="utf-8")).get("entries", [])
    return entries[-GUESTBOOK_SHOWN:][::-1]


def clean_message(text: str) -> str:
    """Deja solo texto plano de una línea, sin controles ni enlaces. Se aplica al guardar y al dibujar."""
    text = unicodedata.normalize("NFC", text or "")
    text = "".join(ch if ch == " " or unicodedata.category(ch)[0] not in "CZ" else " " for ch in text)
    text = re.sub(r"https?://\S+|www\.\S+", "", text)
    text = re.sub(r"[<>`]", "", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:GUESTBOOK_MAX_LEN].rstrip()


def uptime(created_at: str, today: dt.date | None = None) -> str:
    start = dt.date.fromisoformat(created_at[:10])
    today = today or dt.date.today()
    months = (today.year - start.year) * 12 + today.month - start.month - (today.day < start.day)
    years, months = divmod(months, 12)
    parts = [f"{years} año{'s' if years != 1 else ''}"] if years else []
    if months:
        parts.append(f"{months} mes{'es' if months != 1 else ''}")
    return ", ".join(parts) or "recién llegado"


def short_date(iso: str) -> str:
    d = dt.date.fromisoformat(iso[:10])
    return f"{d.day} {MESES[d.month - 1]}"


# ---------------------------------------------------------- utilerías ---

def pixels(rows: list[str], x: float, y: float, px: int, palette: dict[str, str]) -> str:
    return "".join(sprite(["".join("#" if c == ch else "." for c in row) for row in rows], x, y, px, color)
                   for ch, color in palette.items())


def prompt(host: str, cmd: str, y: int, th: dict) -> str:
    user, _, machine = host.partition("@")
    return (f'<text x="{PAD}" y="{y}" {VTF} font-size="{FS}" xml:space="preserve">'
            f'<tspan fill="{th["accent"]}">{t(user)}</tspan><tspan fill="{th["muted"]}">@</tspan>'
            f'<tspan fill="{th["accent"]}">{t(machine)}</tspan><tspan fill="{th["muted"]}">:~$ </tspan>'
            f'<tspan fill="{th["text"]}">{t(cmd)}</tspan></text>')


def line(x: float, y: float, text: str, color: str, size: int = FS, anchor: str = "start", extra: str = "") -> str:
    return (f'<text x="{x:g}" y="{y:g}" {VTF} font-size="{size}" fill="{color}" text-anchor="{anchor}" '
            f'xml:space="preserve"{extra}>{t(text)}</text>')


def label(x: float, y: float, text: str, color: str, size: int = 10, anchor: str = "start") -> str:
    return f'<text x="{x:g}" y="{y:g}" {PXF} font-size="{size}" fill="{color}" text-anchor="{anchor}">{t(text)}</text>'


# ------------------------------------------------------------ tarjetas ---

def neofetch_card(cfg: dict, dyn: list[tuple[str, str]], th: dict) -> str:
    s = cfg["system"]
    host = s.get("host") or cfg["banner"]["host"]
    fields = [tuple(f) for f in s["fields"]] + dyn
    tx = 250
    H = 96 + len(fields) * LH + 62
    out = [card(W, H, th)]
    vt_text, px_text = [], []

    px = 9
    ty = (H - len(TUX) * px) / 2
    out.append('<defs><filter id="ol" x="-10%" y="-10%" width="120%" height="120%">'
               '<feMorphology in="SourceAlpha" operator="dilate" radius="1.5" result="d"/>'
               f'<feFlood flood-color="{th["border"]}"/><feComposite in2="d" operator="in"/>'
               '<feMerge><feMergeNode/><feMergeNode in="SourceGraphic"/></feMerge></filter></defs>'
               f'<g filter="url(#ol)">{pixels(TUX, 58, ty, px, TUX_COLORS)}</g>')

    y = 60
    out.append(prompt(host, "neofetch", y, th))
    vt_text.append(f"{host}:~$ neofetch")
    y += 36
    user, _, machine = host.partition("@")
    out.append(f'<text x="{tx}" y="{y}" {VTF} font-size="26"><tspan fill="{th["accent"]}">{t(user)}</tspan>'
               f'<tspan fill="{th["muted"]}">@</tspan><tspan fill="{th["accent"]}">{t(machine)}</tspan></text>')
    out.append(line(tx, y + 20, "-" * len(host), th["muted"]))
    vt_text += [host, "-"]
    y += 46
    for key, value in fields:
        out.append(f'<text x="{tx}" y="{y}" {VTF} font-size="{FS}"><tspan fill="{th["accent2"]}">{t(key)}</tspan>'
                   f'<tspan fill="{th["muted"]}">: </tspan><tspan fill="{th["text"]}">{t(value)}</tspan></text>')
        vt_text.append(f"{key}: {value}")
        y += LH
    y += 14
    for i, color in enumerate(TERM_COLORS):
        out.append(f'<rect class="pop" style="animation-delay:{.2 + i * .06:.2f}s" x="{tx + i * 24}" y="{y}" '
                   f'width="20" height="14" fill="{color}"/>')
    css = font_face(VT, VT_FILE, "".join(vt_text)) + ANIM_CSS
    return svg(W, H, f"neofetch: {', '.join(f'{k} {v}' for k, v in fields)}", "".join(out), css=css)


def man_card(cfg: dict, th: dict) -> str:
    m = cfg["man"]
    adv = font_advance(VT_FILE) * FS
    cols = int((W - 2 * PAD - 40) / adv)
    out = [card(W, 0, th)]
    vt_text, px_text = [], []

    y = 44
    for x, anchor, text in ((PAD, "start", "ALEXIS(1)"), (W / 2, "middle", "Manual del usuario"),
                            (W - PAD, "end", "ALEXIS(1)")):
        out.append(label(x, y, text, th["muted"], 9, anchor))
        px_text.append(text)
    y += 40

    def section(title: str, lines: list[str], x: float = PAD + 40) -> None:
        nonlocal y
        out.append(label(PAD, y, title, th["accent"], 10))
        px_text.append(title)
        y += 24
        for ln in lines:
            out.append(line(x, y, ln, th["text"]))
            vt_text.append(ln)
            y += LH
        y += 14

    section("NAME", wrap(m["name"], cols, 3))
    section("SYNOPSIS", [m["synopsis"]])
    section("DESCRIPTION", wrap(m["description"], cols, 6))
    out.append(label(PAD, y, "OPTIONS", th["accent"], 10))
    px_text.append("OPTIONS")
    y += 24
    desc_x = PAD + 220
    desc_cols = int((W - PAD - desc_x) / adv)
    for flag, desc in m["options"]:
        out.append(line(PAD + 40, y, flag, th["accent2"]))
        vt_text.append(flag)
        for ln in wrap(desc, desc_cols, 3):
            out.append(line(desc_x, y, ln, th["text"]))
            vt_text.append(ln)
            y += LH
        y += 4
    y += 10
    section("BUGS", wrap(m["bugs"], cols, 3))
    section("SEE ALSO", [m["see_also"]])
    H = y + 26
    out.append(label(PAD, H - 22, m.get("footer", "Fedora Linux"), th["muted"], 8))
    out.append(label(W - PAD, H - 22, "ALEXIS(1)", th["muted"], 8, "end"))
    px_text.append(m.get("footer", "Fedora Linux"))
    out[0] = card(W, H, th)
    css = font_face(VT, VT_FILE, "".join(vt_text)) + font_face(PIXEL, PIXEL_FILE, "".join(px_text)) + ANIM_CSS
    return svg(W, H, f"man alexis: {m['name']}", "".join(out), css=css)


def history_card(host: str, user: str, commits: list[dict], th: dict) -> str:
    rows = max(len(commits), 1)
    H = 74 + rows * LH + 30
    out = [card(W, H, th)]
    vt_text = []
    out.append(prompt(host, "history | tail -5", 48, th))
    vt_text.append(f"{host}:~$ history | tail -5")
    adv = font_advance(VT_FILE) * FS
    y = 84
    if not commits:
        text = "(sin commits públicos en los últimos 90 días)"
        out.append(line(PAD, y, text, th["muted"]))
        vt_text.append(text)
    for i, c in enumerate(commits):
        repo = c["repo"].removeprefix(f"{user}/")
        right = f"{repo} · {short_date(c['date'])}"
        avail = int((W - 2 * PAD) / adv) - len(right) - 3
        cmd = f'git commit -m "{c["message"]}"'
        if len(cmd) > avail - 8:
            cmd = cmd[: avail - 9].rstrip() + '…"'
        number = f"{1017 - len(commits) + i + 1:5d}"
        out.append(f'<g class="fade" style="animation-delay:{.1 + i * .12:.2f}s">'
                   f'<text x="{PAD}" y="{y}" {VTF} font-size="{FS}" xml:space="preserve">'
                   f'<tspan fill="{th["muted"]}">{number}  </tspan><tspan fill="{th["text"]}">{t(cmd)}</tspan></text>'
                   f'{line(W - PAD, y, right, th["muted"], FS, "end")}</g>')
        vt_text += [number, cmd, right]
        y += LH
    css = font_face(VT, VT_FILE, "".join(vt_text)) + ANIM_CSS
    return svg(W, H, "Últimos commits: " + "; ".join(c["message"] for c in commits), "".join(out), css=css)


def sudo_card(host: str, th: dict, theme: str) -> str:
    H = 200
    out = [card(W, H, th)]
    vt_text = []
    out.append(prompt(host, "sudo rm -rf /", 48, th))
    vt_text.append(f"{host}:~$ sudo rm -rf /")
    ask = "[sudo] contraseña de visitante: "
    out.append(line(PAD, 82, ask, th["text"]))
    vt_text.append(ask)
    adv = font_advance(VT_FILE) * FS
    for i in range(8):
        out.append(f'<g class="pop" style="animation-delay:{.6 + i * .18:.2f}s">'
                   f'{line(PAD + (len(ask) + i) * adv, 82, "*", th["text"])}</g>')
    vt_text.append("*")
    msgs = [("visitante no está en el archivo sudoers.", RED[theme], 2.4),
            ("Este incidente será reportado.", RED[theme], 2.8),
            ("(buen intento)", th["muted"], 3.6)]
    y = 112
    for text, color, delay in msgs:
        out.append(f'<g class="fade" style="animation-delay:{delay}s">{line(PAD, y, text, color)}</g>')
        vt_text.append(text)
        y += LH
    out.append(f'<g class="fade" style="animation-delay:4s">{prompt(host, "", y + 4, th)}'
               f'<text class="blink" x="{PAD + (len(host) + 4) * adv:g}" y="{y + 4}" {VTF} font-size="{FS}" '
               f'fill="{th["accent"]}">▋</text></g>')
    vt_text.append("▋")
    css = font_face(VT, VT_FILE, "".join(vt_text)) + ANIM_CSS
    return svg(W, H, "sudo rm -rf /: visitante no está en el archivo sudoers. Este incidente será reportado.",
               "".join(out), css=css)


def guestbook_card(host: str, entries: list[dict], total: int, th: dict) -> str:
    rows = max(len(entries), 1)
    H = 74 + rows * LH + 30
    out = [card(W, H, th)]
    vt_text = []
    out.append(prompt(host, "tail visitas.log", 48, th))
    vt_text.append(f"{host}:~$ tail visitas.log")
    count = f"{total} firma{'s' if total != 1 else ''}"
    out.append(line(W - PAD, 48, count, th["muted"], FS, "end"))
    vt_text.append(count)
    y = 84
    if not entries:
        text = "-- vacío. Sé el primero en firmar --"
        out.append(line(PAD, y, text, th["muted"]))
        vt_text.append(text)
    for i, e in enumerate(entries):
        date, login, message = short_date(e["date"]), clean_message(e["login"]), clean_message(e["message"])
        out.append(f'<g class="fade" style="animation-delay:{.1 + i * .12:.2f}s">'
                   f'<text x="{PAD}" y="{y}" {VTF} font-size="{FS}" xml:space="preserve">'
                   f'<tspan fill="{th["muted"]}">[{t(date)}] </tspan><tspan fill="{th["accent2"]}">@{t(login)}</tspan>'
                   f'<tspan fill="{th["muted"]}">: </tspan><tspan fill="{th["text"]}">{t(message)}</tspan></text></g>')
        vt_text.append(f"[{date}] @{login}: {message}")
        y += LH
    css = font_face(VT, VT_FILE, "".join(vt_text)) + ANIM_CSS
    return svg(W, H, f"Libro de visitas: {count}", "".join(out), css=css)


def continue_card(th: dict) -> str:
    """Pantalla arcade CONTINUE? con cuenta regresiva; el README la envuelve en el enlace al portafolio."""
    Wc, Hc = 420, 150
    ac = ARCADE
    out = [f'<rect x=".5" y=".5" width="{Wc - 1}" height="{Hc - 1}" rx="10" fill="{ac["screen"]}" stroke="{th["accent"]}" stroke-opacity=".6"/>']
    out.append(label(Wc / 2, 42, "CONTINUE?", ac["score"], 16, "middle"))
    for d in range(10):
        out.append(f'<text class="cd" style="animation-delay:{9 - d}s" x="{Wc / 2}" y="104" {PXF} font-size="40" '
                   f'fill="{ac["text"]}" text-anchor="middle">{d}</text>')
    out.append(f'<g class="bl">{label(Wc / 2, 134, "PRESS START", ac["levels"][2], 10, "middle")}</g>')
    out.append(label(Wc - 16, 24, "CREDITS 01", ac["muted"], 7, "end"))
    out.append(f'<rect x="0" y="0" width="{Wc}" height="{Hc}" rx="10" fill="url(#scan)"/>')
    out.insert(0, '<defs><pattern id="scan" width="4" height="4" patternUnits="userSpaceOnUse">'
                  '<rect width="4" height="2" fill="#000" fill-opacity=".25"/></pattern></defs>')
    css = font_face(PIXEL, PIXEL_FILE, "CONTINUE?0123456789PRESS START CREDITS 01") + RETRO_CSS + CONSOLE_CSS
    return svg(Wc, Hc, "CONTINUE? PRESS START: abre el portafolio", "".join(out), css=css)


def konami_card(cfg: dict, th: dict) -> str:
    Wc, Hc = 420, 162
    fact = cfg["konami"].get("fact", "me debes un café.")
    out = [card(Wc, Hc, th)]
    for i in range(3):
        out.append(f'<g class="pop" style="animation-delay:{.3 + i * .25:.2f}s">'
                   f'{sprite(HEART, 28 + i * 36, 30, 4, "#ff5f56")}</g>')
    out.append(label(28, 84, "CHEAT ACTIVADO", th["muted"], 8))
    out.append(f'<g class="fade" style="animation-delay:1s">{label(28, 106, "30 VIDAS EXTRA", th["accent"], 13)}</g>')
    lines = wrap(fact, 32, 2)
    for i, ln in enumerate(lines):
        out.append(f'<g class="fade" style="animation-delay:{1.4 + i * .2:.1f}s">{line(28, 126 + i * 20, ln, th["text"], 20)}</g>')
    css = (font_face(VT, VT_FILE, "".join(lines)) + font_face(PIXEL, PIXEL_FILE, "CHEAT ACTIVADO30 VIDAS EXTRA")
           + ANIM_CSS)
    return svg(Wc, Hc, f"Código Konami: 30 vidas extra. {fact}", "".join(out), css=css)
