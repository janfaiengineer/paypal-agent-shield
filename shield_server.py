import os
import asyncio
import uuid
import json
from pathlib import Path
from datetime import datetime
from typing import List
from dotenv import load_dotenv
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

# Carga variables de entorno (.env) para Google ADK (GOOGLE_API_KEY) y PayPal
load_dotenv()

from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types

from paypal_apimatic_client import PayPalAPIMaticProcessor
from ap2_crypto import (
    sign_cfo_policy,
    verify_cfo_policy,
    compute_policy_hash,
    verify_agent_checkout,
    get_public_key_hex,
    CFO_PUBLIC_KEY,
    AGENT_PUBLIC_KEY,
)
from ap2_shield_agent.agent import root_agent

app = FastAPI(title="PayPal Agent Shield — Unified Console")
paypal_sdk = PayPalAPIMaticProcessor()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- RUNTIME NATIVO DE GOOGLE ADK ---
APP_NAME = "paypal_agent_shield_app"
USER_ID = "cfo_executive"
session_service = InMemorySessionService()
adk_runner = Runner(
    agent=root_agent,
    app_name=APP_NAME,
    session_service=session_service,
)

# --- CATÁLOGO DE VERDAD (GROUND-TRUTH) PARA PREVENIR ALUCINACIONES ---
TRUSTED_CATALOG = {
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


class CredentialsConfig(BaseModel):
    google_api_key: str = ""
    paypal_client_id: str = ""
    paypal_client_secret: str = ""


_init_sig = sign_cfo_policy("pol_aggrid_001", "procurement-01", 200.00, "OFFICE_AND_TECH")

state = {
    "policies": {
        "procurement-01": {
            "policy_id": "pol_aggrid_001",
            "agent_id": "procurement-01",
            "max_budget_usd": 200.00,
            "remaining_usd": 200.00,
            "allowed_category": "OFFICE_AND_TECH",
            "cfo_signature": _init_sig,
            "cfo_pubkey": get_public_key_hex(CFO_PUBLIC_KEY)[:16],
            "agent_pubkey": get_public_key_hex(AGENT_PUBLIC_KEY)[:16],
        }
    },
    "audit_log": []
}

subscribers: List[asyncio.Queue] = []


def now_str() -> str:
    return datetime.now().strftime("%H:%M:%S")


def enrich_policy_hash(p: dict) -> str:
    h = compute_policy_hash(
        p["policy_id"], p["agent_id"], p["max_budget_usd"], p["allowed_category"], p["cfo_signature"]
    )
    p["ap2_policy_hash"] = h
    return h


async def broadcast_state():
    p = state["policies"]["procurement-01"]
    enrich_policy_hash(p)
    snapshot = json.dumps({"policy": p, "audit_log": state["audit_log"]})
    for q in subscribers:
        await q.put(snapshot)


@app.get("/", response_class=HTMLResponse)
async def serve_dashboard():
    return Path("index.html").read_text(encoding="utf-8")


@app.get("/api/state")
async def get_state():
    p = state["policies"]["procurement-01"]
    enrich_policy_hash(p)
    return {"policy": p, "audit_log": state["audit_log"]}


@app.get("/api/config/status")
async def get_config_status():
    """Devuelve si las llaves ya están activas (sin exponer los secretos al navegador)."""
    has_gemini = bool(os.environ.get("GOOGLE_API_KEY"))
    return {
        "gemini_ready": has_gemini,
        "paypal_live_ready": paypal_sdk.is_configured,
    }


@app.post("/api/config")
async def update_runtime_config(cfg: CredentialsConfig):
    """Actualiza en memoria las credenciales de Google ADK y PayPal APIMatic SDK."""
    if cfg.google_api_key.strip():
        os.environ["GOOGLE_API_KEY"] = cfg.google_api_key.strip()

    if cfg.paypal_client_id.strip() and cfg.paypal_client_secret.strip():
        paypal_sdk.configure_credentials(cfg.paypal_client_id, cfg.paypal_client_secret)

    state["audit_log"].insert(0, {
        "timestamp": now_str(),
        "mandate_id": "SYS-CFG",
        "item": "Runtime Credentials Updated",
        "amount": 0.0,
        "status": "POLICY_SIGNED",
        "details": f"Gemini Key: {'ACTIVE' if os.environ.get('GOOGLE_API_KEY') else 'MISSING'} | PayPal Mode: {'LIVE SANDBOX' if paypal_sdk.is_configured else 'SIMULATED'}"
    })
    await broadcast_state()
    return {
        "status": "OK",
        "gemini_ready": bool(os.environ.get("GOOGLE_API_KEY")),
        "paypal_live_ready": paypal_sdk.is_configured
    }


@app.post("/api/policy")
async def update_policy(update: PolicyUpdate):
    pol_id = f"pol_{uuid.uuid4().hex[:6]}"
    real_cfo_sig = sign_cfo_policy(
        pol_id, update.agent_id, update.max_budget_usd, update.allowed_category
    )

    new_policy = {
        "policy_id": pol_id,
        "agent_id": update.agent_id,
        "max_budget_usd": update.max_budget_usd,
        "remaining_usd": update.max_budget_usd,
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


@app.post("/api/checkout")
async def process_ap2_checkout(req: CheckoutRequest):
    p = state["policies"].get(req.agent_id)
    expected_hash = enrich_policy_hash(p)

    # 1. Verificar firma Ed25519 del CFO
    if not verify_cfo_policy(p["policy_id"], p["agent_id"], p["max_budget_usd"], p["allowed_category"], p["cfo_signature"]):
        reason = "CRYPTO_ERROR: Firma Ed25519 del CFO inválida."
        state["audit_log"].insert(0, {"timestamp": now_str(), "mandate_id": req.mandate_id, "item": req.product_name, "amount": req.total_amount, "status": "BLOCKED_BY_SHIELD", "details": reason})
        await broadcast_state()
        return {"authorized": False, "error": reason, "remaining_usd": p["remaining_usd"]}

    # 2. Verificar firma Ed25519 del Agente sobre el Checkout Mandate
    agent_sig_valid = verify_agent_checkout(
        mandate_id=req.mandate_id,
        agent_id=req.agent_id,
        parent_policy_hash=req.parent_policy_hash,
        sku=req.sku,
        total_amount=req.total_amount,
        merchant_paypal_email=req.merchant_paypal_email,
        signature_b64=req.agent_signature
    )
    if not agent_sig_valid:
        reason = "ED25519_INVALID_SIGNATURE: Adulteración detectada en tránsito (Firma no coincide con el payload)."
        state["audit_log"].insert(0, {"timestamp": now_str(), "mandate_id": req.mandate_id, "item": req.product_name, "amount": req.total_amount, "status": "BLOCKED_BY_SHIELD", "details": reason})
        await broadcast_state()
        return {"authorized": False, "error": reason, "remaining_usd": p["remaining_usd"]}

    # 3. Validar Ground-Truth del Catálogo (Anti-Alucinaciones del LLM)
    trusted_item = TRUSTED_CATALOG.get(req.sku)
    if not trusted_item:
        reason = f"HALLUCINATION_BLOCKED: El SKU '{req.sku}' no existe en Channel3."
        state["audit_log"].insert(0, {"timestamp": now_str(), "mandate_id": req.mandate_id, "item": req.product_name, "amount": req.total_amount, "status": "BLOCKED_BY_SHIELD", "details": reason})
        await broadcast_state()
        return {"authorized": False, "error": reason, "remaining_usd": p["remaining_usd"]}

    if req.total_amount != trusted_item["price"] or req.merchant_paypal_email != trusted_item["paypal_email"]:
        reason = f"GROUND_TRUTH_MISMATCH: El agente envió ${req.total_amount:.2f}, pero el precio oficial de {req.sku} es ${trusted_item['price']:.2f}."
        state["audit_log"].insert(0, {"timestamp": now_str(), "mandate_id": req.mandate_id, "item": req.product_name, "amount": req.total_amount, "status": "BLOCKED_BY_SHIELD", "details": reason})
        await broadcast_state()
        return {"authorized": False, "error": reason, "remaining_usd": p["remaining_usd"]}

    # 4. Validar Hash de Política AP2
    if req.parent_policy_hash != expected_hash:
        reason = "AP2_HASH_MISMATCH: La política del CFO cambió antes de liquidar."
        state["audit_log"].insert(0, {"timestamp": now_str(), "mandate_id": req.mandate_id, "item": req.product_name, "amount": req.total_amount, "status": "BLOCKED_BY_SHIELD", "details": reason})
        await broadcast_state()
        return {"authorized": False, "error": reason, "remaining_usd": p["remaining_usd"]}

    # 5. Validar Presupuesto Disponible en AG Grid
    if req.total_amount > p["remaining_usd"]:
        reason = f"BUDGET_EXCEEDED: Carrito ${req.total_amount:.2f} USD > Disponible en AG Grid ${p['remaining_usd']:.2f} USD"
        state["audit_log"].insert(0, {"timestamp": now_str(), "mandate_id": req.mandate_id, "item": req.product_name, "amount": req.total_amount, "status": "BLOCKED_BY_SHIELD", "details": reason})
        await broadcast_state()
        return {"authorized": False, "error": reason, "remaining_usd": p["remaining_usd"]}

    # 6. Liquidar en PayPal Sandbox vía APIMatic SDK
    try:
        pp_settlement = await asyncio.to_thread(
            paypal_sdk.execute_ap2_settlement,
            mandate_id=req.mandate_id,
            parent_policy_hash=expected_hash,
            product_name=req.product_name,
            amount_usd=req.total_amount,
            merchant_paypal_email=req.merchant_paypal_email,
        )
    except Exception as e:
        reason = f"PAYPAL_API_ERROR: {str(e)}"
        state["audit_log"].insert(0, {"timestamp": now_str(), "mandate_id": req.mandate_id, "item": req.product_name, "amount": req.total_amount, "status": "BLOCKED_BY_SHIELD", "details": reason})
        await broadcast_state()
        return {"authorized": False, "error": reason, "remaining_usd": p["remaining_usd"]}

    p["remaining_usd"] -= req.total_amount
    pp_tx_id = pp_settlement["paypal_order_id"]
    pp_mode = pp_settlement["mode"]

    state["audit_log"].insert(0, {
        "timestamp": now_str(),
        "mandate_id": req.mandate_id,
        "item": req.product_name,
        "amount": req.total_amount,
        "status": "PAYPAL_COMPLETED",
        "details": f"PayPal Order: {pp_tx_id} | Ed25519 Verified | {pp_mode}"
    })
    await broadcast_state()
    return {
        "authorized": True,
        "paypal_tx_id": pp_tx_id,
        "paypal_mode": pp_mode,
        "remaining_usd": p["remaining_usd"],
        "ap2_proof": expected_hash
    }


@app.post("/api/chat")
async def chat_endpoint(req: ChatRequest):
    """Ejecuta el agente de Google ADK y devuelve los trazos de herramientas + respuesta."""
    session = await session_service.get_session(
        app_name=APP_NAME, user_id=USER_ID, session_id=req.session_id
    )
    if not session:
        await session_service.create_session(
            app_name=APP_NAME, user_id=USER_ID, session_id=req.session_id
        )

    user_msg = types.Content(role="user", parts=[types.Part.from_text(text=req.message)])
    tools_called = []
    final_reply = ""

    async for event in adk_runner.run_async(
        user_id=USER_ID, session_id=req.session_id, new_message=user_msg
    ):
        for fn in event.get_function_calls():
            tools_called.append(fn.name)
        if event.is_final_response() and event.content and event.content.parts:
            final_reply = "".join(part.text or "" for part in event.content.parts)

    return {
        "reply": final_reply or "Operación procesada.",
        "tools": tools_called
    }


@app.get("/api/stream")
async def stream_events(request: Request):
    q = asyncio.Queue()
    subscribers.append(q)
    async def event_generator():
        try:
            while True:
                if await request.is_disconnected():
                    break
                data = await q.get()
                yield f"data: {data}\n\n"
        finally:
            subscribers.remove(q)
    return StreamingResponse(event_generator(), media_type="text/event-stream")