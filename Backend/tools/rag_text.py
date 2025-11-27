from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import faiss
import numpy as np
import pickle
from langchain_google_genai import GoogleGenerativeAIEmbeddings

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"

def _env(name: str, default: Optional[str] = None) -> str:
    return os.getenv(name) or os.getenv(name.lower()) or (default or "")

INDEX_DIR = Path(_env("RAG_INDEX_DIR", str(DATA_DIR / ".faiss_text")))
INDEX_FILE = INDEX_DIR / "index.faiss"
META_FILE = INDEX_DIR / "meta.pkl"
DOCS_DIR = Path(_env("RAG_DOCS_DIR", str(DATA_DIR / "docs")))
DOC_EXTS = {".txt", ".md", ".pdf"}

_INDEX: Optional[faiss.Index] = None
_META: List[Dict[str, Any]] = []

_HAS_PYMUPDF = False
try:
    import fitz
    _HAS_PYMUPDF = True
except Exception:
    _HAS_PYMUPDF = False


def _get_embedder() -> GoogleGenerativeAIEmbeddings:
    api_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
    if not api_key:
        raise RuntimeError("Defina GEMINI_API_KEY para usar o RAG")
    return GoogleGenerativeAIEmbeddings(
        model="text-embedding-004",
        google_api_key=api_key,
    )


def _read_txt_md(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8").strip()
    except UnicodeDecodeError:
        return path.read_text(encoding="latin-1", errors="ignore").strip()


def _read_pdf(path: Path) -> str:
    if not _HAS_PYMUPDF:
        return ""
    try:
        text_parts: List[str] = []
        with fitz.open(str(path)) as doc:
            for page in doc:
                text_parts.append(page.get_text("text"))
        return "\n".join(text_parts).strip()
    except Exception:
        return ""


def carregar_docs(pasta: Optional[str] = None) -> List[Dict[str, str]]:
    base = Path(pasta) if pasta else DOCS_DIR
    docs: List[Dict[str, str]] = []
    if not base.exists():
        print(f"RAG: pasta de docs não existe: {base}")
        return docs

    total_arquivos = 0
    lidos = 0

    for path in sorted(base.rglob("*")):
        if not path.is_file():
            continue
        ext = path.suffix.lower()
        if ext not in DOC_EXTS:
            continue
        total_arquivos += 1

        text = ""
        if ext in {".txt", ".md"}:
            text = _read_txt_md(path)
        elif ext == ".pdf":
            text = _read_pdf(path)

        text = (text or "").strip()
        if not text:
            continue

        docs.append(
            {
                "id": str(path.resolve()),
                "title": path.stem,
                "text": text,
            }
        )
        lidos += 1

    print(f"RAG: docs encontrados={total_arquivos}, lidos={lidos}")
    return docs


def _save_index(index: faiss.Index, meta: List[Dict[str, Any]]) -> None:
    INDEX_DIR.mkdir(parents=True, exist_ok=True)
    faiss.write_index(index, str(INDEX_FILE))
    with META_FILE.open("wb") as fh:
        pickle.dump(meta, fh)


def _load_index() -> Tuple[Optional[faiss.Index], List[Dict[str, Any]]]:
    if not INDEX_FILE.exists() or not META_FILE.exists():
        return None, []
    index = faiss.read_index(str(INDEX_FILE))
    with META_FILE.open("rb") as fh:
        meta = pickle.load(fh)
    return index, meta


def build_or_load_index(
    docs: Optional[List[Dict[str, str]]] = None,
) -> Tuple[Optional[faiss.Index], List[Dict[str, Any]]]:
    global _INDEX, _META
    embedder = _get_embedder()

    if docs:
        textos = [item["text"] for item in docs if item.get("text")]
        if textos:
            embeddings = embedder.embed_documents(textos)
            array = np.array(embeddings, dtype="float32")
            faiss.normalize_L2(array)
            index = faiss.IndexFlatIP(array.shape[1])
            index.add(array)
            meta = [
                {"title": item["title"], "source": item["id"], "text": item["text"]}
                for item in docs
                if item.get("text")
            ]
            _save_index(index, meta)
            _INDEX, _META = index, meta
            print(f"RAG: index com {len(meta)} docs")
            return index, meta

    index, meta = _load_index()
    _INDEX, _META = index, meta
    if index:
        print(f"RAG: index com {len(meta)} docs")
    else:
        print("RAG: index sem docs")
    return index, meta


def _ensure_index() -> bool:
    global _INDEX, _META
    if _INDEX is not None:
        return True
    index, meta = _load_index()
    if not index:
        return False
    _INDEX, _META = index, meta
    return True


def buscar(query: str, k: int = 5) -> List[Dict[str, Any]]:
    if not query or not _ensure_index():
        return []

    embedder = _get_embedder()
    vetor = np.array([embedder.embed_query(query)], dtype="float32")
    faiss.normalize_L2(vetor)
    k_value = min(k, len(_META)) or 1
    scores, indices = _INDEX.search(vetor, k_value)
    resultados: List[Dict[str, Any]] = []
    for score, idx in zip(scores[0], indices[0]):
        if idx < 0 or idx >= len(_META):
            continue
        meta = _META[idx]
        texto = " ".join((meta.get("text") or "").split())
        trecho = texto[:10000].rsplit(" ", 1)[0] + "..." if len(texto) > 10000 else texto
        resultados.append(
            {
                "title": meta.get("title", "sem título"),
                "trecho": trecho,
                "score": float(score),
            }
        )
    return resultados


def contexto_curto(query: str, k: int = 5) -> str:
    resultados = buscar(query, k=k)
    if not resultados:
        return ""
    partes = [f"{item['title']}: {item['trecho']}" for item in resultados]
    return " ".join(partes)
