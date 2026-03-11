"""Local embedding engine - sentence-transformers on MPS/CPU.

Embeds text into 384-dim vectors. Model loads lazily on first call.
Vectors stored as numpy blobs in SQLite.
"""
import numpy as np
from pathlib import Path

from config import EMBEDDING_MODEL, EMBEDDING_DIM, MODELS_DIR

MODEL_NAME = EMBEDDING_MODEL

# Lazy-loaded singleton
_model = None


def _ensure_installed():
    """Install sentence-transformers on first use if not present."""
    try:
        import sentence_transformers  # noqa: F401
    except ImportError:
        import subprocess, sys
        print("  [embeddings] Installing sentence-transformers (one-time)...")
        subprocess.check_call(
            [sys.executable, "-m", "pip", "install", "-q", "sentence-transformers"],
            stdout=subprocess.DEVNULL,
        )


def _load_model():
    """Load sentence-transformer model, caching to MODELS_DIR."""
    global _model
    if _model is not None:
        return _model

    _ensure_installed()
    from sentence_transformers import SentenceTransformer
    import torch

    cache_dir = MODELS_DIR / MODEL_NAME
    cache_dir.mkdir(parents=True, exist_ok=True)

    device = "mps" if torch.backends.mps.is_available() else "cpu"
    print(f"  [embeddings] Loading {MODEL_NAME} on {device}...")

    _model = SentenceTransformer(
        MODEL_NAME,
        cache_folder=str(MODELS_DIR),
        device=device,
    )
    print(f"  [embeddings] Model loaded ({EMBEDDING_DIM}-dim, {device})")
    return _model


def embed(text: str) -> np.ndarray:
    """Embed a single text into a 384-dim float32 vector.

    Lazy-loads the model on first call.
    """
    model = _load_model()
    vec = model.encode(text, convert_to_numpy=True, normalize_embeddings=True)
    return vec.astype(np.float32)


def embed_batch(texts: list[str]) -> list[np.ndarray]:
    """Batch embed multiple texts for efficiency.

    Returns a list of 384-dim float32 vectors.
    """
    if not texts:
        return []
    model = _load_model()
    vecs = model.encode(texts, convert_to_numpy=True, normalize_embeddings=True,
                        batch_size=32, show_progress_bar=False)
    return [v.astype(np.float32) for v in vecs]


def cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
    """Cosine similarity between two vectors.

    Assumes vectors are already normalized (as produced by embed()),
    so this is just the dot product. Falls back to full formula if not.
    """
    dot = np.dot(a, b)
    norm_a = np.linalg.norm(a)
    norm_b = np.linalg.norm(b)
    if norm_a == 0 or norm_b == 0:
        return 0.0
    # For normalized vectors this is ~= dot, but safe either way
    return float(dot / (norm_a * norm_b))


def vector_to_blob(vec: np.ndarray) -> bytes:
    """Serialize a numpy vector to bytes for SQLite BLOB storage."""
    return vec.astype(np.float32).tobytes()


def blob_to_vector(blob: bytes) -> np.ndarray:
    """Deserialize a SQLite BLOB back to a numpy vector."""
    return np.frombuffer(blob, dtype=np.float32).copy()
