"""Resolve ferramentas também quando o aplicativo herdou um PATH antigo."""
import os
from pathlib import Path
import shutil


def search_path():
    paths = [os.environ.get('PATH', '')]
    if os.name == 'nt':
        import winreg
        for root, key in [(winreg.HKEY_CURRENT_USER, 'Environment'),
                          (winreg.HKEY_LOCAL_MACHINE, r'SYSTEM\CurrentControlSet\Control\Session Manager\Environment')]:
            try:
                with winreg.OpenKey(root, key) as handle:
                    value, _ = winreg.QueryValueEx(handle, 'Path')
                    paths.append(os.path.expandvars(value))
            except OSError:
                pass
    return os.pathsep.join(paths)


def locate(name):
    if name not in ('ffmpeg', 'ffprobe'):
        raise ValueError('Ferramenta desconhecida.')
    override = os.environ.get(name.upper() + '_PATH')
    if override:
        path = Path(override.strip('"')).expanduser()
        return str(path.resolve()) if path.is_file() else None
    found = shutil.which(name, path=search_path())
    if found:
        return str(Path(found).resolve())
    filename = name + ('.exe' if os.name == 'nt' else '')
    root = Path(__file__).resolve().parent
    for folder in (root / 'bin', root / 'ffmpeg' / 'bin'):
        if (folder / filename).is_file():
            return str(folder / filename)
    if os.name == 'nt':
        packages = Path(os.environ.get('LOCALAPPDATA', Path.home() / 'AppData' / 'Local')) / 'Microsoft' / 'WinGet' / 'Packages'
        for path in sorted(packages.glob(f'*FFmpeg*/*/bin/{filename}'), reverse=True):
            if path.is_file():
                return str(path.resolve())
    return None


def require(name):
    path = locate(name)
    if not path:
        raise RuntimeError(f'{name} não encontrado. Configure {name.upper()}_PATH com o caminho completo do executável ou consulte o README.')
    return path


def health():
    return {name: bool(locate(name)) for name in ('ffmpeg', 'ffprobe')}
