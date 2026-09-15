#!/usr/bin/env python3
"""Registra una firma del libro de visitas a partir del issue que disparó el workflow.

Lee el evento de GitHub Actions (GITHUB_EVENT_PATH), toma el título del
issue como mensaje, lo limpia y lo guarda en assets/guestbook.json. El
texto viene de terceros: nunca se ejecuta ni se pasa a un shell, y al
dibujarlo generate.py lo escapa y lo vuelve a limpiar.

Escribe `resultado=ok|vacio|bot` en GITHUB_OUTPUT para que el workflow
sepa qué contestar en el issue.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from consola import GUESTBOOK, clean_message  # noqa: E402

MAX_ENTRIES = 50


def main() -> None:
    event = json.loads(Path(os.environ["GITHUB_EVENT_PATH"]).read_text(encoding="utf-8"))
    issue = event["issue"]
    author = issue["user"]
    message = clean_message(issue.get("title") or "")

    if author.get("type") != "User":
        resultado = "bot"
    elif not message:
        resultado = "vacio"
    else:
        resultado = "ok"
        data = json.loads(GUESTBOOK.read_text(encoding="utf-8")) if GUESTBOOK.exists() else {"entries": []}
        entries = [e for e in data["entries"] if e.get("issue") != issue["number"]]  # idempotente si se repite
        entries.append({"issue": issue["number"], "login": author["login"], "message": message,
                        "date": issue["created_at"][:10]})
        data["entries"] = entries[-MAX_ENTRIES:]
        GUESTBOOK.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")

    if os.environ.get("GITHUB_OUTPUT"):
        with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8") as fh:
            fh.write(f"resultado={resultado}\n")
    print(f"resultado={resultado} login={author.get('login')} mensaje={message!r}")


if __name__ == "__main__":
    main()
