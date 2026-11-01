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
    APIMatic logging configuration following the `python-configuration-resilience` skill:
    RequestLoggingConfiguration and ResponseLoggingConfiguration are passed as fields of
    LoggingConfiguration with `mask_sensitive_headers=True` to protect OAuth 2.0 tokens.
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
    Official APIMatic-generated PayPal client (`paypal-server-sdk` v2.4.0)
    built following all 8 skills from the APIMatic Context Plugin for PayPal
    (`paypaldev/server-sdk-context-plugin-preview`):
      - `python-getting-started` & `python-client-initialization`
      - `python-authentication` (ClientCredentialsAuthCredentials + clone_with)
      - `python-calling-endpoints` (OrdersController property + Shape-2 options dict + ApiResponse.body)
      - `python-models` (OrderRequest, PurchaseUnitRequest, AmountWithBreakdown & APIHelper.SKIP safe reads)
      - `python-error-handling` (AuthValidationException, ErrorException, ApiException with getattr guard)
      - `python-configuration-resilience` (timeout=30, max_retries=0 under Render Workflows, LoggingConfiguration)
    """

    def __init__(self):
        # Support both PAYPAL_CLIENT_ID and the native O_AUTH_CLIENT_ID from the APIMatic SDK
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
        Initializes `PaypalServersdkClient` with flat transport arguments (`python-client-initialization`).
        - `max_retries=0`: avoids compounding retries when running inside Render Workflows
          (`python-configuration-resilience`).
        - `timeout=30`: sized considering that the first OAuth 2.0 call consumes up to
          2 timeout windows (fetch_token + endpoint call).
        """
        credentials = ClientCredentialsAuthCredentials(
            o_auth_client_id=client_id,
            o_auth_client_secret=client_secret,
        )
        if self.client is not None:
            # Official `python-authentication` pattern: use `client.config.clone_with(...)`
            # and construct a new client from that immutable configuration.
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
        Hot-reloads PayPal Sandbox credentials at runtime from the web UI (BYOK)
        using `config.clone_with(...)` per the `python-authentication` skill.
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
        Builds a strongly typed APIMatic OrderRequest and dispatches it to PayPal Sandbox.
        Stamps the AP2 cryptographic policy hash directly onto the PayPal ledger record.
        """
        # Clean simulated fallback when Sandbox keys are not yet configured
        if not self.is_configured or self.client is None:
            return {
                "mode": "SANDBOX_SIMULATED (Missing keys in .env)",
                "paypal_order_id": f"SIM-PP-{uuid.uuid4().hex[:8].upper()}",
                "status": "COMPLETED",
            }

        # Access controller as a property on the client (`python-calling-endpoints`)
        orders_controller = self.client.orders
        stamped_custom_id = f"AP2_POLICY:{parent_policy_hash[:24]}"

        # 1. Deterministic mapping from AP2 -> APIMatic Models (PayPal Orders v2)
        order_body = OrderRequest(
            intent=CheckoutPaymentIntent.CAPTURE,
            purchase_units=[
                PurchaseUnitRequest(
                    reference_id=mandate_id,
                    # Stamp the AP2 cryptographic lineage proof into the PayPal transaction:
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
            # 2. Live call to PayPal Sandbox via APIMatic SDK (Shape 2: options dict)
            response = orders_controller.create_order(
                {
                    "body": order_body,
                    "paypal_request_id": mandate_id,  # Native PayPal idempotency key
                    "prefer": "return=representation",
                }
            )
        except AuthValidationException as auth_err:
            # `python-error-handling`: AuthValidationException does NOT inherit from ApiException
            # and is raised prior to sending the request if OAuth 2.0 Client Credentials fail.
            raise RuntimeError(
                f"APIMatic OAuth2 AuthValidationException: {auth_err}"
            ) from auth_err
        except ErrorException as err_exc:
            # `python-error-handling`: Avoid the typed-exception trap using getattr(..., None)
            issues = getattr(err_exc, "details", None) or getattr(err_exc, "message", None)
            raise RuntimeError(
                f"PayPal Orders v2 ErrorException ({err_exc.response_code}): {issues or err_exc.reason}"
            ) from err_exc
        except ApiException as api_exc:
            raise RuntimeError(
                f"PayPal APIMatic ApiException ({api_exc.response_code}): {api_exc.reason}"
            ) from api_exc

        # 3. Direct read from `ApiResponse` envelope (`response.body` and `response.status_code`)
        #    using `getattr` in case any optional field was omitted via `APIHelper.SKIP` (`python-models`).
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
        Captures or queries a created order in PayPal Orders v2 using `OrdersController.capture_order`
        and `OrdersController.get_order` following the APIMatic Context Plugin patterns.
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
            # If the order is in CREATED state awaiting payer approval in Sandbox,
            # fetch its live status via `get_order` (Shape 2 options dict).
            order_resp = orders_controller.get_order({"id": paypal_order_id})
            order_model = order_resp.body
            return {
                "mode": "LIVE_PAYPAL_SANDBOX_APIMATIC",
                "paypal_order_id": getattr(order_model, "id", paypal_order_id),
                "status": getattr(order_model, "status", "CREATED"),
                "http_status_code": order_resp.status_code,
                "note": getattr(err_exc, "message", None) or err_exc.reason,
            }
