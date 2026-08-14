# Manufacturer retrieval research

The application distinguishes discovery from authority. Google Search is a selective discovery primitive; its output is candidate metadata and citations, never the product database. A deterministic allowlist maps a manufacturer to verified domains before retrieval. URL Context is reserved for a specific approved public URL and can return citation/retrieval metadata; its retrieved content is counted in input/tool-use token accounting.

The local fetcher remains useful for deterministic cache/hash/parser behavior and does not grant agents arbitrary HTTP access. Production persistence is represented in `database/schema.sql` through manufacturer domains, source candidates, retrievals, documents, chunks, and evidence candidates.

Official references: [Google Search grounding](https://ai.google.dev/gemini-api/docs/google-search), [URL Context](https://ai.google.dev/gemini-api/docs/url-context), [tool combinations](https://ai.google.dev/gemini-api/docs/tool-combination), and [Docling](https://docling-project.github.io/docling/).
