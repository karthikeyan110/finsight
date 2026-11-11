# FinSight ML report (2026-11-11)

## Revenue forecast backtest (last 4 quarters held out, MAPE - lower is better)

| Ticker | Quarters | Prophet | Naive | Seasonal naive | Winner |
|---|---|---|---|---|---|
| AAPL | 15 | 8.3% | 18.1% | 12.3% | Prophet |
| MSFT | 16 | 1.7% | 7.6% | 15.1% | Prophet |
| AMZN | 15 | 5.2% | 13.1% | 13.6% | Prophet |
| GOOGL | 13 | 7.5% | 13.2% | 17.1% | Prophet |
| NVDA | 15 | 21.9% | 35.9% | 44.5% | Prophet |
| TSLA | 15 | 11.0% | 12.6% | 11.9% | Prophet |
| KO | 15 | 5.3% | 3.4% | 6.1% | Naive |
| WMT | 15 | 2.2% | 3.5% | 5.8% | Prophet |
| JPM | 15 | 3.4% | 9.2% | 11.4% | Prophet |
| NKE | 16 | 10.9% | 4.7% | 0.7% | Seasonal naive |

Warnings:
- GOOGL: Series mixes revenue tags (RevenueFromContractWithCustomerExcludingAssessedTax, Revenues), so values may not be fully comparable.

## Anomalies for our 10 companies

Method: year-over-year % change vs the company's own history. Flagged when |z| > 4 AND the change is at least 15 percentage points from its usual change. 'Size peers agree' (Isolation Forest per size bucket) is information only.
Flagged: 23 for our 10 companies (15,663 across all 7,236 companies). Most extreme first.

| Ticker | Metric | Period end | YoY change | Usual | z | Size peers agree | Reason |
|---|---|---|---|---|---|---|---|
| WMT | OperatingIncomeLoss | 2023-10-31 | +130% | +8% | +24.7 | no | Operating income rose 130% vs the same quarter last year ($2.69B -> $6.20B). Its usual year-over-year change is +8%, so this is far outside its normal range (z = +24.7). For similar-size companies a change like this is not unusual. |
| NVDA | OperatingIncomeLoss | 2023-10-31 | +1,633% | +110% | +22.7 | no | Operating income rose 1,633% vs the same quarter last year ($601.00M -> $10.42B). Its usual year-over-year change is +110%, so this is far outside its normal range (z = +22.7). For similar-size companies a change like this is not unusual. |
| GOOGL | NetIncomeLoss | 2026-06-30 | +298% | +34% | +22.4 | no | Net income rose 298% vs the same quarter last year ($28.20B -> $112.19B). Its usual year-over-year change is +34%, so this is far outside its normal range (z = +22.4). For similar-size companies a change like this is not unusual. |
| NKE | NetIncomeLoss | 2026-05-31 | +407% | -27% | +20.1 | no | Net income rose 407% vs the same quarter last year ($211.00M -> $1.07B). Its usual year-over-year change is -27%, so this is far outside its normal range (z = +20.1). For similar-size companies a change like this is not unusual. |
| WMT | NetIncomeLoss | 2024-10-31 | +910% | +19% | +16.1 | no | Net income rose 910% vs the same quarter last year ($453.00M -> $4.58B). Its usual year-over-year change is +19%, so this is far outside its normal range (z = +16.1). For similar-size companies a change like this is not unusual. |
| NVDA | NetIncomeLoss | 2023-10-31 | +1,259% | +109% | +15.6 | no | Net income rose 1,259% vs the same quarter last year ($680.00M -> $9.24B). Its usual year-over-year change is +109%, so this is far outside its normal range (z = +15.6). For similar-size companies a change like this is not unusual. |
| AMZN | OperatingIncomeLoss | 2023-09-30 | +343% | +43% | +8.8 | no | Operating income rose 343% vs the same quarter last year ($2.52B -> $11.19B). Its usual year-over-year change is +43%, so this is far outside its normal range (z = +8.8). For similar-size companies a change like this is not unusual. |
| NVDA | OperatingIncomeLoss | 2024-04-30 | +690% | +110% | +8.6 | no | Operating income rose 690% vs the same quarter last year ($2.14B -> $16.91B). Its usual year-over-year change is +110%, so this is far outside its normal range (z = +8.6). For similar-size companies a change like this is not unusual. |
| NVDA | Liabilities | 2026-07-31 | +125% | +48% | +8.2 | no | Total liabilities rose 125% vs the same quarter last year ($40.61B -> $91.29B). Its usual year-over-year change is +48%, so this is far outside its normal range (z = +8.2). For similar-size companies a change like this is not unusual. |
| AAPL | NetIncomeLoss | 2025-09-30 | +86% | +9% | +7.9 | no | Net income rose 86% vs the same quarter last year ($14.74B -> $27.47B). Its usual year-over-year change is +9%, so this is far outside its normal range (z = +7.9). For similar-size companies a change like this is not unusual. |
| TSLA | OperatingIncomeLoss | 2026-03-31 | +136% | -40% | +7.1 | no | Operating income rose 136% vs the same quarter last year ($399.00M -> $941.00M). Its usual year-over-year change is -40%, so this is far outside its normal range (z = +7.1). For similar-size companies a change like this is not unusual. |
| NVDA | NetIncomeLoss | 2024-04-30 | +628% | +109% | +7.0 | no | Net income rose 628% vs the same quarter last year ($2.04B -> $14.88B). Its usual year-over-year change is +109%, so this is far outside its normal range (z = +7.0). For similar-size companies a change like this is not unusual. |
| JPM | Revenue | 2025-06-30 | -11% | +9% | -5.9 | no | Revenue fell 11% vs the same quarter last year ($50.20B -> $44.91B). Its usual year-over-year change is +9%, so this is far outside its normal range (z = -5.9). For similar-size companies a change like this is not unusual. |
| NVDA | Revenue | 2024-04-30 | +262% | +85% | +5.8 | no | Revenue rose 262% vs the same quarter last year ($7.19B -> $26.04B). Its usual year-over-year change is +85%, so this is far outside its normal range (z = +5.8). For similar-size companies a change like this is not unusual. |
| JPM | Revenue | 2026-06-30 | +28% | +9% | +5.5 | no | Revenue rose 28% vs the same quarter last year ($44.91B -> $57.35B). Its usual year-over-year change is +9%, so this is far outside its normal range (z = +5.5). For similar-size companies a change like this is not unusual. |
| AMZN | OperatingIncomeLoss | 2024-03-31 | +221% | +43% | +5.2 | no | Operating income rose 221% vs the same quarter last year ($4.77B -> $15.31B). Its usual year-over-year change is +43%, so this is far outside its normal range (z = +5.2). For similar-size companies a change like this is not unusual. |
| NVDA | Assets | 2026-07-31 | +128% | +70% | +5.2 | yes | Total assets rose 128% vs the same quarter last year ($140.74B -> $320.27B). Its usual year-over-year change is +70%, so this is far outside its normal range (z = +5.2). Similar-size companies rarely see a change like this either. |
| KO | NetIncomeLoss | 2025-06-30 | +58% | +9% | +4.7 | no | Net income rose 58% vs the same quarter last year ($2.41B -> $3.81B). Its usual year-over-year change is +9%, so this is far outside its normal range (z = +4.7). For similar-size companies a change like this is not unusual. |
| AAPL | NetIncomeLoss | 2024-09-30 | -36% | +9% | -4.6 | no | Net income fell 36% vs the same quarter last year ($22.96B -> $14.74B). Its usual year-over-year change is +9%, so this is far outside its normal range (z = -4.6). For similar-size companies a change like this is not unusual. |
| AMZN | Assets | 2026-06-30 | +61% | +22% | +4.5 | no | Total assets rose 61% vs the same quarter last year ($682.17B -> $1.10T). Its usual year-over-year change is +22%, so this is far outside its normal range (z = +4.5). For similar-size companies a change like this is not unusual. |
| WMT | OperatingIncomeLoss | 2026-07-31 | +29% | +8% | +4.1 | no | Operating income rose 29% vs the same quarter last year ($7.29B -> $9.38B). Its usual year-over-year change is +8%, so this is far outside its normal range (z = +4.1). For similar-size companies a change like this is not unusual. |
| GOOGL | NetIncomeLoss | 2026-03-31 | +81% | +34% | +4.0 | no | Net income rose 81% vs the same quarter last year ($34.54B -> $62.58B). Its usual year-over-year change is +34%, so this is far outside its normal range (z = +4.0). For similar-size companies a change like this is not unusual. |
| AAPL | Assets | 2026-06-30 | +16% | +0% | +4.0 | no | Total assets rose 16% vs the same quarter last year ($331.50B -> $383.27B). Its usual year-over-year change is +0%, so this is far outside its normal range (z = +4.0). For similar-size companies a change like this is not unusual. |

Possible restatements (negative derived Q4) among our 10 companies: 0
