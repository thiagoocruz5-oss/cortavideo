"""Um subprocesso por etapa, logs em disco e término garantido no timeout."""
import atexit
import subprocess
import tempfile
import threading
import os
import time

ACTIVE = set()
LOCK = threading.Lock()


def kill_process(process):
    if os.name == 'nt':
        # O executável do venv pode iniciar outro Python como processo filho.
        try:
            subprocess.run([os.path.join(os.environ.get('SystemRoot', r'C:\Windows'), 'System32', 'taskkill.exe'),
                            '/PID', str(process.pid), '/T', '/F'],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=10)
        except (OSError, subprocess.TimeoutExpired):
            pass
    if process.poll() is None:
        process.kill()
    process.wait()


def stop_all():
    with LOCK:
        processes = list(ACTIVE)
    for process in processes:
        if process.poll() is None:
            try:
                kill_process(process)
            except (OSError, subprocess.TimeoutExpired):
                pass


atexit.register(stop_all)


def run_process(args, cwd=None, timeout=7200, on_tick=None):
    # Nenhum pipe cresce na RAM. Todos os processos iniciados aqui são folhas.
    with tempfile.TemporaryFile() as stdout, tempfile.TemporaryFile() as stderr:
        process = subprocess.Popen(args, cwd=cwd, stdout=stdout, stderr=stderr,
                                   stdin=subprocess.DEVNULL)
        with LOCK:
            ACTIVE.add(process)
        try:
            try:
                if on_tick is None:
                    code = process.wait(timeout=timeout)
                else:
                    deadline = time.monotonic() + timeout
                    while True:
                        on_tick()
                        remaining = deadline - time.monotonic()
                        if remaining <= 0:
                            raise subprocess.TimeoutExpired(args[0], timeout)
                        try:
                            code = process.wait(timeout=min(1, remaining))
                            on_tick()
                            break
                        except subprocess.TimeoutExpired:
                            continue
            except subprocess.TimeoutExpired as exc:
                raise RuntimeError('O processamento excedeu o tempo limite. Tente um vídeo menor.') from exc
            if code:
                stderr.seek(0, 2)
                stderr.seek(max(0, stderr.tell() - 2500))
                detail = stderr.read().decode('utf-8', errors='replace')
                raise RuntimeError(f'Processamento interrompido (código {code}). Pode faltar memória. {detail}')
            stdout.seek(0)
            return stdout.read(2 * 1024 * 1024).decode('utf-8', errors='replace')
        finally:
            if process.poll() is None:
                kill_process(process)
            with LOCK:
                ACTIVE.discard(process)
