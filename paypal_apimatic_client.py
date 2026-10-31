import os
import json
import uuid
import logging
from dotenv import load_dotenv

from apimatic_core.exceptions.auth_validation_exception import AuthValidationException
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
from paypalserversdk.exceptions.api_exception import ApiException
from paypalserversdk.exceptions.error_exception import ErrorException
from paypalserversdk.api_helper import APIHelper

load_dotenv()

logger = logging.getLogger("paypal_agent_shield.apimatic")


def _build_logging_config() -> LoggingConfiguration:
    """
    Configuración de logging de APIMatic siguiendo el skill `python-configuration-resilience`:
    RequestLoggingConfiguration y ResponseLoggingConfiguration se pasan como campos de
    LoggingConfiguration con `mask_sensitive_headers=True` para proteger tokens OAuth 2.0.
    """
    return LoggingConfiguration(
        logger=logger,
        mask_sensitive_headers=True,
        request_logging_config=RequestLoggingConfiguration(
            log_body=False,
            log_headers=True,
        ),
        response_logging_config=ResponseLoggingConfiguration(
            log_headers=True,
        ),
    )


class PayPalAPIMaticProcessor:
    """
    Cliente oficial de PayPal generado con APIMatic (`paypal-server-sdk` v2.4.0)
    construido siguiendo los 8 skills del APIMatic Context Plugin for PayPal
    (`paypaldev/server-sdk-context-plugin-preview`):
      - `python-getting-started` & `python-client-initialization`
      - `python-authentication` (ClientCredentialsAuthCredentials + clone_with)
      - `python-calling-endpoints` (OrdersController property + Shape-2 options dict + ApiResponse.body)
      - `python-models` (OrderRequest, PurchaseUnitRequest, AmountWithBreakdown & APIHelper.SKIP safe reads)
      - `python-error-handling` (AuthValidationException, ErrorException, ApiException con getattr guard)
      - `python-configuration-resilience` (timeout=30, max_retries=0 bajo Render Workflows, LoggingConfiguration)
    """

    def __init__(self):
        # Soportamos tanto PAYPAL_CLIENT_ID como el nombre nativo O_AUTH_CLIENT_ID del SDK de APIMatic
        self.client_id = (
            os.getenv("PAYPAL_CLIENT_ID", "") or os.getenv("O_AUTH_CLIENT_ID", "")
        ).strip()
        self.client_secret = (
            os.getenv("PAYPAL_CLIENT_SECRET", "") or os.getenv("O_AUTH_CLIENT_SECRET", "")
        ).strip()
        self.is_configured = bool(
            self.client_id
            and self.client_secret
            and "tu_paypal" not in self.client_id
            and "your_paypal" not in self.client_id
        )

        self.client: PaypalServersdkClient | None = None
        if self.is_configured:
            self.client = self._create_client(self.client_id, self.client_secret)

    def _create_client(self, client_id: str, client_secret: str) -> PaypalServersdkClient:
        """
        Inicializa `PaypalServersdkClient` con argumentos planos (`python-client-initialization`).
        - `max_retries=0`: evita multiplicar reintentos cuando ya corre dentro de Render Workflows
          (`python-configuration-resilience`).
        - `timeout=30`: dimensionado considerando que la primera llamada OAuth 2.0 consume hasta
          2 ventanas de timeout (fetch_token + endpoint call).
        """
        credentials = ClientCredentialsAuthCredentials(
            o_auth_client_id=client_id,
            o_auth_client_secret=client_secret,
        )
        if self.client is not None:
            # Patrón oficial de `python-authentication`: usar `client.config.clone_with(...)`
            # y construir un nuevo cliente a partir de esa configuración inmutable.
            cloned_config = self.client.config.clone_with(
                client_credentials_auth_credentials=credentials,
                environment=Environment.SANDBOX,
            )
            return PaypalServersdkClient(config=cloned_config)

        return PaypalServersdkClient(
            client_credentials_auth_credentials=credentials,
            environment=Environment.SANDBOX,
            timeout=30,
            max_retries=0,
            logging_configuration=_build_logging_config(),
        )

    def configure_credentials(self, client_id: str, client_secret: str):
        """
        Permite actualizar las credenciales de PayPal Sandbox en caliente desde la GUI (BYOK)
        usando `config.clone_with(...)` según el skill `python-authentication`.
        """
        self.client_id = client_id.strip()
        self.client_secret = client_secret.strip()
        self.is_configured = bool(
            self.client_id
            and self.client_secret
            and "tu_paypal" not in self.client_id
            and "your_paypal" not in self.client_id
        )
        if self.is_configured:
            self.client = self._create_client(self.client_id, self.client_secret)
        else:
            self.client = None

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
        if not self.is_configured or self.client is None:
            return {
                "mode": "SANDBOX_SIMULATED (Faltan llaves en .env)",
                "paypal_order_id": f"SIM-PP-{uuid.uuid4().hex[:8].upper()}",
                "status": "COMPLETED",
            }

        # El controlador se accede como propiedad del cliente (`python-calling-endpoints`)
        orders_controller = self.client.orders
        stamped_custom_id = f"AP2_POLICY:{parent_policy_hash[:24]}"

        # 1. Mapeo determinista de AP2 -> Modelos de APIMatic (PayPal Orders v2)
        order_body = OrderRequest(
            intent=CheckoutPaymentIntent.CAPTURE,
            purchase_units=[
                PurchaseUnitRequest(
                    reference_id=mandate_id,
                    # Estampamos la prueba criptográfica AP2 dentro de la transacción de PayPal:
                    custom_id=stamped_custom_id,
                    invoice_id=f"AP2-INV-{mandate_id.upper()}",
                    description=f"AP2 Agent Purchase: {product_name}"[:127],
                    amount=AmountWithBreakdown(
                        currency_code="USD",
                        value=f"{amount_usd:.2f}",
                    ),
                )
            ],
        )

        try:
            # 2. Llamada real a PayPal Sandbox vía APIMatic SDK (Shape 2: options dict)
            response = orders_controller.create_order(
                {
                    "body": order_body,
                    "paypal_request_id": mandate_id,  # Idempotencia nativa en PayPal
                    "prefer": "return=representation",
                }
            )
        except AuthValidationException as auth_err:
            # `python-error-handling`: AuthValidationException NO hereda de ApiException
            # y se lanza antes de enviar el request si falla OAuth 2.0 Client Credentials.
            raise RuntimeError(
                f"APIMatic OAuth2 AuthValidationException: {auth_err}"
            ) from auth_err
        except ErrorException as err_exc:
            # `python-error-handling`: Evitar el typed-exception trap usando getattr(..., None)
            issues = getattr(err_exc, "details", None) or getattr(err_exc, "message", None)
            raise RuntimeError(
                f"PayPal Orders v2 ErrorException ({err_exc.response_code}): {issues or err_exc.reason}"
            ) from err_exc
        except ApiException as api_exc:
            raise RuntimeError(
                f"PayPal APIMatic ApiException ({api_exc.response_code}): {api_exc.reason}"
            ) from api_exc

        # 3. Lectura directa del sobre `ApiResponse` (`response.body` y `response.status_code`)
        #    usando `getattr` por si algún campo opcional fue omitido con `APIHelper.SKIP` (`python-models`).
        order_model = response.body
        paypal_order_id = getattr(order_model, "id", None)
        paypal_status = getattr(order_model, "status", None)

        if not paypal_order_id and order_model is not None:
            result_data = json.loads(APIHelper.json_serialize(order_model))
            paypal_order_id = result_data.get("id")
            paypal_status = result_data.get("status", "CREATED")

        return {
            "mode": "LIVE_PAYPAL_SANDBOX_APIMATIC",
            "paypal_order_id": paypal_order_id,
            "status": paypal_status or "CREATED",
            "http_status_code": response.status_code,
            "ap2_custom_id_stamped": stamped_custom_id,
        }

    def capture_ap2_order(self, paypal_order_id: str, mandate_id: str | None = None) -> dict:
        """
        Captura o consulta una orden creada en PayPal Orders v2 usando `OrdersController.capture_order`
        y `OrdersController.get_order` siguiendo los patrones del APIMatic Context Plugin.
        """
        if not self.is_configured or self.client is None:
            return {
                "mode": "SANDBOX_SIMULATED",
                "paypal_order_id": paypal_order_id,
                "status": "COMPLETED",
            }

        orders_controller = self.client.orders
        try:
            capture_resp = orders_controller.capture_order(
                {
                    "id": paypal_order_id,
                    "paypal_request_id": mandate_id or f"cap-{uuid.uuid4().hex[:10]}",
                    "prefer": "return=representation",
                }
            )
            order_model = capture_resp.body
            return {
                "mode": "LIVE_PAYPAL_SANDBOX_APIMATIC",
                "paypal_order_id": getattr(order_model, "id", paypal_order_id),
                "status": getattr(order_model, "status", "COMPLETED"),
                "http_status_code": capture_resp.status_code,
            }
        except ErrorException as err_exc:
            # Si la orden está en estado CREATED esperando aprobación del pagador en Sandbox,
            # consultamos su estado real con `get_order` (Shape 2 options dict).
            order_resp = orders_controller.get_order({"id": paypal_order_id})
            order_model = order_resp.body
            return {
                "mode": "LIVE_PAYPAL_SANDBOX_APIMATIC",
                "paypal_order_id": getattr(order_model, "id", paypal_order_id),
                "status": getattr(order_model, "status", "CREATED"),
                "http_status_code": order_resp.status_code,
                "note": getattr(err_exc, "message", None) or err_exc.reason,
            }
