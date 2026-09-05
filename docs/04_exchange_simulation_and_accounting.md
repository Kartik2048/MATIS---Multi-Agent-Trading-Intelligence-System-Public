# Exchange Simulation & Accounting

## 1. Indian Rupee (INR) Native Architecture

Unlike traditional crypto simulators that operate in fictional, frictionless USD balances, MATIS v3 is modeled directly on the **CoinDCX Indian cryptocurrency exchange**. Every asset valuation, cash balance, fee deduction, and profit/loss calculation is computed natively in **INR (₹)**.

```text
               ┌────────────────────────────────────────────────────────┐
               │              COINDCX INR SIMULATION ENGINE             │
               ├────────────────────────────────────────────────────────┤
               │ • Base Currency:           INR (₹)                     │
               │ • Initial Cash Balance:    ₹10,000.00                  │
               │ • Minimum Order Size:      ₹100.00                     │
               │ • Base Spot Taker Fee:     0.50%                       │
               │ • GST on Exchange Fee:     18.00%                      │
               │ • Effective Fee Rate:      ~0.59% (0.005 × 1.18)       │
               └────────────────────────────────────────────────────────┘
```

---

## 2. Order Validation & Fee Computation

Before an order touches the database ledger, it passes through `validate_coindcx_trade()` in `ml_database.py`:

### A. Minimum Order Threshold Check
CoinDCX enforces a strict minimum order size of **₹100**:
$$\text{Order Value (INR)} \ge ₹100.00$$

If $\text{Order Value} < ₹100$, the transaction is immediately rejected and recorded in `trade_logs` with terminal status `BLOCKED_COINDCX`.

### B. Fee & GST Mathematical Formula
Exchange trading fees in India attract Goods and Services Tax (GST) at 18%:

$$\text{Base Fee} = \text{Trade Value} \times 0.005$$
$$\text{GST Amount} = \text{Base Fee} \times 0.18$$
$$\text{Total Fee (INR)} = \text{Trade Value} \times 0.005 \times 1.18 \approx \text{Trade Value} \times 0.0059$$

*Example*: For a ₹1,500.00 trade:
$$\text{Base Fee} = 1500 \times 0.005 = ₹7.50$$
$$\text{GST} = 7.50 \times 0.18 = ₹1.35$$
$$\text{Total Fee} = 7.50 + 1.35 = ₹8.85$$

### C. Solvency Checks
- **On BUY**:
  $$\text{Total Cost} = \text{Trade Value} + \text{Total Fee}$$
  $$\text{Required Condition}: \text{Liquid Cash (INR)} \ge \text{Total Cost}$$
- **On SELL**:
  $$\text{Required Condition}: \text{Held Asset Balance} \ge \text{Units To Sell}$$

---

## 3. Cost-Basis & Profit/Loss Accounting

### A. Rolling Average Entry Price (Cost-Basis)
When buying into an existing coin position, the average cost basis is recalculated using weighted volume averaging:

$$\text{New Avg Price} = \frac{(\text{Current Balance} \times \text{Current Avg Price}) + (\text{New Units} \times \text{Execution Price})}{\text{Current Balance} + \text{New Units}}$$

If the position is brand new ($\text{Balance} = 0$), the average entry price is simply the execution price.

### B. Realized Profit & Loss (P&L)
Realized profit is locked in exclusively when an asset is sold:

$$\text{Realized P&L (INR)} = \Big[(\text{Sell Price} - \text{Avg Entry Price}) \times \text{Units Sold}\Big] - \text{Fee Paid (INR)}$$

*Example*:
- Bought $0.001\text{ BTC}$ at an average entry price of $₹8,000,000$.
- Sold $0.001\text{ BTC}$ at $₹8,500,000$.
- Trade Value: $₹8,500.00$. Fee: $₹8,500 \times 0.0059 = ₹50.15$.
$$\text{Gross Profit} = (8,500,000 - 8,000,000) \times 0.001 = ₹500.00$$
$$\text{Realized Net Profit} = ₹500.00 - ₹50.15 = ₹449.85$$

> **Rule**: Selling a partial position does **not** alter the remaining position's `avg_entry_price`. Only when the coin balance falls to zero is the average entry price reset to ₹0.00.

### C. Unrealized Profit & Loss (P&L)
Computed continuously in real time as live CoinDCX spot prices stream in:

$$\text{Unrealized P&L (INR)} = (\text{Live Spot Price} - \text{Avg Entry Price}) \times \text{Held Coin Units}$$

---

## 4. Mark-to-Market Portfolio Valuation

Total account valuation tracks cash plus all active cryptocurrency holdings marked against the latest CoinDCX spot prices:

$$\text{Total Portfolio Value} = \text{Liquid Cash (INR)} + \sum_{i=1}^{N} \Big(\text{Holding Units}_i \times \text{Live Spot Price}_i\Big)$$

$$\text{Net P&L (INR)} = \text{Total Portfolio Value} - \text{Initial Deposit (₹10,000)}$$

$$\text{Net P&L (\%)} = \left(\frac{\text{Total Portfolio Value} - 10000}{10000}\right) \times 100$$
