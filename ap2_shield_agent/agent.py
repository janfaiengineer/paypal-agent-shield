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
    """Detecta el puerto pasado por CLI a uvicorn (--port XXXX) si existe."""
    for i, arg in enumerate(sys.argv):
        if arg == "--port" and i + 1 < len(sys.argv):
            return sys.argv[i + 1].strip()
        if arg.startswith("--port="):
            return arg.split("=", 1)[1].strip()
    return ""


def _get_shield_base_url() -> str:
    """Resuelve dinámicamente la URL del servidor Shield tanto en local como en Render."""
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
    """Devuelve la URL principal seguida de puertos locales de respaldo (8000, 8001)."""
    primary = _get_shield_base_url()
    candidates = [primary]
    for fallback_port in ("8000", "8001"):
        url = f"http://127.0.0.1:{fallback_port}"
        if url not in candidates:
            candidates.append(url)
    return candidates


async def _shield_request(method: str, path: str, timeout: float = 20.0, **kwargs) -> httpx.Response:
    """Realiza la petición al servidor Shield probando puertos locales alternativos si hay ConnectError."""
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


async def search_catalog_channel3(query: str) -> dict:
    """
    Busca productos reales en tiempo real usando la API de Channel3 (100M+ productos).

    Args:
        query: Producto a buscar en inglés o español (ej. 'ergonomic office chair', '4k monitor', 'mechanical keyboard').
    """
    res = await _shield_request("GET", "/api/catalog/search", timeout=20.0, params={"q": query})
    res.raise_for_status()
    return res.json()


async def get_ag_grid_policy_state() -> dict:
    """
    Consulta en tiempo real el servidor de PayPal Agent Shield para obtener el presupuesto disponible
    en AG Grid, las llaves públicas Ed25519 y el Hash criptográfico AP2 activo del CFO.
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
    Construye el Checkout Mandate AP2, lo firma criptográficamente con la llave privada Ed25519
    del agente y lo envía a PayPal Agent Shield para su verificación y liquidación en PayPal.

    Args:
        sku: SKU exacto del producto a comprar.
        product_name: Nombre del producto.
        price: Precio total en USD.
        merchant_paypal_email: Correo de PayPal del comercio.
        simulate_tampering: Si es True, altera el precio después de firmar con Ed25519 para demostrar cómo el Shield detecta ataques Man-in-the-Middle.
    """
    state_res = await _shield_request("GET", "/api/state", timeout=35.0)
    policy = state_res.json()["policy"]

    mandate_id = f"ap2_chk_{uuid.uuid4().hex[:8]}"
    agent_id = "procurement-01"
    parent_hash = policy["ap2_policy_hash"]

    # 1. Firma criptográfica Ed25519 generada por el Agente ADK
    real_signature = sign_agent_checkout(
        mandate_id=mandate_id,
        agent_id=agent_id,
        parent_policy_hash=parent_hash,
        sku=sku,
        total_amount=price,
        merchant_paypal_email=merchant_paypal_email
    )

    # Si simulamos ataque, corrompemos el monto en tránsito tras haber firmado
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

    # 2. Llamada asíncrona al Firewall PayPal Agent Shield
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
    Consulta el estado en vivo del Bryntum TaskBoard (tarjetas en cuarentena HITL, órdenes liquidadas
    y amenazas bloqueadas) junto con la telemetría del grafo de Google ADK 2.0 Workflow.
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
    Reanuda un mandato en cuarentena HITL (Human-in-the-Loop) en el Bryntum TaskBoard y el grafo ADK 2.0.
    Si target_column es 'PAYPAL_SETTLED', re-firma la política Ed25519 del CFO ampliando el presupuesto
    y liquida la orden en PayPal Sandbox. Si es 'BLOCKED_THREAT', rechaza definitivamente el mandato.

    Args:
        mandate_id: ID del mandato en cuarentena (ej. 'ap2_chk_...').
        target_column: Columna destino en Bryntum TaskBoard ('PAYPAL_SETTLED' o 'BLOCKED_THREAT').
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
    Nodo 1 del Grafo ADK 2.0: Inspecciona Gate 1 (Firma Ed25519 CFO) y Gate 2 (Firma Ed25519 Agente).
    Enruta ataques Man-in-the-Middle hacia `adk_node_threat_sink`.
    """
    raw_text = "".join(p.text or "" for p in node_input.parts) if node_input and node_input.parts else "{}"
    payload = json.loads(raw_text)
    visited = list(payload.get("visited_nodes", []))
    visited.append("adk_node_crypto_gate")
    payload["visited_nodes"] = visited

    # Gate 1: Verificar firma Ed25519 de la política CFO
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
        payload["error"] = "CRYPTO_ERROR: Firma Ed25519 del CFO inválida."
        payload["adk_graph_route"] = "route_threat_sink"
        return Event(output=payload, route="route_threat_sink", state={"last_node": ctx.node_path})

    # Gate 2: Verificar firma Ed25519 del Agente (Anti-MitM)
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
        payload["error"] = "ED25519_INVALID_SIGNATURE: Adulteración detectada en tránsito (Firma no coincide con el payload)."
        payload["adk_graph_route"] = "route_threat_sink"
        return Event(output=payload, route="route_threat_sink", state={"last_node": ctx.node_path})

    return Event(output=payload, route="route_ground_truth", state={"last_node": ctx.node_path})


@node
async def adk_node_channel3_ground_truth(ctx: Context, node_input: dict[str, Any]) -> Event:
    """
    Nodo 2 del Grafo ADK 2.0: Inspecciona Gate 3 (Ground-Truth de SKU y precio contra Channel3).
    Enruta alucinaciones del LLM hacia `adk_node_threat_sink`.
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
        payload["error"] = f"HALLUCINATION_BLOCKED: El SKU '{sku}' no existe en Channel3."
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
            f"GROUND_TRUTH_MISMATCH: El agente envió ${payload['total_amount']:.2f}, "
            f"pero el precio oficial de {sku} es ${trusted_item['price']:.2f}."
        )
        payload["adk_graph_route"] = "route_threat_sink"
        return Event(output=payload, route="route_threat_sink", state={"last_node": ctx.node_path})

    return Event(output=payload, route="route_policy_and_budget", state={"last_node": ctx.node_path})


@node
async def adk_node_policy_budget_gate(ctx: Context, node_input: dict[str, Any]) -> Event:
    """
    Nodo 3 del Grafo ADK 2.0: Inspecciona Gate 4 (Hash AP2) y Gate 5 (Saldo en AG Grid).
    Si el carrito supera el presupuesto disponible, enruta a `adk_node_cfo_hitl_quarantine`
    para colocar la tarjeta en cuarentena interactiva en Bryntum TaskBoard.
    """
    payload = dict(node_input)
    visited = list(payload.get("visited_nodes", []))
    visited.append("adk_node_policy_budget_gate")
    payload["visited_nodes"] = visited

    if payload["parent_policy_hash"] != payload["expected_policy_hash"]:
        payload["verdict_status"] = "BLOCKED_BY_SHIELD"
        payload["bryntum_column"] = "BLOCKED_THREAT"
        payload["threat_category"] = "AP2_LINEAGE_MISMATCH"
        payload["error"] = "AP2_HASH_MISMATCH: La política del CFO cambió antes de liquidar."
        payload["adk_graph_route"] = "route_threat_sink"
        return Event(output=payload, route="route_threat_sink", state={"last_node": ctx.node_path})

    if payload["total_amount"] > payload["remaining_usd"]:
        shortfall = round(payload["total_amount"] - payload["remaining_usd"], 2)
        payload["shortfall_usd"] = shortfall
        payload["verdict_status"] = "BLOCKED_BY_SHIELD"
        payload["bryntum_column"] = "QUARANTINED"
        payload["threat_category"] = "CFO_HITL_BUDGET_QUARANTINE"
        payload["error"] = (
            f"BUDGET_EXCEEDED: Carrito ${payload['total_amount']:.2f} USD > "
            f"Disponible en AG Grid ${payload['remaining_usd']:.2f} USD "
            f"(En cuarentena HITL en Bryntum TaskBoard — Déficit: +${shortfall:.2f} USD)"
        )
        payload["adk_graph_route"] = "route_cfo_hitl_quarantine"
        return Event(output=payload, route="route_cfo_hitl_quarantine", state={"last_node": ctx.node_path})

    payload["adk_graph_route"] = "route_paypal_settlement"
    return Event(output=payload, route="route_paypal_settlement", state={"last_node": ctx.node_path})


@node
async def adk_node_cfo_hitl_quarantine(ctx: Context, node_input: dict[str, Any]) -> Event:
    """
    Nodo 4A (HITL Quarantine): Pausa el mandato de compra en la columna `QUARANTINED`
    del Bryntum TaskBoard esperando que el CFO arrastre la tarjeta para re-firmar y liquidar.
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
    Nodo 4B (Threat Sink): Bloquea permanentemente ataques criptográficos (MitM) o alucinaciones de LLM
    en la columna `BLOCKED_THREAT` del Bryntum TaskBoard.
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
    Nodo 4C (PayPal Settlement): Autoriza el mandato verificado por las 5 compuertas para
    su liquidación en PayPal Sandbox (vía Render Workflows / APIMatic SDK) y mueve la tarjeta
    a `PAYPAL_SETTLED` en el Bryntum TaskBoard.
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
        "Grafo determinista de Google ADK 2.0 que conecta la inspección criptográfica de 5 compuertas "
        "con el tablero interactivo Bryntum TaskBoard (HITL Quarantine, Threat Sink y PayPal Settlement)."
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
    Ejecuta el grafo `ap2_checkout_graph` de Google ADK 2.0 y devuelve el veredicto estructurado,
    la ruta condicional tomada y la traza exacta de nodos recorridos.
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
    description="Agente de compras autónomo gobernado por Google ADK 2.0 Graph Workflows, criptografía Ed25519 (AP2), AG Grid, Bryntum TaskBoard y PayPal Agent Shield.",
    instruction="""
    Eres el Agente de Compras Autónomo corporativo operando con Google ADK 2.0 (Graph Workflows + Agent), el protocolo criptográfico AP2 (Ed25519), AG Grid, Bryntum TaskBoard y PayPal Agent Shield.
    Responde de forma concisa, ejecutiva y bien estructurada.

    FLUJO DE TRABAJO:
    1. Si te piden ver el presupuesto, el catálogo o el estado del Bryntum TaskBoard / Grafo ADK, usa `get_ag_grid_policy_state`, `search_catalog_channel3` o `get_bryntum_taskboard_and_graph_state`.
    2. PROHIBIDO INVENTAR PRODUCTOS O SKUs: Muestra únicamente los productos devueltos por `search_catalog_channel3` incluyendo siempre su `sku`, `price` y `paypal_email` exactos. Si `search_catalog_channel3` devuelve una lista vacía o un error, infórmalo claramente al usuario y NO inventes productos por tu cuenta.
    3. Cuando te pidan comprar un producto, usa exactamente el `sku`, `name`, `price` y `paypal_email` que devolvió `search_catalog_channel3` (vuelve a llamar a `search_catalog_channel3` si no tienes esos datos exactos en la conversación) y ejecuta `execute_ap2_checkout`.
    4. Si el usuario pide explícitamente simular un ataque criptográfico, adulteración o firma inválida, pasa `simulate_tampering=True` a `execute_ap2_checkout`.
    5. Si el usuario pide explícitamente simular una alucinación de precio o SKU (o cambiar el precio manualmente a otro valor), pasa ese valor alterado con `simulate_tampering=False` para demostrar cómo la validación Ground-Truth del Shield lo detiene.
    6. Si una compra excede el presupuesto (`hitl_quarantined=True`), explica que el grafo de ADK (`ap2_zero_trust_checkout_graph`) pausó la orden en el nodo `adk_node_cfo_hitl_quarantine` y colocó la tarjeta en la columna `⏳ CFO Quarantine (HITL)` del **Bryntum TaskBoard**, donde el CFO puede arrastrarla a `💳 PayPal Sandbox Settled` para auto-firmar el presupuesto Ed25519 y liquidarla en PayPal (o pedirte aprobarla con `resolve_quarantined_mandate_hitl`).
    7. Resume siempre: ID del mandato AP2, nodos recorridos en el Grafo ADK (`adk_graph_visited_nodes`), columna en Bryntum TaskBoard (`bryntum_taskboard_column`), veredicto del Shield / ID de PayPal y saldo restante en AG Grid.
    """,
    tools=[
        search_catalog_channel3,
        get_ag_grid_policy_state,
        execute_ap2_checkout,
        get_bryntum_taskboard_and_graph_state,
        resolve_quarantined_mandate_hitl,
    ]
)