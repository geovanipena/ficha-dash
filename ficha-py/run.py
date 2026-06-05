"""Inicia o Ficha-Py localmente e abre o navegador na interface.

Uso:

    python run.py            # porta 8050
    python run.py --port 9000

É o jeito recomendado de rodar local: sobe o servidor Dash e abre o navegador
automaticamente em http://127.0.0.1:<porta>.
"""

from __future__ import annotations

import argparse
import threading
import webbrowser

from app import app


def main() -> None:
    parser = argparse.ArgumentParser(description="Ficha-Py — ficha técnica de radioterapia (local).")
    parser.add_argument("--port", type=int, default=8050, help="Porta HTTP (padrão: 8050).")
    parser.add_argument("--host", default="127.0.0.1", help="Host (padrão: 127.0.0.1).")
    parser.add_argument("--no-browser", action="store_true", help="Não abrir o navegador.")
    args = parser.parse_args()

    url = f"http://{args.host}:{args.port}"
    if not args.no_browser:
        threading.Timer(1.2, lambda: webbrowser.open(url)).start()
    print(f"Ficha-Py rodando em {url}  (Ctrl+C para encerrar)")
    app.run(host=args.host, port=args.port, debug=False)


if __name__ == "__main__":
    main()
