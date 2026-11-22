# Meesho AI Seller Control Center — Starter Module 01

A standalone Flask application for importing Meesho seller reports into a local SQLite database. This is the first working module: report upload, basic report-type detection, normalized storage, duplicate protection, import audit history and a dashboard preview.

## 1. Run locally

```bash
python -m venv .venv
# Windows:
.venv\Scripts\activate
# macOS/Linux:
source .venv/bin/activate

pip install -r requirements.txt
python app.py
```

Open http://127.0.0.1:5000

## 2. Import workflow

1. Download a report from the Meesho Supplier Panel.
2. Open the dashboard and choose the CSV/XLS/XLSX file.
3. Select Auto-detect or choose Orders, Returns, Settlements, Advertising or Inventory.
4. Import. The dashboard shows added/skipped row counts and the Import history page records each accepted file.

The importer stores the original row as JSON as well as a set of normalized fields. This preserves source columns for future mapping refinements.

## 3. Important limitations

- This is not an official Meesho integration and does not log in to Meesho.
- Live API sync requires authorised Meesho API/partner credentials and documented endpoints.
- Meesho report headers can vary. Review the source report and adjust the aliases in `app.py` if your exports use different column names.
- Current duplicate detection is conservative and based on report-specific identifiers. For ads/inventory, use date/campaign or SKU identifiers in the export to avoid collapsing separate snapshots.
- This module does not yet calculate final profit, GST/ITC, return-adjusted contribution, ad attribution or settlement reconciliation.
- Do not upload passwords, OTPs, payment credentials or unnecessary customer personal data.

## 4. Deploy to Render

1. Push this folder to a private GitHub repository.
2. Create a new Web Service on Render and connect the repository.
3. Build command: `pip install -r requirements.txt`
4. Start command: `gunicorn app:app`
5. Add environment variables:
   - `SECRET_KEY`: a long random secret
   - `DATABASE_PATH`: preferably a path on a persistent disk, e.g. `/var/data/seller_data.db`
6. Attach a Render persistent disk and mount it at `/var/data`. Without persistent storage, SQLite data may be lost on redeploy.

For production use, configure authentication, HTTPS, backups, access controls and a persistent database before importing sensitive seller data.

## 5. Next modules

- Header mapping wizard for actual Meesho exports
- Product master and purchase-cost management
- Return/RTO loss analysis
- Settlement reconciliation
- Advertising campaign performance
- Profit by SKU and order
- Authenticated ChatGPT tools / MCP interface
- Authorised API sync, if access is granted
