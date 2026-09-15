#!/usr/bin/env python3
"""Genera las imágenes SVG del perfil: banner, radar, tarjetas y heatmap.

Solo usa la biblioteca estándar de Python. Los datos salen de la API GraphQL
de GitHub con GH_TOKEN / GITHUB_TOKEN, o con `gh auth token` si lo corres en
tu computadora:

    python scripts/generate.py

Lo que se puede personalizar (banner, habilidades, proyectos) vive en
assets/profile.json. Cada imagen se genera en versión clara y oscura.
"""
from __future__ import annotations

import base64
import datetime as dt
import io
import json
import math
import os
import random
import subprocess
import sys
import urllib.parse
import urllib.request
from pathlib import Path
from xml.sax.saxutils import escape

ROOT = Path(__file__).resolve().parent.parent
ASSETS = ROOT / "assets"

THEMES = {
    "dark": {
        "bg": "#0d1117", "panel": "#161b22", "border": "#30363d", "grid": "#21262d",
        "text": "#e6edf3", "muted": "#8b949e", "accent": "#3fb950", "accent2": "#58a6ff",
        "levels": ["#21262d", "#0e4429", "#006d32", "#26a641", "#39d353"],
    },
    "light": {
        "bg": "#ffffff", "panel": "#f6f8fa", "border": "#d0d7de", "grid": "#eaeef2",
        "text": "#1f2328", "muted": "#656d76", "accent": "#1a7f37", "accent2": "#0969da",
        "levels": ["#ebedf0", "#9be9a8", "#40c463", "#30a14e", "#216e39"],
    },
}
MONO = "'JetBrains Mono','Fira Code','SF Mono',Menlo,Consolas,'DejaVu Sans Mono',monospace"
SANS = "-apple-system,BlinkMacSystemFont,'Segoe UI',Helvetica,Arial,sans-serif"
MESES = ["ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic"]

# Letras de 5x7 para el arte de iniciales del banner. Agrega las que necesites.
GLYPHS = {
    "A": [".###.", "#...#", "#...#", "#####", "#...#", "#...#", "#...#"],
    "R": ["####.", "#...#", "#...#", "####.", "#.#..", "#..#.", "#...#"],
}

ANIM_CSS = (
    ".fade{opacity:0;animation:fade .45s ease-out forwards}"
    ".pop{opacity:0;animation:fade .3s ease-out forwards}"
    ".type{animation:type var(--d) steps(var(--n)) forwards}"
    ".blink{animation:blink 1.1s steps(1) infinite}"
    ".grow{transform-origin:var(--o);animation:grow .9s cubic-bezier(.2,.8,.2,1) forwards;transform:scale(0)}"
    "@keyframes fade{from{opacity:0;transform:translateY(5px)}to{opacity:1;transform:none}}"
    "@keyframes type{to{transform:translateX(var(--w))}}"
    "@keyframes blink{50%{fill-opacity:0}}"
    "@keyframes grow{to{transform:scale(1)}}"
    "@media (prefers-reduced-motion:reduce){.fade,.pop,.grow{animation:none;opacity:1;transform:none}"
    ".type{display:none}.blink{animation:none}}"
)

# Pantalla arcade del banner. Siempre oscura, en los dos temas, como un CRT.
ARCADE = {
    "screen": "#050a06", "rain": "#39d353", "head": "#d2ffd2", "off": "#1b2a1f",
    "levels": ["#006d32", "#26a641", "#39d353"], "p1": "#ff5f56", "score": "#ffbd2e",
    "coin": "#58a6ff", "alien": "#d2a8ff", "ship": "#58a6ff", "text": "#e6edf3", "muted": "#8b949e",
}
RAIN_CHARS = "ｱｲｳｴｵｶｷｸｹｺｻｼｽｾｿﾀﾁﾂﾃﾄﾅﾆﾇﾈﾉﾊﾋﾌﾍﾎﾏﾐﾑﾒﾓﾔﾕﾖﾗﾘﾙﾚﾛﾜﾝ0123456789Z:=*+<>"
ALIEN = (
    ["..#######..", ".#########.", "##..###..##", "###########", "..##...##..", ".##.....##.", "#.........#"],
    ["..#######..", ".#########.", "##..###..##", "###########", "..##...##..", "...##.##...", "..#.....#.."],
)
SHIP = ["....#....", "...###...", ".#######.", "#########", "##.#.#.##"]

ARCADE_CSS = (
    # La columna mide 240px: arranca arriba de la pantalla y termina abajo de ella.
    ".rain{animation:rain var(--d) linear infinite}"
    "@keyframes rain{from{transform:translateY(-180px)}to{transform:translateY(292px)}}"
    ".pulse{animation:pulse 2.4s ease-in-out infinite}"
    "@keyframes pulse{50%{opacity:.5}}"
    ".march{animation:march 7s steps(28) infinite alternate}"
    "@keyframes march{to{transform:translateX(var(--mx))}}"
    ".f1{animation:f1 .6s steps(1) infinite}.f2{opacity:0;animation:f2 .6s steps(1) infinite}"
    "@keyframes f1{50%{opacity:0}}@keyframes f2{50%{opacity:1}}"
    ".ship{animation:ship 5.5s ease-in-out infinite alternate}"
    "@keyframes ship{to{transform:translateX(var(--sx))}}"
    ".shot{animation:shot 1.1s linear infinite}"
    "@keyframes shot{from{transform:translateY(0)}85%{opacity:1}to{transform:translateY(-150px);opacity:0}}"
    ".bl{animation:bl 1s steps(1) infinite}@keyframes bl{50%{opacity:0}}"
    ".swapA{animation:sa 8s steps(1) infinite}.swapB{opacity:0;animation:sb 8s steps(1) infinite}"
    "@keyframes sa{50%{opacity:0}}@keyframes sb{50%{opacity:1}}"
    "@media (prefers-reduced-motion:reduce){.rain,.pulse,.march,.f1,.ship,.bl,.swapA{animation:none}"
    ".f2,.swapB,.shot{animation:none;display:none}}"
)


# ---------------------------------------------------------------- datos ---

def get_token() -> str:
    for key in ("GH_TOKEN", "GITHUB_TOKEN"):
        if os.environ.get(key):
            return os.environ[key]
    try:
        out = subprocess.run(["gh", "auth", "token"], capture_output=True, text=True, check=True)
        return out.stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        sys.exit("Falta GH_TOKEN (o inicia sesión con `gh auth login`).")


def graphql(query: str, token: str) -> dict:
    req = urllib.request.Request(
        "https://api.github.com/graphql",
        data=json.dumps({"query": query}).encode(),
        headers={"Authorization": f"bearer {token}", "Content-Type": "application/json",
                 "User-Agent": "profile-generator"},
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        body = json.load(resp)
    if body.get("errors"):
        sys.exit(f"Error de GraphQL: {body['errors']}")
    return body["data"]


def fetch(cfg: dict, token: str) -> dict:
    user = cfg["user"]
    repo_fields = "name url homepageUrl stargazerCount primaryLanguage { name color }"
    aliases = "\n".join(
        f'p{i}: repository(owner: "{user}", name: "{p["repo"]}") {{ {repo_fields} }}'
        for i, p in enumerate(cfg["projects"])
    )
    query = f"""{{
      user(login: "{user}") {{
        createdAt
        contributionsCollection {{
          totalCommitContributions
          contributionCalendar {{
            totalContributions
            weeks {{ contributionDays {{ date contributionCount }} }}
          }}
        }}
        repositories(ownerAffiliations: OWNER, isFork: false, first: 100) {{
          totalCount
          nodes {{
            isPrivate
            stargazerCount
            languages(first: 10, orderBy: {{field: SIZE, direction: DESC}}) {{
              edges {{ size node {{ name color }} }}
            }}
          }}
        }}
      }}
      {aliases}
    }}"""
    return graphql(query, token)


def streaks(counts: list[int]) -> tuple[int, int]:
    longest = run = 0
    for c in counts:
        run = run + 1 if c else 0
        longest = max(longest, run)
    i = len(counts) - 1
    if i >= 0 and counts[i] == 0:  # hoy todavía puede no tener actividad
        i -= 1
    current = 0
    while i >= 0 and counts[i]:
        current += 1
        i -= 1
    return current, longest


def language_mix(repos: list[dict], include_private: bool, ignore: set[str]) -> list[tuple[str, float, str]]:
    sizes: dict[str, int] = {}
    colors: dict[str, str] = {}
    for repo in repos:
        if repo["isPrivate"] and not include_private:
            continue
        for edge in repo["languages"]["edges"]:
            name = edge["node"]["name"]
            if name in ignore:
                continue
            sizes[name] = sizes.get(name, 0) + edge["size"]
            colors[name] = edge["node"]["color"] or "#8b949e"
    total = sum(sizes.values()) or 1
    ranked = sorted(sizes.items(), key=lambda kv: -kv[1])
    mix = [(name, size * 100 / total, colors[name]) for name, size in ranked[:5]]
    rest = sum(size for _, size in ranked[5:])
    if rest:
        mix.append(("Otros", rest * 100 / total, "#8b949e"))
    return mix


# ------------------------------------------------------------ utilerías ---

def a(value) -> str:
    return escape(str(value), {'"': "&quot;"})


def t(value) -> str:
    return escape(str(value))


def svg(width: int, height: int, label: str, body: str, css: str = ANIM_CSS) -> str:
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}" role="img" aria-label="{a(label)}">'
        f"<title>{t(label)}</title><style>{css}</style>{body}</svg>\n"
    )


def card(width: int, height: int, th: dict) -> str:
    return (f'<rect x=".5" y=".5" width="{width - 1}" height="{height - 1}" rx="10" '
            f'fill="{th["bg"]}" stroke="{th["border"]}"/>')


def heading(x: int, y: int, cmd: str, th: dict) -> str:
    return (f'<text x="{x}" y="{y}" font-family="{MONO}" font-size="14" font-weight="600">'
            f'<tspan fill="{th["accent"]}">$</tspan> <tspan fill="{th["text"]}">{t(cmd)}</tspan></text>')


def wrap(text: str, width: int, max_lines: int) -> list[str]:
    lines, cur = [], ""
    for word in text.split():
        if cur and len(cur) + 1 + len(word) > width:
            lines.append(cur)
            cur = word
        else:
            cur = f"{cur} {word}".strip()
    if cur:
        lines.append(cur)
    if len(lines) > max_lines:
        lines = lines[:max_lines]
        lines[-1] = lines[-1][: width - 1].rstrip() + "…"
    return lines


# -------------------------------------------------------------- dibujos ---

def banner(cfg: dict, user: dict, th: dict, score: int) -> str:
    W, H = 1200, 330
    b = cfg["banner"]
    host = b["host"]
    fs, cw = 19, 19 * 0.62  # tamaño de fuente y ancho estimado de carácter
    x0, y0, gap = 60, 106, 31
    out = [f'<rect width="{W}" height="{H}" fill="{th["bg"]}"/>',
           f'<rect x="20.5" y="16.5" width="1159" height="297" rx="12" fill="{th["panel"]}" stroke="{th["border"]}"/>',
           f'<line x1="21" y1="52.5" x2="1179" y2="52.5" stroke="{th["border"]}"/>']
    for i, color in enumerate(("#ff5f56", "#ffbd2e", "#27c93f")):
        out.append(f'<circle cx="{46 + i * 22}" cy="34.5" r="6" fill="{color}"/>')
    out.append(f'<text x="600" y="39" text-anchor="middle" font-family="{MONO}" font-size="13" '
               f'fill="{th["muted"]}">{t(host)}: ~</text>')

    def prompt_tspans() -> str:
        return (f'<tspan fill="{th["accent"]}">{t(host)}</tspan><tspan fill="{th["muted"]}">:</tspan>'
                f'<tspan fill="{th["accent2"]}">~</tspan><tspan fill="{th["muted"]}">$ </tspan>')

    # Línea 1: el comando se "escribe" con una tapa que se desliza a la derecha.
    cmd = b["command"]
    cmd_x = x0 + (len(host) + 4) * cw
    cmd_w = len(cmd) * cw + 8
    type_start, type_dur = 0.7, len(cmd) * 0.055
    out.append(f'<g class="pop" style="animation-delay:.2s"><text x="{x0}" y="{y0}" font-family="{MONO}" '
               f'font-size="{fs}" xml:space="preserve">{prompt_tspans()}<tspan fill="{th["text"]}">{t(cmd)}</tspan></text></g>')
    out.append(f'<rect class="type" x="{cmd_x - 2:.1f}" y="{y0 - fs}" width="{cmd_w:.1f}" height="{fs + 8}" '
               f'fill="{th["panel"]}" style="--w:{cmd_w:.1f}px;--n:{len(cmd)};--d:{type_dur:.2f}s;'
               f'animation-delay:{type_start}s"/>')

    delay = type_start + type_dur + 0.3
    y = y0
    for key, value in b["lines"]:
        y += gap
        value_color = th["text"]
        dot = ""
        if value.startswith("●"):
            dot = f'<tspan fill="{th["accent"]}">● </tspan>'
            value = value[1:].strip()
        out.append(
            f'<g class="fade" style="animation-delay:{delay:.2f}s"><text y="{y}" font-family="{MONO}" font-size="{fs}">'
            f'<tspan x="{x0}" fill="{th["muted"]}">›</tspan>'
            f'<tspan x="{x0 + 2 * cw:.1f}" fill="{th["accent2"]}">{t(key)}</tspan>'
            f'<tspan x="{x0 + 13 * cw:.1f}" fill="{value_color}">{dot}{t(value)}</tspan></text></g>')
        delay += 0.18
    y += gap
    out.append(f'<g class="fade" style="animation-delay:{delay:.2f}s"><text x="{x0}" y="{y}" font-family="{MONO}" '
               f'font-size="{fs}" xml:space="preserve">{prompt_tspans()}<tspan class="blink" '
               f'fill="{th["accent"]}">▋</tspan></text></g>')

    out.append(arcade(cfg.get("initials", ""), score, user["createdAt"][:4], th["accent"]))
    return svg(W, H, f"{host} — {cmd}", "".join(out), css=ANIM_CSS + ARCADE_CSS)


def sprite(rows: list[str], x: float, y: float, px: int, color: str) -> str:
    d = "".join(f"M{x + c * px:g} {y + r * px:g}h{px}v{px}h-{px}z"
                for r, row in enumerate(rows) for c, ch in enumerate(row) if ch == "#")
    return f'<path d="{d}" fill="{color}"/>'


def arcade(initials: str, score: int, year: str, accent: str) -> str:
    """Pantalla CRT con lluvia tipo Matrix, las iniciales en píxeles y detalles arcade."""
    rng = random.Random(initials + year)  # determinista: el SVG solo cambia si cambian los datos
    ac = ARCADE
    X, Y, SW, SH = 784, 62, 380, 242
    cx = X + SW / 2
    out = [
        "<defs>"
        f'<clipPath id="screen"><rect x="{X}" y="{Y}" width="{SW}" height="{SH}" rx="8"/></clipPath>'
        '<pattern id="scan" width="4" height="4" patternUnits="userSpaceOnUse">'
        '<rect width="4" height="2" fill="#000" fill-opacity=".28"/></pattern>'
        '<radialGradient id="vig" r="70%"><stop offset="60%" stop-color="#000" stop-opacity="0"/>'
        '<stop offset="100%" stop-color="#000" stop-opacity=".65"/></radialGradient>'
        '<filter id="glow" x="-20%" y="-20%" width="140%" height="140%"><feGaussianBlur stdDeviation="2.2" result="b"/>'
        '<feMerge><feMergeNode in="b"/><feMergeNode in="SourceGraphic"/></feMerge></filter>'
        "</defs>",
        f'<rect x="{X}" y="{Y}" width="{SW}" height="{SH}" rx="8" fill="{ac["screen"]}"/>',
        '<g clip-path="url(#screen)">',
    ]

    # Lluvia: columnas de 16 caracteres que caen a distinta velocidad; la cabeza brilla más.
    for x in range(X + 8, X + SW - 4, 16):
        small = rng.random() < 0.4
        dur = rng.uniform(3.5, 8.0)
        spans = "".join(
            f'<tspan x="{x}" dy="15" fill="{ac["head"] if j == 15 else ac["rain"]}" '
            f'fill-opacity="{1 if j == 15 else (j + 1) / 18:.2f}">{t(rng.choice(RAIN_CHARS))}</tspan>'
            for j in range(16))
        out.append(f'<g class="rain" style="--d:{dur:.2f}s;animation-delay:-{rng.uniform(0, dur):.2f}s" '
                   f'opacity="{.35 if small else .6}"><text font-family="{MONO}" '
                   f'font-size="{11 if small else 14}">{spans}</text></g>')

    # Nave que dispara desde abajo (va antes de las iniciales para que queden encima).
    ship_w = len(SHIP[0]) * 3
    sx, sy = X + 14, Y + SH - 38
    out.append(f'<g class="ship" style="--sx:{SW - 28 - ship_w}px">'
               f'<rect class="shot" x="{sx + ship_w / 2 - 1.5:g}" y="{sy - 10}" width="3" height="8" fill="{ac["score"]}"/>'
               f'{sprite(SHIP, sx, sy, 3, ac["ship"])}</g>')

    # Iniciales: los píxeles se "decodifican" en orden aleatorio y luego laten en diagonal.
    letters = [GLYPHS[ch] for ch in initials if ch in GLYPHS]
    if letters:
        cell, pitch = 19, 22
        cols = len(letters) * 6 - 1
        ax = cx - (cols * pitch - (pitch - cell)) / 2
        ay = Y + 48
        off, on = [], []
        for li, glyph in enumerate(letters):
            for r, row in enumerate(glyph):
                for c, ch in enumerate(row):
                    col = li * 6 + c
                    px, py = ax + col * pitch, ay + r * pitch
                    if ch == "#":
                        color = ac["levels"][(r * 7 + col * 3) % 3]
                        on.append(f'<g class="pop" style="animation-delay:{rng.uniform(.3, 1.6):.2f}s">'
                                  f'<rect class="pulse" style="animation-delay:{(col + r) * .12:.2f}s" x="{px:g}" '
                                  f'y="{py}" width="{cell}" height="{cell}" rx="3" fill="{color}"/></g>')
                    else:
                        off.append(f'<rect x="{px:g}" y="{py}" width="{cell}" height="{cell}" rx="3" '
                                   f'fill="{ac["off"]}" fill-opacity=".55"/>')
        out.append("".join(off))
        out.append(f'<g filter="url(#glow)">{"".join(on)}</g>')

    # Alien que marcha de lado a lado con dos cuadros de animación.
    alien_w = len(ALIEN[0][0]) * 3
    alx, aly = X + 12, Y + 25
    out.append(f'<g class="march" style="--mx:{SW - 24 - alien_w}px">'
               f'<g class="f1">{sprite(ALIEN[0], alx, aly, 3, ac["alien"])}</g>'
               f'<g class="f2">{sprite(ALIEN[1], alx, aly, 3, ac["alien"])}</g></g>')

    hud = f'font-family="{MONO}" font-size="12" font-weight="700"'
    out.append(f'<text class="bl" x="{X + 14}" y="{Y + 20}" {hud} fill="{ac["p1"]}">1UP</text>')
    out.append(f'<text x="{X + SW - 14}" y="{Y + 20}" text-anchor="end" {hud} fill="{ac["text"]}">'
               f'HI-SCORE <tspan fill="{ac["score"]}">{score:06d}</tspan></text>')
    out.append(f'<g class="swapA"><text class="bl" x="{cx:g}" y="{Y + SH - 10}" text-anchor="middle" {hud} '
               f'letter-spacing="2" fill="{ac["coin"]}">INSERT COIN</text></g>')
    out.append(f'<g class="swapB"><text x="{cx:g}" y="{Y + SH - 10}" text-anchor="middle" {hud} '
               f'fill="{ac["muted"]}">EN GITHUB DESDE {year}</text></g>')
    out.append("</g>")

    out.append(f'<rect x="{X}" y="{Y}" width="{SW}" height="{SH}" rx="8" fill="url(#scan)"/>'
               f'<rect x="{X}" y="{Y}" width="{SW}" height="{SH}" rx="8" fill="url(#vig)"/>'
               f'<rect x="{X + .5}" y="{Y + .5}" width="{SW - 1}" height="{SH - 1}" rx="8" fill="none" '
               f'stroke="{accent}" stroke-opacity=".55"/>')
    return "".join(out)


def radar(cfg: dict, th: dict) -> str:
    W, H = 420, 400
    skills = cfg["skills"]
    n = len(skills)
    cx, cy, r = 210, 218, 110
    out = [card(W, H, th), heading(24, 36, "./skills --autoevaluacion", th)]

    def point(i: int, value: float) -> tuple[float, float]:
        ang = -math.pi / 2 + i * 2 * math.pi / n
        return cx + math.cos(ang) * r * value / 10, cy + math.sin(ang) * r * value / 10

    for ring in (2, 4, 6, 8, 10):
        pts = " ".join(f"{x:.1f},{y:.1f}" for x, y in (point(i, ring) for i in range(n)))
        out.append(f'<polygon points="{pts}" fill="none" stroke="{th["border"]}" stroke-width="1"/>')
    for i in range(n):
        x, y = point(i, 10)
        out.append(f'<line x1="{cx}" y1="{cy}" x2="{x:.1f}" y2="{y:.1f}" stroke="{th["border"]}"/>')
    pts = " ".join(f"{x:.1f},{y:.1f}" for x, y in (point(i, s["value"]) for i, s in enumerate(skills)))
    dots = "".join(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="3.5" fill="{th["accent"]}"/>'
                   for x, y in (point(i, s["value"]) for i, s in enumerate(skills)))
    out.append(f'<g class="grow" style="--o:{cx}px {cy}px;animation-delay:.2s">'
               f'<polygon points="{pts}" fill="{th["accent"]}" fill-opacity=".22" stroke="{th["accent"]}" '
               f'stroke-width="2" stroke-linejoin="round"/>{dots}</g>')
    for i, s in enumerate(skills):
        ang = -math.pi / 2 + i * 2 * math.pi / n
        lx, ly = cx + math.cos(ang) * (r + 18), cy + math.sin(ang) * (r + 18)
        cos = math.cos(ang)
        anchor = "middle" if abs(cos) < 0.3 else ("start" if cos > 0 else "end")
        ly += 5 + math.sin(ang) * 6
        out.append(f'<text x="{lx:.1f}" y="{ly:.1f}" text-anchor="{anchor}" font-family="{SANS}" font-size="13" '
                   f'fill="{th["text"]}">{t(s["name"])} <tspan fill="{th["muted"]}">{s["value"]}</tspan></text>')
    return svg(W, H, "Radar de habilidades", "".join(out))


def languages_card(mix: list[tuple[str, float, str]], th: dict) -> str:
    W, H = 420, 195
    out = [card(W, H, th), heading(24, 36, "cat lenguajes.txt", th)]
    bar_x, bar_w = 24, 372
    out.append(f'<clipPath id="bar"><rect x="{bar_x}" y="54" width="{bar_w}" height="10" rx="5"/></clipPath>')
    out.append(f'<g clip-path="url(#bar)"><rect x="{bar_x}" y="54" width="{bar_w}" height="10" fill="{th["grid"]}"/>')
    x = bar_x
    for i, (_, pct, color) in enumerate(mix):
        w = bar_w * pct / 100
        out.append(f'<rect class="pop" style="animation-delay:{.15 + i * .08:.2f}s" x="{x:.1f}" y="54" '
                   f'width="{w + .5:.1f}" height="10" fill="{color}"/>')
        x += w
    out.append("</g>")
    for i, (name, pct, color) in enumerate(mix):
        col, row = i % 2, i // 2
        lx, ly = 24 + col * 198, 100 + row * 32
        out.append(f'<g class="fade" style="animation-delay:{.3 + i * .06:.2f}s">'
                   f'<circle cx="{lx + 5}" cy="{ly - 4}" r="5" fill="{color}"/>'
                   f'<text x="{lx + 18}" y="{ly}" font-family="{SANS}" font-size="13" fill="{th["text"]}">{t(name)}</text>'
                   f'<text x="{lx + 176}" y="{ly}" text-anchor="end" font-family="{MONO}" font-size="12" '
                   f'fill="{th["muted"]}">{pct:.1f}%</text></g>')
    return svg(W, H, "Lenguajes más usados", "".join(out))


def stats_card(stats: list[tuple[str, str]], th: dict) -> str:
    W, H = 420, 195
    out = [card(W, H, th), heading(24, 36, "git log --stats", th),
           f'<text x="396" y="36" text-anchor="end" font-family="{SANS}" font-size="12" '
           f'fill="{th["muted"]}">últimos 12 meses</text>']
    for i, (value, label) in enumerate(stats):
        col, row = i % 3, i // 3
        x, y = 24 + col * 132, 94 + row * 62
        out.append(f'<g class="fade" style="animation-delay:{.15 + i * .07:.2f}s">'
                   f'<text x="{x}" y="{y}" font-family="{MONO}" font-size="26" font-weight="700" '
                   f'fill="{th["accent"] if i == 0 else th["text"]}">{t(value)}</text>'
                   f'<text x="{x}" y="{y + 20}" font-family="{SANS}" font-size="12" fill="{th["muted"]}">{t(label)}</text></g>')
    return svg(W, H, "Estadísticas de GitHub", "".join(out))


def heatmap(weeks: list[dict], total: int, th: dict) -> str:
    W, H = 880, 215
    pitch, cell = 15, 11
    x0, y0 = 52, 74
    counts = sorted(d["contributionCount"] for w in weeks for d in w["contributionDays"] if d["contributionCount"])
    quart = [counts[min(len(counts) - 1, int(len(counts) * p))] for p in (.25, .5, .75)] if counts else []

    def level(c: int) -> int:
        return 0 if not c else 1 + sum(c > q for q in quart)

    out = [card(W, H, th), heading(24, 36, "git log --graph", th),
           f'<text x="856" y="36" text-anchor="end" font-family="{SANS}" font-size="12" '
           f'fill="{th["muted"]}">{total} contribuciones en el último año</text>']
    for row, label in ((1, "lun"), (3, "mié"), (5, "vie")):
        out.append(f'<text x="{x0 - 8}" y="{y0 + row * pitch + 9}" text-anchor="end" font-family="{SANS}" '
                   f'font-size="10" fill="{th["muted"]}">{label}</text>')
    last_month, last_x = None, -99
    for wi, week in enumerate(weeks):
        x = x0 + wi * pitch
        first = week["contributionDays"][0]["date"]
        month = int(first[5:7])
        if month != last_month and x - last_x >= 3 * pitch:
            out.append(f'<text x="{x}" y="{y0 - 10}" font-family="{SANS}" font-size="10" '
                       f'fill="{th["muted"]}">{MESES[month - 1]}</text>')
            last_x = x
        last_month = month
        cells = []
        for day in week["contributionDays"]:
            c = day["contributionCount"]
            cells.append(f'<rect x="{x}" y="{y0 + weekday(day["date"]) * pitch}" width="{cell}" height="{cell}" rx="2" '
                         f'fill="{th["levels"][level(c)]}"><title>{c} el {day["date"]}</title></rect>')
        out.append(f'<g class="pop" style="animation-delay:{wi * .012:.3f}s">{"".join(cells)}</g>')
    lx = 856 - 5 * pitch - 22
    out.append(f'<text x="{lx - 6}" y="{H - 18}" text-anchor="end" font-family="{SANS}" font-size="10" '
               f'fill="{th["muted"]}">menos</text>')
    for i in range(5):
        out.append(f'<rect x="{lx + i * pitch}" y="{H - 27}" width="{cell}" height="{cell}" rx="2" fill="{th["levels"][i]}"/>')
    out.append(f'<text x="{lx + 5 * pitch + 2}" y="{H - 18}" font-family="{SANS}" font-size="10" '
               f'fill="{th["muted"]}">más</text>')
    return svg(W, H, "Gráfica de contribuciones", "".join(out))


def weekday(date: str) -> int:
    """Día de la semana con domingo = 0, como la gráfica de GitHub."""
    return (dt.date.fromisoformat(date).weekday() + 1) % 7


def project_card(project: dict, repo: dict | None, th: dict, user: str, image: str | None) -> str:
    """Tarjeta de proyecto. Con `image` (JPEG en base64) muestra la captura en una ventana de navegador."""
    W = 400
    bar, shot_h = 26, 170
    top = bar + shot_h if image else 0
    H = 140 + top
    out = [card(W, H, th)]
    if image:
        home = (repo or {}).get("homepageUrl")
        address = urllib.parse.urlparse(home).netloc if home else f"github.com/{user}/{project['repo']}"
        out.append(f'<clipPath id="shot"><path d="M.5 {top}V10.5A10 10 0 0 1 10.5 .5H389.5A10 10 0 0 1 399.5 10.5V{top}Z"/></clipPath>'
                   f'<g clip-path="url(#shot)"><rect width="{W}" height="{bar}" fill="{th["panel"]}"/>'
                   + "".join(f'<circle cx="{16 + i * 13}" cy="13" r="4" fill="{c}"/>'
                             for i, c in enumerate(("#ff5f56", "#ffbd2e", "#27c93f")))
                   + f'<text x="{W / 2:g}" y="17" text-anchor="middle" font-family="{MONO}" font-size="10" '
                     f'fill="{th["muted"]}">{t(address)}</text>'
                     f'<image href="data:image/jpeg;base64,{image}" y="{bar}" width="{W}" height="{shot_h}" '
                     f'preserveAspectRatio="xMidYMin slice"/></g>'
                     f'<path d="M1 {bar + .5}H{W - 1}M1 {top + .5}H{W - 1}" stroke="{th["border"]}"/>')
    out.append(f'<text x="24" y="{top + 38}" font-family="{MONO}" font-size="16" font-weight="700" fill="{th["accent2"]}">'
               f'<tspan fill="{th["muted"]}">~/</tspan>{t(project["title"])}</text>')
    for i, line in enumerate(wrap(project["description"], 50, 2)):
        out.append(f'<text x="24" y="{top + 66 + i * 19}" font-family="{SANS}" font-size="13" '
                   f'fill="{th["text"]}">{t(line)}</text>')
    x = 24
    lang = (repo or {}).get("primaryLanguage")
    if lang:
        out.append(f'<circle cx="{x + 5}" cy="{H - 26}" r="5" fill="{lang["color"] or th["muted"]}"/>'
                   f'<text x="{x + 16}" y="{H - 22}" font-family="{SANS}" font-size="12" '
                   f'fill="{th["muted"]}">{t(lang["name"])}</text>')
        x += 30 + len(lang["name"]) * 7
    if repo and repo["stargazerCount"]:
        out.append(f'<text x="{x}" y="{H - 22}" font-family="{SANS}" font-size="12" '
                   f'fill="{th["muted"]}">★ {repo["stargazerCount"]}</text>')
    if repo and repo.get("homepageUrl"):
        out.append(f'<text x="376" y="{H - 22}" text-anchor="end" font-family="{MONO}" font-size="12" '
                   f'fill="{th["accent"]}">demo ↗</text>')
    return svg(W, H, project["title"], "".join(out), css="")


# ------------------------------------------------------ fuentes retro ---
# Un <img> con SVG no puede cargar fuentes externas, así que se incrustan
# recortadas a los caracteres que usa cada imagen (requiere fonttools).

FONTS = ROOT / "scripts" / "fonts"
VT, VT_FILE = "VT323", "VT323-Regular.ttf"
PIXEL, PIXEL_FILE = "PressStart2P", "PressStart2P-Regular.ttf"
PLATFORMS = {"spotify": ("SPOTIFY", "#1db954"), "youtube": ("YOUTUBE", "#ff0033")}

RETRO_CSS = (
    ".bar{transform:scaleX(0);animation:bar 1.2s cubic-bezier(.2,.8,.2,1) forwards}"
    "@keyframes bar{to{transform:scaleX(1)}}"
    ".bl{animation:bl 1s steps(1) infinite}@keyframes bl{50%{opacity:0}}"
    ".spin{animation:spin 3s linear infinite}@keyframes spin{to{transform:rotate(360deg)}}"
    ".eq{animation:eq .9s ease-in-out infinite alternate}"
    "@keyframes eq{from{transform:scaleY(.2)}to{transform:scaleY(1)}}"
    "@media (prefers-reduced-motion:reduce){.bar{animation:none;transform:none}.bl,.spin,.eq{animation:none}}"
)


def font_face(family: str, file: str, text: str) -> str:
    from fontTools import subset
    from fontTools.ttLib import TTFont

    font = TTFont(FONTS / file, recalcTimestamp=False)  # sin timestamp: el SVG no cambia entre corridas
    subsetter = subset.Subsetter(subset.Options())
    subsetter.populate(text=text + " ")
    subsetter.subset(font)
    buf = io.BytesIO()
    font.save(buf)
    data = base64.b64encode(buf.getvalue()).decode()
    return f"@font-face{{font-family:'{family}';src:url(data:font/ttf;base64,{data}) format('truetype')}}"


def font_advance(file: str) -> float:
    """Ancho de un carácter como fracción del tamaño de fuente (las dos fuentes son monoespaciadas)."""
    from fontTools.ttLib import TTFont

    font = TTFont(FONTS / file, lazy=True)
    return font["hmtx"]["a"][0] / font["head"].unitsPerEm


def whoami_card(cfg: dict, th: dict) -> str:
    w = cfg["whoami"]
    W, pad, fs, lh = 880, 32, 24, 27
    adv = font_advance(VT_FILE)
    cols = int(540 / (adv * fs))
    vt = f"font-family=\"'{VT}',monospace\""
    px = f"font-family=\"'{PIXEL}',monospace\""
    vt_text, px_text = [], []
    out = [card(W, 0, th)]  # la altura se ajusta al final

    y = 48
    out.append(f'<text x="{pad}" y="{y}" {px} font-size="12" fill="{th["accent"]}">PLAYER 1</text>'
               f'<text class="bl" x="{W - pad}" y="{y}" text-anchor="end" {px} font-size="10" '
               f'fill="{th["accent"]}">ONLINE</text>'
               f'<path d="M{pad} {y + 16.5}H{W - pad}" stroke="{th["border"]}" stroke-dasharray="4 4"/>')
    px_text += ["PLAYER 1", "ONLINE"]

    # El texto va sin animación de entrada: es el contenido principal y debe verse siempre.
    y += 56
    for line in wrap(w["intro"], cols, 99):
        out.append(f'<text x="{pad}" y="{y}" {vt} font-size="{fs}" fill="{th["text"]}">{t(line)}</text>')
        vt_text.append(line)
        y += lh
    y += 14
    for label, text in w["items"]:
        for i, line in enumerate(wrap(f"{label}: {text}", cols - 2, 99)):
            if i == 0:
                content = (f'<tspan fill="{th["accent"]}">&gt; </tspan><tspan fill="{th["accent2"]}">{t(label)}:</tspan>'
                           f'<tspan fill="{th["text"]}">{t(line[len(label) + 1:])}</tspan>')
                x = pad
            else:
                content, x = t(line), pad + 2 * adv * fs
            out.append(f'<text x="{x:g}" y="{y}" {vt} font-size="{fs}" fill="{th["text"]}" '
                       f'xml:space="preserve">{content}</text>')
            vt_text.append("> " + line)
            y += lh
        y += 6
    left_end = y

    # Ficha de personaje a la derecha.
    bx, by = 600, 96
    bw = W - pad - bx
    vfs = 22
    vcols = int((bw - 36) / (adv * vfs))
    box = []
    yy = by + 30
    box.append(f'<text x="{bx + 18}" y="{yy}" {px} font-size="10" fill="{th["accent"]}">FICHA</text>')
    px_text.append("FICHA")
    yy += 28
    for label, value in w.get("sheet", []):
        box.append(f'<text x="{bx + 18}" y="{yy}" {px} font-size="8" fill="{th["muted"]}">{t(label)}</text>')
        px_text.append(label)
        for i, line in enumerate(wrap(value, vcols, 2)):
            box.append(f'<text x="{bx + 18}" y="{yy + 22 + i * 20}" {vt} font-size="{vfs}" '
                       f'fill="{th["text"]}">{t(line)}</text>')
            vt_text.append(line)
            yy += 20
        yy += 30
    bar_w = bw - 36
    for i, (label, value) in enumerate(w.get("bars", [])):
        box.append(f'<text x="{bx + 18}" y="{yy}" {px} font-size="8" fill="{th["muted"]}">{t(label)}</text>'
                   f'<text x="{bx + bw - 18}" y="{yy}" text-anchor="end" {px} font-size="8" '
                   f'fill="{th["muted"]}">{round(value * 100)}%</text>'
                   f'<rect x="{bx + 18}" y="{yy + 8}" width="{bar_w}" height="10" fill="{th["grid"]}"/>'
                   f'<rect class="bar" style="transform-origin:{bx + 18}px 0;animation-delay:{.4 + i * .15:.2f}s" '
                   f'x="{bx + 18}" y="{yy + 8}" width="{bar_w * value:.1f}" height="10" fill="{th["accent"]}"/>'
                   f'<path d="{"".join(f"M{bx + 18 + s}.5 {yy + 8}v10" for s in range(8, bar_w, 8))}" '
                   f'stroke="{th["bg"]}" stroke-width="2"/>')
        px_text.append(f"{label}{round(value * 100)}%")
        yy += 38
    box_h = yy - by
    out.append(f'<rect x="{bx + .5}" y="{by + .5}" width="{bw - 1}" height="{box_h}" rx="6" '
               f'fill="{th["panel"]}" stroke="{th["border"]}"/>')
    out.extend(box)

    H = max(left_end, by + box_h) + 24
    out[0] = card(W, H, th)
    css = (font_face(VT, VT_FILE, "".join(vt_text)) + font_face(PIXEL, PIXEL_FILE, "".join(px_text))
           + ANIM_CSS + RETRO_CSS)
    return svg(W, H, " ".join([w["intro"]] + [f"{a}: {b}" for a, b in w["items"]]), "".join(out), css=css)


def playlist_card(pl: dict, th: dict) -> str:
    W, H = 420, 150
    name, color = PLATFORMS.get(pl["platform"], (pl["platform"].upper(), th["accent"]))
    vt = f"font-family=\"'{VT}',monospace\""
    px = f"font-family=\"'{PIXEL}',monospace\""
    cx, cy, r = 78, 75, 50
    out = [card(W, H, th)]

    def polar(angle: float, radius: float) -> str:
        rad = math.radians(angle)
        return f"{cx + math.cos(rad) * radius:.1f} {cy + math.sin(rad) * radius:.1f}"

    grooves = "".join(f'<circle cx="{cx}" cy="{cy}" r="{g}" fill="none" stroke="#2b2b2b"/>' for g in (44, 37, 30, 24))
    out.append(f'<g class="spin" style="transform-origin:{cx}px {cy}px">'
               f'<circle cx="{cx}" cy="{cy}" r="{r}" fill="#0b0b0b"/>{grooves}'
               f'<path d="M{cx} {cy}L{polar(-115, r)}A{r} {r} 0 0 1 {polar(-75, r)}Z" fill="#fff" fill-opacity=".1"/>'
               f'<circle cx="{cx}" cy="{cy}" r="17" fill="{color}"/>'
               f'<circle cx="{cx}" cy="{cy}" r="3" fill="{th["bg"]}"/></g>')

    tx = 150
    title = pl["title"] if len(pl["title"]) <= 22 else pl["title"][:21] + "…"
    subtitle = f"{name} · {pl['kind']}"
    out.append(f'<rect class="bl" x="{tx}" y="31" width="6" height="6" fill="{color}"/>'
               f'<text x="{tx + 14}" y="38" {px} font-size="8" fill="{th["muted"]}">NOW PLAYING</text>'
               f'<text x="{tx}" y="74" {vt} font-size="30" fill="{th["text"]}">{t(title)}</text>'
               f'<text x="{tx}" y="98" {vt} font-size="21" fill="{th["muted"]}">{t(subtitle)}</text>'
               f'<rect x="{tx + .5}" y="110.5" width="80" height="22" rx="3" fill="none" stroke="{color}"/>'
               f'<text x="{tx + 40.5}" y="126" text-anchor="middle" {px} font-size="9" fill="{color}">PLAY</text>')
    base = 132
    for i, (dur, delay) in enumerate(((.8, .1), (.55, .4), (.95, .2), (.65, .6), (.75, .3), (.5, .5), (.9, .0))):
        x = 312 + i * 12
        out.append(f'<rect class="eq" style="transform-origin:{x}px {base}px;animation-duration:{dur}s;'
                   f'animation-delay:-{delay}s" x="{x}" y="{base - 40}" width="7" height="40" fill="{color}" '
                   f'fill-opacity=".85"/>')
    css = (font_face(VT, VT_FILE, title + subtitle) + font_face(PIXEL, PIXEL_FILE, "NOW PLAYING PLAY")
           + RETRO_CSS)
    return svg(W, H, f"{pl['title']} en {name}", "".join(out), css=css)


# ----------------------------------------------------------------- main ---

def write(name: str, content: str) -> None:
    (ASSETS / name).write_text(content, encoding="utf-8", newline="\n")
    print(f"  assets/{name}")


def main() -> None:
    cfg = json.loads((ASSETS / "profile.json").read_text(encoding="utf-8"))
    data = fetch(cfg, get_token())
    user = data["user"]
    coll = user["contributionsCollection"]
    weeks = coll["contributionCalendar"]["weeks"]
    counts = [d["contributionCount"] for w in weeks for d in w["contributionDays"]]
    current, longest = streaks(counts)
    repos = user["repositories"]
    stats = [
        (str(coll["contributionCalendar"]["totalContributions"]), "contribuciones"),
        (str(coll["totalCommitContributions"]), "commits"),
        (str(sum(1 for c in counts if c)), "días activos"),
        (f"{current}d", "racha actual"),
        (f"{longest}d", "racha más larga"),
        (str(repos["totalCount"]), "repositorios"),
    ]
    mix = language_mix(repos["nodes"], cfg.get("include_private_languages", False),
                       set(cfg.get("ignore_languages", [])))

    # Capturas opcionales: "image" en cada proyecto, ruta relativa a la raíz del repo.
    images = {p["repo"]: base64.b64encode((ROOT / p["image"]).read_bytes()).decode()
              for p in cfg["projects"] if p.get("image")}

    print("Generando:")
    for name, th in THEMES.items():
        write(f"banner-{name}.svg", banner(cfg, user, th, coll["contributionCalendar"]["totalContributions"]))
        write(f"radar-{name}.svg", radar(cfg, th))
        write(f"card-langs-{name}.svg", languages_card(mix, th))
        write(f"card-stats-{name}.svg", stats_card(stats, th))
        write(f"heatmap-{name}.svg", heatmap(weeks, coll["contributionCalendar"]["totalContributions"], th))
        if cfg.get("whoami"):
            write(f"whoami-{name}.svg", whoami_card(cfg, th))
        for i, pl in enumerate(cfg.get("playlists", [])):
            write(f"playlist-{i}-{name}.svg", playlist_card(pl, th))
        for i, project in enumerate(cfg["projects"]):
            write(f"project-{project['repo']}-{name}.svg",
                  project_card(project, data.get(f"p{i}"), th, cfg["user"], images.get(project["repo"])))


if __name__ == "__main__":
    main()
