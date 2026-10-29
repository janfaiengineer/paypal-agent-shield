import os
from dotenv import load_dotenv
from render import Workflows, TaskContext, Retry

from ap2_crypto import verify_agent_checkout
from paypal_apimatic_client import PayPalAPIMaticProcessor

load_dotenv()

# Inicialización del motor distribuido Render Workflows
app = Workflows(
    default_retry=Retry(
        max_retries=2,
        wait_duration_ms=1000,
        backoff_scaling=1.5,
    ),
    default_timeout=120,
    default_plan="flex",
)


@app.task(name="verify_ap2_mandate_task")
def verify_ap2_mandate_task(ctx: TaskContext, payload: dict) -> dict:
    """
    Tarea distribuida 1: Verifica la firma criptográfica Ed25519 del Checkout Mandate AP2
    en una instancia aislada de Render Workflows.
    """
    is_valid = verify_agent_checkout(
        mandate_id=payload["mandate_id"],
        agent_id=payload["agent_id"],
        parent_policy_hash=payload["parent_policy_hash"],
        sku=payload["sku"],
        total_amount=float(payload["total_amount"]),
        merchant_paypal_email=payload["merchant_paypal_email"],
        signature_b64=payload["agent_signature"],
    )
    return {
        "ed25519_valid": is_valid,
        "mandate_id": payload["mandate_id"],
    }


@app.task(name="settle_paypal_sandbox_task")
def settle_paypal_sandbox_task(ctx: TaskContext, payload: dict) -> dict:
    """
    Tarea distribuida 2: Liquida el mandato AP2 en PayPal Sandbox usando el SDK de APIMatic.
    """
    processor = PayPalAPIMaticProcessor()
    if payload.get("paypal_client_id") and payload.get("paypal_client_secret"):
        processor.configure_credentials(
            payload["paypal_client_id"],
            payload["paypal_client_secret"],
        )

    return processor.execute_ap2_settlement(
        mandate_id=payload["mandate_id"],
        parent_policy_hash=payload["parent_policy_hash"],
        product_name=payload["product_name"],
        amount_usd=float(payload["total_amount"]),
        merchant_paypal_email=payload["merchant_paypal_email"],
    )


@app.task(name="orchestrate_ap2_checkout_workflow")
async def orchestrate_ap2_checkout_workflow(ctx: TaskContext, payload: dict) -> dict:
    """
    Workflow principal en Render Workflows:
    Encadena (chaining) la verificación criptográfica Ed25519 y la liquidación en PayPal Sandbox.
    """
    crypto_check = await ctx.run(verify_ap2_mandate_task, payload)
    if not crypto_check.get("ed25519_valid"):
        return {
            "authorized": False,
            "error": "ED25519_INVALID_SIGNATURE: Firma rechazada por Render Workflow Node.",
        }

    settlement = await ctx.run(settle_paypal_sandbox_task, payload)
    return {
        "authorized": True,
        "settlement": settlement,
    }


if __name__ == "__main__":
    app.start()
