"""RAG de 'modo estudio': indexa tus apuntes (PDF/DOCX/TXT) por materia y,
para cada pregunta, busca los fragmentos más relevantes para dárselos como
contexto real al modelo (local o en la nube) — en vez de que responda solo
de memoria.

No hay ningún entrenamiento aquí: el modelo de embeddings (multilingual-e5-small,
corre en CPU, no toca la GPU) solo convierte texto en vectores para poder
comparar significado. El resultado (los vectores) se guarda en disco junto a
cada materia, en una subcarpeta .rag_index/, y se reutiliza tal cual mientras
no agregues o cambies archivos — abrir la app de nuevo no repite el cálculo.
"""

import json
import os
import re
import shutil
import unicodedata

HOME = os.path.expanduser("~")
# Carpeta fija y única para TODO lo del modo estudio — a propósito, para que
# nunca queden materias o archivos regados por Documentos/Escritorio/etc.
# (eso sí puede pasar en modo local/online normal, donde el usuario tiene
# control total de dónde crear cosas; en modo estudio no: todo vive aquí
# dentro, organizado por materia).
STUDY_BASE = os.path.join(HOME, "Documents", "RAG_Rochy")

CHUNK_WORDS = 220
CHUNK_OVERLAP = 40
TOP_K = 4
# Probado con e5-small: el puntaje ABSOLUTO no distingue bien "relevante" de
# "no relevante" (hasta preguntas sin relación puntúan parecido) — lo que sí
# es confiable es el ORDEN (el fragmento correcto siempre queda primero). Por
# eso no se filtra por un umbral fijo: se devuelven los top_k más parecidos y
# se deja que el propio modelo decida si de verdad aplican (ya se le pide
# explícitamente en el prompt que lo diga si no vienen al caso).

SUPPORTED_EXTENSIONS = {".pdf", ".docx", ".txt", ".md"}

_model = None


def _get_model():
    global _model
    if _model is None:
        from sentence_transformers import SentenceTransformer

        _model = SentenceTransformer("intfloat/multilingual-e5-small")
    return _model


def _safe_name(name: str) -> str:
    name = unicodedata.normalize("NFKD", name.strip().lower())
    name = "".join(c for c in name if not unicodedata.combining(c))
    name = re.sub(r"[^a-z0-9_\-]+", "_", name)
    return name.strip("_") or "materia"


def subject_dir(subject: str) -> str:
    return os.path.join(STUDY_BASE, _safe_name(subject))


def ensure_subject_folder(subject: str) -> str:
    sdir = subject_dir(subject)
    os.makedirs(sdir, exist_ok=True)
    return sdir


def _index_dir(sdir: str) -> str:
    return os.path.join(sdir, ".rag_index")


def list_subjects() -> list:
    if not os.path.isdir(STUDY_BASE):
        return []
    return sorted(d for d in os.listdir(STUDY_BASE) if os.path.isdir(os.path.join(STUDY_BASE, d)))


def _extract_text(path: str) -> str:
    ext = os.path.splitext(path)[1].lower()
    if ext == ".pdf":
        from pypdf import PdfReader

        reader = PdfReader(path)
        return "\n".join((page.extract_text() or "") for page in reader.pages)
    if ext == ".docx":
        import docx

        doc = docx.Document(path)
        return "\n".join(p.text for p in doc.paragraphs)
    with open(path, "r", encoding="utf-8", errors="ignore") as f:
        return f.read()


def _chunk_text(text: str) -> list:
    words = text.split()
    if not words:
        return []
    chunks = []
    step = CHUNK_WORDS - CHUNK_OVERLAP
    start = 0
    while start < len(words):
        chunk = " ".join(words[start : start + CHUNK_WORDS])
        if chunk.strip():
            chunks.append(chunk)
        if start + CHUNK_WORDS >= len(words):
            break
        start += step
    return chunks


def _file_signature(path: str) -> str:
    stat = os.stat(path)
    return f"{stat.st_mtime_ns}:{stat.st_size}"


def index_subject(subject: str) -> str:
    """Procesa los archivos nuevos o modificados de una materia y actualiza su
    índice. Los archivos que no cambiaron desde la última vez no se vuelven a
    procesar (se detecta por fecha de modificación + tamaño), así que abrir la
    app de nuevo y volver a esta materia no recalcula nada de cero."""
    import numpy as np

    sdir = subject_dir(subject)
    os.makedirs(sdir, exist_ok=True)
    idir = _index_dir(sdir)
    os.makedirs(idir, exist_ok=True)

    meta_path = os.path.join(idir, "meta.json")
    vectors_path = os.path.join(idir, "vectors.npy")

    meta = {"files": {}, "chunks": []}
    vectors = None
    if os.path.exists(meta_path) and os.path.exists(vectors_path):
        with open(meta_path, "r", encoding="utf-8") as f:
            meta = json.load(f)
        vectors = np.load(vectors_path)

    files = [
        f
        for f in os.listdir(sdir)
        if os.path.isfile(os.path.join(sdir, f)) and os.path.splitext(f)[1].lower() in SUPPORTED_EXTENSIONS
    ]

    if not files:
        return (
            f"No encontré archivos en la carpeta de '{subject}' ({sdir}). "
            "Copia ahí tus PDF, DOCX o TXT y vuelve a decírmelo."
        )

    known_files = meta["files"]
    new_or_changed = []
    for fname in files:
        fpath = os.path.join(sdir, fname)
        sig = _file_signature(fpath)
        if known_files.get(fname) != sig:
            new_or_changed.append((fname, fpath, sig))

    removed_files = [f for f in known_files if f not in files]

    if not new_or_changed and not removed_files:
        return f"'{subject}' ya estaba al día: {len(files)} archivo(s), {len(meta['chunks'])} fragmentos indexados."

    stale = {f for f, _, _ in new_or_changed} | set(removed_files)
    keep_idx = [i for i, c in enumerate(meta["chunks"]) if c["source"] not in stale]
    kept_chunks = [meta["chunks"][i] for i in keep_idx]
    kept_vectors = vectors[keep_idx] if vectors is not None and len(keep_idx) else None

    new_chunks = []
    for fname, fpath, sig in new_or_changed:
        try:
            text = _extract_text(fpath)
        except Exception as exc:
            known_files[fname] = sig
            print(f"[study_rag] no pude leer {fname}: {exc}")
            continue
        for chunk in _chunk_text(text):
            new_chunks.append({"text": chunk, "source": fname})
        known_files[fname] = sig

    for fname in removed_files:
        known_files.pop(fname, None)

    model = _get_model()
    if new_chunks:
        new_vecs = model.encode(["passage: " + c["text"] for c in new_chunks], normalize_embeddings=True)
    else:
        new_vecs = np.zeros((0, 384), dtype="float32")

    all_chunks = kept_chunks + new_chunks
    if kept_vectors is not None and len(kept_vectors):
        all_vectors = np.vstack([kept_vectors, new_vecs]) if len(new_vecs) else kept_vectors
    else:
        all_vectors = new_vecs

    meta["files"] = known_files
    meta["chunks"] = all_chunks

    with open(meta_path, "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False)
    np.save(vectors_path, all_vectors)

    return (
        f"Listo, '{subject}' indexado: {len(files)} archivo(s), {len(all_chunks)} fragmentos en total "
        f"({len(new_or_changed)} nuevo(s) o actualizado(s))."
    )


FILE_PICKER_TYPES = ("Documentos de estudio (*.pdf;*.docx;*.txt;*.md)",)


def pick_and_copy_files(subject: str) -> str:
    """Abre el selector nativo de archivos de Windows (el mismo de siempre,
    el que usas para adjuntar algo en cualquier programa) y copia lo que
    elijas a la carpeta de esa materia. Como es una app de escritorio en tu
    propia PC, no hace falta "subir" nada a ningún lado — Python ya tiene
    acceso directo a esos archivos una vez los eliges, solo los copia.

    IMPORTANTE sobre hilos: esta función SIEMPRE debe llamarse desde un
    método expuesto a la interfaz (ver ui_bridge.py), nunca desde un hilo de
    Python que nosotros creamos directamente — pywebview solo garantiza que
    el diálogo nativo funcione bien si se invoca por ese camino."""
    import webview

    dest = subject_dir(subject)
    os.makedirs(dest, exist_ok=True)

    window = webview.windows[0]
    paths = window.create_file_dialog(
        webview.FileDialog.OPEN, allow_multiple=True, file_types=FILE_PICKER_TYPES
    )
    if not paths:
        return f"No elegiste ningún archivo para '{subject}'."

    copied = 0
    for path in paths:
        try:
            shutil.copy(path, dest)
            copied += 1
        except Exception as exc:
            print(f"[study_rag] no pude copiar {path}: {exc}")

    if copied == 0:
        return f"No pude copiar los archivos que elegiste para '{subject}'."

    return f"Copié {copied} archivo(s) a '{subject}'. {index_subject(subject)}"


def search(subject: str, query: str, top_k: int = TOP_K) -> list:
    """Devuelve los top_k fragmentos más parecidos semánticamente a la
    pregunta (o una lista vacía si la materia no tiene nada indexado)."""
    sdir = subject_dir(subject)
    idir = _index_dir(sdir)
    meta_path = os.path.join(idir, "meta.json")
    vectors_path = os.path.join(idir, "vectors.npy")
    if not os.path.exists(meta_path) or not os.path.exists(vectors_path):
        return []

    import numpy as np

    with open(meta_path, "r", encoding="utf-8") as f:
        meta = json.load(f)
    if not meta["chunks"]:
        return []
    vectors = np.load(vectors_path)

    model = _get_model()
    query_vec = model.encode(["query: " + query], normalize_embeddings=True)[0]
    scores = vectors @ query_vec
    top_idx = np.argsort(-scores)[:top_k]
    return [meta["chunks"][i]["text"] for i in top_idx]


def forget_subject(subject: str) -> str:
    """Borra solo el índice calculado — tus archivos originales NUNCA se
    tocan. Si vuelves a entrar a esa materia, se recalcula desde cero."""
    sdir = subject_dir(subject)
    idir = _index_dir(sdir)
    if os.path.isdir(idir):
        shutil.rmtree(idir)
        return f"Listo, olvidé lo indexado de '{subject}'. Tus archivos siguen intactos en {sdir}."
    return f"No tenía nada indexado de '{subject}'."


def delete_subject(subject: str) -> str:
    """Borra la materia por completo: archivos originales E índice. A
    diferencia de forget_subject (que solo limpia el índice y conserva tus
    apuntes), esto es lo que usa el botón de basura del selector de materias
    en la interfaz — ahí sí se espera que la materia desaparezca del todo."""
    sdir = subject_dir(subject)
    if os.path.isdir(sdir):
        shutil.rmtree(sdir)
        return f"Listo, borré la materia '{subject}' por completo."
    return f"No encontré la materia '{subject}'."
