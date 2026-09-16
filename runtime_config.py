"""Mesmo perfil no build e na execução; Windows mantém base por padrão."""
import os


def low_memory():
    return os.getenv('LOW_MEMORY_MODE', '1' if os.getenv('RENDER') else '0') == '1'


def model_name():
    return os.getenv('WHISPER_MODEL') or ('tiny' if low_memory() else 'base')
