# Production RAG: target architecture and work plan

## Keep the RAG service separate

Keep the RAG source in `backend/rag/` and the geospatial API in `backend/app/`. They are two Python applications that both import a top-level package named `app`; importing them in one interpreter can resolve the wrong `app.main` module. They also need different dependency sets and scale differently: retrieval/LLM traffic needs model memory and provider limits, while GIS work needs raster/geometry and PostGIS capacity. A monorepo with separate containers is a good arrangement. The geospatial API should call the RAG HTTP API through an internal service name, as it does in Compose.

The application currently provides a local PDF ingestion CLI, OCR options, chunk metadata, multilingual E5 embeddings, local persistent Chroma, metadata filtering, retrieval diagnostics, citation snippets, and several answer providers. It is a development foundation. Local Chroma is a single-node store and the API has no user authentication, per-document authorization, ingestion job service, or measured retrieval/answer quality gate.

## Production stages

### 1. Lock down the service boundary

- Put the dashboard/API and RAG API behind TLS and an authenticated gateway. Use OAuth2/OIDC or a managed identity provider; pass a verified user/tenant identity to retrieval.
- Keep RAG and model endpoints on a private network. Do not publish Ollama, Chroma, PostGIS, or Redis ports to the internet.
- Move secrets to the deployment secret manager. Remove development credentials and avoid exposing raw provider URLs, keys, prompt text, or document content in logs.
- Add request size, token, concurrency, and per-user rate limits. Keep retrieval diagnostics disabled outside a protected operator environment.

### 2. Make document ingestion a controlled pipeline

- Keep uploads out of the request worker. Accept a document reference, enqueue an ingestion job, and return a job ID. A separate worker should scan and validate the file, extract text/OCR in a constrained process, normalize metadata, chunk, embed, and index.
- Persist the original file, checksum, owner/tenant, parser version, embedding model/version, ingestion status, and error summary. Make retries idempotent and support document replacement and deletion from every index.
- Validate MIME type and size from file contents, scan for malware, and treat OCR/PDF parsing as untrusted input. Keep temporary files outside the web root and expire them.
- Keep credentials out of document metadata and do not silently mix embeddings from different models. Give each embedding model/version its own collection or index namespace and provide a repeatable re-index migration.

### 3. Improve retrieval and grounding

- Build a reviewed test set from representative English and Marathi questions, expected source pages, unanswerable cases, and adversarial instructions inside documents. Track Recall@k / MRR for retrieval and citation correctness, groundedness, and answerability for generation.
- Tune chunk size/overlap, metadata filters, hybrid lexical/vector search, and a cross-encoder reranker against that test set. Do not choose thresholds from a few demonstrations.
- Treat retrieved passages as untrusted evidence, not instructions. Require the model to say when evidence is insufficient, cite claims to returned page IDs, and validate citations against the retrieved set before returning the answer.
- Return the retrieved source IDs and snippets separately from the generated answer. Record the index version, embedding model, retrieval parameters, and answer model with each response.

### 4. Add durable storage and service reliability

- Use a server vector database or a managed vector store with backups, access control, encryption, and restore drills when multiple replicas or tenants are required. Keep local Chroma for development/single-node use.
- Run stateless API replicas separately from ingestion workers. Put long OCR, embedding, and batch re-index jobs on a durable queue. Use explicit connect/read timeouts, bounded retries with jitter, circuit breakers, and provider allowlists.
- Separate liveness from readiness. Readiness should report vector-store connectivity and index availability; liveness should not load a model or count an entire collection on every probe.
- Add structured logs with request/job IDs, latency histograms, error rates, provider/model and index versions, queue age, retrieval scores, and token/cost metrics. Redact question text and retrieved passages by default.
- Define retention/deletion policies, tenant isolation, index snapshots, restore procedures, and model/provider rollback procedures.

### 5. Make changes measurable before rollout

- Add unit tests for parsing/chunking/metadata, API contract tests, and a fixed RAG evaluation suite. Add load tests for concurrent retrieval and slow/unavailable providers.
- Compare a new parser, embedding model, prompt, or reranker offline before publishing a new index. Deploy a versioned index behind a small canary, monitor quality and latency, and keep a rollback path.
- Add human review for high-impact emergency instructions. Do not present generated guidance as an official alert unless it is sourced from an approved authority and has an operational approval path.

## Suggested implementation order

1. Establish RAG API contract, auth boundary, health/readiness semantics, and response provenance.
2. Add a versioned document manifest and ingestion job/status store while preserving the current CLI for local development.
3. Create the retrieval evaluation set and citation/grounding checks before changing model or chunking behavior.
4. Add tenant-aware storage, deletion, backups, and a production vector database.
5. Add worker queue, metrics/tracing, rate limits, and deployment secrets; then run load and recovery exercises.

