# Market Options Analyzer

This is a local Streamlit app based on the logic in `auto_app_v2.py`, which is launched by `BhavopyAnalysis.command`.

## Run on macOS

Double-click `Run.command`, or run:

```bash
cd /path/to/MarketOptionsAnalyzer
python3 -m pip install -r requirements.txt
python3 -m streamlit run app.py
```

The app opens in your browser on localhost. For public hosting, follow [DEPLOY.md](DEPLOY.md).

## Data sources

- **NSE derivatives:** Choose a trading date. The app downloads the NSE F&O bhavcopy, participant open-interest report, and sector close report. Available symbols come from that day's F&O file. NSE report availability and URLs are controlled by NSE.
- **US options:** Enter any US underlying symbol supported by MarketData.app and your own [MarketData.app API token](https://www.marketdata.app/docs/api/authentication/). The app requests the entire end-of-day chain for the chosen date. The free plan currently provides one year of history and 100 credits per day; large chains may consume several credits.
- **CSV / NSE ZIP:** Upload a MarketData.app chain export, NSE bhavcopy, or a CSV with `symbol,expiration,side,strike,option_price,volume,open_interest`. Optional columns are `underlying_price,bid,ask,contract`. Dates should be `YYYY-MM-DD`; side should be `call` or `put`. Enter the underlying reference price in the app if the file lacks it. This is how to use option chains from other markets.

The app analyzes **optionable underlyings**. A stock, index, future, or other instrument with no option-chain data cannot produce max pain or put/call ratios.

## Calculations

- Max pain: listed strike with the smallest intrinsic payout based on selected-expiry open interest.
- Put/call OI and volume ratios.
- ATM: closest listed strike, or floor to a configurable strike step.
- Expected move: `reference price × assumed IV × sqrt(days to expiry / 365)`, with a 0.5% floor; or a fixed percentage.
- Model delta, daily theta, and risk-neutral probability of finishing in the money using Black-Scholes with user-set IV and rate, zero dividend yield, and the selected reference price. These are simulated values, not historical exchange Greeks.
- Call range: strike + option price; put range: strike − option price. The 20 contracts with the largest open interest × option price are ranked by proximity to the expected-move target. The first two form resistance/support levels.

For US historical data, the chain uses the option mid price where positive, falling back to the last traded price. Historical US open interest reflects positions published before that trading day's open. Volume and quoted prices reflect the selected day's close. For NSE, the app uses option close and the matching futures close when available.

This app is for analysis; calculated levels are not forecasts or executable quotes.
