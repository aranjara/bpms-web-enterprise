import os, sys, socket, threading, subprocess, time, webbrowser
from pathlib import Path
import pystray
from PIL import Image, ImageDraw
from pystray import MenuItem as item
BASE_DIR = Path(__file__).resolve().parent
APP_FILE = BASE_DIR / 'app.py'
REPORT_FILE = BASE_DIR / 'Reporte BPMS.xlsx'
SERVER_PORT = 5000
class BPMSWebTray:
    def __init__(self): self.server_process=None; self.icon=None
    def create_image(self):
        img = Image.new('RGB',(64,64),'#0f3d6e'); d=ImageDraw.Draw(img)
        d.rounded_rectangle((6,6,58,58), radius=10, fill='#0f3d6e', outline='#ffffff', width=2); d.text((15,18),'BP',fill='#ffffff'); return img
    def is_port_open(self, host='127.0.0.1', port=SERVER_PORT):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock: sock.settimeout(0.5); return sock.connect_ex((host,port))==0
    def notify(self, message):
        if self.icon:
            try: self.icon.notify(message, 'Control BPMS Web')
            except Exception: pass
    def start_server(self, icon=None, item=None):
        if self.is_port_open(): return
        if not APP_FILE.exists(): self.notify('No se encontró app.py.'); return
        if not REPORT_FILE.exists(): self.notify("No se encontró 'Reporte BPMS.xlsx'."); return
        creationflags = subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
        self.server_process = subprocess.Popen([sys.executable, str(APP_FILE)], cwd=str(BASE_DIR), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=creationflags)
        for _ in range(20):
            time.sleep(0.5)
            if self.is_port_open(): self.notify('Servidor iniciado.'); return
        self.notify('El servidor no respondió.')
    def stop_server(self, icon=None, item=None):
        if self.server_process and self.server_process.poll() is None:
            self.server_process.terminate(); time.sleep(1)
            if self.server_process.poll() is None: self.server_process.kill()
        self.notify('Servidor detenido.')
    def open_web(self, icon=None, item=None):
        if not self.is_port_open(): self.start_server()
        webbrowser.open(f'http://127.0.0.1:{SERVER_PORT}')
    def quit_app(self, icon=None, item=None): self.stop_server(); self.icon.stop()
    def run(self):
        self.icon = pystray.Icon('bpms_web', self.create_image(), 'Control BPMS Web', pystray.Menu(item('Abrir BPMS Web', self.open_web, default=True), item('Iniciar servidor', self.start_server), item('Detener servidor', self.stop_server), item('Salir', self.quit_app)))
        threading.Thread(target=self.start_server, daemon=True).start(); self.icon.run()
if __name__ == '__main__': BPMSWebTray().run()
