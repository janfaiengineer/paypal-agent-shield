import os
import json
import uuid
from dotenv import load_dotenv

from paypalserversdk.http.auth.o_auth_2 import ClientCredentialsAuthCredentials
from paypalserversdk.logging.configuration.api_logging_configuration import (
    LoggingConfiguration,
    RequestLoggingConfiguration,
    ResponseLoggingConfiguration,
)
from paypalserversdk.paypal_serversdk_client import PaypalServersdkClient
from paypalserversdk.configuration import Environment
from paypalserversdk.models.order_request import OrderRequest
from paypalserversdk.models.checkout_payment_intent import CheckoutPaymentIntent
from paypalserversdk.models.purchase_unit_request import PurchaseUnitRequest
from paypalserversdk.models.amount_with_breakdown import AmountWithBreakdown
from paypalserversdk.api_helper import APIHelper

load_dotenv()


class PayPalAPIMaticProcessor:
    """
    Cliente oficial de PayPal generado con APIMatic para liquidar mandatos AP2.
    """

    def __init__(self):
        self.client_id = os.getenv("PAYPAL_CLIENT_ID", "")
        self.client_secret = os.getenv("PAYPAL_CLIENT_SECRET", "")
        self.is_configured = bool(
            self.client_id
            and self.client_secret
            and "tu_paypal" not in self.client_id
        )

        self.client = None
        if self.is_configured:
            self.client = PaypalServersdkClient(
                client_credentials_auth_credentials=ClientCredentialsAuthCredentials(
                    o_auth_client_id=self.client_id,
                    o_auth_client_secret=self.client_secret,
                ),
                environment=Environment.SANDBOX,
            )

    def configure_credentials(self, client_id: str, client_secret: str):
        """Permite actualizar las credenciales de PayPal Sandbox en caliente desde la GUI."""
        self.client_id = client_id.strip()
        self.client_secret = client_secret.strip()
        self.is_configured = bool(self.client_id and self.client_secret)
        if self.is_configured:
            self.client = PaypalServersdkClient(
                client_credentials_auth_credentials=ClientCredentialsAuthCredentials(
                    o_auth_client_id=self.client_id,
                    o_auth_client_secret=self.client_secret,
                ),
                environment=Environment.SANDBOX,
            )

    def execute_ap2_settlement(
        self,
        mandate_id: str,
        parent_policy_hash: str,
        product_name: str,
        amount_usd: float,
        merchant_paypal_email: str,
    ) -> dict:
        """
        Construye el OrderRequest tipado con APIMatic y lo envía a PayPal Sandbox.
        Estampa el Hash Criptográfico de AP2 directamente en el registro de PayPal.
        """
        # Si aún no pegas tus llaves de Sandbox, hace fallback limpio para no romper la demo
        if not self.is_configured:
            return {
                "mode": "SANDBOX_SIMULATED (Faltan llaves en .env)",
                "paypal_order_id": f"SIM-PP-{uuid.uuid4().hex[:8].upper()}",
                "status": "COMPLETED",
            }

        orders_controller = self.client.orders

        # 1. Mapeo determinista de AP2 -> Modelos de APIMatic (PayPal Orders v2)
        order_body = OrderRequest(
            intent=CheckoutPaymentIntent.CAPTURE,
            purchase_units=[
                PurchaseUnitRequest(
                    reference_id=mandate_id,
                    # Estampamos la prueba criptográfica AP2 dentro de la transacción de PayPal:
                    custom_id=f"AP2_POLICY:{parent_policy_hash[:24]}",
                    invoice_id=f"AP2-INV-{mandate_id.upper()}",
                    description=f"AP2 Agent Purchase: {product_name}",
                    amount=AmountWithBreakdown(
                        currency_code="USD",
                        value=f"{amount_usd:.2f}",
                    ),
                )
            ],
        )

        # 2. Llamada real a los servidores de PayPal Sandbox vía APIMatic SDK
        response = orders_controller.create_order(
            {
                "body": order_body,
                "paypal_request_id": mandate_id,  # Idempotencia nativa en PayPal
                "prefer": "return=representation",
            }
        )

        result_data = json.loads(APIHelper.json_serialize(response.body))
        paypal_order_id = result_data.get("id")
        paypal_status = result_data.get("status", "CREATED")

        return {
            "mode": "LIVE_PAYPAL_SANDBOX_APIMATIC",
            "paypal_order_id": paypal_order_id,
            "status": paypal_status,
            "ap2_custom_id_stamped": f"AP2_POLICY:{parent_policy_hash[:24]}",
        }