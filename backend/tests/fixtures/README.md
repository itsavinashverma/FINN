# TEST FIXTURES — NOT LIVE DATA

These files are **real responses captured on 2026-11-13** from the live sources, saved so that
parsing and normalisation can be tested offline. They are used **only by `tests/`**; the API never
serves them, and nothing in `finn/` reads this directory.

| File | Captured from | Notes |
|---|---|---|
| `nse_announcements_TCS.json` | `nseindia.com/api/corporate-announcements?symbol=TCS&from_date=01-10-2026&to_date=13-11-2026` | trimmed to first 15 items |
| `nse_announcements_all_2026-11-12_one_per_desc.json` | same API, all equities for 12-Nov-2026 | one item per distinct NSE `desc` label (56) for classifier coverage |
| `bse_announcements_TCS.json` | `api.bseindia.com/BseIndiaAPI/api/AnnSubCategoryGetData/w` (scrip 532540, 01-Oct → 13-Nov-2026) | complete response |
| `screener_TCS_consolidated.html` | `screener.in/company/TCS/consolidated/` | complete page |
| `nse_integrated_filing_list_{TCS,HDFCBANK}.json` | `nseindia.com/api/integrated-filing-results?symbol=…&type=Integrated Filing- Financials` | complete response (7 quarters × 2 bases) |
| `nse_if_TCS_consolidated_2026Q2.xml` | `nsearchives…/INTEGRATED_FILING_INDAS_1734607_08102026100810_WEB.xml` | company format; values cross-checked against Screener |
| `nse_if_TCS_consolidated_2026Q4.xml` | TCS Q4 FY26 integrated filing XBRL | Q4 layout (Jan–Mar quarter + full year) |
| `nse_if_HDFCBANK_consolidated_2026Q2.xml` | HDFCBANK Q2 FY27 integrated filing XBRL | banking format |
| `nse_if_BAJFINANCE_consolidated_2026Q2.xml` | `…/INTEGRATED_FILING_NBFC_INDAS_1742040_19102026075918_WEB.xml` | NBFC format |
