# agents.py — MATIS LangGraph Agent Nodes (NVIDIA NIM)
from time import sleep
import os
import time
import json
from dotenv import load_dotenv
from pydantic import BaseModel, Field
from langchain_nvidia_ai_endpoints import ChatNVIDIA
from state import AgentState

# Load API keys from .env
load_dotenv()

# --- SCHEMA DEFINITIONS ---

class SentimentResponse(BaseModel):
    sentiment_score: float = Field(description="A score between 0.0 (extremely bearish) and 1.0 (extremely bullish).")
    summary: str = Field(description="A brief 1-2 sentence summary of the news.")

class TradeProposal(BaseModel):
    action: str = Field(description="Must be strictly 'BUY', 'SELL', or 'HOLD'.")
    confidence: int = Field(description="An integer between 0 and 100 representing confidence.")
    reasoning: str = Field(description="The detailed logical reasoning for the trade.")


# --- LLM INITIALIZATION (NVIDIA NIM) ---

# BRAIN 1: The Heavyweight (Strategist + Critic)
llm_strategist = ChatNVIDIA(
    model="meta/llama-3.3-70b-instruct",
    temperature=0.1,
    api_key=os.getenv("NVIDIA_API_KEY")
)

# BRAIN 2: The Fast Checker (Sentinel — news parsing)
llm_sentinel = ChatNVIDIA(
    model="meta/llama-3.3-70b-instruct",
    temperature=0.2,
    api_key=os.getenv("NVIDIA_API_KEY")
)

# Critic uses the same heavyweight model but invoked raw (no structured output)
llm_critic = ChatNVIDIA(
    model="meta/llama-3.3-70b-instruct",
    temperature=0.1,
    api_key=os.getenv("NVIDIA_API_KEY")
)


# ============================================================
#  Helper: Clean markdown fences from LLM output
# ============================================================
def _strip_markdown_fences(text: str) -> str:
    """Strip ```json ... ``` wrappers from LLM output."""
    text = text.strip()
    if text.startswith("```json"):
        text = text[7:]
    if text.startswith("```"):
        text = text[3:]
    if text.endswith("```"):
        text = text[:-3]
    return text.strip()


# ============================================================
#  SENTINEL NODE — News Sentiment Analysis
# ============================================================
def sentinel_node(state: AgentState):
    print("Sentinel: Reading the news...")
    news = state.get("news_headlines", [])
    asset = state.get("asset", "Unknown Asset")

    # If there's no news, return a neutral score
    if not news:
         return {"sentiment_score": 0.50}

    # Use raw invoke + JSON parsing (same pattern as Critic — avoids NIM structured output bugs)
    prompt = f"""
    You are a cryptocurrency market sentiment analyst.
    Analyze the following news headlines for {asset}.

    Headlines:
    {news}

    Determine the overall sentiment score (0.0 = extremely bearish, 1.0 = extremely bullish).

    CRITICAL: Respond ONLY with a raw JSON object. No markdown, no backticks.
    Example: {{"sentiment_score": 0.65, "summary": "Mostly positive outlook based on adoption news."}}
    """

    max_retries = 3
    for attempt in range(max_retries):
        try:
            response = llm_sentinel.invoke(prompt)
            raw_text = _strip_markdown_fences(response.content)
            data = json.loads(raw_text)

            score = float(data.get("sentiment_score", 0.5))
            summary = data.get("summary", "No summary provided.")

            # Clamp score to valid range
            score = max(0.0, min(1.0, score))

            print(f"Sentinel determined sentiment: {score} - {summary}")
            return {"sentiment_score": score}

        except (json.JSONDecodeError, Exception) as e:
            print(f"⚠️ Sentinel parse failed or rate limit hit (attempt {attempt + 1}/{max_retries}): {e}")
            sleep(5)
            continue

    print("⚠️ Sentinel fallback: returning neutral sentiment 0.50")
    return {"sentiment_score": 0.50}


# ============================================================
#  STRATEGIST NODE — Trade Proposal (Self-Healing JSON Loop)
# ============================================================
def strategist_node(state: AgentState):
    print("\nStrategist: Analyzing data and formulating trade...")
    # Gather all current context
    asset = state.get("asset")
    market_data = state.get("market_data", {})
    semantic_payload = state.get("semantic_payload", {})
    past_feedback = state.get("critic_feedback", "None")

    # Pull portfolio balances for inventory awareness
    portfolio = state.get("portfolio", {})
    inr_balance = portfolio.get("inr_balance", 0.0)
    asset_balance = portfolio.get("asset_balance", 0.0)

    # Extract semantic fields
    macro_ctx = semantic_payload.get("macro_context", "N/A")
    news_sent = semantic_payload.get("news_sentiment", "N/A")
    tech = semantic_payload.get("technical_state", {})
    trend_str = tech.get("trend", "N/A")
    momentum_str = tech.get("momentum", "N/A")
    volatility_str = tech.get("volatility", "N/A")
    volume_str = tech.get("volume", "N/A")

    prompt = f"""
    You are a professional crypto trading strategist.
    You are evaluating {asset}. Propose a trade based on the following pre-processed market intelligence:

    === MACRO ENVIRONMENT ===
    {macro_ctx}

    === NEWS SENTIMENT ===
    {news_sent}

    === TECHNICAL STATE ===
    Trend: {trend_str}
    Momentum: {momentum_str}
    Volatility: {volatility_str}
    Volume: {volume_str}

    === YOUR CURRENT PORTFOLIO ===
    Available Cash: ₹{inr_balance:,.2f} INR
    {asset} Holdings: {asset_balance:.8f}

    === STRICT INVENTORY RULES ===
    - If your {asset} balance is 0 or near 0, you CANNOT propose SELL. You have nothing to sell.
    - If your INR balance is very low (< ₹100), you CANNOT propose BUY. You have no buying power.
    - ALWAYS respect these constraints. Proposing an impossible trade is a critical failure.
    - If both balances prevent action, you MUST propose HOLD.

    === POSITION SIZING ===
    You MUST also specify "allocation_pct": a number from 1.0 to 100.0 representing what
    percentage of available capital (for BUY) or inventory (for SELL) to use.
    - Low conviction / high risk: use 3-10%
    - Medium conviction: use 10-25%
    - High conviction with strong multi-signal alignment: use 25-50%
    - For HOLD, set allocation_pct to 0.

    PREVIOUS CRITIC FEEDBACK: {past_feedback}
    If the critic rejected your last proposal, you MUST change your strategy based on their feedback.

    CRITICAL: Respond ONLY with a raw JSON object. No markdown, no backticks, no explanation outside the JSON.
    You MUST include all four fields. The confidence MUST be a raw integer (not a string).
    Example: {{"action": "BUY", "confidence": 82, "allocation_pct": 15.0, "reasoning": "RSI is oversold at 28, EMA crossover confirms uptrend, strong buy signal."}}
    """

    max_retries = 3
    response = None

    for attempt in range(max_retries):
        try:
            response = llm_strategist.invoke(prompt)
            raw_text = _strip_markdown_fences(response.content)
            data = json.loads(raw_text)

            action = str(data.get("action", "HOLD")).strip().upper()
            if action not in ["BUY", "SELL", "HOLD"]:
                action = "HOLD"

            confidence = int(data.get("confidence", 0))
            confidence = max(0, min(100, confidence))

            # Parse and clamp allocation percentage
            allocation_pct = float(data.get("allocation_pct", 5.0))
            allocation_pct = max(0.0, min(100.0, allocation_pct))

            reasoning = str(data.get("reasoning", "No reasoning provided."))

            print(f"Strategist proposes: {action} (Confidence: {confidence}%, Allocation: {allocation_pct}%)")
            print(f"Reasoning: {reasoning}")
            print(f"Portfolio context: ₹{inr_balance:,.2f} INR | {asset_balance:.8f} {asset}")

            return {"proposed_trade": {"action": action, "confidence": confidence, "allocation_pct": allocation_pct, "reasoning": reasoning}}

        except json.JSONDecodeError:
            snippet = response.content[:150] if response else "NO RESPONSE"
            print(f"⚠️ Strategist JSON parse failed (attempt {attempt + 1}/{max_retries}): {snippet}")
            sleep(5)
            continue
        except Exception as e:
            print(f"⚠️ Strategist unexpected error or rate limit hit (attempt {attempt + 1}/{max_retries}): {e}")
            sleep(5)
            continue

    # === LOUD FALLBACK: All retries exhausted — default to HOLD ===
    raw_snippet = response.content[:100] if response else "NO RESPONSE CAPTURED"
    fallback_reasoning = f"⚠️ SYSTEM ERROR: Strategist LLM failed to output valid JSON after {max_retries} attempts. Defaulting to HOLD. Raw: {raw_snippet}"
    print(fallback_reasoning)

    return {"proposed_trade": {"action": "HOLD", "confidence": 0, "allocation_pct": 0.0, "reasoning": fallback_reasoning}}


# ============================================================
#  CRITIC NODE — Self-Healing Retry Loop (Raw JSON Parsing)
# ============================================================
def critic_node(state: AgentState):
    print("\nCritic: Evaluating proposal...")

    proposal = state.get("proposed_trade", {})
    semantic_payload = state.get("semantic_payload", {})
    iterations = state.get("feedback_iterations", 0)
    new_iterations = iterations + 1

    # Build a readable market summary for the critic from the semantic payload
    tech = semantic_payload.get("technical_state", {})
    market_summary = (
        f"Asset: {semantic_payload.get('asset', 'Unknown')}\n"
        f"Macro: {semantic_payload.get('macro_context', 'N/A')}\n"
        f"Sentiment: {semantic_payload.get('news_sentiment', 'N/A')}\n"
        f"Trend: {tech.get('trend', 'N/A')}\n"
        f"Momentum: {tech.get('momentum', 'N/A')}\n"
        f"Volatility: {tech.get('volatility', 'N/A')}\n"
        f"Volume: {tech.get('volume', 'N/A')}"
    )

    base_prompt = f"""
    You are a ruthless risk and logic evaluator.
    Review this proposed trade against the current market intelligence.

    === MARKET INTELLIGENCE ===
    {market_summary}

    === PROPOSED TRADE ===
    {proposal}

    If the trade is logical and aligns with the market conditions, approve it.
    If the trade ignores basic trading principles (like buying into extreme overbought RSI > 70 without strong reason, or ignoring bearish macro gravity), reject it and explain exactly why.

    CRITICAL: Respond ONLY with a raw JSON object. No markdown, no <function> tags, no backticks.
    Example: {{"is_safe": "yes", "feedback": "Trade is sound and follows all rules."}}
    """

    max_retries = 3
    response = None

    for attempt in range(max_retries):
        try:
            response = llm_critic.invoke(base_prompt)
            raw_text = _strip_markdown_fences(response.content)
            data = json.loads(raw_text)

            is_safe = str(data.get("is_safe", "no")).strip().lower() == "yes"
            feedback = data.get("feedback", "No feedback provided.")

            if is_safe or new_iterations >= 3:
                print(f"Critic: APPROVED (Iteration {new_iterations}, Attempt {attempt + 1})")
                return {"critic_feedback": "APPROVED", "feedback_iterations": new_iterations}
            else:
                print(f"Critic: REJECTED - {feedback} (Iteration {new_iterations}, Attempt {attempt + 1})")
                return {"critic_feedback": feedback, "feedback_iterations": new_iterations}

        except json.JSONDecodeError:
            snippet = response.content[:120] if response else "NO RESPONSE"
            print(f"⚠️ Critic JSON parse failed (attempt {attempt + 1}/{max_retries}): {snippet}")
            sleep(5)
            continue
        except Exception as e:
            print(f"⚠️ Critic unexpected error or rate limit hit (attempt {attempt + 1}/{max_retries}): {e}")
            sleep(5)
            continue

    # === LOUD FALLBACK: All retries exhausted ===
    raw_snippet = response.content[:100] if response else "NO RESPONSE CAPTURED"
    fallback_msg = f"⚠️ SYSTEM ERROR: Critic LLM failed to output valid JSON after {max_retries} attempts. Trade blocked for safety. Raw output: {raw_snippet}"
    print(fallback_msg)

    return {
        "critic_feedback": fallback_msg,
        "feedback_iterations": new_iterations
    }


# ============================================================
#  RISK MANAGER NODE — Dynamic Position Sizing (Multi-Asset)
# ============================================================
def risk_manager_node(state: AgentState):
    print("\nRisk Manager: Finalizing position...")

    # Grab the final approved proposal and current price
    asset = state.get("asset", "UNKNOWN")
    proposal = state.get("proposed_trade", {})
    market_data = state.get("market_data", {})

    # Pull portfolio for safety checks
    portfolio = state.get("portfolio", {})
    inr_balance = portfolio.get("inr_balance", 0.0)
    asset_balance = portfolio.get("asset_balance", 0.0)

    action = proposal.get("action", "HOLD")
    confidence = proposal.get("confidence", 0)
    allocation_pct = proposal.get("allocation_pct", 0.0)
    current_price = market_data.get("price", 0)
    reasoning = proposal.get("reasoning", "No reasoning provided.")

    # === DEBUG: Show every value so we can trace overrides ===
    print(f"DEBUG: Asset={asset} | Action={action} | Confidence={confidence}% | Allocation={allocation_pct}%")
    print(f"DEBUG: INR Balance={inr_balance:,.2f} | {asset} Balance={asset_balance:.8f}")
    print(f"DEBUG: Price={current_price:,.2f}")

    # Clamp allocation to safe bounds
    allocation_pct = max(0.0, min(100.0, allocation_pct))

    # Convert percentage to fraction for execution
    allocation_fraction = allocation_pct / 100.0

    # === DYNAMIC RISK THRESHOLD CALCULATION ===
    # Ensure the sentiment score is extracted as a float. Default to neutral 0.5 on failure.
    try:
        sentiment_float = float(state.get("sentiment_score", 0.5))
    except (ValueError, TypeError, NameError):
        sentiment_float = 0.5

    # Normalize [0.0, 1.0] to [-1.0, 1.0] multiplier
    sentiment_multiplier = (sentiment_float - 0.5) * 2.0

    base_buy_threshold = 75
    base_sell_threshold = 65

    # Dynamic shifting based on the multiplier
    dynamic_buy_threshold = int(base_buy_threshold - (sentiment_multiplier * 10))
    dynamic_sell_threshold = int(base_sell_threshold + (sentiment_multiplier * 10))

    required_confidence = dynamic_buy_threshold if action == "BUY" else dynamic_sell_threshold

    print(f"DEBUG: Sentiment={sentiment_float:.2f} | Multiplier={sentiment_multiplier:.2f} | Dynamic BUY Threshold={dynamic_buy_threshold}% | Dynamic SELL Threshold={dynamic_sell_threshold}%")

    # === STRICT RISK LOGIC EXECUTION ===
    if action in ["BUY", "SELL"] and confidence >= required_confidence and allocation_pct >= 1.0:
        status = "EXECUTE_TRADE"
        print(f"DEBUG: Action {action} | Confidence {confidence}% >= Dynamic Target {required_confidence}% | Allocation {allocation_pct}% >= 1% — EXECUTE_TRADE")
    else:
        status = "HOLD"
        allocation_fraction = 0.0
        if action in ["BUY", "SELL"] and confidence >= required_confidence and allocation_pct < 1.0:
            print(f"DEBUG: Allocation {allocation_pct}% < 1% — dust trade blocked, forcing HOLD")
        elif action in ["BUY", "SELL"]:
            print(f"DEBUG: Confidence {confidence}% < Dynamic Target {required_confidence}% — forcing HOLD")
        else:
            print(f"DEBUG: Action is HOLD — no trade needed")

    # === SAFETY GATE: Inventory Check (Multi-Asset) ===
    if status == "EXECUTE_TRADE":
        if action == "SELL" and asset_balance <= 0:
            print(f"Risk Manager: BLOCKED SELL — {asset} balance is {asset_balance:.8f}, nothing to sell.")
            status = "HOLD"
            allocation_fraction = 0.0
            reasoning = f"BLOCKED: Cannot SELL with {asset_balance:.8f} {asset}. Original: {reasoning}"
        elif action == "BUY" and inr_balance < 100:
            print(f"Risk Manager: BLOCKED BUY — INR balance is ₹{inr_balance:.2f}, insufficient funds.")
            status = "HOLD"
            allocation_fraction = 0.0
            reasoning = f"BLOCKED: Cannot BUY with ₹{inr_balance:.2f} INR. Original: {reasoning}"

    print(f"Risk Manager Decision: {status} | Allocation: {allocation_pct}% | Portfolio: ₹{inr_balance:,.2f} INR, {asset_balance:.8f} {asset}")

    # Pass everything down so n8n can log it
    return {
        "final_decision": {
            "status": status,
            "asset": asset,
            "action": action,
            "allocation_pct": allocation_pct,
            "allocation_fraction": allocation_fraction,
            "price": current_price,
            "confidence": confidence,
            "reasoning": reasoning,
            "sentiment": state.get("sentiment_score"),
            "critic_notes": state.get("critic_feedback")
        }
    }