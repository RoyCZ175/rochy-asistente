"""Puente entre la interfaz (JavaScript, interface/index.html) y Python,
expuesto vía pywebview: cualquier método público de StudyFilesApi queda
disponible en el navegador como `window.pywebview.api.<método>(...)`, y
devuelve una Promise con el resultado.

Solo existe para el selector de archivos nativo del modo estudio — pywebview
garantiza el manejo correcto de hilos para el diálogo nativo de Windows
cuando se invoca por este camino (desde la interfaz), así que TODO acceso a
study_rag.pick_and_copy_files debe pasar por aquí, nunca llamarse directo
desde un hilo de Python nuestro (voice_assistant.py solo le pide a la
interfaz que dispare esta llamada, vía ui_server.broadcast_open_file_picker)."""

import mode_state
import study_rag
import study_state
import ui_server


class StudyFilesApi:
    def list_subjects(self) -> list:
        """Para el selector de materias de la interfaz: qué carpetas de
        estudio ya existen, para elegir una con un clic en vez de escribir
        (y acordarse de) el nombre exacto cada vez."""
        return study_rag.list_subjects()

    def activate_subject(self, subject: str) -> dict:
        """Reactiva una materia que ya existe (reindexando solo lo que haya
        cambiado) sin pasar por el selector de archivos — para cuando el
        usuario ya tiene la carpeta con apuntes y solo quiere retomarla."""
        if not subject or not subject.strip():
            return {"ok": False, "message": "Falta el nombre de la materia."}

        try:
            message = study_rag.index_subject(subject)
        except Exception as exc:
            message = f"No pude activar '{subject}': {exc}"
            print(f"Rochy: {message}")
            ui_server.broadcast_transcript("assistant", message)
            return {"ok": False, "message": message}

        study_state.set_subject(subject)
        ai_mode = "local" if mode_state.is_forced_local() else "online"
        reply = f"{message} Modo estudio de {subject} activado."
        print(f"Rochy: {reply}")
        ui_server.broadcast_transcript("assistant", reply)
        ui_server.broadcast_mode(ai_mode, study_state.get_subject())
        return {"ok": True, "message": reply}

    def pick_and_copy(self, subject: str) -> dict:
        if not subject or not subject.strip():
            return {"ok": False, "message": "Falta el nombre de la materia."}

        try:
            message = study_rag.pick_and_copy_files(subject)
        except Exception as exc:
            message = f"No pude completar el modo estudio de '{subject}': {exc}"
            print(f"Rochy: {message}")
            ui_server.broadcast_transcript("assistant", message)
            return {"ok": False, "message": message}

        if "No elegiste" not in message and "No pude copiar" not in message:
            study_state.set_subject(subject)

        ai_mode = "local" if mode_state.is_forced_local() else "online"
        print(f"Rochy: {message}")
        ui_server.broadcast_transcript("assistant", message)
        ui_server.broadcast_mode(ai_mode, study_state.get_subject())
        return {"ok": True, "message": message}
