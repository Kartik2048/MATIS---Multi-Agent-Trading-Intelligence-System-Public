# MATIS v3 — Multi-Agent Trading Intelligence System

MATIS (Multi-Agent Trading Intelligence System) v3 is an advanced, autonomous cryptocurrency paper-trading engine driven by multiple intelligent AI agents. It integrates live market data from Binance and CoinDCX, technical indicators, news sentiment analysis, and a LangGraph-based reasoning framework powered by NVIDIA NIM (LLaMA 3.3 70B). 

Version 3 marks a massive architectural shift to a native **INR (Indian Rupee)** trading environment, complete with simulated CoinDCX trading constraints (₹100 minimum trades + ~0.59% GST inclusive fees), ML data logging for future model training, and a high-performance Vanilla JS dashboard powered by live WebSockets.

## Architecture

MATIS leverages LangGraph to orchestrate a pipeline of specialized AI agents:

1. **Sentinel**: Parses live news headlines (via n8n) and determines a market sentiment score.
2. **Semantic Builder**: An intermediate pre-processing layer that transforms raw technical data and sentiment into descriptive English strings. It calculates **Relative Volume (RVOL)** and **BTC Macro Gravity** benchmarks.
3. **Strategist**: Analyzes pre-processed "Semantic Market Intelligence" (Trend, Momentum, Volatility, Volume, and Macro Context) to propose a trade (BUY / SELL / HOLD) along with a specific allocation percentage.
4. **Critic**: A rigorous evaluator that reviews the Strategist's proposal against the semantic intelligence to ensure logical safety. It can reject trades that ignore macro gravity or basic principles.
5. **Risk Manager**: Performs final validation against the paper trading portfolio balances, dynamically sizes the position, checks CoinDCX minimum trading limits (₹100), and deducts simulated trading fees before execution.

## Key Features

- **Native INR Execution**: Uses live CoinDCX `BTCINR`, `ETHINR`, etc. data for precise entry/exit pricing. Includes a dynamic fallback system that fetches the live `USDTINR` conversion rate.
- **CoinDCX Constraints Engine**: Simulates real-world exchange limitations, rigidly applying ~0.59% fees and preventing micro-trades below ₹100.
- **ML Data Logging Pipeline**: Silently logs every LLM decision, indicator state, and simulated outcome into `matis_ml_training.db` for future supervised ML model training.
- **Multi-Asset Support**: Trades BTC, ETH, SOL, XRP, BNB, and LINK.
- **Pure Local Indicators**: Computes indicators directly via Pandas/NumPy (RSI, Bollinger Bands, ATR, EMAs 9/21, and **Relative Volume**).
- **Semantic Translation Layer**: Converts raw technical numbers into descriptive text (e.g., "Price is testing the Upper Bollinger Band") to improve LLM reasoning accuracy.
- **Macro Gravity Engine**: Dynamically benchmarks altcoin performance against Bitcoin's 24-hour trend to determine broader market environment.
- **Paper Trading Engine**: Local SQLite database (`matis_paper_trading.db`) that simulates trades with a **₹10,000 INR starting balance**. Tracks total portfolio value, asset cost basis, and detailed trade reasoning.
- **High-Performance Dashboard**: A fully vanilla JS/HTML frontend that receives live price updates over WebSockets from the FastAPI backend without exhausting browser memory.
- **n8n Workflow Integration**: Uses `n8n workflow.json` as a data aggregator, passing news payloads to the backend API (`/analyze_trade`).

## Setup & Installation

1. Create a Python virtual environment:
   ```bash
   python -m venv venv
   source venv/bin/activate  # On Windows: venv\Scripts\activate
   ```

2. Install the required dependencies:
   ```bash
   cd matis_backend
   pip install -r requirements.txt
   ```

3. Set up environment variables in a `.env` file at the root or within the `matis_backend` folder:
   ```env
   NVIDIA_API_KEY=your_nvidia_nim_api_key_here
   ```

4. Run the FastAPI server:
   ```bash
   python main.py
   ```
   *The server will start on `http://localhost:8000`. Open this URL in your browser to view the dashboard.*

## Workflow Trigger

To simulate or run the live agent, import the provided `n8n workflow.json` into your local n8n instance. This workflow fetches the latest news and triggers the MATIS agent evaluations periodically.