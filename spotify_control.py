"""Control de reproducción y búsqueda de Spotify vía la Web API.

Requiere Spotify Premium (Spotify exige Premium tanto para usar la API web
como para controlar la reproducción) y un dispositivo activo (la app de
Spotify abierta en el PC, el móvil o el navegador) — la API solo controla
una sesión de reproducción que ya existe, no reproduce audio por sí misma.
"""

import spotipy
from spotipy.oauth2 import SpotifyOAuth

SCOPE = "user-modify-playback-state user-read-playback-state user-read-currently-playing"

_client = None


def _get_client(config):
    global _client
    if _client is not None:
        return _client

    if not config.spotify_client_id or not config.spotify_client_secret:
        raise RuntimeError(
            "Spotify no está configurado. Agrega SPOTIFY_CLIENT_ID y "
            "SPOTIFY_CLIENT_SECRET en tu .env."
        )

    auth = SpotifyOAuth(
        client_id=config.spotify_client_id,
        client_secret=config.spotify_client_secret,
        redirect_uri=config.spotify_redirect_uri,
        scope=SCOPE,
        cache_path=".spotify_cache",
    )
    _client = spotipy.Spotify(auth_manager=auth)
    return _client


def _no_device_message() -> str:
    return "No hay ningún dispositivo de Spotify activo. Abre Spotify en tu PC, móvil o el navegador e intenta de nuevo."


def search(config, query: str) -> str:
    sp = _get_client(config)
    results = sp.search(q=query, type="track", limit=3)
    items = results["tracks"]["items"]
    if not items:
        return f"No encontré nada para '{query}' en Spotify."
    lines = [f"{t['name']} de {t['artists'][0]['name']}" for t in items]
    return "Encontré: " + "; ".join(lines) + "."


def play(config, query: str = "") -> str:
    sp = _get_client(config)
    try:
        if query:
            results = sp.search(q=query, type="track", limit=1)
            items = results["tracks"]["items"]
            if not items:
                return f"No encontré '{query}' en Spotify."
            track = items[0]
            sp.start_playback(uris=[track["uri"]])
            return f"Reproduciendo {track['name']} de {track['artists'][0]['name']}."
        sp.start_playback()
        return "Reanudando la música."
    except spotipy.SpotifyException as exc:
        if exc.http_status == 404:
            return _no_device_message()
        return f"Spotify no pudo hacer eso: {exc.msg}"


def pause(config) -> str:
    sp = _get_client(config)
    try:
        sp.pause_playback()
        return "Música en pausa."
    except spotipy.SpotifyException as exc:
        if exc.http_status == 404:
            return _no_device_message()
        return f"Spotify no pudo hacer eso: {exc.msg}"


def next_track(config) -> str:
    sp = _get_client(config)
    try:
        sp.next_track()
        return "Siguiente canción."
    except spotipy.SpotifyException as exc:
        if exc.http_status == 404:
            return _no_device_message()
        return f"Spotify no pudo hacer eso: {exc.msg}"


def previous_track(config) -> str:
    sp = _get_client(config)
    try:
        sp.previous_track()
        return "Canción anterior."
    except spotipy.SpotifyException as exc:
        if exc.http_status == 404:
            return _no_device_message()
        return f"Spotify no pudo hacer eso: {exc.msg}"


def current_track(config) -> str:
    sp = _get_client(config)
    playback = sp.current_playback()
    if not playback or not playback.get("item"):
        return "No hay nada sonando ahora mismo."
    item = playback["item"]
    return f"Sonando: {item['name']} de {item['artists'][0]['name']}."


def set_volume(config, level: int) -> str:
    sp = _get_client(config)
    level = max(0, min(100, level))
    try:
        sp.volume(level)
        return f"Volumen de Spotify al {level} por ciento."
    except spotipy.SpotifyException as exc:
        if exc.http_status == 404:
            return _no_device_message()
        return f"Spotify no pudo hacer eso: {exc.msg}"
