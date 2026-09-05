# graph.py
from langgraph.graph import StateGraph, END
from state import AgentState
from agents import sentinel_node, strategist_node, critic_node, risk_manager_node
from indicators import build_semantic_payload


def semantic_builder_node(state: AgentState):
    """
    Intermediate node: runs AFTER sentinel (so sentiment_score is available)
    and BEFORE strategist. Builds the semantic payload from raw market_data
    + sentiment and injects it into the state.
    """
    asset = state.get("asset", "UNKNOWN")
    market_data = state.get("market_data", {})
    sentiment_score = state.get("sentiment_score", 0.5)

    payload = build_semantic_payload(asset, market_data, sentiment_score)
    print(f"[SEMANTIC] Built payload for {asset}: Macro={payload.get('macro_context', 'N/A')}")
    return {"semantic_payload": payload}


from price_feed import get_inr_price, get_usd_to_inr_rate


def check_trade_value(state: AgentState) -> str:
    """
    Evaluates if the Strategist's proposed trade meets the minimum CoinDCX ₹100 INR threshold.
    If it doesn't, bypass the Critic and go straight to the Risk Manager to block the trade,
    saving unnecessary API calls and time.
    """
    proposal = state.get("proposed_trade", {})
    action = proposal.get("action", "HOLD")
    
    if action == "HOLD":
        return "risk_manager"
        
    portfolio = state.get("portfolio", {})
    inr_balance = portfolio.get("inr_balance", 0.0)
    asset_balance = portfolio.get("asset_balance", 0.0)
    asset = state.get("asset", "")
    
    market_data = state.get("market_data", {})
    price = market_data.get("price", 0.0)
    
    allocation_pct = proposal.get("allocation_pct", 0.0)
    allocation_fraction = allocation_pct / 100.0
    
    trade_value = 0.0
    if action == "BUY":
        trade_value = inr_balance * allocation_fraction
    elif action == "SELL":
        inr_p = get_inr_price(asset)
        if inr_p <= 0:
            inr_p = price * get_usd_to_inr_rate()
        trade_value = (asset_balance * allocation_fraction) * inr_p
        
    if trade_value < 100.0:
        print(f"Graph Router: Bypassing Critic! Proposed {action} value (₹{trade_value:.2f}) is below CoinDCX minimum of ₹100.")
        return "risk_manager"
        
    return "critic"


def should_replan(state: AgentState) -> str:
    feedback = state.get("critic_feedback", "")
    if "APPROVED" in feedback:
        return "risk_manager" 
    else:
        return "strategist"   

# Initialize the graph
workflow = StateGraph(AgentState)

# Add nodes
workflow.add_node("sentinel", sentinel_node)
workflow.add_node("semantic_builder", semantic_builder_node)
workflow.add_node("strategist", strategist_node)
workflow.add_node("critic", critic_node)
workflow.add_node("risk_manager", risk_manager_node)

# Define edges: sentinel → semantic_builder → strategist → critic → ...
workflow.set_entry_point("sentinel")
workflow.add_edge("sentinel", "semantic_builder")
workflow.add_edge("semantic_builder", "strategist")

workflow.add_conditional_edges(
    "strategist",
    check_trade_value,
    {"critic": "critic", "risk_manager": "risk_manager"}
)

workflow.add_conditional_edges(
    "critic",
    should_replan,
    {"strategist": "strategist", "risk_manager": "risk_manager"}
)

workflow.add_edge("risk_manager", END)

# Compile the final application
matis_app = workflow.compile()