# StockSense — Smart Retail Inventory

This upgrade preserves the original Flask + SQLite login, inventory, sales, and reorder flow and adds batch-level stock entries, expiry alerts, barcode lookup, analytics, shop name, and supplier scorecards.

## Run on Windows (Python 3.13 supported)

1. Extract the ZIP, then open the `StockSense_Fixed` folder in VS Code.
2. Open **Terminal → New Terminal**.
3. Create a virtual environment:
   ```powershell
   python -m venv .venv
   ```
4. Activate it:
   ```powershell
   Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
   .\.venv\Scripts\Activate.ps1
   ```
   If your terminal already shows `(.venv)`, skip these two steps.
5. Install packages:
   ```powershell
   python -m pip install -r requirements.txt
   ```
6. Start:
   ```powershell
   python app.py
   ```
7. Open `http://127.0.0.1:5000`.

## New features

- Shop name saved to the signed-in account.
- Barcode lookup using manual entry, supported phone camera scanning, or uploaded barcode image.
- Existing barcode matches show saved batches; unknown barcodes are not auto-filled with invented product data.
- Add each new delivery as its own stock entry with its own quantity, batch label and expiry date. The same barcode can have multiple batches.
- Dashboard warns about batches expiring today or within the next 3 days; expired batches are flagged.
- Expired batches are blocked from sales, and overselling is blocked.
- Weekly (7 days), monthly (30 days), and yearly (365 days) best-seller charts display quantity and purchase-value estimates from recorded sales.
- Supplier scorecards store average delivery days, purchase price, delayed deliveries, product issues and notes.
- Reorder suggestions use daily demand × supplier lead time + safety stock − usable stock. Expired stock is excluded from usable stock.
- Stock movement history is recorded for opening batches and sales.

## Barcode notes

Camera scanning needs a supported browser and permission. Browser camera access generally requires HTTPS or localhost. The live camera/photo detector uses the browser's `BarcodeDetector` API, which is not supported in every browser. If unavailable, enter the barcode manually. The file upload form accepts PNG/JPG/WEBP files and provides a server-side upload path, but decoding from a photo is performed in a supported browser. No external product database is connected, so the barcode only finds records already saved in this shop account.

## Existing database

The app adds columns and tables with safe additive migrations on startup; it does not intentionally delete existing users, products or sales. Back up `stocksense.db` before upgrading. Existing product rows are retained as individual stock entries.

## Important limitations

- This is a local educational prototype, not a production-ready POS.
- Historical sales charts use the existing sales records. Purchase value uses purchase cost saved at sale time when available, otherwise current product cost for older records.
- Sales quantity is tracked against the selected batch. For accurate expiry/FIFO handling, choose the batch being sold.
- Supplier scorecard records information for comparison; it is not an external verified supplier rating. Supplier recommendation is a basic scorecard, not an ML model.
- Demand prediction is a transparent baseline formula, not a trained AI model. Better forecasts need sufficient historical sales.
- Chart.js is loaded from a CDN, so charts need internet access. Other pages remain usable without chart loading.
- Before public deployment, set `STOCKSENSE_SECRET_KEY` to a secure random value, turn off debug mode, and add production security controls.


## Bundled Excel product data

The provided `data/stocksense_products.csv` was generated from the supplied `stocksense.xlsx` workbook (20 product records). When a user logs in or opens the dashboard, StockSense automatically adds any bundled products whose barcodes are not already in that user's inventory. Existing products are preserved. Imported quantities start at 0; enter the actual quantity in the inventory page.
