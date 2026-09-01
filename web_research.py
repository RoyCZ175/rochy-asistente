"""Investigación web REAL: a diferencia de `web_search` (system_control.py),
que solo abre una pestaña para que el usuario mire, esto busca de verdad y le
trae el contenido de las páginas de vuelta a la IA — es lo que hace posible
"investiga esto y compáralo con mi PDF".

Sin API key: se usa la versión HTML simple de DuckDuckGo (html.duckduckgo.com,
pensada para navegadores sin JavaScript) para sacar los primeros resultados,
y luego se descarga el texto de esas páginas directamente."""

import requests
from bs4 import BeautifulSoup

# Un User-Agent genérico ("RochyBot/1.0") hacía que DuckDuckGo devolviera una
# página de "sospecha de bot" (HTTP 202, sin resultados de verdad) en vez de
# la búsqueda real — se comprobó en vivo. Con un User-Agent de navegador de
# verdad, responde normal (200, con resultados).
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "es-ES,es;q=0.9,en;q=0.8",
    "Referer": "https://html.duckduckgo.com/",
}
SEARCH_URL = "https://html.duckduckgo.com/html/"
# Nada de esto es sobre "cuántos caracteres caben" en realidad: se comprobó
# en vivo (con RateLimitError real de Groq) que la cuenta tiene un límite de
# 8000 tokens por minuto, y con varias llamadas seguidas en el mismo minuto
# (pruebas, cambios de calidad, conversación normal) ese presupuesto se
# agota fácil — cuando la llamada de "resumen final" falla por eso, el
# respaldo de AIBrain.ask() devuelve el texto crudo de esta herramienta tal
# cual (a propósito, para no perder el trabajo real). Por eso el tamaño se
# mantiene moderado: no evita el límite de tokens por sí solo, pero si el
# respaldo llega a activarse, que sea texto limpio y corto, no una pared de
# texto con instrucciones de por medio.
TIMEOUT = 8
MAX_RESULTS = 2
MAX_CHARS_PER_PAGE = 800


def _search_urls(query: str, max_results: int = MAX_RESULTS) -> list:
    resp = requests.post(SEARCH_URL, data={"q": query}, headers=HEADERS, timeout=TIMEOUT)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")
    urls = []
    for link in soup.select("a.result__a"):
        href = link.get("href")
        if href:
            urls.append(href)
        if len(urls) >= max_results:
            break
    return urls


def _page_text(url: str) -> str:
    resp = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")
    for tag in soup(["script", "style", "nav", "footer", "header", "table"]):
        tag.decompose()

    # Preferir párrafos de verdad (<p>) sobre el texto de la página entera:
    # en Wikipedia y la mayoría de artículos, el resto (infoboxes, tablas de
    # datos, menús) es puro ruido de "clave: valor" que no ayuda a resumir y
    # sí tienta al modelo a simplemente repetirlo tal cual en vez de
    # sintetizarlo — se comprobó en vivo con una respuesta real.
    paragraphs = [p.get_text(separator=" ", strip=True) for p in soup.find_all("p")]
    paragraphs = [p for p in paragraphs if len(p) > 40]
    text = " ".join(paragraphs) if paragraphs else " ".join(soup.get_text(separator=" ").split())
    text = " ".join(text.split())
    return text[:MAX_CHARS_PER_PAGE]


def web_read(query: str) -> str:
    try:
        urls = _search_urls(query)
    except Exception as exc:
        return f"No pude buscar '{query}' en internet ahora mismo: {exc}"

    if not urls:
        return f"No encontré resultados de verdad para '{query}'."

    parts = []
    sources = []
    for url in urls:
        try:
            text = _page_text(url)
        except Exception:
            continue
        if text:
            parts.append(text)
            sources.append(url)

    if not parts:
        return f"Encontré páginas para '{query}' pero no pude leer el contenido de ninguna."

    # Texto limpio, sin instrucciones ni "Fuente: URL" incrustadas en el
    # cuerpo — el modelo sintetiza bien esto solo (comprobado en vivo con
    # llamadas aisladas), y si por lo que sea el respaldo de AIBrain.ask()
    # termina devolviendo esto tal cual al usuario, que sea legible y no una
    # instrucción interna leída en voz alta por error.
    body = "\n\n".join(parts)
    return f"{body}\n\n(Fuentes: {', '.join(sources)})"
