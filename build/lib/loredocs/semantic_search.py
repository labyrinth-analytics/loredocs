"""LanceDB hybrid search for LoreDocs Pro.

Chunk-aware document index: documents are split at paragraph boundaries
(max ~256 tokens per chunk). Each chunk gets its own embedding. Search
returns doc_ids deduped by best-scoring chunk.

All lancedb, sentence-transformers, and pyarrow imports are lazy -- free-tier
users who have not installed Pro deps will never trigger them.

ADR: docs/agent-reports/architecture/proposals/lancedb_hybrid_search_evaluation_20260511.md
Stage: 2B (LoreDocs). Follows Stage 2A (LoreConvo, hybrid_search.py).
"""
import logging
import os
import re
from pathlib import Path
from typing import List, Optional

_log = logging.getLogger(__name__)

CHUNK_MAX_CHARS = 1024  # approx 256 tokens at 4 chars/token average

# Truncated UUIDs are [0-9a-f-]{1..12}; safe_id must not contain SQL metacharacters.
# LanceDB 0.30.2 has no parameterized filter API; constrain input space here.
# Revisit on every LanceDB upgrade to check for parameterized support.
_SAFE_ID_RE = re.compile(r'^[0-9a-f-]{1,36}$', re.IGNORECASE)


def _chunk_text(text: str) -> List[str]:
    """Split text at paragraph boundaries, max CHUNK_MAX_CHARS per chunk.

    Returns a list of non-empty chunk strings.
    """
    if not text or not text.strip():
        return []

    paragraphs = [p.strip() for p in text.split('\n\n') if p.strip()]
    if not paragraphs:
        paragraphs = [text.strip()]

    chunks: List[str] = []
    current_parts: List[str] = []
    current_len = 0

    for para in paragraphs:
        if len(para) > CHUNK_MAX_CHARS:
            if current_parts:
                chunks.append('\n\n'.join(current_parts))
                current_parts, current_len = [], 0
            for i in range(0, len(para), CHUNK_MAX_CHARS):
                chunks.append(para[i:i + CHUNK_MAX_CHARS])
        elif current_len + len(para) + 2 > CHUNK_MAX_CHARS and current_parts:
            chunks.append('\n\n'.join(current_parts))
            current_parts, current_len = [para], len(para)
        else:
            current_parts.append(para)
            current_len += len(para) + 2

    if current_parts:
        chunks.append('\n\n'.join(current_parts))

    return [c for c in chunks if c.strip()]


def _rrf_merge(vec_results: list, fts_results: list, k: int = 60, limit: int = 40) -> list:
    """Reciprocal Rank Fusion of chunk-level vector and FTS result lists."""
    scores: dict = {}
    id_to_row: dict = {}
    for rank, r in enumerate(vec_results):
        key = (r.get('doc_id', ''), r.get('chunk_index', 0))
        scores[key] = scores.get(key, 0.0) + 1.0 / (k + rank + 1)
        id_to_row[key] = r
    for rank, r in enumerate(fts_results):
        key = (r.get('doc_id', ''), r.get('chunk_index', 0))
        scores[key] = scores.get(key, 0.0) + 1.0 / (k + rank + 1)
        id_to_row[key] = r
    ranked = sorted(scores.items(), key=lambda x: x[1], reverse=True)
    return [id_to_row[key] for key, _ in ranked[:limit]]


def _dedup_to_docs(chunks: list, limit: int) -> List[str]:
    """Take the first (best-scoring) chunk per doc_id, return doc_ids in order."""
    seen: dict = {}
    for chunk in chunks:
        doc_id = chunk.get('doc_id', '')
        if doc_id and doc_id not in seen:
            seen[doc_id] = True
    return list(seen.keys())[:limit]


class DocLanceIndex:
    """Manages docs.lance/ LanceDB chunk index for LoreDocs Pro hybrid search.

    Dual-write pattern: SQLite is the system of record; this index is derived.
    If the index is lost or corrupted, call rebuild() to regenerate from SQLite.

    File layout:
        ~/.loredocs/loredocs.db     -- SQLite (always present, all tiers)
        ~/.loredocs/docs.lance/     -- LanceDB (Pro only, chmod 700)
    """

    def __init__(self, lance_dir: Path):
        self._lance_dir = lance_dir
        self._model = None
        self._db = None
        self._table = None

    def _get_model(self):
        if self._model is None:
            from sentence_transformers import SentenceTransformer  # noqa: lazy Pro dep
            self._model = SentenceTransformer('BAAI/bge-small-en-v1.5')
        return self._model

    def _get_db(self):
        if self._db is None:
            import lancedb  # noqa: lazy Pro dep
            self._lance_dir.mkdir(parents=True, exist_ok=True)
            os.chmod(self._lance_dir, 0o700)
            self._db = lancedb.connect(str(self._lance_dir))
        return self._db

    def _open_table(self):
        """Try to open the docs table; return None if it does not exist."""
        if self._table is None:
            try:
                self._table = self._get_db().open_table('docs')
            except Exception:
                self._table = None
        return self._table

    @staticmethod
    def _make_schema():
        import pyarrow as pa  # noqa: lazy Pro dep
        return pa.schema([
            pa.field('doc_id', pa.string()),
            pa.field('chunk_index', pa.int32()),
            pa.field('vault_id', pa.string()),
            pa.field('name', pa.string()),
            pa.field('chunk_text', pa.string()),
            pa.field('vector', pa.list_(pa.float32(), 384)),
        ])

    def is_available(self) -> bool:
        """Return True if the index exists and has at least one row."""
        try:
            table = self._open_table()
            return table is not None and table.count_rows() > 0
        except Exception:
            return False

    def index_document(self, doc_id: str, vault_id: str, name: str, text: str) -> bool:
        """Chunk and index a document. Returns True on success.

        Replaces any existing chunks for this doc_id, then inserts new chunks.
        Errors are logged but never raised (never block a document save).
        """
        if not text or not text.strip():
            return True
        if not _SAFE_ID_RE.match(doc_id):
            _log.warning("index_document: unsafe doc_id rejected: %.32s", doc_id)
            return True

        try:
            prefix = f"{name}. " if name else ""
            chunks = _chunk_text(prefix + text)
            if not chunks:
                return True

            model = self._get_model()
            embeddings = model.encode(chunks, show_progress_bar=False, batch_size=32)

            rows = [{
                'doc_id': doc_id,
                'chunk_index': i,
                'vault_id': vault_id,
                'name': name or '',
                'chunk_text': chunk[:2000],
                'vector': embeddings[i].tolist(),
            } for i, chunk in enumerate(chunks)]

            table = self._open_table()
            if table is None:
                self._table = self._get_db().create_table('docs', rows, schema=self._make_schema())
                self._table.create_fts_index('name', replace=True)
                self._table.create_fts_index('chunk_text', replace=True)
            else:
                table.delete(f"doc_id = '{doc_id}'")
                table.add(rows)

            return True
        except Exception as exc:
            _log.error("Lance index_document failed for %s: %s", doc_id, exc)
            return False

    def delete_document(self, doc_id: str) -> bool:
        """Remove all chunks for a document from the index."""
        if not _SAFE_ID_RE.match(doc_id):
            _log.warning("delete_document: unsafe doc_id rejected: %.32s", doc_id)
            return True
        try:
            table = self._open_table()
            if table is not None:
                table.delete(f"doc_id = '{doc_id}'")
            return True
        except Exception as exc:
            _log.error("Lance delete_document failed for %s: %s", doc_id, exc)
            return False

    def search(self, query: str, vault_id: Optional[str] = None, limit: int = 10) -> List[str]:
        """Hybrid search (vector + BM25 FTS + RRF + doc-level dedup).

        Returns doc_ids in relevance order (best first).
        Returns empty list if index is unavailable or search fails.
        """
        table = self._open_table()
        if table is None:
            return []

        try:
            q_vec = self._get_model().encode(query).tolist()

            where_clause: Optional[str] = None
            if vault_id:
                if not _SAFE_ID_RE.match(vault_id):
                    _log.warning("search: unsafe vault_id rejected: %.32s", vault_id)
                    return []
                # LanceDB 0.30.2 has no parameterized filter API; '' escapes a single-quote.
                # Revisit on every LanceDB upgrade to check for parameterized support.
                safe_vault = vault_id.replace("'", "''")
                where_clause = f"vault_id = '{safe_vault}'"

            vec_q = table.search(q_vec, vector_column_name='vector', query_type='vector')
            if where_clause:
                vec_q = vec_q.where(where_clause)
            vec_results = vec_q.limit(limit * 4).to_list()

            fts_results: list = []
            try:
                fts_q = table.search(query, query_type='fts')
                if where_clause:
                    fts_q = fts_q.where(where_clause)
                fts_results = fts_q.limit(limit * 4).to_list()
            except Exception:
                pass  # FTS index may not exist on very new tables

            merged = _rrf_merge(vec_results, fts_results, k=60, limit=limit * 4)
            return _dedup_to_docs(merged, limit=limit)
        except Exception as exc:
            _log.error("Lance search failed: %s", exc)
            return []

    def rebuild(self, docs: list) -> int:
        """Rebuild the Lance index from a list of doc dicts.

        Each dict must have: doc_id, vault_id, name, text.
        Drops and recreates the table. Returns total chunk count indexed.
        Raises on fatal errors (caller should handle).
        """
        valid = [d for d in docs if d.get('doc_id') and d.get('text', '').strip()]
        if not valid:
            return 0

        model = self._get_model()
        all_rows: list = []
        for doc in valid:
            prefix = f"{doc.get('name', '')}. " if doc.get('name') else ""
            chunks = _chunk_text(prefix + doc['text'])
            if not chunks:
                continue
            embeddings = model.encode(chunks, show_progress_bar=False, batch_size=32)
            for i, chunk in enumerate(chunks):
                all_rows.append({
                    'doc_id': doc['doc_id'],
                    'chunk_index': i,
                    'vault_id': doc.get('vault_id', ''),
                    'name': doc.get('name', ''),
                    'chunk_text': chunk[:2000],
                    'vector': embeddings[i].tolist(),
                })

        if not all_rows:
            return 0

        db = self._get_db()
        try:
            db.drop_table('docs')
        except Exception:
            pass
        self._table = None

        schema = self._make_schema()
        self._table = db.create_table('docs', all_rows, schema=schema)
        self._table.create_fts_index('name', replace=True)
        self._table.create_fts_index('chunk_text', replace=True)
        os.chmod(self._lance_dir, 0o700)
        return len(all_rows)


def get_lance_db_path(root: Optional[Path] = None) -> Optional[Path]:
    """Return the docs.lance/ directory path for this LoreDocs install.

    Used by LoreConvo to locate the LoreDocs Lance index for cross-product
    similarity queries without hardcoding the path. Returns None if the
    index directory does not exist (Pro not enabled or never indexed).
    """
    from .storage import DEFAULT_ROOT
    lance_dir = (root or DEFAULT_ROOT) / 'docs.lance'
    return lance_dir if lance_dir.exists() else None
