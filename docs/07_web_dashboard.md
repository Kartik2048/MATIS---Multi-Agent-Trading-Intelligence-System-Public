# Real-Time Web Dashboard

## 1. Dashboard Architecture

MATIS features a high-performance, single-page trading cockpit located at `matis_backend/static/index.html`. It is built with vanilla HTML5, CSS3, and JavaScript, eliminating Node.js bundling overhead or bulky framework runtimes.

```text
FastAPI Server (Port 8000)
       │
       ├──► GET /                     ──► Serves static/index.html
       ├──► WS /ws/prices             ──► Streams live CoinDCX INR ticker updates
       └──► REST Endpoints (/api/...) ──► Polled for portfolio, trades & charts
```

---

## 2. Key Interface Sections

### A. Live Price & Navigation Banner
- **Streaming Rates**: Real-time CoinDCX spot prices with 24-hour percentage changes streamed continuously over WebSockets.
- **Active Asset Selector**: Dropdown switcher (`BTC`, `ETH`, `SOL`, `XRP`, `BNB`, `LINK`) that re-indexes the dashboard view to the selected coin.
- **On-Demand Evaluation Button**: A quick-trigger button (`⚡ Analyze [Asset] Now`) allowing operators to initiate an immediate multi-agent evaluation for the active coin without waiting for the 5-minute background cycle.

### B. Core Metrics Grid
- **Total Portfolio Value**: Mark-to-market valuation combining liquid INR cash and active coin holdings.
- **Liquid INR Cash**: Available cash for new allocations.
- **Global Net P&L**: Lifetime gain/loss split into **Realized P&L** (closed trades) and **Unrealized P&L** (open positions).
- **Selected Asset P&L**: Individual coin performance displaying weighted average entry price, total units held, and current cost basis.
- **Executed Trade Counter**: Displays the exact count of filled `BUY` and `SELL` orders, remaining at zero on `HOLD` without false inflation.

### C. Chart.js Data Visualizations
- **Portfolio Equity Curve**: Plots chronological total account valuation over time using snapshots from `matis_ml_training.db`.
- **Asset Performance Attribution**: Bar chart illustrating trade distribution and realized profit contribution per cryptocurrency.

### D. Interactive Trade History Ledger
The table features a dedicated **Asset** column with custom color-coded badges for instant visual identification:

$$\text{Time} \;\mid\; \mathbf{Asset} \;\mid\; \text{Action} \;\mid\; \text{Price} \;\mid\; \text{Size} \;\mid\; \text{Value (INR)} \;\mid\; \text{Realized P&L} \;\mid\; \text{Confidence} \;\mid\; \text{Reasoning}$$

| Column | Description |
|---|---|
| **Time** | Localized timestamp formatted as `MMM DD, HH:MM:SS`. |
| **Asset** | Prominent color-coded badge: `BTC` (Gold), `ETH` (Purple), `SOL` (Teal), `XRP` (Sky Blue), `BNB` (Yellow), `LINK` (Blue). |
| **Action** | Directional badge: `▲ BUY` (Green), `▼ SELL` (Red), `⏸ HOLD` (Slate Gray). |
| **Price** | Spot execution or evaluated market price in INR. |
| **Size** | Transacted coin units (displayed as `—` on `HOLD` while keeping the coin badge clear). |
| **Value (INR)** | Total order value in INR. |
| **Realized P&L** | Realized profit or loss locked in on `SELL`. |
| **Confidence** | Visual percentage bar with color progression (Green $\ge 80\%$, Yellow $\ge 60\%$, Red $< 60\%$). |
| **Reasoning** | The complete synthesis and rationale produced by the Strategist and validated by the Critic. |

---

## 3. Real-Time WebSocket Streaming

The dashboard connects to `ws://localhost:8000/ws/prices` on initial load:

```javascript
const ws = new WebSocket(`ws://${location.host}/ws/prices`);
ws.onmessage = (event) => {
    const msg = JSON.parse(event.data);
    if (msg.type === 'price_update') {
        updateINRPrices(msg.prices);
    }
};
```
- Includes automatic reconnection handling (`setTimeout(connectWebSocket, 3000)` on disconnect).
- Updates DOM price items with subtle green/red price flash animations.

---

## 4. Reset & Safety Controls

The dashboard includes a dedicated **Reset Environment** button (`#btnReset`):
- Triggers a confirmation prompt to prevent accidental data loss.
- Dispatches a `POST /api/reset` call that wipes trade logs, restores cash balance to ₹10,000.00, and zeroes all coin holdings.
- Immediately refreshes all dashboard charts and metrics to the pristine baseline.
