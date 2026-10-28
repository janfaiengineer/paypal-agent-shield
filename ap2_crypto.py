import hashlib
import base64
from cryptography.hazmat.primitives.asymmetric import ed25519
from cryptography.hazmat.primitives import serialization
from cryptography.exceptions import InvalidSignature


def _derive_ed25519_keypair(seed_phrase: str) -> tuple[ed25519.Ed25519PrivateKey, ed25519.Ed25519PublicKey]:
    """Genera un par de llaves Ed25519 determinista de 32 bytes para la demo."""
    seed_32_bytes = hashlib.sha256(seed_phrase.encode("utf-8")).digest()
    private_key = ed25519.Ed25519PrivateKey.from_private_bytes(seed_32_bytes)
    public_key = private_key.public_key()
    return private_key, public_key


# Identidades criptográficas separadas: CFO (AG Grid) vs Agente (Google ADK)
CFO_PRIVATE_KEY, CFO_PUBLIC_KEY = _derive_ed25519_keypair("AP2-CFO-GOVERNANCE-ROOT-KEY-2026")
AGENT_PRIVATE_KEY, AGENT_PUBLIC_KEY = _derive_ed25519_keypair("AP2-ADK-PROCUREMENT-AGENT-01-KEY")


def get_public_key_hex(pub_key: ed25519.Ed25519PublicKey) -> str:
    raw = pub_key.public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw
    )
    return raw.hex()


# =====================================================================
# 1. FIRMA Y VERIFICACIÓN DEL MANDATO DEL CFO (Intent / Policy Mandate)
# =====================================================================
def canonical_policy_bytes(policy_id: str, agent_id: str, max_budget_usd: float, allowed_category: str) -> bytes:
    """Construye la representación canónica exacta de la regla de AG Grid."""
    canonical_str = f"AP2_POLICY_V1|{policy_id}|{agent_id}|{float(max_budget_usd):.2f}|{allowed_category}"
    return canonical_str.encode("utf-8")


def sign_cfo_policy(policy_id: str, agent_id: str, max_budget_usd: float, allowed_category: str) -> str:
    """Firma la política usando la llave privada Ed25519 del CFO."""
    payload = canonical_policy_bytes(policy_id, agent_id, max_budget_usd, allowed_category)
    signature = CFO_PRIVATE_KEY.sign(payload)
    return base64.urlsafe_b64encode(signature).decode("utf-8")


def verify_cfo_policy(policy_id: str, agent_id: str, max_budget_usd: float, allowed_category: str, signature_b64: str) -> bool:
    """Verifica con la llave pública del CFO que el presupuesto no fue alterado."""
    try:
        payload = canonical_policy_bytes(policy_id, agent_id, max_budget_usd, allowed_category)
        sig_bytes = base64.urlsafe_b64decode(signature_b64.encode("utf-8"))
        CFO_PUBLIC_KEY.verify(sig_bytes, payload)
        return True
    except (InvalidSignature, Exception):
        return False


def compute_policy_hash(policy_id: str, agent_id: str, max_budget_usd: float, allowed_category: str, cfo_signature: str) -> str:
    """Calcula el SHA-256 del mandato incluyendo la firma Ed25519 del CFO."""
    payload = canonical_policy_bytes(policy_id, agent_id, max_budget_usd, allowed_category).decode("utf-8")
    full_record = f"{payload}|SIG:{cfo_signature}"
    return hashlib.sha256(full_record.encode("utf-8")).hexdigest()


# =====================================================================
# 2. FIRMA Y VERIFICACIÓN DEL MANDATO DE COMPRA (ADK Checkout Mandate)
# =====================================================================
def canonical_checkout_bytes(
    mandate_id: str,
    agent_id: str,
    parent_policy_hash: str,
    sku: str,
    total_amount: float,
    merchant_paypal_email: str
) -> bytes:
    """Construye el mensaje canónico que firma el Agente de Google ADK."""
    canonical_str = (
        f"AP2_CHECKOUT_V1|{mandate_id}|{agent_id}|{parent_policy_hash}|"
        f"{sku}|{float(total_amount):.2f}|{merchant_paypal_email}"
    )
    return canonical_str.encode("utf-8")


def sign_agent_checkout(
    mandate_id: str,
    agent_id: str,
    parent_policy_hash: str,
    sku: str,
    total_amount: float,
    merchant_paypal_email: str
) -> str:
    """El agente de Google ADK firma el carrito con su llave privada Ed25519."""
    payload = canonical_checkout_bytes(
        mandate_id, agent_id, parent_policy_hash, sku, total_amount, merchant_paypal_email
    )
    signature = AGENT_PRIVATE_KEY.sign(payload)
    return base64.urlsafe_b64encode(signature).decode("utf-8")


def verify_agent_checkout(
    mandate_id: str,
    agent_id: str,
    parent_policy_hash: str,
    sku: str,
    total_amount: float,
    merchant_paypal_email: str,
    signature_b64: str
) -> bool:
    """PayPal Agent Shield verifica con la llave pública del agente que el mandato es auténtico e íntegro."""
    try:
        payload = canonical_checkout_bytes(
            mandate_id, agent_id, parent_policy_hash, sku, total_amount, merchant_paypal_email
        )
        sig_bytes = base64.urlsafe_b64decode(signature_b64.encode("utf-8"))
        AGENT_PUBLIC_KEY.verify(sig_bytes, payload)
        return True
    except (InvalidSignature, Exception):
        return False