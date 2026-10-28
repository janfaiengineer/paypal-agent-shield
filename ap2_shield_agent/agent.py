import sys
from pathlib import Path
import uuid
import httpx
from google.adk.agents import Agent

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from ap2_crypto import sign_agent_checkout

SHIELD_BASE_URL = "http://localhost:8001"


def search_catalog_channel3(query: str) -> dict:
    """
    Busca productos disponibles en el catálogo de comercio electrónico verificado (vía Channel3).

    Args:
        query: Palabra clave del producto a buscar (ej. 'silla', 'monitor', 'laptop', 'teclado', 'todo').
    """
    catalog = [
        {"sku": "CHAIR-ERG-01", "name": "Silla de Oficina Ergonómica", "price": 120.00, "merchant_id": "m_office_01", "paypal_email": "office-supply@sandbox.paypal.com"},
        {"sku": "KEYB-MECH-02", "name": "Teclado Mecánico Inalámbrico", "price": 65.00, "merchant_id": "m_tech_01", "paypal_email": "peripherals@sandbox.paypal.com"},
        {"sku": "MON-4K-27", "name": "Monitor 4K 27 Pulgadas", "price": 150.00, "merchant_id": "m_tech_02", "paypal_email": "monitors-direct@sandbox.paypal.com"},
        {"sku": "LAP-PRO-16", "name": "Laptop Developer 16GB RAM", "price": 799.00, "merchant_id": "m_tech_02", "paypal_email": "monitors-direct@sandbox.paypal.com"}
    ]
    q = query.lower().strip()
    if q in ["todo", "todos", "catalogo", "catálogo", ""]:
        return {"catalog_results": catalog}
    filtered = [item for item in catalog if q in item["name"].lower() or q in item["sku"].lower()]
    return {"catalog_results": filtered if filtered else catalog}


async def get_ag_grid_policy_state() -> dict:
    """
    Consulta en tiempo real el servidor de PayPal Agent Shield para obtener el presupuesto disponible
    en AG Grid, las llaves públicas Ed25519 y el Hash criptográfico AP2 activo del CFO.
    """
    async with httpx.AsyncClient(timeout=5.0) as client:
        res = await client.get(f"{SHIELD_BASE_URL}/api/state")
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
    async with httpx.AsyncClient(timeout=20.0) as client:
        state_res = await client.get(f"{SHIELD_BASE_URL}/api/state")
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
        chk_res = await client.post(f"{SHIELD_BASE_URL}/api/checkout", json=checkout_payload)
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
            "ap2_cryptographic_proof": result.get("ap2_proof")[:20] + "...",
            "ag_grid_remaining_usd": result.get("remaining_usd")
        }


root_agent = Agent(
    name="paypal_ap2_procurement_agent",
    model="gemini-3.5-flash",
    description="Agente de compras autónomo gobernado por criptografía Ed25519 (AP2), AG Grid y PayPal Agent Shield.",
    instruction="""
    Eres el Agente de Compras Autónomo corporativo operando con Google ADK, el protocolo criptográfico AP2 (Ed25519) y PayPal Agent Shield.
    Responde de forma concisa, ejecutiva y bien estructurada.

    FLUJO DE TRABAJO:
    1. Si te piden ver el presupuesto o catálogo, usa `get_ag_grid_policy_state` o `search_catalog_channel3`.
    2. Cuando te pidan comprar un producto, busca sus datos exactos en `search_catalog_channel3` si no los tienes, y ejecuta inmediatamente `execute_ap2_checkout`.
    3. Si el usuario pide simular un ataque criptográfico, adulteración o firma inválida, pasa `simulate_tampering=True` a `execute_ap2_checkout`.
    4. Si el usuario pide simular una alucinación de precio o cambiar el precio manualmente a otro valor, pasa ese precio alterado con `simulate_tampering=False` para demostrar cómo la validación Ground-Truth del Shield lo detiene.
    5. Resume siempre: ID del mandato AP2, estado de la firma Ed25519, veredicto del Shield / ID de PayPal y saldo restante en AG Grid.
    """,
    tools=[
        search_catalog_channel3,
        get_ag_grid_policy_state,
        execute_ap2_checkout
    ]
)