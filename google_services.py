"""Integración con Google Calendar y Gmail (cuenta personal del usuario, vía OAuth).

Regla de seguridad para el correo: enviar SIEMPRE es un proceso de dos pasos.
draft_email() prepara el mensaje y devuelve un texto para que el asistente lo
lea en voz alta pidiendo confirmación explícita; send_email() solo envía si
existe un borrador ya preparado. No existe ninguna función que redacte y
envíe en un solo paso — así un malentendido del micrófono nunca termina en
un correo real enviado por accidente.
"""

import base64
import os
from datetime import datetime, timezone
from email.mime.text import MIMEText

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

SCOPES = [
    "https://www.googleapis.com/auth/calendar",
    "https://www.googleapis.com/auth/gmail.send",
    "https://www.googleapis.com/auth/gmail.readonly",
]

TOKEN_PATH = "google_token.json"

_pending_email = None  # {"to", "subject", "body"} en espera de confirmación


def _get_credentials(config):
    creds = None
    if os.path.exists(TOKEN_PATH):
        creds = Credentials.from_authorized_user_file(TOKEN_PATH, SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            if not os.path.exists(config.google_credentials_path):
                raise RuntimeError(
                    "Falta google_credentials.json. Descárgalo desde Google Cloud Console "
                    "(Credenciales > ID de cliente de OAuth > Aplicación de escritorio) y "
                    "guárdalo en la carpeta del proyecto."
                )
            flow = InstalledAppFlow.from_client_secrets_file(config.google_credentials_path, SCOPES)
            creds = flow.run_local_server(port=0)
        with open(TOKEN_PATH, "w", encoding="utf-8") as f:
            f.write(creds.to_json())
    return creds


def _calendar(config):
    return build("calendar", "v3", credentials=_get_credentials(config))


def _gmail(config):
    return build("gmail", "v1", credentials=_get_credentials(config))


def create_event(config, summary: str, start_iso: str, end_iso: str = "", description: str = "") -> str:
    service = _calendar(config)
    event = {
        "summary": summary,
        "description": description,
        "start": {"dateTime": start_iso},
        "end": {"dateTime": end_iso or start_iso},
    }
    service.events().insert(calendarId="primary", body=event).execute()
    return f"Evento '{summary}' creado en tu calendario de Google."


def list_upcoming_events(config, max_results: int = 10) -> str:
    service = _calendar(config)
    now = datetime.now(timezone.utc).isoformat()
    result = (
        service.events()
        .list(calendarId="primary", timeMin=now, maxResults=max_results, singleEvents=True, orderBy="startTime")
        .execute()
    )
    events = result.get("items", [])
    if not events:
        return "No tienes eventos próximos en tu calendario de Google."
    lines = []
    for ev in events:
        start = ev["start"].get("dateTime", ev["start"].get("date"))
        lines.append(f"{ev.get('summary', '(sin título)')} - {start}")
    return "Tus próximos eventos: " + "; ".join(lines) + "."


def draft_email(to: str, subject: str, body: str) -> str:
    global _pending_email
    _pending_email = {"to": to, "subject": subject, "body": body}
    body_clean = body.strip().rstrip(".")
    return (
        f"Voy a enviar un correo a {to} con asunto '{subject}' que dice: {body_clean}. "
        "¿Confirmas que lo envíe?"
    )


def cancel_email() -> str:
    global _pending_email
    _pending_email = None
    return "Correo cancelado, no se envió nada."


def send_email(config) -> str:
    global _pending_email
    if not _pending_email:
        return "No hay ningún correo preparado para enviar. Primero dime a quién, el asunto y el mensaje."
    draft = _pending_email

    # el borrador solo se descarta si el envío tiene éxito, para poder reintentar si falla
    service = _gmail(config)
    message = MIMEText(draft["body"])
    message["to"] = draft["to"]
    message["subject"] = draft["subject"]
    raw = base64.urlsafe_b64encode(message.as_bytes()).decode()
    service.users().messages().send(userId="me", body={"raw": raw}).execute()
    _pending_email = None
    return f"Correo enviado a {draft['to']}."


def list_recent_emails(config, max_results: int = 5) -> str:
    service = _gmail(config)
    result = service.users().messages().list(userId="me", maxResults=max_results, labelIds=["INBOX"]).execute()
    messages = result.get("messages", [])
    if not messages:
        return "No tienes correos recientes."
    lines = []
    for m in messages:
        msg = (
            service.users()
            .messages()
            .get(userId="me", id=m["id"], format="metadata", metadataHeaders=["From", "Subject"])
            .execute()
        )
        headers = {h["name"]: h["value"] for h in msg["payload"]["headers"]}
        lines.append(f"{headers.get('Subject', '(sin asunto)')} de {headers.get('From', '?')}")
    return "Tus correos recientes: " + "; ".join(lines) + "."
