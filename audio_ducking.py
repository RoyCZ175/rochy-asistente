"""Baja el volumen de lo que esté sonando de fondo (música, un video) cuando
Rochy empieza a escuchar o a hablar, y lo regresa a como estaba al terminar
— mismo comportamiento que Alexa/Google Home con música de fondo, para que
no se mezcle con lo que dice el usuario o Rochy.

Usa pycaw (ya en requirements, se usa para volumen/mute en system_control.py)
para bajar el volumen de CADA APLICACIÓN por separado — a propósito no toca
el volumen general del sistema: eso también bajaría la propia voz de Rochy
al hablar. Se excluye a sí mismo (python.exe/pythonw.exe) de la lista de
aplicaciones a las que les baja el volumen."""

from pycaw.pycaw import AudioUtilities

DUCK_LEVEL = 0.25
OWN_PROCESS_NAMES = {"python.exe", "pythonw.exe"}

# Recuerda el volumen real de cada sesión que bajamos (por PID), para
# devolverlo tal cual estaba — no a un número fijo — al restaurar.
_original_volumes: dict = {}


def duck() -> None:
    """Baja el volumen de todo lo demás. Seguro de llamar varias veces
    seguidas (ej. una conversación con más de un turno): no vuelve a guardar
    un volumen ya bajado como si fuera el "original"."""
    try:
        sessions = AudioUtilities.GetAllSessions()
    except Exception:
        return

    for session in sessions:
        process = session.Process
        if process is None or process.name() in OWN_PROCESS_NAMES:
            continue
        volume_iface = session.SimpleAudioVolume
        if volume_iface is None:
            continue
        pid = process.pid
        if pid not in _original_volumes:
            try:
                _original_volumes[pid] = volume_iface.GetMasterVolume()
            except Exception:
                continue
        try:
            volume_iface.SetMasterVolume(DUCK_LEVEL, None)
        except Exception:
            pass


def restore() -> None:
    """Devuelve el volumen real que tenía cada aplicación antes de duck()."""
    try:
        sessions = AudioUtilities.GetAllSessions()
    except Exception:
        _original_volumes.clear()
        return

    for session in sessions:
        process = session.Process
        if process is None:
            continue
        original = _original_volumes.pop(process.pid, None)
        if original is None:
            continue
        volume_iface = session.SimpleAudioVolume
        if volume_iface is None:
            continue
        try:
            volume_iface.SetMasterVolume(original, None)
        except Exception:
            pass

    _original_volumes.clear()
