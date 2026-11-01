import hashlib
import base64
from cryptography.hazmat.primitives.asymmetric import ed25519
from cryptography.hazmat.primitives import serialization
from cryptography.exceptions import InvalidSignature


def _derive_ed25519_keypair(seed_phrase: str) -> tuple[ed25519.Ed25519PrivateKey, ed25519.Ed25519PublicKey]:
    """Generates a deterministic 32-byte Ed25519 keypair for the demo."""
    seed_32_bytes = hashlib.sha256(seed_phrase.encode("utf-8")).digest()
    private_key = ed25519.Ed25519PrivateKey.from_private_bytes(seed_32_bytes)
    public_key = private_key.public_key()
    return private_key, public_key


# Isolated cryptographic identities: CFO (AG Grid) vs Agent (Google ADK)
CFO_PRIVATE_KEY, CFO_PUBLIC_KEY = _derive_ed25519_keypair("AP2-CFO-GOVERNANCE-ROOT-KEY-2026")
AGENT_PRIVATE_KEY, AGENT_PUBLIC_KEY = _derive_ed25519_keypair("AP2-ADK-PROCUREMENT-AGENT-01-KEY")


def get_public_key_hex(pub_key: ed25519.Ed25519PublicKey) -> str:
    raw = pub_key.public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw
    )
    return raw.hex()


# =====================================================================
# 1. CFO MANDATE SIGNING & VERIFICATION (Intent / Policy Mandate)
# =====================================================================
def canonical_policy_bytes(policy_id: str, agent_id: str, max_budget_usd: float, allowed_category: str) -> bytes:
    """Builds the exact canonical byte representation of the AG Grid policy rule."""
    canonical_str = f"AP2_POLICY_V1|{policy_id}|{agent_id}|{float(max_budget_usd):.2f}|{allowed_category}"
    return canonical_str.encode("utf-8")


def sign_cfo_policy(policy_id: str, agent_id: str, max_budget_usd: float, allowed_category: str) -> str:
    """Signs the policy using the CFO's Ed25519 private key."""
    payload = canonical_policy_bytes(policy_id, agent_id, max_budget_usd, allowed_category)
    signature = CFO_PRIVATE_KEY.sign(payload)
    return base64.urlsafe_b64encode(signature).decode("utf-8")


def verify_cfo_policy(policy_id: str, agent_id: str, max_budget_usd: float, allowed_category: str, signature_b64: str) -> bool:
    """Verifies with the CFO's public key that the budget rule was not tampered with."""
    try:
        payload = canonical_policy_bytes(policy_id, agent_id, max_budget_usd, allowed_category)
        sig_bytes = base64.urlsafe_b64decode(signature_b64.encode("utf-8"))
        CFO_PUBLIC_KEY.verify(sig_bytes, payload)
        return True
    except (InvalidSignature, Exception):
        return False


def compute_policy_hash(policy_id: str, agent_id: str, max_budget_usd: float, allowed_category: str, cfo_signature: str) -> str:
    """Computes the SHA-256 digest of the policy mandate including the CFO's Ed25519 signature."""
    payload = canonical_policy_bytes(policy_id, agent_id, max_budget_usd, allowed_category).decode("utf-8")
    full_record = f"{payload}|SIG:{cfo_signature}"
    return hashlib.sha256(full_record.encode("utf-8")).hexdigest()


# =====================================================================
# 2. CHECKOUT MANDATE SIGNING & VERIFICATION (ADK Checkout Mandate)
# =====================================================================
def canonical_checkout_bytes(
    mandate_id: str,
    agent_id: str,
    parent_policy_hash: str,
    sku: str,
    total_amount: float,
    merchant_paypal_email: str
) -> bytes:
    """Builds the canonical checkout message signed by the Google ADK Agent."""
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
    """The Google ADK agent signs the checkout cart with its Ed25519 private key."""
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
    """PayPal Agent Shield verifies with the agent's public key that the checkout mandate is authentic and intact."""
    try:
        payload = canonical_checkout_bytes(
            mandate_id, agent_id, parent_policy_hash, sku, total_amount, merchant_paypal_email
        )
        sig_bytes = base64.urlsafe_b64decode(signature_b64.encode("utf-8"))
        AGENT_PUBLIC_KEY.verify(sig_bytes, payload)
        return True
    except (InvalidSignature, Exception):
        return False