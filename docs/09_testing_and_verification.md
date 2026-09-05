# Testing & Verification

## 1. Testing Philosophy & Strategy

MATIS v3 incorporates an automated test suite implemented in **pytest** (`tests/`) to ensure deterministic execution across indicator calculations, risk boundaries, ledger math, and notification filters.

Because MATIS is an autonomous trading platform managing continuous state, tests adhere to three strict principles:
1. **Zero Production Mutation**: Tests **never** read or write to `matis_paper_trading.db` or `matis_ml_training.db`.
2. **Ephemeral Database Isolation**: Every individual test function executes against a dedicated temporary SQLite instance instantiated inside pytest's `tmp_path`.
3. **No External LLM API Calls in Unit Tests**: Agent logic and network requests are decoupled or mocked to allow lightning-fast local execution without burning NVIDIA NIM quotas.

---

## 2. Test Suite Structure

```text
tests/
├── __init__.py
├── conftest.py                   # Global fixtures: temp SQLite DBs & sys.path configuration
├── test_api.py                   # FastAPI client endpoint tests & trade count filters (5 tests)
├── test_database.py              # Portfolio ledger, P&L & BUY/SELL execution tests (7 tests)
├── test_indicators.py            # Technical indicators (RSI, ATR, BB, RVOL) & semantic layer (9 tests)
├── test_ml_database.py           # CoinDCX fees, ₹100 limits & ML logging tests (4 tests)
├── test_scheduler_semaphore.py   # asyncio.Semaphore concurrency & basket loop tests (2 tests)
└── test_telegram_filter.py       # Strict Telegram notification filter (BUY/SELL only) (5 tests)
```

---

## 3. Database Isolation Fixture (`conftest.py`)

Using pytest's `tmp_path` and `monkeypatch`, `conftest.py` redirects `database.DB_PATH` and `ml_database.ML_DB_PATH` to temporary folders before each test executes:

```python
@pytest.fixture(autouse=True)
def isolated_databases(tmp_path, monkeypatch):
    """
    Direct all SQLite connections to a temporary directory for each test run.
    Ensures tests never touch or mutate the live trading databases.
    """
    test_db = str(tmp_path / "test_paper_trading.db")
    test_ml_db = str(tmp_path / "test_ml_training.db")

    monkeypatch.setattr(database, "DB_PATH", test_db)
    monkeypatch.setattr(ml_database, "ML_DB_PATH", test_ml_db)

    database.init_db()
    ml_database.init_ml_db()

    yield
```

---

## 4. Module Breakdown

### A. `test_database.py` (7 Tests)
- `test_initial_portfolio_state`: Verifies fresh database initializes with ₹10,000 INR cash and zero holdings.
- `test_buy_trade_execution`: Verifies cash deduction, fee addition, coin balance increase, and average entry price tracking.
- `test_buy_insufficient_funds`: Verifies buy attempts exceeding cash balance are safely rejected.
- `test_sell_trade_execution_and_realized_profit`: Verifies gross profit calculation minus fees matches expected net realized P&L.
- `test_sell_insufficient_asset`: Verifies selling coins not held is blocked.
- `test_trade_count_filters_out_hold`: Confirms `get_executed_trades_count()` strictly increments on `BUY`/`SELL` and **does not increment on `HOLD`**.
- `test_reset_portfolio`: Confirms portfolio wipe returns balance to ₹10,000 and zeroes all records.

### B. `test_telegram_filter.py` (5 Tests)
- `test_telegram_suppresses_hold_action`: Confirms `action == "HOLD"` triggers zero network requests.
- `test_telegram_suppresses_hold_status`: Confirms status `HOLD` (forced by risk manager) suppresses alerts.
- `test_telegram_sends_on_buy`: Confirms actionable `BUY` dispatches a formatted markdown report.
- `test_telegram_sends_on_sell`: Confirms actionable `SELL` dispatches a formatted alert.
- `test_telegram_no_credentials`: Confirms graceful silent return when credentials are absent.

### C. `test_scheduler_semaphore.py` (2 Tests)
- `test_semaphore_limits_concurrency`: Proves `asyncio.Semaphore(2)` restricts active concurrent workers to exactly 2.
- `test_full_basket_handles_individual_asset_failure`: Confirms `asyncio.gather(*tasks, return_exceptions=True)` allows healthy asset evaluations to proceed even if an individual asset fails.

### D. `test_indicators.py` (9 Tests)
- Tests `_rsi`, `_bollinger_bands`, `_atr`, `_ema`, and `_rvol` against synthetic time-series data.
- Tests semantic translators: `translate_trend`, `translate_momentum`, `translate_macro_context`, and `build_semantic_payload`.

### E. `test_ml_database.py` (4 Tests)
- `test_coindcx_validation_min_trade_size`: Enforces ₹100 minimum order boundary.
- `test_coindcx_validation_insufficient_inr`: Verifies order + fee solvency check.
- `test_ml_trade_logging_and_retrieval`: Validates logging of LLM traces and action filters.
- `test_equity_curve_snapshots`: Validates historical mark-to-market snapshot logging.

### F. `test_api.py` (5 Tests)
- `test_root_serves_html_with_asset_column`: Verifies HTML contains the dedicated Asset column and styles.
- `test_portfolio_summary_endpoint`: Verifies JSON structure and initial `total_trades=0`.
- `test_trades_endpoint_executed_count_filter`: Confirms `/api/trades` accurately returns `executed_count`.
- `test_system_endpoint`: Validates uptime and price feed health.
- `test_reset_endpoint`: Validates `/api/reset` route functionality.

---

## 5. Running the Tests

Execute tests from the repository root:

```bash
# Run the entire test suite
pytest -v

# Run with short output
pytest

# Target specific modules
pytest tests/test_database.py -v
pytest tests/test_telegram_filter.py -v
pytest tests/test_api.py -v
```

### Verified Test Run:
```text
======================= 32 passed in 11.05s =======================
```
