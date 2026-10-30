import os
import sys
from pathlib import Path
import uuid
import httpx
from dotenv import load_dotenv
from google.adk.agents import Agent

load_dotenv()
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.8-flash").strip() or "gemini-3.8-flash"

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from ap2_crypto import sign_agent_checkout

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
            "status": "SHIELD_BLOCKED",
            "mandate_id": mandate_id,
            "ed25519_signature_sent": real_signature[:24] + "...",
            "shield_error": result.get("error"),
            "ag_grid_remaining_usd": result.get("remaining_usd")
        }

    return {
        "status": "PAYPAL_COMPLETED",
        "mandate_id": mandate_id,
        "ed25519_signature_verified": real_signature[:24] + "...",
        "paypal_transaction_id": result.get("paypal_tx_id"),
        "paypal_mode": result.get("paypal_mode"),
        "render_workflow_engine": result.get("workflow_engine", "LOCAL_INLINE"),
        "ap2_cryptographic_proof": result.get("ap2_proof")[:20] + "...",
        "ag_grid_remaining_usd": result.get("remaining_usd")
    }


root_agent = Agent(
    name="paypal_ap2_procurement_agent",
    model=GEMINI_MODEL,
    description="Agente de compras autónomo gobernado por criptografía Ed25519 (AP2), AG Grid y PayPal Agent Shield.",
    instruction="""
    Eres el Agente de Compras Autónomo corporativo operando con Google ADK, el protocolo criptográfico AP2 (Ed25519) y PayPal Agent Shield.
    Responde de forma concisa, ejecutiva y bien estructurada.

    FLUJO DE TRABAJO:
    1. Si te piden ver el presupuesto o catálogo, usa `get_ag_grid_policy_state` o `search_catalog_channel3`.
    2. PROHIBIDO INVENTAR PRODUCTOS O SKUs: Muestra únicamente los productos devueltos por `search_catalog_channel3` incluyendo siempre su `sku`, `price` y `paypal_email` exactos. Si `search_catalog_channel3` devuelve una lista vacía o un error, infórmalo claramente al usuario y NO inventes productos por tu cuenta.
    3. Cuando te pidan comprar un producto, usa exactamente el `sku`, `name`, `price` y `paypal_email` que devolvió `search_catalog_channel3` (vuelve a llamar a `search_catalog_channel3` si no tienes esos datos exactos en la conversación) y ejecuta `execute_ap2_checkout`.
    4. Si el usuario pide explícitamente simular un ataque criptográfico, adulteración o firma inválida, pasa `simulate_tampering=True` a `execute_ap2_checkout`.
    5. Si el usuario pide explícitamente simular una alucinación de precio o SKU (o cambiar el precio manualmente a otro valor), pasa ese valor alterado con `simulate_tampering=False` para demostrar cómo la validación Ground-Truth del Shield lo detiene.
    6. Resume siempre: ID del mandato AP2, estado de la firma Ed25519, veredicto del Shield / ID de PayPal y saldo restante en AG Grid.
    """,
    tools=[
        search_catalog_channel3,
        get_ag_grid_policy_state,
        execute_ap2_checkout
    ]
)