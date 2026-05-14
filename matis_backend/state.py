# state.py
from typing import TypedDict, List, Dict, Any

class AgentState(TypedDict):
    asset: str
    market_data: Dict[str, Any]       # price, RSI, BB, ATR, EMAs, RVOL, btc_24h_change
    news_headlines: List[str]
    sentiment_score: float
    semantic_payload: Dict[str, Any]  # Pre-processed semantic market intelligence for LLM
    technical_signals: Dict[str, Any]
    historical_context: str
    proposed_trade: Dict[str, Any]
    critic_feedback: str
    feedback_iterations: int
    final_decision: Dict[str, Any]
    portfolio: Dict[str, Any]         # usd_balance + asset_balance (dynamic per asset)