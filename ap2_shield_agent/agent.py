import json
import os
import sys
from pathlib import Path
from typing import Any
import uuid
import httpx
from dotenv import load_dotenv
from pydantic import BaseModel
from google.adk.agents import Agent
from google.adk.agents.context import Context
from google.adk.events.event import Event
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.adk.workflow import Workflow, node
from google.genai import types

load_dotenv()
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.8-flash").strip() or "gemini-3.8-flash"

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from ap2_crypto import (
    sign_agent_checkout,
    verify_cfo_policy,
    verify_agent_checkout,
)

def _detect_cli_port() -> str:
    """Detects the port passed via CLI to uvicorn (--port XXXX) if present."""
    for i, arg in enumerate(sys.argv):
        if arg == "--port" and i + 1 < len(sys.argv):
            return sys.argv[i + 1].strip()
        if arg.startswith("--port="):
            return arg.split("=", 1)[1].strip()
    return ""


def _get_shield_base_url() -> str:
    """Dynamically resolves the Shield server URL both locally and on Render."""
    custom_url = os.getenv("SHIELD_BASE_URL", "").strip()
    if custom_url:
        return custom_url.rstrip("/")
    port = (
        os.getenv("SHIELD_RUNTIME_PORT", "").strip()
        or os.getenv("PORT", "").strip()
        or _detect_cli_port()
        or "8000"
    )
    return f"http://127.0.0.1:{port}"


def _get_candidate_base_urls() -> list[str]:
    """Returns the primary URL followed by fallback local ports (8000, 8001)."""
    primary = _get_shield_base_url()
    candidates = [primary]
    for fallback_port in ("8000", "8001"):
        url = f"http://127.0.0.1:{fallback_port}"
        if url not in candidates:
            candidates.append(url)
    return candidates


async def _shield_request(method: str, path: str, timeout: float = 20.0, **kwargs) -> httpx.Response:
    """Dispatches a request to the Shield server, falling back across local ports on ConnectError."""
    last_exc = None
    async with httpx.AsyncClient(timeout=timeout) as client:
        for base_url in _get_candidate_base_urls():
            try:
                res = await client.request(method, f"{base_url}{path}", **kwargs)
                os.environ["SHIELD_RUNTIME_PORT"] = base_url.rsplit(":", 1)[-1]
                return res
            except httpx.ConnectError as exc:
                last_exc = exc
                continue
    raise last_exc


SHIELD_BASE_URL = _get_shield_base_url()


async def search_catalog_channel3(
    query: str,
    max_price: float | None = None,
) -> dict:
    """
    Searches real products in real time using the Channel3 API (100M+ products, 25,000+ retailers).
    Returns titles, images, prices, availability (`availability`), purchase links (`buy_url`),
    features (`key_features`), variants (`variants`), and the verified PayPal Sandbox email.

    Args:
        query: Product query to search (e.g. 'ergonomic office chair', '4k monitor', 'mechanical keyboard').
        max_price: (Optional) Maximum price filter in USD (`SearchFilters(price=SearchFilterPrice(max_price=...))`).
    """
    params: dict[str, Any] = {"q": query}
    if max_price is not None and float(max_price) > 0:
        params["max_price"] = float(max_price)
    res = await _shield_request("GET", "/api/catalog/search", timeout=20.0, params=params)
    res.raise_for_status()
    return res.json()


async def enrich_and_recommend_channel3(
    sku: str,
    max_price: float | None = None,
) -> dict:
    """
    Enriches a SKU with Channel3's `products.retrieve` (full description, `key_features`,
    `availability`, `buy_url`, `variants`) and fetches similar product recommendations with
    `products.find_similar` (optionally filtered by `max_price` to fit the CFO budget ceiling).

    Args:
        sku: Channel3 product ID/SKU to enrich and use as a recommendation seed.
        max_price: (Optional) Maximum budget in USD to filter similar recommendations.
    """
    params: dict[str, Any] = {}
    if max_price is not None and float(max_price) > 0:
        params["max_price"] = float(max_price)
    res = await _shield_request("GET", f"/api/catalog/enrich/{sku}", timeout=20.0, params=params)
    res.raise_for_status()
    return res.json()


async def get_ag_grid_policy_state() -> dict:
    """
    Queries the PayPal Agent Shield server in real time to fetch the available budget
    in AG Grid, Ed25519 public keys, and the CFO's active AP2 cryptographic policy hash.
    """
    res = await _shield_request("GET", "/api/state", timeout=5.0)
    res.raise_for_status()
    return res.json()["policy"]


async def execute_ap2_checkout(
    sku: str,
    product_name: str,
    price: float,
    merchant_paypal_email: str,
    simulate_tampering: bool = False
) -> dict:
    """
    Builds the AP2 Checkout Mandate, cryptographically signs it with the agent's Ed25519
    private key, and sends it to PayPal Agent Shield for verification and PayPal settlement.

    Args:
        sku: Exact SKU of the product to purchase.
        product_name: Product name.
        price: Total price in USD.
        merchant_paypal_email: Merchant PayPal email address.
        simulate_tampering: If True, alters the price in transit after signing with Ed25519 to demonstrate how the Shield detects Man-in-the-Middle attacks.
    """
    state_res = await _shield_request("GET", "/api/state", timeout=35.0)
    policy = state_res.json()["policy"]

    mandate_id = f"ap2_chk_{uuid.uuid4().hex[:8]}"
    agent_id = "procurement-01"
    parent_hash = policy["ap2_policy_hash"]

    # 1. Ed25519 cryptographic signature generated by the ADK Agent
    real_signature = sign_agent_checkout(
        mandate_id=mandate_id,
        agent_id=agent_id,
        parent_policy_hash=parent_hash,
        sku=sku,
        total_amount=price,
        merchant_paypal_email=merchant_paypal_email
    )

    # If simulating an attack, corrupt the amount in transit after signing
    sent_price = price + 50.0 if simulate_tampering else price

    checkout_payload = {
        "mandate_id": mandate_id,
        "agent_id": agent_id,
        "parent_policy_hash": parent_hash,
        "sku": sku,
        "product_name": product_name,
        "total_amount": sent_price,
        "merchant_paypal_email": merchant_paypal_email,
        "agent_signature": real_signature
    }

    # 2. Asynchronous call to the PayPal Agent Shield Firewall
    chk_res = await _shield_request("POST", "/api/checkout", timeout=35.0, json=checkout_payload)
    result = chk_res.json()

    if not result.get("authorized"):
        return {
            "status": result.get("status", "SHIELD_BLOCKED"),
            "mandate_id": mandate_id,
            "ed25519_signature_sent": real_signature[:24] + "...",
            "shield_error": result.get("error"),
            "adk_graph_route": result.get("adk_graph_route", "route_threat_sink"),
            "adk_graph_visited_nodes": result.get("adk_graph_nodes", []),
            "bryntum_taskboard_column": result.get("bryntum_column", "BLOCKED_THREAT"),
            "hitl_quarantined": result.get("hitl_quarantined", False),
            "ag_grid_remaining_usd": result.get("remaining_usd"),
        }

    return {
        "status": "PAYPAL_COMPLETED",
        "mandate_id": mandate_id,
        "ed25519_signature_verified": real_signature[:24] + "...",
        "paypal_transaction_id": result.get("paypal_tx_id"),
        "paypal_mode": result.get("paypal_mode"),
        "render_workflow_engine": result.get("workflow_engine", "LOCAL_INLINE"),
        "adk_graph_route": result.get("adk_graph_route", "route_paypal_settlement"),
        "adk_graph_visited_nodes": result.get("adk_graph_nodes", []),
        "bryntum_taskboard_column": result.get("bryntum_column", "PAYPAL_SETTLED"),
        "ap2_cryptographic_proof": result.get("ap2_proof")[:20] + "...",
        "ag_grid_remaining_usd": result.get("remaining_usd"),
    }


async def get_bryntum_taskboard_and_graph_state() -> dict:
    """
    Queries the live state of the Bryntum TaskBoard (HITL quarantined cards, settled orders,
    and blocked threats) along with the Google ADK 2.0 Workflow graph telemetry.
    """
    res = await _shield_request("GET", "/api/state", timeout=10.0)
    res.raise_for_status()
    data = res.json()
    return {
        "adk_graph_telemetry": data.get("adk_graph_telemetry", {}),
        "taskboard_cards": data.get("taskboard_cards", []),
        "policy": data.get("policy", {}),
    }


async def resolve_quarantined_mandate_hitl(
    mandate_id: str,
    target_column: str = "PAYPAL_SETTLED",
) -> dict:
    """
    Resumes a HITL (Human-in-the-Loop) quarantined mandate in the Bryntum TaskBoard and ADK 2.0 graph.
    If target_column is 'PAYPAL_SETTLED', re-signs the CFO's Ed25519 policy expanding the budget
    and settles the order on PayPal Sandbox. If 'BLOCKED_THREAT', permanently rejects the mandate.

    Args:
        mandate_id: ID of the quarantined mandate (e.g. 'ap2_chk_...').
        target_column: Target column on the Bryntum TaskBoard ('PAYPAL_SETTLED' or 'BLOCKED_THREAT').
    """
    res = await _shield_request(
        "POST",
        "/api/quarantine/resolve",
        timeout=35.0,
        json={"mandate_id": mandate_id, "target_column": target_column},
    )
    res.raise_for_status()
    return res.json()


# ============================================================================
# GOOGLE ADK 2.0 GRAPH WORKFLOW ENGINE (DETERMINISTIC 5-GATE + HITL ROUTING)
# ============================================================================

class AP2GraphContextPayload(BaseModel):
    mandate_id: str
    agent_id: str
    parent_policy_hash: str
    expected_policy_hash: str
    sku: str
    product_name: str
    total_amount: float
    merchant_paypal_email: str
    agent_signature: str
    policy_id: str
    max_budget_usd: float
    remaining_usd: float
    allowed_category: str
    cfo_signature: str
    trusted_item: dict[str, Any] | None = None
    hitl_override_approved: bool = False
    visited_nodes: list[str] = []


@node
async def adk_node_crypto_gate(ctx: Context, node_input: types.Content) -> Event:
    """
    ADK 2.0 Graph Node 1: Inspects Gate 1 (CFO Ed25519 Signature) and Gate 2 (Agent Ed25519 Signature).
    Routes Man-in-the-Middle attacks to `adk_node_threat_sink`.
    """
    raw_text = "".join(p.text or "" for p in node_input.parts) if node_input and node_input.parts else "{}"
    payload = json.loads(raw_text)
    visited = list(payload.get("visited_nodes", []))
    visited.append("adk_node_crypto_gate")
    payload["visited_nodes"] = visited

    # Gate 1: Verify CFO policy Ed25519 signature
    cfo_ok = verify_cfo_policy(
        payload["policy_id"],
        payload["agent_id"],
        payload["max_budget_usd"],
        payload["allowed_category"],
        payload["cfo_signature"],
    )
    if not cfo_ok:
        payload["verdict_status"] = "BLOCKED_BY_SHIELD"
        payload["bryntum_column"] = "BLOCKED_THREAT"
        payload["threat_category"] = "CFO_CRYPTO_INVALID"
        payload["error"] = "CRYPTO_ERROR: Invalid CFO Ed25519 signature."
        payload["adk_graph_route"] = "route_threat_sink"
        return Event(output=payload, route="route_threat_sink", state={"last_node": ctx.node_path})

    # Gate 2: Verify Agent Ed25519 signature (Anti-MitM)
    agent_ok = verify_agent_checkout(
        mandate_id=payload["mandate_id"],
        agent_id=payload["agent_id"],
        parent_policy_hash=payload["parent_policy_hash"],
        sku=payload["sku"],
        total_amount=payload["total_amount"],
        merchant_paypal_email=payload["merchant_paypal_email"],
        signature_b64=payload["agent_signature"],
    )
    if not agent_ok:
        payload["verdict_status"] = "BLOCKED_BY_SHIELD"
        payload["bryntum_column"] = "BLOCKED_THREAT"
        payload["threat_category"] = "MITM_SIGNATURE_TAMPERING"
        payload["error"] = "ED25519_INVALID_SIGNATURE: In-transit payload tampering detected (Signature does not match payload)."
        payload["adk_graph_route"] = "route_threat_sink"
        return Event(output=payload, route="route_threat_sink", state={"last_node": ctx.node_path})

    return Event(output=payload, route="route_ground_truth", state={"last_node": ctx.node_path})


@node
async def adk_node_channel3_ground_truth(ctx: Context, node_input: dict[str, Any]) -> Event:
    """
    ADK 2.0 Graph Node 2: Inspects Gate 3 (SKU and price Ground-Truth against Channel3).
    Routes LLM hallucinations to `adk_node_threat_sink`.
    """
    payload = dict(node_input)
    visited = list(payload.get("visited_nodes", []))
    visited.append("adk_node_channel3_ground_truth")
    payload["visited_nodes"] = visited

    trusted_item = payload.get("trusted_item")
    sku = payload["sku"]
    if not trusted_item:
        payload["verdict_status"] = "BLOCKED_BY_SHIELD"
        payload["bryntum_column"] = "BLOCKED_THREAT"
        payload["threat_category"] = "LLM_SKU_HALLUCINATION"
        payload["error"] = f"HALLUCINATION_BLOCKED: SKU '{sku}' does not exist in Channel3."
        payload["adk_graph_route"] = "route_threat_sink"
        return Event(output=payload, route="route_threat_sink", state={"last_node": ctx.node_path})

    if (
        payload["total_amount"] != trusted_item["price"]
        or payload["merchant_paypal_email"] != trusted_item["paypal_email"]
    ):
        payload["verdict_status"] = "BLOCKED_BY_SHIELD"
        payload["bryntum_column"] = "BLOCKED_THREAT"
        payload["threat_category"] = "LLM_PRICE_HALLUCINATION"
        payload["error"] = (
            f"GROUND_TRUTH_MISMATCH: Agent submitted ${payload['total_amount']:.2f}, "
            f"but the official price for {sku} is ${trusted_item['price']:.2f}."
        )
        payload["adk_graph_route"] = "route_threat_sink"
        return Event(output=payload, route="route_threat_sink", state={"last_node": ctx.node_path})

    return Event(output=payload, route="route_policy_and_budget", state={"last_node": ctx.node_path})


@node
async def adk_node_policy_budget_gate(ctx: Context, node_input: dict[str, Any]) -> Event:
    """
    ADK 2.0 Graph Node 3: Inspects Gate 4 (AP2 Lineage Hash) and Gate 5 (AG Grid Remaining Budget).
    If the cart exceeds available budget, routes to `adk_node_cfo_hitl_quarantine`
    to place the card in interactive quarantine on the Bryntum TaskBoard.
    """
    payload = dict(node_input)
    visited = list(payload.get("visited_nodes", []))
    visited.append("adk_node_policy_budget_gate")
    payload["visited_nodes"] = visited

    if payload["parent_policy_hash"] != payload["expected_policy_hash"]:
        payload["verdict_status"] = "BLOCKED_BY_SHIELD"
        payload["bryntum_column"] = "BLOCKED_THREAT"
        payload["threat_category"] = "AP2_LINEAGE_MISMATCH"
        payload["error"] = "AP2_HASH_MISMATCH: CFO policy changed prior to settlement."
        payload["adk_graph_route"] = "route_threat_sink"
        return Event(output=payload, route="route_threat_sink", state={"last_node": ctx.node_path})

    if payload["total_amount"] > payload["remaining_usd"]:
        shortfall = round(payload["total_amount"] - payload["remaining_usd"], 2)
        payload["shortfall_usd"] = shortfall
        payload["verdict_status"] = "BLOCKED_BY_SHIELD"
        payload["bryntum_column"] = "QUARANTINED"
        payload["threat_category"] = "CFO_HITL_BUDGET_QUARANTINE"
        payload["error"] = (
            f"BUDGET_EXCEEDED: Cart ${payload['total_amount']:.2f} USD > "
            f"Available in AG Grid ${payload['remaining_usd']:.2f} USD "
            f"(In HITL quarantine on Bryntum TaskBoard — Shortfall: +${shortfall:.2f} USD)"
        )
        payload["adk_graph_route"] = "route_cfo_hitl_quarantine"
        return Event(output=payload, route="route_cfo_hitl_quarantine", state={"last_node": ctx.node_path})

    payload["adk_graph_route"] = "route_paypal_settlement"
    return Event(output=payload, route="route_paypal_settlement", state={"last_node": ctx.node_path})


@node
async def adk_node_cfo_hitl_quarantine(ctx: Context, node_input: dict[str, Any]) -> Event:
    """
    Node 4A (HITL Quarantine): Pauses the purchase mandate in the `QUARANTINED` column
    of the Bryntum TaskBoard waiting for the CFO to drag the card to re-sign and settle.
    """
    payload = dict(node_input)
    visited = list(payload.get("visited_nodes", []))
    visited.append("adk_node_cfo_hitl_quarantine")
    payload["visited_nodes"] = visited
    payload["authorized"] = False
    payload["hitl_quarantined"] = True
    payload["interrupt_id"] = f"hitl_{payload['mandate_id']}"
    payload["terminal_node_path"] = ctx.node_path
    return Event(output=payload, state={"quarantined_mandate": payload["mandate_id"]})


@node
async def adk_node_threat_sink(ctx: Context, node_input: dict[str, Any]) -> Event:
    """
    Node 4B (Threat Sink): Permanently blocks cryptographic (MitM) attacks or LLM hallucinations
    in the `BLOCKED_THREAT` column of the Bryntum TaskBoard.
    """
    payload = dict(node_input)
    visited = list(payload.get("visited_nodes", []))
    visited.append("adk_node_threat_sink")
    payload["visited_nodes"] = visited
    payload["authorized"] = False
    payload["hitl_quarantined"] = False
    payload["terminal_node_path"] = ctx.node_path
    return Event(output=payload, state={"blocked_mandate": payload["mandate_id"]})


@node
async def adk_node_paypal_settlement(ctx: Context, node_input: dict[str, Any]) -> Event:
    """
    Node 4C (PayPal Settlement): Authorizes the mandate verified across all 5 gates for
    PayPal Sandbox settlement (via Render Workflows / APIMatic SDK) and moves the card
    to `PAYPAL_SETTLED` on the Bryntum TaskBoard.
    """
    payload = dict(node_input)
    visited = list(payload.get("visited_nodes", []))
    visited.append("adk_node_paypal_settlement")
    payload["visited_nodes"] = visited
    payload["authorized"] = True
    payload["hitl_quarantined"] = False
    payload["bryntum_column"] = "PAYPAL_SETTLED"
    payload["terminal_node_path"] = ctx.node_path
    return Event(output=payload, state={"settled_mandate": payload["mandate_id"]})


ap2_checkout_graph = Workflow(
    name="ap2_zero_trust_checkout_graph",
    description=(
        "Deterministic Google ADK 2.0 graph connecting 5-gate cryptographic inspection "
        "with the interactive Bryntum TaskBoard (HITL Quarantine, Threat Sink, and PayPal Settlement)."
    ),
    edges=[
        ("START", adk_node_crypto_gate),
        (
            adk_node_crypto_gate,
            {
                "route_ground_truth": adk_node_channel3_ground_truth,
                "route_threat_sink": adk_node_threat_sink,
            },
        ),
        (
            adk_node_channel3_ground_truth,
            {
                "route_policy_and_budget": adk_node_policy_budget_gate,
                "route_threat_sink": adk_node_threat_sink,
            },
        ),
        (
            adk_node_policy_budget_gate,
            {
                "route_paypal_settlement": adk_node_paypal_settlement,
                "route_cfo_hitl_quarantine": adk_node_cfo_hitl_quarantine,
                "route_threat_sink": adk_node_threat_sink,
            },
        ),
    ],
)

_graph_session_service = InMemorySessionService()
_graph_runner = Runner(
    agent=ap2_checkout_graph,
    app_name="ap2_shield_graph_engine",
    session_service=_graph_session_service,
)


async def run_adk_checkout_graph_workflow(graph_input: dict[str, Any]) -> dict[str, Any]:
    """
    Executes the Google ADK 2.0 `ap2_checkout_graph` workflow and returns the structured verdict,
    conditional route taken, and exact trace of visited nodes.
    """
    session_id = f"wf_{graph_input.get('mandate_id', uuid.uuid4().hex[:8])}_{uuid.uuid4().hex[:4]}"
    await _graph_session_service.create_session(
        app_name="ap2_shield_graph_engine",
        user_id="shield_firewall",
        session_id=session_id,
    )
    msg = types.Content(
        role="user",
        parts=[types.Part.from_text(text=json.dumps(graph_input))],
    )
    final_output: dict[str, Any] = {}
    async for ev in _graph_runner.run_async(
        user_id="shield_firewall",
        session_id=session_id,
        new_message=msg,
    ):
        out = getattr(ev, "output", None)
        if isinstance(out, dict):
            final_output = out
    return final_output


root_agent = Agent(
    name="paypal_ap2_procurement_agent",
    model=GEMINI_MODEL,
    description="Autonomous procurement agent governed by Google ADK 2.0 Graph Workflows, Ed25519 (AP2) cryptography, AG Grid, Bryntum TaskBoard, and PayPal Agent Shield.",
    instruction="""
    You are the enterprise Autonomous Procurement Agent operating with Google ADK 2.0 (Graph Workflows + Agent), the AP2 cryptographic protocol (Ed25519), AG Grid, Bryntum TaskBoard, and PayPal Agent Shield.
    Always respond in clear, concise, executive English with well-structured formatting.

    WORKFLOW RULES:
    1. When asked to inspect the budget, catalog, or the state of the Bryntum TaskBoard / ADK Graph, call `get_ag_grid_policy_state`, `search_catalog_channel3`, or `get_bryntum_taskboard_and_graph_state`.
    2. NEVER INVENT PRODUCTS OR SKUS: Only display products returned by `search_catalog_channel3`, always including their exact `sku`, `price`, and `paypal_email`. If `search_catalog_channel3` returns an empty list or an error, report it clearly to the user and DO NOT fabricate products.
    3. When asked to buy a product, use the exact `sku`, `name`, `price`, and `paypal_email` returned by `search_catalog_channel3` (call `search_catalog_channel3` again if you don't have those exact values in the conversation) and execute `execute_ap2_checkout`.
    4. If the user explicitly asks to simulate a cryptographic attack, payload tampering, or invalid signature, pass `simulate_tampering=True` to `execute_ap2_checkout`.
    5. If the user explicitly asks to simulate a price or SKU hallucination (or manually override the price to another value), pass that altered value with `simulate_tampering=False` to demonstrate how the Shield's Ground-Truth validation intercepts it.
    6. If a purchase exceeds the available budget (`hitl_quarantined=True`), explain that the ADK graph (`ap2_zero_trust_checkout_graph`) paused the order at node `adk_node_cfo_hitl_quarantine` and placed the card in the `⏳ CFO Quarantine (HITL)` column of the **Bryntum TaskBoard**, where the CFO can drag it to `💳 PayPal Sandbox Settled` to auto-sign the expanded Ed25519 budget and settle it on PayPal (or ask you to approve it via `resolve_quarantined_mandate_hitl`).
    7. Always summarize: AP2 Mandate ID, visited ADK Graph nodes (`adk_graph_visited_nodes`), Bryntum TaskBoard column (`bryntum_taskboard_column`), Shield verdict / PayPal Order ID, and remaining balance in AG Grid.
    """,
    tools=[
        search_catalog_channel3,
        enrich_and_recommend_channel3,
        get_ag_grid_policy_state,
        execute_ap2_checkout,
        get_bryntum_taskboard_and_graph_state,
        resolve_quarantined_mandate_hitl,
    ]
)