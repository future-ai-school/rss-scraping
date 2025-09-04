import os
import uuid
from io import BytesIO
from typing import List, Optional, Tuple

import psycopg2
from psycopg2.extras import RealDictCursor
from bs4 import BeautifulSoup
from pdfminer.high_level import extract_text as pdf_extract_text
from dotenv import load_dotenv

try:
    from openai import OpenAI  # openai>=1.0.0
except Exception:
    OpenAI = None


def load_config():
    load_dotenv()
    return {
        "pg_host": os.getenv("PGHOST", "localhost"),
        "pg_port": int(os.getenv("PGPORT", "5432")),
        "pg_db": os.getenv("PGDATABASE", "postgres"),
        "pg_user": os.getenv("PGUSER", "postgres"),
        "pg_password": os.getenv("PGPASSWORD", ""),
        "openai_api_key": os.getenv("OPENAI_API_KEY"),
        "embedding_model": os.getenv("OPENAI_EMBEDDING_MODEL", "text-embedding-3-small"),
        # NOTE: OpenAI text-embedding-3-small -> 1536 dims; 3-large -> 3072
        # The provided schema showed vector(1024). Adjust EMBEDDING_DIM or table accordingly.
        "embedding_dim": int(os.getenv("EMBEDDING_DIM", "1536")),
        "source_table": os.getenv("SOURCE_TABLE", "crawled_pages"),
        # Default target table renamed for committee deliberations
        "target_table": os.getenv("TARGET_TABLE", "committee_deliberations_embeddings"),
        "url_filter_regex": os.getenv("URL_FILTER_REGEX"),
        "batch_size": int(os.getenv("BATCH_SIZE", "50")),
    }


def connect_db(cfg):
    conn = psycopg2.connect(
        host=cfg["pg_host"],
        port=cfg["pg_port"],
        dbname=cfg["pg_db"],
        user=cfg["pg_user"],
        password=cfg["pg_password"],
    )
    conn.autocommit = False
    return conn


## Table creation moved to schema.sql; ensure schema exists outside this script.


def parse_html(content_bytes: bytes) -> str:
    soup = BeautifulSoup(content_bytes, "html.parser")
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()
    return soup.get_text(" ", strip=True)


def parse_pdf(content_bytes: bytes) -> str:
    bio = BytesIO(content_bytes)
    text = pdf_extract_text(bio) or ""
    return text.strip()


def extract_text(content: bytes, content_type: Optional[str]) -> Optional[str]:
    if not content:
        return None
    ct = (content_type or "").lower()
    if "pdf" in ct:
        return parse_pdf(content)
    if "html" in ct or ct.startswith("text/"):
        try:
            return parse_html(content)
        except Exception:
            try:
                return content.decode("utf-8", errors="ignore")
            except Exception:
                return None
    try:
        return parse_pdf(content)
    except Exception:
        try:
            return content.decode("utf-8", errors="ignore")
        except Exception:
            return None


def chunk_text(text: str, chunk_size: int = 4000, overlap: int = 400) -> List[str]:
    if not text:
        return []
    chunks: List[str] = []
    start = 0
    n = len(text)
    while start < n:
        end = min(start + chunk_size, n)
        chunks.append(text[start:end])
        if end == n:
            break
        start = max(end - overlap, start + 1)
    return chunks


def avg_vectors(vectors: List[List[float]]) -> List[float]:
    if not vectors:
        return []
    dim = len(vectors[0])
    sums = [0.0] * dim
    for v in vectors:
        if len(v) != dim:
            raise ValueError("Embedding dimensions mismatch")
        for i in range(dim):
            sums[i] += v[i]
    c = float(len(vectors))
    return [x / c for x in sums]


def to_pgvector(vec: List[float]) -> str:
    return "[" + ",".join(f"{x:.8f}" for x in vec) + "]"


def embed_batches(client, model: str, texts: List[str], batch_size: int) -> List[List[float]]:
    out: List[List[float]] = []
    for i in range(0, len(texts), batch_size):
        batch = texts[i : i + batch_size]
        resp = client.embeddings.create(model=model, input=batch)
        out.extend([d.embedding for d in resp.data])
    return out


def fetch_rows(conn, cfg, limit: int) -> List[dict]:
    sql = [
        f"SELECT id, url, content_type, content FROM {cfg['source_table']} ",
        "WHERE status_code = 200 AND content IS NOT NULL ",
        f"AND NOT EXISTS (SELECT 1 FROM {cfg['target_table']} t WHERE t.speech_id = {cfg['source_table']}.url) ",
    ]
    params: Tuple = tuple()
    if cfg["url_filter_regex"]:
        sql.append("AND url ~ %s ")
        params = (cfg["url_filter_regex"],)
    sql.append("ORDER BY id ASC ")
    sql.append("LIMIT %s")
    params = params + (limit,)
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute("".join(sql), params)
        return list(cur.fetchall())


def insert_row(conn, cfg, row: dict, full_text: str, embedding: List[float]):
    emb = to_pgvector(embedding)
    with conn.cursor() as cur:
        cur.execute(
            f"""
            INSERT INTO {cfg['target_table']} (
                id, speech_id, speaker, speaker_role, speaker_group,
                speech_text, issue_id, meeting_name, date, speech_url,
                speech_order, embedding
            ) VALUES (
                %s, %s, %s, %s, %s,
                %s, %s, %s, %s, %s,
                %s, %s::vector
            )
            ON CONFLICT (speech_id) DO UPDATE SET
                speech_text = EXCLUDED.speech_text,
                embedding = EXCLUDED.embedding,
                updated_at = CURRENT_TIMESTAMP
            """,
            (
                str(uuid.uuid4()),
                row["url"],  # speech_id = url
                None,
                None,
                None,
                full_text,
                None,
                None,
                None,
                row["url"],
                None,
                emb,
            ),
        )


def run():
    cfg = load_config()
    if not cfg["openai_api_key"]:
        raise RuntimeError("OPENAI_API_KEY is required")
    if OpenAI is None:
        raise RuntimeError("openai package is not installed. Run: pip install -r requirements.txt")

    client = OpenAI(api_key=cfg["openai_api_key"])  # type: ignore
    conn = connect_db(cfg)
    try:
        # Ensure the table/extension via schema.sql beforehand
        processed = 0
        while True:
            rows = fetch_rows(conn, cfg, cfg["batch_size"])
            if not rows:
                break

            docs: List[str] = []
            pairs = []  # (row, raw_text)
            for r in rows:
                content = r["content"].tobytes() if hasattr(r["content"], "tobytes") else r["content"]
                text = extract_text(content, r.get("content_type"))
                if not text:
                    continue
                pairs.append((r, text))
                docs.append(text)

            if not pairs:
                break

            # Chunk per document, embed chunks, then average per document
            per_doc_chunks: List[List[str]] = []
            flat: List[str] = []
            for _, txt in pairs:
                ch = chunk_text(txt)
                if not ch:
                    ch = [txt]
                per_doc_chunks.append(ch)
                flat.extend(ch)

            flat_vecs = embed_batches(client, cfg["embedding_model"], flat, batch_size=16)

            # Re-assemble per-doc averages
            vectors: List[List[float]] = []
            i = 0
            for ch in per_doc_chunks:
                k = len(ch)
                vec = avg_vectors(flat_vecs[i : i + k])
                i += k
                vectors.append(vec)

            # Insert
            for (row, full_text), vec in zip(pairs, vectors):
                if len(vec) != cfg["embedding_dim"]:
                    raise RuntimeError(
                        f"Embedding dim {len(vec)} != table dim {cfg['embedding_dim']}. Set EMBEDDING_DIM or adjust table."
                    )
                insert_row(conn, cfg, row, full_text, vec)

            conn.commit()
            processed += len(vectors)
            print(f"Processed {processed} into {cfg['target_table']}")
    finally:
        conn.close()


if __name__ == "__main__":
    run()
