"""Ejecuta esto para conectar tu plataforma cuando el login es con Google (SSO).

Abre una ventana de navegador real apuntando a tu plataforma. Tú inicias
sesión normalmente (con Google, con tu 2FA, lo que sea) — ese proceso pasa
directo entre tú, tu navegador y Google/Moodle, nunca por este código.
Cuando detecta que ya entraste (llegaste al dashboard), guarda la sesión
resultante (cookies) en un archivo local para poder leer tus tareas
después, sin volver a pedirte que inicies sesión hasta que esa sesión
expire por sí sola.
"""

from playwright.sync_api import sync_playwright

DEFAULT_BASE_URL = "https://b-learning.cenestur.edu.ec"
SESSION_PATH = "university_session.json"


def main() -> None:
    base_url = input(f"URL de la plataforma [{DEFAULT_BASE_URL}]: ").strip() or DEFAULT_BASE_URL
    login_url = base_url.rstrip("/") + "/login/index.php"
    dashboard_url_fragment = "/my/"

    print("\nSe va a abrir una ventana del navegador.")
    print("Inicia sesión ahí con normalidad (Google, contraseña, verificación en dos pasos, etc.).")
    print("Esta ventana la espero yo — no cierres la consola.\n")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        context = browser.new_context()
        page = context.new_page()
        page.goto(login_url)

        print("Esperando a que termines de iniciar sesión (hasta 5 minutos)...")
        try:
            page.wait_for_url(f"**{dashboard_url_fragment}**", timeout=5 * 60 * 1000)
        except Exception:
            print("\nNo detecté que llegaras al dashboard (¿tardaste más de 5 minutos, o la URL")
            print("del dashboard es distinta?). Vuelve a intentarlo, o dime qué URL tiene tu")
            print("dashboard una vez logueado para ajustar la detección.")
            browser.close()
            return

        context.storage_state(path=SESSION_PATH)
        browser.close()

    print(f"\n¡Listo! Sesión guardada en {SESSION_PATH}.")
    print("Agrega esta línea a tu .env:\n")
    print(f"UNIVERSITY_BASE_URL={base_url}")


if __name__ == "__main__":
    main()
