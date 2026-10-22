"""Imita a nginx para probar sin publicar: sirve web/ en /gameflix/ y pasa /gameflix/api/ al servicio.

    GAMEFLIX_PUERTO=18777 GAMEFLIX_BD=/tmp/x/gameflix.db GAMEFLIX_ROMS=/tmp/x/roms python3 servidor.py &
    python3 herramientas/servidor_prueba.py 18778 18777      # -> http://127.0.0.1:18778/gameflix/
"""

import sys
import urllib.error
import urllib.request
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

WEB = Path(__file__).resolve().parent.parent / 'web'
PUERTO = int(sys.argv[1]) if len(sys.argv) > 1 else 18778
API = int(sys.argv[2]) if len(sys.argv) > 2 else 18777


class Manejador(SimpleHTTPRequestHandler):
    def log_message(self, formato, *args):
        pass

    def translate_path(self, path):
        return super().translate_path(path.removeprefix('/gameflix'))

    def proxy(self):
        largo = int(self.headers.get('Content-Length') or 0)
        cuerpo = self.rfile.read(largo) if largo else None
        destino = f'http://127.0.0.1:{API}' + self.path.removeprefix('/gameflix')
        pedido = urllib.request.Request(destino, data=cuerpo, method=self.command)
        for k in ('Cookie', 'Content-Type'):
            if self.headers.get(k):
                pedido.add_header(k, self.headers[k])
        try:
            r = urllib.request.urlopen(pedido)
        except urllib.error.HTTPError as e:
            r = e
        datos = r.read()
        self.send_response(r.status)
        for k, v in r.headers.items():
            if k.lower() not in ('content-length', 'connection', 'transfer-encoding', 'server', 'date'):
                self.send_header(k, v)
        self.send_header('Content-Length', str(len(datos)))
        self.end_headers()
        if self.command != 'HEAD':
            self.wfile.write(datos)

    def atender(self):
        if self.path.startswith('/gameflix/api/'):
            return self.proxy()
        if not self.path.startswith('/gameflix/'):
            self.send_error(404)
            return
        if self.command in ('GET', 'HEAD'):
            return super().do_GET() if self.command == 'GET' else super().do_HEAD()
        self.send_error(405)

    do_GET = do_HEAD = do_POST = do_PUT = do_PATCH = do_DELETE = atender


if __name__ == '__main__':
    ThreadingHTTPServer(('127.0.0.1', PUERTO), partial(Manejador, directory=str(WEB))).serve_forever()
