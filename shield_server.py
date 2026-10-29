import os
import re
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

try:
    from channel3 import AsyncChannel3Client
except ImportError:
    try:
        from channel3_sdk import AsyncChannel3 as AsyncChannel3Client
    except ImportError:
        AsyncChannel3Client = None

try:
    from render import RenderAsync
except ImportError:
    RenderAsync = None

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
    gemini_model: str = ""
    paypal_client_id: str = ""
    paypal_client_secret: str = ""
    channel3_api_key: str = ""
    render_api_key: str = ""
    render_workflow_slug: str = ""


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


def _has_valid_key(env_name: str) -> bool:
    val = os.environ.get(env_name, "").strip()
    return bool(val) and "tu_api_key" not in val.lower()


@app.get("/api/config/status")
async def get_config_status():
    """Devuelve si las llaves ya están activas (sin exponer los secretos al navegador)."""
    has_gemini = _has_valid_key("GOOGLE_API_KEY") or _has_valid_key("GEMINI_API_KEY")
    has_channel3 = _has_valid_key("CHANNEL3_API_KEY")
    has_render_wf = _has_valid_key("RENDER_API_KEY") and RenderAsync is not None
    return {
        "gemini_ready": has_gemini,
        "gemini_model": str(root_agent.model),
        "paypal_live_ready": paypal_sdk.is_configured,
        "channel3_ready": has_channel3,
        "render_workflow_ready": has_render_wf,
        "render_workflow_slug": os.getenv("RENDER_WORKFLOW_SLUG", "paypal-shield-workflow"),
    }


@app.post("/api/config")
async def update_runtime_config(cfg: CredentialsConfig):
    """Actualiza en memoria las credenciales de Google ADK, PayPal APIMatic SDK, Channel3 y Render Workflows."""
    if cfg.google_api_key.strip():
        os.environ["GOOGLE_API_KEY"] = cfg.google_api_key.strip()

    if cfg.gemini_model.strip():
        os.environ["GEMINI_MODEL"] = cfg.gemini_model.strip()
        root_agent.model = cfg.gemini_model.strip()

    if cfg.paypal_client_id.strip() and cfg.paypal_client_secret.strip():
        os.environ["PAYPAL_CLIENT_ID"] = cfg.paypal_client_id.strip()
        os.environ["PAYPAL_CLIENT_SECRET"] = cfg.paypal_client_secret.strip()
        paypal_sdk.configure_credentials(cfg.paypal_client_id, cfg.paypal_client_secret)

    if cfg.channel3_api_key.strip():
        os.environ["CHANNEL3_API_KEY"] = cfg.channel3_api_key.strip()

    if cfg.render_api_key.strip():
        os.environ["RENDER_API_KEY"] = cfg.render_api_key.strip()

    if cfg.render_workflow_slug.strip():
        os.environ["RENDER_WORKFLOW_SLUG"] = cfg.render_workflow_slug.strip()

    has_render_wf = _has_valid_key("RENDER_API_KEY") and RenderAsync is not None
    state["audit_log"].insert(0, {
        "timestamp": now_str(),
        "mandate_id": "SYS-CFG",
        "item": "Runtime Credentials Updated",
        "amount": 0.0,
        "status": "POLICY_SIGNED",
        "details": (
            f"Model: {root_agent.model} | Gemini Key: {'ACTIVE' if os.environ.get('GOOGLE_API_KEY') else 'MISSING'} | "
            f"Channel3: {'ACTIVE' if os.environ.get('CHANNEL3_API_KEY') else 'MISSING'} | "
            f"PayPal: {'LIVE SANDBOX' if paypal_sdk.is_configured else 'SIMULATED'} | "
            f"Render Workflows: {'DISTRIBUTED' if has_render_wf else 'LOCAL_FALLBACK'}"
        )
    })
    await broadcast_state()
    return {
        "status": "OK",
        "gemini_ready": bool(os.environ.get("GOOGLE_API_KEY")),
        "gemini_model": str(root_agent.model),
        "paypal_live_ready": paypal_sdk.is_configured,
        "channel3_ready": bool(os.environ.get("CHANNEL3_API_KEY")),
        "render_workflow_ready": has_render_wf,
    }


@app.get("/api/catalog/search")
async def search_live_channel3(q: str = "office chair"):
    """
    Consulta productos reales en Channel3 API y registra sus precios oficiales
    en TRUSTED_CATALOG para mantener la validación Anti-Alucinaciones del Shield.
    """
    c3_key = os.environ.get("CHANNEL3_API_KEY", "").strip()

    # 1. Si no hay API Key de Channel3 configurada, usa el catálogo semilla de respaldo
    if not c3_key or "tu_api_key" in c3_key:
        fallback_items = [
            {"sku": sku, "name": sku, "price": data["price"], "paypal_email": data["paypal_email"], "source": "LOCAL_FALLBACK"}
            for sku, data in TRUSTED_CATALOG.items()
        ]
        return {"mode": "FALLBACK_CATALOG", "products": fallback_items}

    # 2. Búsqueda real en el Product Graph de Channel3 (100M+ productos)
    try:
        client = AsyncChannel3Client(api_key=c3_key, timeout=15.0)
        response = await client.products.search(query=q, limit=5)

        # Soporta tanto respuesta directa (.products) como Pager (.items / .response.products)
        raw_products = getattr(response, "products", None) or getattr(response, "items", None)
        if not raw_products and hasattr(response, "response"):
            raw_products = getattr(response.response, "products", None)
        raw_products = raw_products or []

        live_products = []
        for prod in raw_products:
            # Extraer el precio real de la primera oferta disponible
            raw_price = None
            brand_list = getattr(prod, "brands", None) or []
            first_brand = getattr(brand_list[0], "name", None) if brand_list else None
            merchant_name = getattr(prod, "brand_name", None) or first_brand or "verified-retailer"

            if getattr(prod, "offers", None) and len(prod.offers) > 0:
                offer = prod.offers[0]
                # Soporta tanto offer.price numérico como objeto Price según versión del SDK
                raw_price = getattr(offer.price, "price", offer.price)
                merchant_name = (
                    getattr(offer, "merchant_name", None)
                    or getattr(offer, "domain", None)
                    or merchant_name
                )
            elif getattr(prod, "price", None):
                raw_price = getattr(prod.price, "price", prod.price)

            if not raw_price or float(raw_price) <= 0:
                continue

            price_usd = round(float(raw_price), 2)
            sku = str(prod.id)
            slug = re.sub(r"[^a-z0-9]+", "-", merchant_name.lower()).strip("-") or "merchant"
            sandbox_payee = f"{slug}@sandbox.paypal.com"

            images_list = getattr(prod, "images", None) or []
            first_image = getattr(images_list[0], "url", None) if images_list else None
            image_url = getattr(prod, "image_url", None) or first_image

            # CRÍTICO: Registramos la verdad oficial en memoria del Shield (Anti-Alucinación)
            TRUSTED_CATALOG[sku] = {
                "price": price_usd,
                "paypal_email": sandbox_payee
            }

            live_products.append({
                "sku": sku,
                "name": prod.title,
                "brand_or_merchant": merchant_name,
                "price": price_usd,
                "paypal_email": sandbox_payee,
                "image_url": image_url,
                "source": "LIVE_CHANNEL3_API"
            })

        return {"mode": "LIVE_CHANNEL3_API", "products": live_products}

    except Exception as e:
        return {"mode": "CHANNEL3_ERROR_FALLBACK", "error": str(e), "products": []}


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

    # 6. Liquidar en PayPal Sandbox vía Render Workflows (o ejecución local como fallback)
    workflow_engine_note = "LOCAL_INLINE"
    pp_settlement = None

    if _has_valid_key("RENDER_API_KEY") and RenderAsync is not None:
        workflow_slug = os.getenv("RENDER_WORKFLOW_SLUG", "paypal-shield-workflow").strip() or "paypal-shield-workflow"
        task_slug = f"{workflow_slug}/orchestrate_ap2_checkout_workflow"
        workflow_payload = {
            "mandate_id": req.mandate_id,
            "agent_id": req.agent_id,
            "parent_policy_hash": expected_hash,
            "sku": req.sku,
            "product_name": req.product_name,
            "total_amount": req.total_amount,
            "merchant_paypal_email": req.merchant_paypal_email,
            "agent_signature": req.agent_signature,
            "paypal_client_id": paypal_sdk.client_id,
            "paypal_client_secret": paypal_sdk.client_secret,
        }
        try:
            render_client = RenderAsync(token=os.environ.get("RENDER_API_KEY", "").strip())
            task_run = await render_client.workflows.run_task(task_slug, [workflow_payload])
            wf_result = task_run.results[0] if getattr(task_run, "results", None) else {}
            if not wf_result.get("authorized"):
                reason = wf_result.get("error", "RENDER_WORKFLOW_REJECTED")
                state["audit_log"].insert(0, {"timestamp": now_str(), "mandate_id": req.mandate_id, "item": req.product_name, "amount": req.total_amount, "status": "BLOCKED_BY_SHIELD", "details": reason})
                await broadcast_state()
                return {"authorized": False, "error": reason, "remaining_usd": p["remaining_usd"]}
            pp_settlement = wf_result.get("settlement")
            workflow_engine_note = f"RENDER_WORKFLOW ({task_run.id})"
        except Exception as wf_err:
            workflow_engine_note = f"LOCAL_FALLBACK (WF: {str(wf_err)[:36]})"

    if pp_settlement is None:
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
        "details": f"PayPal Order: {pp_tx_id} | Ed25519 Verified | {workflow_engine_note} | {pp_mode}"
    })
    await broadcast_state()
    return {
        "authorized": True,
        "paypal_tx_id": pp_tx_id,
        "paypal_mode": pp_mode,
        "workflow_engine": workflow_engine_note,
        "remaining_usd": p["remaining_usd"],
        "ap2_proof": expected_hash
    }


@app.post("/api/chat")
async def chat_endpoint(req: ChatRequest):
    """Ejecuta el agente de Google ADK y devuelve los trazos de herramientas + respuesta."""
    if not (_has_valid_key("GOOGLE_API_KEY") or _has_valid_key("GEMINI_API_KEY")):
        return {
            "reply": (
                "🔑 **API Key de Gemini no configurada**\n\n"
                "No se encontró una `GOOGLE_API_KEY` activa. Haz clic en el botón **🔑 API Keys** "
                "en la barra superior para ingresarla en caliente o agrégala en tu archivo `.env`."
            ),
            "tools": [],
        }

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

    try:
        async for event in adk_runner.run_async(
            user_id=USER_ID, session_id=req.session_id, new_message=user_msg
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
                    "⚠️ **Límite de tokens / cuota de Gemini alcanzado (HTTP 429)**\n\n"
                    "Se ha excedido el límite de peticiones o tokens por minuto de tu cuenta de Google Gemini API. "
                    "Por favor espera unos segundos antes de enviar otro mensaje o cambia tu `GOOGLE_API_KEY` en **🔑 API Keys**.\n\n"
                    f"`Detalle: {err_str}`"
                ),
                "tools": tools_called,
            }

        if any(
            k in err_lower
            for k in ("api_key_invalid", "api key not valid", "unauthenticated", "permission_denied", "missing key", "401", "403")
        ):
            return {
                "reply": (
                    "🔑 **API Key de Gemini inválida o sin permisos**\n\n"
                    "La llave `GOOGLE_API_KEY` configurada fue rechazada por Google Gemini API. "
                    "Verifica o actualiza tu llave desde el botón **🔑 API Keys**.\n\n"
                    f"`Detalle: {err_str}`"
                ),
                "tools": tools_called,
            }

        return {
            "reply": f"❌ **Error ejecutando el agente ADK:**\n\n`{err_str}`",
            "tools": tools_called,
        }

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