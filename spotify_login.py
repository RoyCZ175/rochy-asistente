"""Ejecuta esto UNA VEZ, en una consola real, para conectar tu cuenta de Spotify.

Abre tu navegador para que inicies sesión y autorices la app normalmente.
Guarda el token resultante en .spotify_cache para que Rochy no necesite
volver a pedirte esto — solo se refresca solo cuando expira.

Por qué existe este script: el login de Spotify necesita abrir un navegador
y esperar tu autorización, y esa espera solo puede pasar en una consola real
con la que puedas interactuar. Rochy corre en segundo plano sin consola
(pythonw), así que si intentara hacer este login él solo la primera vez que
le pidieras música, se quedaría colgado esperando algo que nunca podrías
completar — por eso ahora falla rápido y te pide correr este script antes.
"""

from config import Config
from spotify_control import SCOPE

from spotipy.oauth2 import SpotifyOAuth


def main() -> None:
    config = Config.load()
    if not config.spotify_client_id or not config.spotify_client_secret:
        print("Falta SPOTIFY_CLIENT_ID / SPOTIFY_CLIENT_SECRET en tu .env. Agrégalos primero.")
        return

    auth = SpotifyOAuth(
        client_id=config.spotify_client_id,
        client_secret=config.spotify_client_secret,
        redirect_uri=config.spotify_redirect_uri,
        scope=SCOPE,
        cache_path=".spotify_cache",
        open_browser=True,
    )

    print("\nSe va a abrir tu navegador para autorizar a Rochy en Spotify.")
    print("Inicia sesión y acepta los permisos con normalidad.\n")

    # Esto abre el navegador, espera la redirección a SPOTIFY_REDIRECT_URI y
    # guarda el token en .spotify_cache — con eso Rochy ya no necesita volver
    # a pasar por este proceso hasta que el token expire por sí solo.
    auth.get_access_token(as_dict=False)
    print("\nListo. Token guardado en .spotify_cache — ya puedes pedirle música a Rochy con normalidad.")


if __name__ == "__main__":
    main()
