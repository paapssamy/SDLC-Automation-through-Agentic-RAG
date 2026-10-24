"""Phase 1 check: run a semantic search against the knowledge base and print the scores.

python scripts/semantic_search.py "add purpose code to pacs.008 messages"
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.rag.embedding_service import get_embedder  # noqa: E402
from app.rag.retriever import Retriever  # noqa: E402

query = " ".join(sys.argv[1:]) or "add purpose code to pacs.008 messages"
emb = get_embedder()
print(f"Embedder: {type(emb).__name__}, dimensions: {len(emb.embed('x'))}")
ctx = Retriever().get_context(query, agent_name="semantic_search_script")
print(f"Query: {query!r}\nFallback to baseline specs: {ctx.used_fallback}\n")
for s in ctx.sources:
    tag = "BASELINE" if s.is_baseline else f"doc {s.doc_id}"
    print(f"  {s.score:5.3f}  {s.service_name:32s} ({tag}, v{s.version})")
