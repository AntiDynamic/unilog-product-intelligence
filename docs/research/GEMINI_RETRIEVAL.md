# Gemini retrieval research

Phase 5 retains `gemini-3.5-flash-lite`. The Interactions API is used for strict structured evidence extraction. The provider exposes only two explicit built-in retrieval selections: `google_search` for unresolved discovery and `url_context` for a specific verified URL. Search is never enabled by the source fetcher, and URL Context is never given an arbitrary URL list.

The application captures request/usage fields when exposed, including tool-call count, and treats source citations as supplemental metadata: the underlying URL, fetched content hash, parser output, and evidence span remain required provenance.

Official references: [Interactions](https://ai.google.dev/gemini-api/docs/interactions-overview), [structured output](https://ai.google.dev/gemini-api/docs/structured-output), [Google Search](https://ai.google.dev/gemini-api/docs/google-search), and [URL Context](https://ai.google.dev/gemini-api/docs/url-context).
