# Local external data

Place challenge-provided or licensed runtime files here locally. This directory is intentionally
ignored except for this README and `.gitkeep`.

Supported examples include:

- `Unihack_ Sample Dataset - Input.csv`
- `Unihack_ Expected Output - Delivery Format.csv`
- `Unilog-Sample_200_Items-Input-vs-Output.xlsx`
- `Sample-1000_Items.xlsx`
- official Unilog reference workbooks and guidelines

Pass an explicit path to the relevant CLI, for example:

```powershell
unilog-phase6 --input data/external/Unihack_ Sample Dataset - Input.csv --limit 3
```

Do not commit challenge datasets, downloaded manufacturer documents, source caches, generated
evidence dumps, or credentials. The application reports unavailable files rather than fabricating
replacement data.
