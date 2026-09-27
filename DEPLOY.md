# Publish on Streamlit Community Cloud

The app is ready for a public Streamlit deployment. GitHub and Streamlit accounts are needed.

1. Create a **public** GitHub repository, such as `market-options-analyzer`.
2. Add `app.py`, `engine.py`, `sources.py`, `requirements.txt`, `README.md`, and `.gitignore` at the repository root. `Run.command` is optional for online hosting. Do not upload API tokens, `.env`, `secrets.toml`, or downloaded market data.
3. Sign in at [share.streamlit.io](https://share.streamlit.io) and connect your GitHub account. The repository owner needs admin access to deploy.
4. Select **Create app** → **Yup, I have an app**. Select the repository and branch; set the entrypoint to `app.py`.
5. Choose an app URL and select **Deploy**. Streamlit will install packages from `requirements.txt`.
6. Open the published URL. For US data, each visitor enters their own MarketData.app token in the password field. NSE and CSV upload do not need that token.

Do not configure one shared MarketData.app token on a public app: every visitor could spend its API credits. The app deliberately requires each visitor to enter their own token for US requests.

The app uses the official NSE report URLs and MarketData.app's historical options API. Their availability and rate limits are controlled by those providers. See [Streamlit's deployment guide](https://docs.streamlit.io/deploy/streamlit-community-cloud/deploy-your-app/deploy), [dependency guide](https://docs.streamlit.io/deploy/streamlit-community-cloud/deploy-your-app/app-dependencies), and [MarketData.app plan limits](https://www.marketdata.app/docs/account/plan-limits/).
