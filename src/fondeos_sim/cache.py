"""Caché en disco para resultados caros (optimizaciones, simulaciones de cartera).

La clave incluye los argumentos, el contenido de todos los planes y el código del paquete, así que
cualquier cambio de reglas o del motor invalida la caché sin tener que borrarla a mano.
"""

import gzip
import hashlib
import pickle
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CACHE_DIR = ROOT / ".cache"


def _fingerprint() -> str:
    h = hashlib.sha256()
    for folder in (ROOT / "plans", Path(__file__).parent):
        for f in sorted(folder.glob("*.y*ml")) + sorted(folder.glob("*.py")):
            if f.name in ("dashboard.py", "cli.py"):
                continue
            h.update(f.name.encode())
            h.update(f.read_bytes())
    return h.hexdigest()[:16]


def cached(name: str, key, fn):
    """Devuelve fn() guardado en disco bajo (name, key, huella de planes y motor)."""
    digest = hashlib.sha256(repr((key, _fingerprint())).encode()).hexdigest()[:20]
    path = CACHE_DIR / f"{name}-{digest}.pkl.gz"
    if path.exists():
        try:
            return pickle.loads(gzip.decompress(path.read_bytes()))
        except Exception:   # caché corrupta o de otra versión: se recalcula
            path.unlink(missing_ok=True)
    value = fn()
    CACHE_DIR.mkdir(exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_bytes(gzip.compress(pickle.dumps(value), 6))
    tmp.replace(path)
    return value
