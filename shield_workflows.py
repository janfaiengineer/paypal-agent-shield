import os
from dotenv import load_dotenv
from render import Workflows, TaskContext, Retry

from ap2_crypto import verify_agent_checkout
from paypal_apimatic_client import PayPalAPIMaticProcessor

load_dotenv()

# Initialize the distributed Render Workflows engine
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
    Distributed Task 1: Verifies the Ed25519 cryptographic signature of the AP2 Checkout Mandate
    in an isolated Render Workflows execution node.
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
    Distributed Task 2: Settles the verified AP2 mandate on PayPal Sandbox using the APIMatic SDK.
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
    Primary Render Workflow:
    Chains Ed25519 cryptographic verification and PayPal Sandbox settlement.
    """
    crypto_check = await ctx.run(verify_ap2_mandate_task, payload)
    if not crypto_check.get("ed25519_valid"):
        return {
            "authorized": False,
            "error": "ED25519_INVALID_SIGNATURE: Signature rejected by Render Workflow Node.",
        }

    settlement = await ctx.run(settle_paypal_sandbox_task, payload)
    return {
        "authorized": True,
        "settlement": settlement,
    }


if __name__ == "__main__":
    app.start()
