# UNILOG workspace UI

Run the application from the repository root:

```powershell
.venv\Scripts\python.exe -m uvicorn unilog_product_intelligence.api:app --reload
```

Open [http://127.0.0.1:8000](http://127.0.0.1:8000). The UI reads the real row-2 enrichment report through `/api/products`; it does not invent dashboard metrics.
