Ingest: Committee Deliberations Embeddings

Overview
- Reads HTML/PDF content from a source table (default: `crawled_pages`).
- Parses to text, chunks internally, creates OpenAI embeddings.
- Stores a single vector per document in `committee_deliberations_embeddings` by default (averaged across chunks).

Important Notes
- Dimension mismatch: OpenAI models commonly return 1536 (`text-embedding-3-small`) or 3072 (`text-embedding-3-large`) dims. The provided schema uses `vector(1024)`. Set `EMBEDDING_DIM=1536` (recommended) or adjust the table. If you must keep 1024, enable a projection strategy yourself before inserting.
- Unique constraint: The provided schema has a UNIQUE on `speech_id`, which implies one row per document. This script stores one vector per document by default. If you want per-chunk rows, remove the unique constraint and add a `chunk_index` column, or create a separate chunk table.

Environment
- Database: `PGHOST`, `PGPORT`, `PGDATABASE`, `PGUSER`, `PGPASSWORD`.
- OpenAI: `OPENAI_API_KEY`.
- Optional:
  - `OPENAI_EMBEDDING_MODEL` (default: `text-embedding-3-small`)
  - `EMBEDDING_DIM` (default: `1536`)
  - `SOURCE_TABLE` (default: `crawled_pages`)
  - `TARGET_TABLE` (default: `committee_deliberations_embeddings`)
  - `URL_FILTER_REGEX` (optional regex to restrict rows by URL)
  - `BATCH_SIZE` (default: `50`)

Run
- Install deps: `pip install -r requirements.txt`
- Execute: `python -m ingest.committee_deliberations_embed`

Schema
- Apply `schema.sql` to create the `committee_deliberations_embeddings` table and the `vector` extension.
- Example inside Docker DB container: `psql -U postgres -d postgres -f /schema.sql`
