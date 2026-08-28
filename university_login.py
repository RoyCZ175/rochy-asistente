"""Conecta la plataforma universitaria (login con Google/SSO).

Abre una ventana de navegador real apuntando a la plataforma. El usuario
inicia sesión normalmente (con Google, con su 2FA, lo que sea) — ese proceso
pasa directo entre él, su navegador y Google/Moodle, nunca por este código.
Cuando detecta que ya entró (llegó al dashboard), guarda la sesión resultante
(cookies) en un archivo local para poder leer sus tareas después.

El navegador usa un PERFIL PROPIO Y SEPARADO (no el Chrome real del usuario,
con todas sus otras contraseñas y sesiones) que sí se guarda en disco entre
usos — así, después del primer login completo, Google ya reconoce ese
navegador como confiable y las próximas veces (cuando la sesión de Moodle
expire de nuevo) suele bastar un clic en la cuenta, sin volver a escribir la
contraseña.
"""

import os
import threading

from playwright.sync_api import sync_playwright

DEFAULT_BASE_URL = "https://b-learning.cenestur.edu.ec"
SESSION_PATH = "university_session.json"
PROFILE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".university_browser_profile")


def login(base_url: str) -> bool:
    """Hace el login de verdad (bloquea hasta que el usuario termine o pasen
    5 minutos). Devuelve True si quedó conectado."""
    login_url = base_url.rstrip("/") + "/login/index.php"
    dashboard_url_fragment = "/my/"

    print("\nSe va a abrir una ventana del navegador.")
    print("Inicia sesión ahí con normalidad (Google, contraseña, verificación en dos pasos, etc.).")
    print("Si ya confiaste en este navegador antes, debería ser mucho más rápido esta vez.\n")

    with sync_playwright() as p:
        context = p.chromium.launch_persistent_context(PROFILE_DIR, headless=False)
        try:
            page = context.new_page()
            page.goto(login_url)

            print("Esperando a que termines de iniciar sesión (hasta 5 minutos)...")
            try:
                page.wait_for_url(f"**{dashboard_url_fragment}**", timeout=5 * 60 * 1000)
            except Exception:
                print("\nNo detecté que llegaras al dashboard (¿tardaste más de 5 minutos, o la URL")
                print("del dashboard es distinta?). Vuelve a intentarlo.")
                return False

            context.storage_state(path=SESSION_PATH)
            return True
        finally:
            context.close()


def start_reconnect(base_url: str) -> str:
    """Dispara el login en segundo plano, sin bloquear el asistente — el
    login real puede tardar minutos esperando al usuario, y Rochy tiene que
    seguir escuchando/respondiendo mientras tanto."""

    def _run() -> None:
        ok = login(base_url)
        if ok:
            import moodle_client

            # Sin esto, moodle_client seguiría usando las cookies viejas que
            # ya tenía en memoria de la sesión anterior (expirada), aunque el
            # archivo en disco ya se haya actualizado con la sesión nueva.
            moodle_client.invalidate_cache()

    threading.Thread(target=_run, daemon=True).start()
    return (
        "Te abrí una ventana del navegador para que inicies sesión en la plataforma. "
        "Avísame cuando termines para volver a intentarlo."
    )


if __name__ == "__main__":
    base_url = input(f"URL de la plataforma [{DEFAULT_BASE_URL}]: ").strip() or DEFAULT_BASE_URL
    if login(base_url):
        print(f"\n¡Listo! Sesión guardada en {SESSION_PATH}.")
        print("Agrega esta línea a tu .env:\n")
        print(f"UNIVERSITY_BASE_URL={base_url}")
