import os
import re
import copy
import math
import secrets
import asyncio
import uuid
import json
from pathlib import Path
from datetime import datetime
from typing import Any, List
from dotenv import load_dotenv
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

try:
    from channel3 import AsyncChannel3Client
except ImportError:
    try:
        from channel3_sdk import AsyncChannel3 as AsyncChannel3Client
    except ImportError:
        AsyncChannel3Client = None

try:
    from channel3_sdk import SearchFilters, SearchFilterPrice
except ImportError:
    SearchFilters = None
    SearchFilterPrice = None

try:
    from render import RenderAsync
except ImportError:
    RenderAsync = None

# Load environment variables (.env) for Google ADK (GOOGLE_API_KEY) and PayPal
load_dotenv()

from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types

from paypal_apimatic_client import PayPalAPIMaticProcessor
from ap2_crypto import (
    sign_cfo_policy,
    verify_cfo_policy,
    compute_policy_hash,
    sign_agent_checkout,
    verify_agent_checkout,
    get_public_key_hex,
    CFO_PUBLIC_KEY,
    AGENT_PUBLIC_KEY,
)
from ap2_shield_agent.agent import (
    ACTIVE_SHIELD_SESSION_ID,
    build_session_procurement_agent,
    root_agent,
    run_adk_checkout_graph_workflow,
)
from ap2_shield_agent.studio_agent import (
    parse_studio_chart_request,
    run_studio_adk_turn,
)

app = FastAPI(title="PayPal Agent Shield — Unified Console")
paypal_sdk = PayPalAPIMaticProcessor()

# --- PER-BROWSER PRIVATE BYOK SESSION STORE (HTTPONLY COOKIE ISOLATION) ---
BYOK_COOKIE_NAME = "shield_byok_sid"
MAX_BYOK_SESSIONS = 500
_SERVER_DEFAULT_ENV: dict[str, str] = {
    "GOOGLE_API_KEY": os.environ.get("GOOGLE_API_KEY", "").strip(),
    "GEMINI_API_KEY": os.environ.get("GEMINI_API_KEY", "").strip(),
    "GEMINI_MODEL": os.environ.get("GEMINI_MODEL", str(root_agent.model)).strip() or str(root_agent.model),
    "PAYPAL_CLIENT_ID": os.environ.get("PAYPAL_CLIENT_ID", "").strip(),
    "PAYPAL_CLIENT_SECRET": os.environ.get("PAYPAL_CLIENT_SECRET", "").strip(),
    "CHANNEL3_API_KEY": os.environ.get("CHANNEL3_API_KEY", "").strip(),
    "RENDER_API_KEY": os.environ.get("RENDER_API_KEY", "").strip(),
    "RENDER_WORKFLOW_SLUG": os.environ.get("RENDER_WORKFLOW_SLUG", "paypal-shield-workflow").strip() or "paypal-shield-workflow",
}
_byok_sessions: dict[str, dict[str, Any]] = {}


@app.middleware("http")
async def byok_session_isolation_middleware(request: Request, call_next):
    """
    Assigns and tracks an isolated HttpOnly session ID (`shield_byok_sid`) per browser
    (and propagates `X-Shield-Session-Id` on internal ADK tool loopback calls) so that
    any credentials entered in BYOK are 100% private to that browser and never shared.
    """
    internal_sid = (request.headers.get("X-Shield-Session-Id") or "").strip()
    cookie_sid = (request.cookies.get(BYOK_COOKIE_NAME) or "").strip()
    sid = internal_sid or cookie_sid
    is_new_cookie = False
    if not sid:
        sid = secrets.token_urlsafe(24)
        is_new_cookie = True

    token = ACTIVE_SHIELD_SESSION_ID.set(sid)
    try:
        response = await call_next(request)
    finally:
        ACTIVE_SHIELD_SESSION_ID.reset(token)

    if is_new_cookie and not internal_sid:
        response.set_cookie(
            key=BYOK_COOKIE_NAME,
            value=sid,
            httponly=True,
            samesite="lax",
            secure=(request.url.scheme == "https"),
            path="/",
        )
    return response

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- GOOGLE ADK NATIVE RUNTIME ---
APP_NAME = "paypal_agent_shield_app"
USER_ID = "cfo_executive"
session_service = InMemorySessionService()
adk_runner = Runner(
    agent=root_agent,
    app_name=APP_NAME,
    session_service=session_service,
)

class _SessionScopedDict(dict):
    """
    Transparent dict proxy that routes all reads and writes to the caller's isolated
    session dictionary (keyed by `ACTIVE_SHIELD_SESSION_ID`), falling back to a default
    in-memory copy when accessed outside an HTTP request context.
    """

    def __init__(self, resolver):
        super().__init__()
        self._resolver = resolver

    def _target(self) -> dict[str, Any]:
        return self._resolver()

    def __getitem__(self, key):
        return self._target()[key]

    def __setitem__(self, key, value):
        self._target()[key] = value

    def __delitem__(self, key):
        del self._target()[key]

    def __contains__(self, key):
        return key in self._target()

    def __iter__(self):
        return iter(self._target())

    def __len__(self):
        return len(self._target())

    def __repr__(self):
        return repr(self._target())

    def get(self, key, default=None):
        return self._target().get(key, default)

    def setdefault(self, key, default=None):
        return self._target().setdefault(key, default)

    def pop(self, key, *args):
        return self._target().pop(key, *args)

    def keys(self):
        return self._target().keys()

    def values(self):
        return self._target().values()

    def items(self):
        return self._target().items()

    def update(self, *args, **kwargs):
        self._target().update(*args, **kwargs)

    def copy(self):
        return self._target().copy()


# --- GROUND-TRUTH CATALOG TO PREVENT HALLUCINATIONS ---
_SEED_TRUSTED_CATALOG: dict[str, dict[str, Any]] = {
    "CHAIR-ERG-01": {"price": 120.00, "paypal_email": "office-supply@sandbox.paypal.com"},
    "KEYB-MECH-02": {"price": 65.00, "paypal_email": "peripherals@sandbox.paypal.com"},
    "MON-4K-27": {"price": 150.00, "paypal_email": "monitors-direct@sandbox.paypal.com"},
    "LAP-PRO-16": {"price": 799.00, "paypal_email": "monitors-direct@sandbox.paypal.com"},
}


class PolicyUpdate(BaseModel):
    agent_id: str
    max_budget_usd: float
    allowed_category: str = "OFFICE_AND_TECH"


class CheckoutRequest(BaseModel):
    mandate_id: str
    agent_id: str
    parent_policy_hash: str
    sku: str
    product_name: str
    total_amount: float
    merchant_paypal_email: str
    agent_signature: str


class ChatRequest(BaseModel):
    message: str
    session_id: str = "Unified-Session-01"


class QuarantineResolveRequest(BaseModel):
    mandate_id: str = ""
    card_id: str = ""
    target_column: str = "PAYPAL_SETTLED"
    cfo_note: str = ""


class CredentialsConfig(BaseModel):
    google_api_key: str = ""
    gemini_model: str = ""
    paypal_client_id: str = ""
    paypal_client_secret: str = ""
    channel3_api_key: str = ""
    render_api_key: str = ""
    render_workflow_slug: str = ""


_init_sig = sign_cfo_policy("pol_aggrid_001", "procurement-01", 200.00, "OFFICE_AND_TECH")

_SEED_STATE_TEMPLATE: dict[str, Any] = {
    "policies": {
        "procurement-01": {
            "policy_id": "pol_aggrid_001",
            "agent_id": "procurement-01",
            "max_budget_usd": 200.00,
            "remaining_usd": 80.00,
            "allowed_category": "OFFICE_AND_TECH",
            "cfo_signature": _init_sig,
            "cfo_pubkey": get_public_key_hex(CFO_PUBLIC_KEY)[:16],
            "agent_pubkey": get_public_key_hex(AGENT_PUBLIC_KEY)[:16],
        }
    },
    "audit_log": [
        {
            "timestamp": datetime.now().strftime("%H:%M:%S"),
            "mandate_id": "SYS-CFG",
            "item": "CFO Policy pol_aggrid_001 (OFFICE_AND_TECH)",
            "amount": 200.00,
            "merchant": "office-supply@sandbox.paypal.com",
            "status": "POLICY_SIGNED",
            "details": f"Ed25519 Policy signed by CFO ($200.00 max) | Sig: {_init_sig[:20]}...",
        },
        {
            "timestamp": datetime.now().strftime("%H:%M:%S"),
            "mandate_id": "ap2_chk_c3_seed",
            "item": "Ergonomic Mesh Chair (CHAIR-ERG-01)",
            "amount": 120.00,
            "merchant": "office-supply@sandbox.paypal.com",
            "status": "PAYPAL_COMPLETED",
            "details": f"Ed25519 Verified | Channel3 Ground-Truth ($120.00) | PayPal Order ID: PAYPAL-SANDBOX-88A1 | Sig: {_init_sig[:18]}...",
        },
        {
            "timestamp": datetime.now().strftime("%H:%M:%S"),
            "mandate_id": "ap2_chk_hitl_demo",
            "item": "Pro Workstation Laptop 16 (LAP-PRO-16)",
            "amount": 799.00,
            "merchant": "monitors-direct@sandbox.paypal.com",
            "status": "QUARANTINED_HITL",
            "details": "BUDGET_EXCEEDED_HITL: Paused at ADK node adk_node_cfo_hitl_quarantine ($799.00 > $80.00 CFO balance).",
        },
        {
            "timestamp": datetime.now().strftime("%H:%M:%S"),
            "mandate_id": "ap2_chk_mitm_01",
            "item": "Spoofed GPU Cluster (HALLUCINATED-SKU)",
            "amount": 950.00,
            "merchant": "hacker@darkweb.io",
            "status": "BLOCKED_BY_SHIELD",
            "details": "GROUND_TRUTH_MISMATCH & ED25519_TAMPERED: Intercepted by AP2 Cryptographic Firewall prior to PayPal Sandbox.",
        },
    ],
    "taskboard_cards": [
        {
            "id": "c3_sync_seed",
            "mandate_id": "c3_sync_seed",
            "name": "Channel3 Ground-Truth Registry",
            "sku": "CHAIR-ERG-01 (+3 SKUs)",
            "amount": 120.00,
            "amount_usd": 120.00,
            "c3_price_usd": 120.00,
            "merchant": "office-supply@sandbox.paypal.com",
            "status": "CHANNEL3_DISCOVERY",
            "prio": "low",
            "adk_node": "adk_node_channel3_ground_truth",
            "adk_route": "ground_truth_locked",
            "adk_nodes": ["START", "search_catalog_channel3"],
            "gate_code": "GROUND_TRUTH_SYNCED",
            "ed25519_sig": _init_sig[:18] + "...",
            "badge": "100M+ Product Graph",
            "details": "Prices and SKUs verified against LLM hallucinations.",
            "description": "Prices and SKUs verified against LLM hallucinations.",
            "timestamp": datetime.now().strftime("%H:%M:%S"),
            "updated_at": datetime.now().strftime("%H:%M:%S"),
            "hitl_quarantined": False,
            "can_approve_hitl": False,
        },
        {
            "id": "ap2_chk_hitl_demo",
            "mandate_id": "ap2_chk_hitl_demo",
            "name": "Pro Workstation Laptop 16",
            "sku": "LAP-PRO-16",
            "amount": 799.00,
            "amount_usd": 799.00,
            "c3_price_usd": 799.00,
            "shortfall_usd": 719.00,
            "merchant": "monitors-direct@sandbox.paypal.com",
            "status": "QUARANTINED",
            "prio": "high",
            "adk_node": "adk_node_cfo_hitl_quarantine",
            "adk_route": "route_cfo_hitl_quarantine",
            "adk_nodes": [
                "adk_node_crypto_gate",
                "adk_node_channel3_ground_truth",
                "adk_node_policy_budget_gate",
                "adk_node_cfo_hitl_quarantine",
            ],
            "gate_code": "BUDGET_EXCEEDED_HITL",
            "ed25519_sig": _init_sig[:18] + "...",
            "badge": "⏳ HITL: Drag to Settle (+$719.00)",
            "details": "Paused at ADK node `adk_node_cfo_hitl_quarantine`. Drag to 'PayPal Sandbox Settled' to auto-sign Ed25519 and settle.",
            "description": "Paused at ADK node adk_node_cfo_hitl_quarantine ($799.00 > $80.00 AG Grid balance).",
            "timestamp": datetime.now().strftime("%H:%M:%S"),
            "updated_at": datetime.now().strftime("%H:%M:%S"),
            "hitl_quarantined": True,
            "can_approve_hitl": True,
        },
        {
            "id": "ap2_chk_c3_seed",
            "mandate_id": "ap2_chk_c3_seed",
            "name": "Ergonomic Mesh Chair",
            "sku": "CHAIR-ERG-01",
            "amount": 120.00,
            "amount_usd": 120.00,
            "c3_price_usd": 120.00,
            "merchant": "office-supply@sandbox.paypal.com",
            "status": "PAYPAL_SETTLED",
            "prio": "medium",
            "adk_node": "adk_node_paypal_settlement",
            "adk_route": "route_paypal_settlement",
            "adk_nodes": [
                "adk_node_crypto_gate",
                "adk_node_channel3_ground_truth",
                "adk_node_policy_budget_gate",
                "adk_node_paypal_settlement",
            ],
            "gate_code": "ALL_5_GATES_PASSED",
            "ed25519_sig": _init_sig[:18] + "...",
            "paypal_tx_id": "PAYPAL-SANDBOX-88A1",
            "paypal_order_id": "PAYPAL-SANDBOX-88A1",
            "badge": "✅ PayPal: PAYPAL-SANDBOX-88A1",
            "details": "Settled on PayPal (SANDBOX_SIMULATED) | Channel3 Ground-Truth ($120.00)",
            "description": "Settled on PayPal (SANDBOX_SIMULATED) | Channel3 Ground-Truth ($120.00)",
            "timestamp": datetime.now().strftime("%H:%M:%S"),
            "updated_at": datetime.now().strftime("%H:%M:%S"),
            "hitl_quarantined": False,
            "can_approve_hitl": False,
        },
        {
            "id": "ap2_chk_mitm_01",
            "mandate_id": "ap2_chk_mitm_01",
            "name": "Spoofed GPU Cluster",
            "sku": "HALLUCINATED-SKU",
            "amount": 950.00,
            "amount_usd": 950.00,
            "c3_price_usd": 950.00,
            "merchant": "hacker@darkweb.io",
            "status": "BLOCKED_THREAT",
            "prio": "high",
            "adk_node": "adk_node_threat_sink",
            "adk_route": "route_threat_sink",
            "adk_nodes": [
                "adk_node_crypto_gate",
                "adk_node_channel3_ground_truth",
                "adk_node_threat_sink",
            ],
            "gate_code": "HALLUCINATION_BLOCKED",
            "ed25519_sig": "TAMPERED_MITM_SIG...",
            "badge": "🛑 HALLUCINATION_BLOCKED",
            "details": "GROUND_TRUTH_MISMATCH & ED25519_TAMPERED: Intercepted by AP2 Cryptographic Firewall prior to PayPal Sandbox.",
            "description": "GROUND_TRUTH_MISMATCH & ED25519_TAMPERED: Intercepted by AP2 Cryptographic Firewall prior to PayPal Sandbox.",
            "timestamp": datetime.now().strftime("%H:%M:%S"),
            "updated_at": datetime.now().strftime("%H:%M:%S"),
            "hitl_quarantined": False,
            "can_approve_hitl": False,
        },
    ],
    "adk_graph_telemetry": {
        "workflow_name": "ap2_zero_trust_checkout_graph",
        "graph_name": "ap2_zero_trust_checkout_graph",
        "last_mandate_id": "ap2_chk_hitl_demo",
        "active_node": "adk_node_cfo_hitl_quarantine",
        "active_route": "route_cfo_hitl_quarantine",
        "last_route": "route_cfo_hitl_quarantine",
        "visited_nodes": [
            "adk_node_crypto_gate",
            "adk_node_channel3_ground_truth",
            "adk_node_policy_budget_gate",
            "adk_node_cfo_hitl_quarantine",
        ],
        "bryntum_column": "QUARANTINED",
        "updated_at": datetime.now().strftime("%H:%M:%S"),
    },
}

_FALLBACK_STATE: dict[str, Any] = copy.deepcopy(_SEED_STATE_TEMPLATE)
_FALLBACK_CATALOG: dict[str, dict[str, Any]] = copy.deepcopy(_SEED_TRUSTED_CATALOG)
subscribers: List[asyncio.Queue] = []


def _get_session_bucket(sid: str | None = None, create: bool = False) -> dict[str, Any]:
    resolved_sid = (sid or ACTIVE_SHIELD_SESSION_ID.get() or "").strip()
    if not resolved_sid:
        return {}
    bucket = _byok_sessions.get(resolved_sid)
    if bucket is None and create:
        if len(_byok_sessions) >= MAX_BYOK_SESSIONS:
            oldest_key = next(iter(_byok_sessions))
            _byok_sessions.pop(oldest_key, None)
        bucket = {}
        _byok_sessions[resolved_sid] = bucket
    return bucket if bucket is not None else {}


def _resolve_session_state() -> dict[str, Any]:
    sid = (ACTIVE_SHIELD_SESSION_ID.get() or "").strip()
    if not sid:
        return _FALLBACK_STATE
    bucket = _get_session_bucket(sid, create=True)
    st = bucket.get("state")
    if st is None:
        st = copy.deepcopy(_SEED_STATE_TEMPLATE)
        bucket["state"] = st
    return st


def _resolve_session_catalog() -> dict[str, dict[str, Any]]:
    sid = (ACTIVE_SHIELD_SESSION_ID.get() or "").strip()
    if not sid:
        return _FALLBACK_CATALOG
    bucket = _get_session_bucket(sid, create=True)
    cat = bucket.get("catalog")
    if cat is None:
        cat = copy.deepcopy(_SEED_TRUSTED_CATALOG)
        bucket["catalog"] = cat
    return cat


def _get_session_subscribers(sid: str | None = None) -> List[asyncio.Queue]:
    resolved_sid = (sid or ACTIVE_SHIELD_SESSION_ID.get() or "").strip()
    if not resolved_sid:
        return subscribers
    bucket = _get_session_bucket(resolved_sid, create=True)
    subs = bucket.get("subscribers")
    if subs is None:
        subs = []
        bucket["subscribers"] = subs
    return subs


state: dict[str, Any] = _SessionScopedDict(_resolve_session_state)
TRUSTED_CATALOG: dict[str, dict[str, Any]] = _SessionScopedDict(_resolve_session_catalog)


def now_str() -> str:
    return datetime.now().strftime("%H:%M:%S")


def _upsert_taskboard_card(card: dict) -> None:
    cards = state["taskboard_cards"]
    cid = card.get("id") or card.get("mandate_id")
    card["id"] = cid
    card["mandate_id"] = cid
    for i, existing in enumerate(cards):
        if existing.get("id") == cid:
            cards[i] = card
            return
    cards.insert(0, card)


def enrich_policy_hash(p: dict) -> str:
    h = compute_policy_hash(
        p["policy_id"], p["agent_id"], p["max_budget_usd"], p["allowed_category"], p["cfo_signature"]
    )
    p["ap2_policy_hash"] = h
    return h


async def broadcast_state():
    p = state["policies"]["procurement-01"]
    enrich_policy_hash(p)
    snapshot = json.dumps({
        "policy": p,
        "audit_log": state["audit_log"],
        "taskboard_cards": state["taskboard_cards"],
        "adk_graph_telemetry": state["adk_graph_telemetry"],
    })
    for q in list(_get_session_subscribers()):
        await q.put(snapshot)


FRONTEND_DIST_DIR = Path(__file__).resolve().parent / "frontend" / "dist"
FRONTEND_ASSETS_DIR = FRONTEND_DIST_DIR / "assets"
if FRONTEND_ASSETS_DIR.is_dir():
    app.mount("/assets", StaticFiles(directory=str(FRONTEND_ASSETS_DIR)), name="assets")


@app.get("/", response_class=HTMLResponse)
async def serve_dashboard():
    react_index = FRONTEND_DIST_DIR / "index.html"
    if react_index.is_file():
        return react_index.read_text(encoding="utf-8")
    return Path("index.html").read_text(encoding="utf-8")


@app.get("/api/state")
async def get_state():
    p = state["policies"]["procurement-01"]
    enrich_policy_hash(p)
    return {
        "policy": p,
        "audit_log": state["audit_log"],
        "taskboard_cards": state["taskboard_cards"],
        "adk_graph_telemetry": state["adk_graph_telemetry"],
    }


def _get_session_cred(env_name: str, sid: str | None = None) -> str:
    bucket = _get_session_bucket(sid, create=False)
    if env_name in bucket:
        return str(bucket[env_name]).strip()
    return _SERVER_DEFAULT_ENV.get(env_name, "").strip()


def _has_valid_key(env_name: str, sid: str | None = None) -> bool:
    val = _get_session_cred(env_name, sid)
    return bool(val) and "tu_api_key" not in val.lower() and "your_" not in val.lower()


def _get_session_paypal_sdk(sid: str | None = None) -> PayPalAPIMaticProcessor:
    bucket = _get_session_bucket(sid, create=False)
    custom_sdk = bucket.get("paypal_sdk")
    if isinstance(custom_sdk, PayPalAPIMaticProcessor):
        return custom_sdk
    return paypal_sdk


@app.get("/api/config/status")
async def get_config_status():
    """Returns whether credentials are active for this caller's private session (without exposing secrets)."""
    has_gemini = _has_valid_key("GOOGLE_API_KEY") or _has_valid_key("GEMINI_API_KEY")
    has_channel3 = _has_valid_key("CHANNEL3_API_KEY")
    has_render_wf = _has_valid_key("RENDER_API_KEY") and RenderAsync is not None
    session_pp = _get_session_paypal_sdk()
    effective_model = _get_session_cred("GEMINI_MODEL") or str(root_agent.model)
    effective_slug = _get_session_cred("RENDER_WORKFLOW_SLUG") or "paypal-shield-workflow"
    return {
        "gemini_ready": has_gemini,
        "gemini_model": effective_model,
        "paypal_live_ready": session_pp.is_configured,
        "channel3_ready": has_channel3,
        "render_workflow_ready": has_render_wf,
        "render_workflow_slug": effective_slug,
    }


@app.post("/api/config")
async def update_runtime_config(cfg: CredentialsConfig):
    """
    Updates private per-browser BYOK credentials in the caller's isolated session bucket
    (`shield_byok_sid` HttpOnly cookie) without writing to global `os.environ` or sharing
    tokens with other visitors.
    """
    bucket = _get_session_bucket(create=True)

    if cfg.google_api_key.strip():
        val = cfg.google_api_key.strip()
        if val.lower() in ("clear", "reset", "none"):
            bucket["GOOGLE_API_KEY"] = ""
            bucket["GEMINI_API_KEY"] = ""
        else:
            bucket["GOOGLE_API_KEY"] = val
            bucket["GEMINI_API_KEY"] = ""

    if cfg.gemini_model.strip():
        bucket["GEMINI_MODEL"] = cfg.gemini_model.strip()

    if cfg.paypal_client_id.strip() and cfg.paypal_client_secret.strip():
        pp_id = cfg.paypal_client_id.strip()
        pp_sec = cfg.paypal_client_secret.strip()
        if pp_id.lower() in ("clear", "reset", "none") or pp_sec.lower() in ("clear", "reset", "none"):
            bucket["PAYPAL_CLIENT_ID"] = ""
            bucket["PAYPAL_CLIENT_SECRET"] = ""
            isolated_pp = PayPalAPIMaticProcessor()
            isolated_pp.configure_credentials("", "")
            bucket["paypal_sdk"] = isolated_pp
        else:
            bucket["PAYPAL_CLIENT_ID"] = pp_id
            bucket["PAYPAL_CLIENT_SECRET"] = pp_sec
            isolated_pp = PayPalAPIMaticProcessor()
            isolated_pp.configure_credentials(pp_id, pp_sec)
            bucket["paypal_sdk"] = isolated_pp

    if cfg.channel3_api_key.strip():
        val = cfg.channel3_api_key.strip()
        bucket["CHANNEL3_API_KEY"] = "" if val.lower() in ("clear", "reset", "none") else val

    if cfg.render_api_key.strip():
        val = cfg.render_api_key.strip()
        bucket["RENDER_API_KEY"] = "" if val.lower() in ("clear", "reset", "none") else val

    if cfg.render_workflow_slug.strip():
        bucket["RENDER_WORKFLOW_SLUG"] = cfg.render_workflow_slug.strip()

    has_gemini = _has_valid_key("GOOGLE_API_KEY") or _has_valid_key("GEMINI_API_KEY")
    has_channel3 = _has_valid_key("CHANNEL3_API_KEY")
    has_render_wf = _has_valid_key("RENDER_API_KEY") and RenderAsync is not None
    session_pp = _get_session_paypal_sdk()
    effective_model = _get_session_cred("GEMINI_MODEL") or str(root_agent.model)

    return {
        "status": "OK",
        "gemini_ready": has_gemini,
        "gemini_model": effective_model,
        "paypal_live_ready": session_pp.is_configured,
        "channel3_ready": has_channel3,
        "render_workflow_ready": has_render_wf,
    }


def _normalize_and_register_channel3_product(prod) -> dict | None:
    """
    Extracts normalized metadata from the Channel3 Product Graph (title, price,
    availability, condition, buy_url, variants, key_features, and image) and registers
    its official price and merchant in TRUSTED_CATALOG (Gate 3 Anti-Hallucination Oracle).
    """
    raw_price = None
    compare_at_price = None
    currency = "USD"
    availability = "InStock"
    condition = "new"
    buy_url = None

    brand_list = getattr(prod, "brands", None) or []
    first_brand = getattr(brand_list[0], "name", None) if brand_list else None
    merchant_name = getattr(prod, "brand_name", None) or first_brand or "verified-retailer"

    if getattr(prod, "offers", None) and len(prod.offers) > 0:
        offer = prod.offers[0]
        raw_price = getattr(offer.price, "price", offer.price)
        compare_at_price = getattr(offer.price, "compare_at_price", None)
        currency = str(getattr(offer.price, "currency", "USD") or "USD")
        availability = str(getattr(offer, "availability", "InStock") or "InStock")
        condition = str(getattr(offer, "condition", "new") or "new")
        buy_url = getattr(offer, "url", None)
        merchant_name = (
            getattr(offer, "merchant_name", None)
            or getattr(offer, "domain", None)
            or merchant_name
        )
    elif getattr(prod, "price", None):
        raw_price = getattr(prod.price, "price", prod.price)
        compare_at_price = getattr(prod.price, "compare_at_price", None)
        currency = str(getattr(prod.price, "currency", "USD") or "USD")

    if not raw_price or float(raw_price) <= 0:
        return None

    price_usd = round(float(raw_price), 2)
    sku = str(prod.id)
    slug = re.sub(r"[^a-z0-9]+", "-", merchant_name.lower()).strip("-") or "merchant"
    sandbox_payee = f"{slug}@sandbox.paypal.com"

    images_list = getattr(prod, "images", None) or []
    first_image = getattr(images_list[0], "url", None) if images_list else None
    image_url = getattr(prod, "image_url", None) or first_image

    key_features = list(getattr(prod, "key_features", None) or [])[:4]
    raw_variants = getattr(prod, "variants", None)
    variants_summary = []
    if raw_variants and getattr(raw_variants, "options", None):
        for opt in raw_variants.options[:3]:
            opt_name = getattr(opt, "name", None)
            if opt_name:
                variants_summary.append(str(opt_name))

    # CRITICAL: Register official ground-truth in Shield memory (Gate 3 Anti-Hallucination)
    TRUSTED_CATALOG[sku] = {
        "price": price_usd,
        "paypal_email": sandbox_payee,
        "availability": availability,
        "buy_url": buy_url,
        "brand_or_merchant": merchant_name,
    }

    return {
        "sku": sku,
        "name": prod.title,
        "brand_or_merchant": merchant_name,
        "price": price_usd,
        "compare_at_price": round(float(compare_at_price), 2) if compare_at_price else None,
        "currency": currency,
        "availability": availability,
        "condition": condition,
        "buy_url": buy_url,
        "key_features": key_features,
        "variants": variants_summary,
        "paypal_email": sandbox_payee,
        "image_url": image_url,
        "source": "LIVE_CHANNEL3_API",
    }


@app.get("/api/catalog/search")
async def search_live_channel3(q: str = "office chair", max_price: float | None = None):
    """
    Queries live products on the Channel3 API (`products.search` with `SearchFilters`)
    and registers their official prices, availability, and buy links in TRUSTED_CATALOG
    to enforce the Shield's Anti-Hallucination validation.
    """
    c3_key = _get_session_cred("CHANNEL3_API_KEY")

    def _build_fallback_catalog():
        return [
            {
                "sku": sku,
                "name": sku,
                "price": data["price"],
                "availability": data.get("availability", "InStock"),
                "condition": "new",
                "buy_url": data.get("buy_url", f"https://trychannel3.com/products/{sku}"),
                "key_features": ["Verified Ground-Truth SKU"],
                "variants": [],
                "paypal_email": data["paypal_email"],
                "source": "LOCAL_FALLBACK",
            }
            for sku, data in TRUSTED_CATALOG.items()
            if max_price is None or float(data["price"]) <= float(max_price)
        ]

    # 1. If no Channel3 API Key is configured, use the fallback seed catalog
    if not c3_key or "tu_api_key" in c3_key or "your_" in c3_key.lower():
        fallback_items = _build_fallback_catalog()
        first_price = float(fallback_items[0]["price"]) if fallback_items else 0.0
        ts = now_str()
        _upsert_taskboard_card({
            "id": "c3_sync_seed",
            "mandate_id": "c3_sync_seed",
            "name": f"Channel3 Search: '{q}'",
            "sku": f"{len(fallback_items)} Verified SKUs",
            "amount": first_price,
            "amount_usd": first_price,
            "c3_price_usd": first_price,
            "merchant": fallback_items[0]["paypal_email"] if fallback_items else "sandbox.paypal.com",
            "status": "CHANNEL3_DISCOVERY",
            "prio": "low",
            "adk_node": "adk_node_channel3_ground_truth",
            "adk_route": "ground_truth_locked",
            "adk_nodes": ["START", "search_catalog_channel3"],
            "gate_code": "GROUND_TRUTH_SYNCED",
            "ed25519_sig": state["policies"]["procurement-01"]["cfo_signature"][:18] + "...",
            "badge": "Ground-Truth Synced",
            "details": f"Catalog synced ({len(fallback_items)} SKUs). Anti-hallucination active.",
            "description": f"Catalog synced ({len(fallback_items)} SKUs). Anti-hallucination active.",
            "timestamp": ts,
            "updated_at": ts,
            "hitl_quarantined": False,
            "can_approve_hitl": False,
        })
        await broadcast_state()
        return {"mode": "FALLBACK_CATALOG", "products": fallback_items}

    # 2. Live search on the Channel3 Product Graph (100M+ products, 25,000+ retailers)
    try:
        client = AsyncChannel3Client(api_key=c3_key, timeout=15.0)
        search_kwargs = {"query": q, "limit": 5}
        if max_price is not None and float(max_price) > 0 and SearchFilters and SearchFilterPrice:
            search_kwargs["filters"] = SearchFilters(
                price=SearchFilterPrice(max_price=float(max_price))
            )

        response = await client.products.search(**search_kwargs)

        # Supports both direct response (.products) and AsyncPager (.items / .response.products)
        raw_products = getattr(response, "products", None) or getattr(response, "items", None)
        if not raw_products and hasattr(response, "response"):
            raw_products = getattr(response.response, "products", None)
        raw_products = raw_products or []

        live_products = []
        for prod in raw_products:
            normalized = _normalize_and_register_channel3_product(prod)
            if normalized:
                live_products.append(normalized)

        if live_products:
            _upsert_taskboard_card({
                "id": "c3_sync_seed",
                "mandate_id": "c3_sync_seed",
                "name": f"Channel3 Live: {live_products[0]['name'][:34]}",
                "sku": f"{live_products[0]['sku']} (+{max(0, len(live_products)-1)})",
                "amount": live_products[0]["price"],
                "amount_usd": live_products[0]["price"],
                "c3_price_usd": live_products[0]["price"],
                "merchant": live_products[0]["paypal_email"],
                "status": "CHANNEL3_DISCOVERY",
                "prio": "low",
                "adk_node": "adk_node_channel3_ground_truth",
                "adk_route": "ground_truth_locked",
                "adk_nodes": ["START", "search_catalog_channel3"],
                "gate_code": "GROUND_TRUTH_SYNCED",
                "ed25519_sig": state["policies"]["procurement-01"]["cfo_signature"][:18] + "...",
                "badge": "LIVE Channel3 Graph",
                "details": f"{len(live_products)} live products registered in Ground-Truth ({live_products[0].get('availability', 'InStock')}).",
                "description": f"{len(live_products)} live products registered in Ground-Truth ({live_products[0].get('availability', 'InStock')}).",
                "timestamp": now_str(),
                "updated_at": now_str(),
                "hitl_quarantined": False,
                "can_approve_hitl": False,
            })
            await broadcast_state()

        return {"mode": "LIVE_CHANNEL3_API", "products": live_products}

    except Exception as e:
        fallback_items = _build_fallback_catalog()
        return {"mode": "CHANNEL3_ERROR_FALLBACK", "error": str(e), "products": fallback_items}


@app.get("/api/catalog/enrich/{sku}")
async def enrich_and_recommend_channel3(sku: str, max_price: float | None = None):
    """
    Product Enrichment & AI Recommendations via Channel3 (`products.retrieve` + `products.find_similar`):
    1. Live SKU enrichment (`title`, `description`, `key_features`, `availability`, `buy_url`, `variants`).
    2. Similar product recommendations (`find_similar`) optionally filtered by `max_price` (e.g., CFO budget).
    """
    c3_key = _get_session_cred("CHANNEL3_API_KEY")
    if not c3_key or "tu_api_key" in c3_key or "your_" in c3_key.lower() or AsyncChannel3Client is None:
        item = TRUSTED_CATALOG.get(sku)
        return {
            "mode": "FALLBACK_ENRICHMENT",
            "enriched_product": {
                "sku": sku,
                "price": item["price"] if item else None,
                "paypal_email": item["paypal_email"] if item else None,
                "availability": "InStock",
            } if item else None,
            "similar_recommendations": [
                {"sku": k, "name": k, "price": v["price"], "paypal_email": v["paypal_email"]}
                for k, v in TRUSTED_CATALOG.items()
                if k != sku and (max_price is None or float(v["price"]) <= float(max_price))
            ],
        }

    try:
        client = AsyncChannel3Client(api_key=c3_key, timeout=15.0)
        prod_detail = await client.products.retrieve(sku)
        enriched = _normalize_and_register_channel3_product(prod_detail)
        if enriched and getattr(prod_detail, "description", None):
            enriched["description"] = str(prod_detail.description)[:280]

        sim_kwargs = {"product_id": sku, "limit": 4}
        if max_price is not None and float(max_price) > 0 and SearchFilters and SearchFilterPrice:
            sim_kwargs["filters"] = SearchFilters(
                price=SearchFilterPrice(max_price=float(max_price))
            )

        sim_resp = await client.products.find_similar(**sim_kwargs)
        raw_sim = getattr(sim_resp, "products", None) or getattr(sim_resp, "items", None) or []
        if not raw_sim and hasattr(sim_resp, "response"):
            raw_sim = getattr(sim_resp.response, "products", None) or []

        recommendations = []
        for sp in raw_sim:
            norm_sim = _normalize_and_register_channel3_product(sp)
            if norm_sim:
                recommendations.append(norm_sim)

        return {
            "mode": "LIVE_CHANNEL3_ENRICH_AND_RECOMMEND",
            "enriched_product": enriched,
            "similar_recommendations": recommendations,
        }
    except Exception as e:
        return {
            "mode": "CHANNEL3_ENRICH_ERROR",
            "error": str(e),
            "enriched_product": None,
            "similar_recommendations": [],
        }


@app.post("/api/policy")
async def update_policy(update: PolicyUpdate):
    if not math.isfinite(update.max_budget_usd) or update.max_budget_usd <= 0:
        return JSONResponse(
            status_code=400,
            content={
                "status": "ERROR",
                "error": "Maximum budget (max_budget_usd) must be a positive number greater than $0.00.",
            },
        )
    pol_id = f"pol_{uuid.uuid4().hex[:6]}"
    real_cfo_sig = sign_cfo_policy(
        pol_id, update.agent_id, update.max_budget_usd, update.allowed_category
    )

    new_policy = {
        "policy_id": pol_id,
        "agent_id": update.agent_id,
        "max_budget_usd": round(float(update.max_budget_usd), 2),
        "remaining_usd": round(float(update.max_budget_usd), 2),
        "allowed_category": update.allowed_category,
        "cfo_signature": real_cfo_sig,
        "cfo_pubkey": get_public_key_hex(CFO_PUBLIC_KEY)[:16],
        "agent_pubkey": get_public_key_hex(AGENT_PUBLIC_KEY)[:16],
    }
    enrich_policy_hash(new_policy)
    state["policies"][update.agent_id] = new_policy

    state["audit_log"].insert(0, {
        "timestamp": now_str(),
        "mandate_id": new_policy["policy_id"],
        "item": "CFO Policy Update (AG Grid)",
        "amount": update.max_budget_usd,
        "status": "POLICY_SIGNED",
        "details": f"Ed25519 CFO Sig: {real_cfo_sig[:18]}... | New Hash: {new_policy['ap2_policy_hash'][:14]}..."
    })
    await broadcast_state()
    return {"status": "UPDATED", "policy": new_policy}


async def _settle_mandate_on_paypal(
    mandate_id: str,
    agent_id: str,
    expected_hash: str,
    sku: str,
    product_name: str,
    total_amount: float,
    merchant_paypal_email: str,
    agent_signature: str,
) -> tuple[dict | None, str, str | None]:
    """Executes settlement on PayPal Sandbox via Render Workflows or local APIMatic SDK."""
    workflow_engine_note = "LOCAL_INLINE"
    pp_settlement = None
    session_pp = _get_session_paypal_sdk()

    if _has_valid_key("RENDER_API_KEY") and RenderAsync is not None:
        workflow_slug = _get_session_cred("RENDER_WORKFLOW_SLUG") or "paypal-shield-workflow"
        task_slug = f"{workflow_slug}/orchestrate_ap2_checkout_workflow"
        workflow_payload = {
            "mandate_id": mandate_id,
            "agent_id": agent_id,
            "parent_policy_hash": expected_hash,
            "sku": sku,
            "product_name": product_name,
            "total_amount": total_amount,
            "merchant_paypal_email": merchant_paypal_email,
            "agent_signature": agent_signature,
            "paypal_client_id": session_pp.client_id,
            "paypal_client_secret": session_pp.client_secret,
        }
        try:
            render_client = RenderAsync(token=_get_session_cred("RENDER_API_KEY"))
            task_run = await render_client.workflows.run_task(task_slug, [workflow_payload])
            wf_result = task_run.results[0] if getattr(task_run, "results", None) else {}
            if not wf_result.get("authorized"):
                reason = wf_result.get("error", "RENDER_WORKFLOW_REJECTED")
                return None, workflow_engine_note, reason
            pp_settlement = wf_result.get("settlement")
            workflow_engine_note = f"RENDER_WORKFLOW ({task_run.id})"
        except Exception as wf_err:
            workflow_engine_note = f"LOCAL_FALLBACK (WF: {str(wf_err)[:36]})"

    if pp_settlement is None:
        try:
            pp_settlement = await asyncio.to_thread(
                session_pp.execute_ap2_settlement,
                mandate_id=mandate_id,
                parent_policy_hash=expected_hash,
                product_name=product_name,
                amount_usd=total_amount,
                merchant_paypal_email=merchant_paypal_email,
            )
        except Exception as e:
            return None, workflow_engine_note, f"PAYPAL_API_ERROR: {str(e)}"

    return pp_settlement, workflow_engine_note, None


@app.post("/api/checkout")
async def process_ap2_checkout(req: CheckoutRequest):
    p = state["policies"].get(req.agent_id)
    if p is None:
        return JSONResponse(
            status_code=400,
            content={
                "authorized": False,
                "status": "BLOCKED_BY_SHIELD",
                "code": "UNKNOWN_AGENT_ID",
                "error": f"AGENT_POLICY_NOT_FOUND: No active policy found for agent '{req.agent_id}'.",
            },
        )
    expected_hash = enrich_policy_hash(p)
    trusted_item = TRUSTED_CATALOG.get(req.sku)

    # 1. Execute Google ADK 2.0 Deterministic Graph (`ap2_zero_trust_checkout_graph`)
    graph_input = {
        "mandate_id": req.mandate_id,
        "agent_id": req.agent_id,
        "parent_policy_hash": req.parent_policy_hash,
        "expected_policy_hash": expected_hash,
        "sku": req.sku,
        "product_name": req.product_name,
        "total_amount": req.total_amount,
        "merchant_paypal_email": req.merchant_paypal_email,
        "agent_signature": req.agent_signature,
        "policy_id": p["policy_id"],
        "max_budget_usd": p["max_budget_usd"],
        "remaining_usd": p["remaining_usd"],
        "allowed_category": p["allowed_category"],
        "cfo_signature": p["cfo_signature"],
        "trusted_item": trusted_item,
        "hitl_override_approved": False,
        "visited_nodes": [],
    }
    graph_res = await run_adk_checkout_graph_workflow(graph_input)
    visited_nodes = graph_res.get("visited_nodes", [])
    adk_route = graph_res.get("adk_graph_route", "route_threat_sink")
    bryntum_col = graph_res.get("bryntum_column", "BLOCKED_THREAT")
    hitl_quarantined = bool(graph_res.get("hitl_quarantined", False))

    active_node = visited_nodes[-1] if visited_nodes else "adk_node_crypto_gate"
    state["adk_graph_telemetry"] = {
        "workflow_name": "ap2_zero_trust_checkout_graph",
        "graph_name": "ap2_zero_trust_checkout_graph",
        "last_mandate_id": req.mandate_id,
        "active_node": active_node,
        "active_route": adk_route,
        "last_route": adk_route,
        "visited_nodes": visited_nodes,
        "bryntum_column": bryntum_col,
        "updated_at": now_str(),
    }

    # 2. If the ADK Graph routed to HITL Quarantine (`QUARANTINED`) or Blocked Threat (`BLOCKED_THREAT`)
    if not graph_res.get("authorized"):
        reason = graph_res.get("error", "SHIELD_REJECTED")
        shortfall = graph_res.get("shortfall_usd", 0.0)
        c3_price = float(trusted_item["price"]) if trusted_item and "price" in trusted_item else float(req.total_amount)
        gate_code = "BUDGET_EXCEEDED" if hitl_quarantined else str(graph_res.get("threat_category", "THREAT_BLOCKED"))
        badge_label = (
            f"⏳ HITL: Drag to Settle (+${shortfall:.2f})"
            if hitl_quarantined
            else f"🛑 {gate_code}"
        )
        card_obj = {
            "id": req.mandate_id,
            "mandate_id": req.mandate_id,
            "name": req.product_name,
            "sku": req.sku,
            "amount": req.total_amount,
            "amount_usd": req.total_amount,
            "c3_price_usd": c3_price,
            "shortfall_usd": shortfall,
            "merchant": req.merchant_paypal_email,
            "status": bryntum_col,
            "prio": "high",
            "adk_node": active_node,
            "adk_route": adk_route,
            "adk_nodes": visited_nodes,
            "gate_code": gate_code,
            "ed25519_sig": (req.agent_signature or "")[:18] + "...",
            "badge": badge_label,
            "details": reason,
            "description": reason,
            "timestamp": now_str(),
            "updated_at": now_str(),
            "hitl_quarantined": hitl_quarantined,
            "can_approve_hitl": hitl_quarantined,
        }
        _upsert_taskboard_card(card_obj)
        audit_status = "QUARANTINED_HITL" if hitl_quarantined else "BLOCKED_BY_SHIELD"
        state["audit_log"].insert(0, {
            "timestamp": now_str(),
            "mandate_id": req.mandate_id,
            "item": req.product_name,
            "amount": req.total_amount,
            "status": audit_status,
            "details": f"{reason} | ADK Graph: {' → '.join(visited_nodes)}",
        })
        await broadcast_state()
        return {
            "authorized": False,
            "status": audit_status,
            "code": gate_code,
            "error": reason,
            "adk_node": active_node,
            "adk_graph_route": adk_route,
            "adk_graph_nodes": visited_nodes,
            "bryntum_column": bryntum_col,
            "hitl_quarantined": hitl_quarantined,
            "taskboard_card": card_obj,
            "remaining_usd": p["remaining_usd"],
        }

    # 3. Settle on PayPal Sandbox via Render Workflows / APIMatic SDK
    pp_settlement, workflow_engine_note, err_reason = await _settle_mandate_on_paypal(
        mandate_id=req.mandate_id,
        agent_id=req.agent_id,
        expected_hash=expected_hash,
        sku=req.sku,
        product_name=req.product_name,
        total_amount=req.total_amount,
        merchant_paypal_email=req.merchant_paypal_email,
        agent_signature=req.agent_signature,
    )
    if err_reason or pp_settlement is None:
        state["audit_log"].insert(0, {
            "timestamp": now_str(),
            "mandate_id": req.mandate_id,
            "item": req.product_name,
            "amount": req.total_amount,
            "status": "BLOCKED_BY_SHIELD",
            "details": err_reason or "PAYPAL_SETTLEMENT_FAILED",
        })
        await broadcast_state()
        return {
            "authorized": False,
            "status": "BLOCKED_BY_SHIELD",
            "error": err_reason,
            "remaining_usd": p["remaining_usd"],
        }

    p["remaining_usd"] = round(p["remaining_usd"] - req.total_amount, 2)
    pp_tx_id = pp_settlement["paypal_order_id"]
    pp_mode = pp_settlement["mode"]
    c3_price = float(trusted_item["price"]) if trusted_item and "price" in trusted_item else float(req.total_amount)

    settled_card = {
        "id": req.mandate_id,
        "mandate_id": req.mandate_id,
        "name": req.product_name,
        "sku": req.sku,
        "amount": req.total_amount,
        "amount_usd": req.total_amount,
        "c3_price_usd": c3_price,
        "merchant": req.merchant_paypal_email,
        "status": "PAYPAL_SETTLED",
        "prio": "medium",
        "adk_node": "adk_node_paypal_settlement",
        "adk_route": adk_route,
        "adk_nodes": visited_nodes,
        "gate_code": "ALL_5_GATES_PASSED",
        "ed25519_sig": (req.agent_signature or "")[:18] + "...",
        "paypal_tx_id": pp_tx_id,
        "paypal_order_id": pp_tx_id,
        "badge": f"✅ PayPal: {pp_tx_id}",
        "details": f"Settled on PayPal ({pp_mode}) | AP2 Proof: {expected_hash[:12]}...",
        "description": f"Settled on PayPal ({pp_mode}) | AP2 Proof: {expected_hash[:12]}...",
        "timestamp": now_str(),
        "updated_at": now_str(),
        "hitl_quarantined": False,
        "can_approve_hitl": False,
    }
    _upsert_taskboard_card(settled_card)

    state["audit_log"].insert(0, {
        "timestamp": now_str(),
        "mandate_id": req.mandate_id,
        "item": req.product_name,
        "amount": req.total_amount,
        "status": "PAYPAL_COMPLETED",
        "details": f"PayPal Order: {pp_tx_id} | Ed25519 Verified | ADK Graph: {' → '.join(visited_nodes)} | {workflow_engine_note} | {pp_mode}",
    })
    await broadcast_state()
    return {
        "authorized": True,
        "status": "PAYPAL_COMPLETED",
        "paypal_tx_id": pp_tx_id,
        "paypal_order_id": pp_tx_id,
        "paypal_mode": pp_mode,
        "workflow_engine": workflow_engine_note,
        "adk_graph_route": adk_route,
        "adk_graph_nodes": visited_nodes,
        "bryntum_column": "PAYPAL_SETTLED",
        "remaining_usd": p["remaining_usd"],
        "ap2_proof": expected_hash,
    }


@app.post("/api/quarantine/resolve")
async def resolve_quarantined_mandate(req: QuarantineResolveRequest):
    """
    Endpoint invoked when dragging a card in Bryntum TaskBoard (Drag & Drop HITL)
    or via the ADK agent's `resolve_quarantined_mandate_hitl` tool.
    """
    lookup_id = (req.mandate_id or req.card_id).strip()
    target_card = None
    for c in state["taskboard_cards"]:
        if c.get("id") == lookup_id or c.get("mandate_id") == lookup_id:
            target_card = c
            break

    if not target_card:
        return {"status": "ERROR", "reason": f"Card '{lookup_id}' was not found in Bryntum TaskBoard.", "error": f"Card '{lookup_id}' was not found in Bryntum TaskBoard."}

    card_status = str(target_card.get("status") or "").upper()
    if card_status == "PAYPAL_SETTLED":
        return {
            "status": "ALREADY_SETTLED",
            "action": "ALREADY_SETTLED",
            "reason": f"Mandate '{lookup_id}' was already settled on PayPal Sandbox.",
            "card": target_card,
        }

    if card_status == "BLOCKED_THREAT" and not target_card.get("hitl_quarantined"):
        return {
            "status": "FORBIDDEN_ZERO_TRUST",
            "reason": "Zero-Trust Policy: Cryptographic attacks (MitM) or price hallucinations cannot be approved.",
            "error": "Zero-Trust Policy: Cryptographic attacks (MitM) or price hallucinations cannot be approved.",
        }

    if card_status != "QUARANTINED" and not target_card.get("hitl_quarantined"):
        return {
            "status": "INVALID_CARD_STATE",
            "reason": f"Card '{lookup_id}' (status={card_status}) is not a mandate in HITL quarantine.",
            "error": f"Card '{lookup_id}' (status={card_status}) is not a mandate in HITL quarantine.",
        }

    p = state["policies"]["procurement-01"]
    target_col = req.target_column.strip().upper()
    if target_col not in ("PAYPAL_SETTLED", "BLOCKED_THREAT"):
        return {
            "status": "ERROR",
            "reason": f"Invalid target column '{target_col}'. Use 'PAYPAL_SETTLED' or 'BLOCKED_THREAT'.",
            "error": f"Invalid target column '{target_col}'. Use 'PAYPAL_SETTLED' or 'BLOCKED_THREAT'.",
        }

    # Case A: CFO drags the card to 'BLOCKED_THREAT' (Reject quarantined purchase)
    if target_col == "BLOCKED_THREAT":
        target_card["status"] = "BLOCKED_THREAT"
        target_card["hitl_quarantined"] = False
        target_card["can_approve_hitl"] = False
        target_card["adk_node"] = "adk_node_threat_sink"
        target_card["adk_route"] = "route_cfo_rejected_hitl"
        target_card["adk_nodes"] = list(target_card.get("adk_nodes", [])) + ["adk_node_threat_sink"]
        target_card["gate_code"] = "CFO_REJECTED_HITL"
        target_card["badge"] = "🛑 CFO Rejected (HITL)"
        target_card["details"] = "Manually rejected by the CFO in Bryntum TaskBoard."
        target_card["description"] = "Manually rejected by the CFO in Bryntum TaskBoard."
        target_card["timestamp"] = now_str()
        target_card["updated_at"] = now_str()

        state["adk_graph_telemetry"] = {
            "workflow_name": "ap2_zero_trust_checkout_graph",
            "graph_name": "ap2_zero_trust_checkout_graph",
            "last_mandate_id": target_card["mandate_id"],
            "active_node": "adk_node_threat_sink",
            "active_route": "route_cfo_rejected_hitl",
            "last_route": "route_cfo_rejected_hitl",
            "visited_nodes": target_card["adk_nodes"],
            "bryntum_column": "BLOCKED_THREAT",
            "updated_at": now_str(),
        }
        state["audit_log"] = [
            e for e in state["audit_log"]
            if not (e.get("mandate_id") == target_card["mandate_id"] and e.get("status") == "QUARANTINED_HITL")
        ]
        state["audit_log"].insert(0, {
            "timestamp": now_str(),
            "mandate_id": target_card["mandate_id"],
            "item": f"{target_card['name']} (Bryntum HITL Reject)",
            "amount": target_card["amount"],
            "merchant": target_card.get("merchant", "sandbox.paypal.com"),
            "status": "BLOCKED_BY_SHIELD",
            "details": "CFO rejected the quarantined mandate from Bryntum TaskBoard.",
        })
        await broadcast_state()
        return {"status": "OK", "action": "REJECTED_BY_CFO", "card": target_card}

    # Case B: CFO drags the card from 'QUARANTINED' to 'PAYPAL_SETTLED' (Auto-Re-Sign Ed25519 + Resume ADK Graph + Settle PayPal)
    amount = float(target_card["amount"])
    sku = target_card["sku"]
    product_name = target_card["name"]
    merchant_email = target_card["merchant"]

    # Ensure the SKU is in TRUSTED_CATALOG in case it is the initial demo card
    if sku not in TRUSTED_CATALOG:
        TRUSTED_CATALOG[sku] = {"price": amount, "paypal_email": merchant_email}

    # 1. Compute new budget to cover the order and pre-sign with the CFO's Ed25519 private key
    shortfall = max(0.0, round(amount - p["remaining_usd"], 2))
    new_max_budget = round(p["max_budget_usd"] + shortfall + 50.0, 2) if shortfall > 0 else p["max_budget_usd"]
    new_remaining_before_charge = round(p["remaining_usd"] + shortfall + 50.0, 2) if shortfall > 0 else p["remaining_usd"]
    new_pol_id = f"pol_hitl_{uuid.uuid4().hex[:5]}"
    new_cfo_sig = sign_cfo_policy(new_pol_id, p["agent_id"], new_max_budget, p["allowed_category"])
    new_policy_hash = compute_policy_hash(
        new_pol_id, p["agent_id"], new_max_budget, p["allowed_category"], new_cfo_sig
    )

    # 2. Re-sign the checkout mandate with the new Policy Hash and resume the ADK 2.0 Graph
    resumed_agent_sig = sign_agent_checkout(
        mandate_id=target_card["mandate_id"],
        agent_id=p["agent_id"],
        parent_policy_hash=new_policy_hash,
        sku=sku,
        total_amount=amount,
        merchant_paypal_email=merchant_email,
    )

    graph_res = await run_adk_checkout_graph_workflow({
        "mandate_id": target_card["mandate_id"],
        "agent_id": p["agent_id"],
        "parent_policy_hash": new_policy_hash,
        "expected_policy_hash": new_policy_hash,
        "sku": sku,
        "product_name": product_name,
        "total_amount": amount,
        "merchant_paypal_email": merchant_email,
        "agent_signature": resumed_agent_sig,
        "policy_id": new_pol_id,
        "max_budget_usd": new_max_budget,
        "remaining_usd": new_remaining_before_charge,
        "allowed_category": p["allowed_category"],
        "cfo_signature": new_cfo_sig,
        "trusted_item": TRUSTED_CATALOG.get(sku),
        "hitl_override_approved": True,
        "visited_nodes": ["adk_node_cfo_hitl_quarantine (RESUMED)"],
    })

    visited_nodes = graph_res.get("visited_nodes", [])
    if not graph_res.get("authorized"):
        await broadcast_state()
        return {"status": "ERROR", "error": graph_res.get("error", "ADK_GRAPH_REJECTED")}

    # 3. Settle on PayPal Sandbox via Render Workflows / APIMatic SDK
    pp_settlement, workflow_engine_note, err_reason = await _settle_mandate_on_paypal(
        mandate_id=target_card["mandate_id"],
        agent_id=p["agent_id"],
        expected_hash=new_policy_hash,
        sku=sku,
        product_name=product_name,
        total_amount=amount,
        merchant_paypal_email=merchant_email,
        agent_signature=resumed_agent_sig,
    )
    if err_reason or pp_settlement is None:
        await broadcast_state()
        return {"status": "ERROR", "error": err_reason or "PAYPAL_SETTLEMENT_ERROR"}

    # Confirm policy update and deduct the settled charge
    p["policy_id"] = new_pol_id
    p["max_budget_usd"] = new_max_budget
    p["remaining_usd"] = round(new_remaining_before_charge - amount, 2)
    p["cfo_signature"] = new_cfo_sig
    enrich_policy_hash(p)

    state["audit_log"] = [
        e for e in state["audit_log"]
        if not (e.get("mandate_id") == target_card["mandate_id"] and e.get("status") == "QUARANTINED_HITL")
    ]
    state["audit_log"].insert(0, {
        "timestamp": now_str(),
        "mandate_id": new_pol_id,
        "item": "CFO HITL Override (Bryntum TaskBoard)",
        "amount": new_max_budget,
        "merchant": merchant_email,
        "status": "POLICY_SIGNED",
        "details": f"Bryntum Drag-to-Approve | Ed25519 CFO Sig: {new_cfo_sig[:16]}... | New AP2 Hash: {new_policy_hash[:14]}...",
    })

    pp_tx_id = pp_settlement["paypal_order_id"]
    pp_mode = pp_settlement["mode"]

    target_card["status"] = "PAYPAL_SETTLED"
    target_card["hitl_quarantined"] = False
    target_card["can_approve_hitl"] = False
    target_card["adk_node"] = "adk_node_paypal_settlement"
    target_card["adk_route"] = "route_paypal_settlement (HITL_RESUMED)"
    target_card["adk_nodes"] = visited_nodes
    target_card["gate_code"] = "CFO_HITL_APPROVED"
    target_card["ed25519_sig"] = resumed_agent_sig[:18] + "..."
    target_card["paypal_tx_id"] = pp_tx_id
    target_card["paypal_order_id"] = pp_tx_id
    target_card["badge"] = f"✅ HITL Settled: {pp_tx_id}"
    target_card["details"] = f"Approved in Bryntum and settled on PayPal ({pp_mode}) | AP2: {new_policy_hash[:12]}..."
    target_card["description"] = f"Approved in Bryntum and settled on PayPal ({pp_mode}) | AP2: {new_policy_hash[:12]}..."
    target_card["timestamp"] = now_str()
    target_card["updated_at"] = now_str()

    state["adk_graph_telemetry"] = {
        "workflow_name": "ap2_zero_trust_checkout_graph",
        "graph_name": "ap2_zero_trust_checkout_graph",
        "last_mandate_id": target_card["mandate_id"],
        "active_node": "adk_node_paypal_settlement",
        "active_route": "route_paypal_settlement (HITL_RESUMED)",
        "last_route": "route_paypal_settlement (HITL_RESUMED)",
        "visited_nodes": visited_nodes,
        "bryntum_column": "PAYPAL_SETTLED",
        "updated_at": now_str(),
    }

    state["audit_log"].insert(0, {
        "timestamp": now_str(),
        "mandate_id": target_card["mandate_id"],
        "item": f"{product_name} (HITL Resumed)",
        "amount": amount,
        "status": "PAYPAL_COMPLETED",
        "details": f"PayPal Order: {pp_tx_id} | Bryntum HITL Drag-to-Settle | ADK Graph: {' → '.join(visited_nodes)} | {pp_mode}",
    })
    await broadcast_state()
    return {
        "status": "OK",
        "action": "APPROVED_AND_SETTLED",
        "card": target_card,
        "mandate_id": target_card["mandate_id"],
        "paypal_tx_id": pp_tx_id,
        "paypal_order_id": pp_tx_id,
        "paypal_mode": pp_mode,
        "new_max_budget_usd": p["max_budget_usd"],
        "remaining_usd": p["remaining_usd"],
        "adk_graph_nodes": visited_nodes,
        "adk_visited_nodes": visited_nodes,
    }


@app.post("/api/chat")
async def chat_endpoint(req: ChatRequest, request: Request):
    """Executes the Google ADK agent and returns tool traces + response."""
    if request.url.port:
        os.environ["SHIELD_RUNTIME_PORT"] = str(request.url.port)

    if not (_has_valid_key("GOOGLE_API_KEY") or _has_valid_key("GEMINI_API_KEY")):
        return {
            "reply": (
                "🔑 **Gemini API Key not configured**\n\n"
                "No active `GOOGLE_API_KEY` was found. Click the **⚙️ API Keys (BYOK)** "
                "button in the top bar to hot-load your key in memory or add it to your `.env` file."
            ),
            "tools": [],
        }

    session_gemini_key = _get_session_cred("GOOGLE_API_KEY") or _get_session_cred("GEMINI_API_KEY")
    session_model = _get_session_cred("GEMINI_MODEL") or str(root_agent.model)
    scoped_session_id = f"{ACTIVE_SHIELD_SESSION_ID.get() or 'anon'}:{req.session_id}"

    session = await session_service.get_session(
        app_name=APP_NAME, user_id=USER_ID, session_id=scoped_session_id
    )
    if not session:
        await session_service.create_session(
            app_name=APP_NAME, user_id=USER_ID, session_id=scoped_session_id
        )

    session_agent = build_session_procurement_agent(
        api_key=session_gemini_key,
        model_name=session_model,
    )
    session_runner = Runner(
        agent=session_agent,
        app_name=APP_NAME,
        session_service=session_service,
    )

    user_msg = types.Content(role="user", parts=[types.Part.from_text(text=req.message)])
    tools_called = []
    final_reply = ""

    try:
        async for event in session_runner.run_async(
            user_id=USER_ID, session_id=scoped_session_id, new_message=user_msg
        ):
            for fn in event.get_function_calls():
                tools_called.append(fn.name)
            if event.is_final_response() and event.content and event.content.parts:
                final_reply = "".join(part.text or "" for part in event.content.parts)
    except Exception as e:
        err_str = str(e)
        err_lower = err_str.lower()

        if any(
            k in err_lower
            for k in ("429", "resource_exhausted", "quota", "rate limit", "too many requests", "token")
        ):
            return {
                "reply": (
                    "⚠️ **Gemini API token / quota limit reached (HTTP 429)**\n\n"
                    "The requests-per-minute or token quota for your Google Gemini API account has been exceeded. "
                    "Please wait a few seconds before sending another message or update your `GOOGLE_API_KEY` in **⚙️ API Keys (BYOK)**.\n\n"
                    f"`Detail: {err_str}`"
                ),
                "tools": tools_called,
            }

        if any(
            k in err_lower
            for k in ("api_key_invalid", "api key not valid", "unauthenticated", "permission_denied", "missing key", "401", "403")
        ):
            return {
                "reply": (
                    "🔑 **Invalid or unauthorized Gemini API Key**\n\n"
                    "The configured `GOOGLE_API_KEY` was rejected by the Google Gemini API. "
                    "Please verify or update your key via the **⚙️ API Keys (BYOK)** button.\n\n"
                    f"`Detail: {err_str}`"
                ),
                "tools": tools_called,
            }

        return {
            "reply": f"❌ **Error executing ADK agent:**\n\n`{err_str}`",
            "tools": tools_called,
        }

    return {
        "reply": final_reply or "Operation processed.",
        "tools": tools_called
    }


_SINGLE_SERIES_WIDGET_TYPES = {
    "pie-chart",
    "donut-chart",
    "funnel-chart",
    "cone-funnel-chart",
    "pyramid-chart",
    "treemap-chart",
    "sunburst-chart",
}


def _parse_studio_chart_request(
    prompt: str,
    existing_add_count: int = 0,
    override_widget_type: str | None = None,
    override_widget_id: str | None = None,
) -> dict:
    return parse_studio_chart_request(
        prompt=prompt,
        existing_add_count=existing_add_count,
        override_widget_type=override_widget_type,
        override_widget_id=override_widget_id,
    )


@app.post("/api/studio/ai/responses")
async def studio_ai_responses(request: Request):
    """
    AG Studio Agent Framework endpoint (`AgLlmAdapter` -> `/api/studio/ai/responses`).
    Delegates execution to the dedicated Google ADK agent (`ap2_shield_agent/studio_agent.py`),
    operating with `Agent`, `Runner`, `InMemorySessionService`, and `AgStudioClientTool(is_long_running=True)`
    to power both the `ap2-shield-auditor` agent and AG Studio's specialist sub-agents
    (`lead`, `data`, `widget`, `page`, `planning`) with automatic deterministic fallback.
    """
    try:
        body = await request.json()
    except Exception:
        body = {}

    session_gemini_key = _get_session_cred("GOOGLE_API_KEY") or _get_session_cred("GEMINI_API_KEY")
    return await run_studio_adk_turn(body, state, api_key=session_gemini_key)


@app.get("/api/stream")
async def stream_events(request: Request):
    q = asyncio.Queue()
    session_subs = _get_session_subscribers()
    session_subs.append(q)
    async def event_generator():
        try:
            while True:
                if await request.is_disconnected():
                    break
                data = await q.get()
                yield f"data: {data}\n\n"
        finally:
            if q in session_subs:
                session_subs.remove(q)
    return StreamingResponse(event_generator(), media_type="text/event-stream")