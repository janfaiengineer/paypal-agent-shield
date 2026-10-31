---
name: 'python-configuration-resilience'
description: 'Tune the PayPal Server SDK Python SDK client — retries, timeout, proxy, transport, environment, logging. Load when adjusting any of these. The parameter list won''t tell you the retry defaults are fixed at generation time (read `Configuration.__init__` rather than assume), that settings are per-client with no per-call override, or that there is no free-form base-URL argument.'
---

# Configuration & resilience for an APIMatic Python SDK

All configuration is supplied when the client is constructed (see **python-client-initialization**), as
**flat keyword arguments** — there is no nested options object and no per-call override:

```python
from paypalserversdk.paypal_serversdk_client import PaypalServersdkClient
from paypalserversdk.configuration import Environment
from paypalserversdk.http.proxy_settings import ProxySettings

client = PaypalServersdkClient(
    environment=Environment.{MEMBER},
    timeout=30,
    max_retries=3,
    backoff_factor=2,
    retry_statuses=[429, 503],
    retry_methods=['GET', 'PUT'],
    proxy_settings=ProxySettings(address='http://localhost', port=8888),
)
```

Anything you leave out keeps the generated default. Anything you pass replaces it outright — these are
plain parameter defaults, not a merge, so passing `retry_statuses=[429]` narrows the list to exactly
that.

## Retries

The retry policy is five arguments: `max_retries`, `backoff_factor`, `retry_statuses`, `retry_methods`,
and (indirectly) `timeout`. `Configuration.create_http_client` hands all of them to the
`RequestsClient` transport, so they are enforced inside the HTTP layer, below the operation call.

> **Do not assume a default.** The defaults are written into `Configuration.__init__` when the SDK is
> generated and differ from build to build. Read that signature in
> `paypalserversdk/configuration.py` — `doc/client.md` tabulates the same values. Retries may well be
> off entirely (`max_retries=0`), in which case a transient `503` surfaces as an `ApiException` on the
> first attempt.

Notes:

- **Only the methods in `retry_methods` are retried**, for statuses and for errors raised after the
  request reached the server. That list is generated and typically covers idempotent methods only, so
  if `POST`/`PATCH`/`DELETE` are absent their failures surface with no retry. Add one only when the
  operation really is idempotent.

  One exception: a failure in the **connect phase** is retried without checking the method list, so a
  connect timeout on a `POST` may be retried even with `POST` absent. A *read* timeout on the same
  `POST` will not be — that is the case that could duplicate a write.
- **Only the statuses in `retry_statuses` are retried**; everything else raises immediately.
- **`timeout` is handed to the transport per request** (`RequestsClient(timeout=self.timeout, ...)` in
  `Configuration.create_http_client`) — it is not a deadline over the whole call including retries. If
  you need a hard overall bound, enforce it in your own code.
- There is **no per-call timeout or cancellation argument**; a call that needs a different budget needs
  a differently-configured client. `client.config.clone_with(timeout=5)` plus a new client is the
  cheapest way to get one.
- **Read the `max_retries=` default in `paypalserversdk/configuration.py`** — it is written in when the
  SDK is generated, so it varies per build. At `0` a transient `503` raises on the first attempt and
  passing `max_retries=0` is a no-op; above `0` every listed status and method is retried underneath your code
  whether you wanted it or not. Raise it only where nothing above the SDK already retries — a task
  queue, a job runner, a failover wrapper, or your own orchestration loop. Retry layers multiply rather
  than add: `max_retries=3` is **four** requests per attempt, so inside a 3-attempt job it is twelve
  requests against an API whose rate limit counts every one.
- **`clone_with` cannot switch retries back off.** It resolves each argument as
  `max_retries or self.max_retries`, and `0` is falsy, so `clone_with(max_retries=0)` silently keeps
  the old value — as does `clone_with(timeout=0)` or an empty `retry_statuses`. Build a fresh client
  instead.

> **A call that fetches a token spends `timeout` twice.** This applies to an SDK secured by an OAuth
> grant — check `paypalserversdk/http/auth/` for an OAuth module; if there is none, skip this.
>
> An operation whose cached token is missing or expired fetches one first, and that **token request**
> shares the one `RequestsClient` — the OAuth controller is built from the same `Configuration` — so it
> is bounded by the same `timeout`. That budget is per request, so the operation can take up to **two**
> full periods; size
> any caller-side deadline against two, not one.
>
> **The failure is disguised.** A failed fetch hands back the previously held token (`None` on a first
> call), and what you get is an `AuthValidationException` carrying the scheme's fixed `error_message` —
> the same one a wrong client id produces, with the underlying exception gone rather than chained. To
> tell "the provider is down" from "our credentials are wrong", call `fetch_token()` yourself at
> startup, or set an OAuth token provider.

## Base URL / environment

There is **no free-form base-URL argument**. The base URL is looked up in the
`Configuration.environments` map by `(environment, server)` and returned by
`Configuration.get_base_uri`, with any server parameters substituted into the URL template.

Read `paypalserversdk/configuration.py` for the real names before naming one — they vary per API. They are members of the `Environment` and `Server`
enums there.
To point the SDK at a mock or proxy that no name covers, use `proxy_settings` (below).

## Proxy

`ProxySettings` (`paypalserversdk/http/proxy_settings.py`) takes a required `address` plus optional
`port`, `username` and `password`. `ProxySettings.from_environment()` builds one from `PROXY_ADDRESS`,
`PROXY_PORT`, `PROXY_USERNAME` and `PROXY_PASSWORD`, returning `None` when `PROXY_ADDRESS` is unset — so
it is safe to pass unconditionally.

## Custom transport

`http_client_instance` accepts your own `requests.Session` (or an implementation of `HttpClientProvider`
from `paypalserversdk/http/http_client_provider.py`), which is how you attach custom adapters,
connection-pool sizes or TLS settings. Pass `override_http_client_configuration=True` alongside it to
have the SDK's timeout and retry settings applied to that client rather than left as you configured it.

## Pagination

**No operation in this API is paginated.** The SDK ships no `paypalserversdk/utilities/pagination/`
package, so there is no `PagedIterable`, no `.pages()`, and no paged-response type to narrow with
`isinstance`. Nothing here needs configuring.

If you need more than one page from a list endpoint, you drive it yourself: the paging arguments are
ordinary parameters on the operation, and the stopping condition comes from the response model rather
than from the SDK. Bound the loop explicitly — nothing in the SDK will stop it for you.

## Logging

The client takes a `logging_configuration` parameter. All three classes come from the
same module, and the request and response halves are **fields of** `LoggingConfiguration` rather than
separate arguments:

```python
from paypalserversdk.logging.configuration.api_logging_configuration import (
    LoggingConfiguration, RequestLoggingConfiguration, ResponseLoggingConfiguration)

client = PaypalServersdkClient(logging_configuration=LoggingConfiguration(
    logger=my_logger,
    request_logging_config=RequestLoggingConfiguration(log_body=True),
    response_logging_config=ResponseLoggingConfiguration(log_headers=True),
))
```

`doc/logging-configuration.md` documents the fields — the logger, the level, and whether sensitive
headers are masked; it carries no import line, so take the module path from above.

## Next

- Step 7, stubbing the SDK → **python-testing**
