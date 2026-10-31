---
name: 'python-testing'
description: 'Unit-test code that calls the PayPal Server SDK Python SDK. Load before stubbing the SDK. The constructor won''t tell you the seam is your own `requests.Session` passed as `http_client_instance` plus `http_call_back` for asserting the request, that `max_retries` is inert on a session you supply, or that an OAuth grant''s token request traverses that same seam.'
---

# Testing code that uses an APIMatic Python SDK

The SDK ships **no mocking helpers for consumers**. Its transport is `requests`, wrapped by
`RequestsClient` from `apimatic-requests-client-adapter`, and the client exposes two seams on its
constructor:

| Argument | Use it for |
| --- | --- |
| `http_client_instance` | supplying your own `requests.Session` (or an `HttpClientProvider`) — the in-process seam: no network, no global patching |
| `http_call_back` | observing the request and response the SDK actually produced — the assertion seam |

The samples below use pytest-style plain `assert` for reference only — mirror whatever the project
already uses.

## The response catcher — copy the SDK's own pattern

`HttpCallBack` (`paypalserversdk/http/http_call_back.py`) has exactly two methods, called around every
request:

```python
from paypalserversdk.http.http_call_back import HttpCallBack

class ResponseCatcher(HttpCallBack):
    def __init__(self):
        self.request = None
        self.response = None

    def on_before_request(self, request):
        self.request = request      # HttpRequest: http_method, query_url, headers,
                                    # query_parameters, parameters, files

    def on_after_response(self, response):
        self.response = response    # HttpResponse: status_code, reason_phrase,
                                    # headers, text, request
```

If the SDK shipped a `tests/` directory it already contains this class as
`tests/http_response_catcher.py`, wired up in `tests/controllers/*_test_base.py` — read those
first and follow the same shape.

## A reusable stub helper

Mount a stub adapter on a `requests.Session` and hand that session to the client:

```python
import requests
from paypalserversdk.paypal_serversdk_client import PaypalServersdkClient

def client_returning(status, body, session_factory):
    """session_factory: builds a requests.Session whose adapter returns (status, body)."""
    catcher = ResponseCatcher()
    client = PaypalServersdkClient(
        http_client_instance=session_factory(status, body),
        http_call_back=catcher,
        max_retries=0,          # see the note below — inert with your own session, set it anyway
    )
    return client, catcher
```

Leave `override_http_client_configuration` at its default here: it exists to let the SDK reapply its own
timeout and retry settings onto the session you passed, which is the opposite of what a stubbed session
wants.

> ### ⚠ One status for every URL cannot test an error path
>
> An operation on an authenticated SDK sends **two** requests: the OAuth token POST first, then the
> operation. A `session_factory` that answers every URL with the same status therefore hands your
> stubbed `422` to the token exchange, and the call dies before the operation is reached — with
> `AuthValidationException: ...OAuthToken is undefined or expired.`, a message naming neither the status
> you stubbed nor the request that actually failed.
>
> Route by URL in the factory rather than returning one status: answer the token path with a `200` and a
> body carrying `access_token` and `expires_in`, and everything else with the status under test. Read the
> real token path off the generated OAuth controller — it comes from the API, so do not assume it.
>
> The alternative is to seed a live token on the client so no fetch happens at all. Either works; what
> does not work is a single-status stub, and that is what the helper above is until you extend it.

Build the session with whichever stubbing library the project already uses — `requests_mock` (mount its
`Adapter`), `responses` (activate it around the test), or a hand-written `requests.adapters.HTTPAdapter`
subclass. All three intercept below the SDK, so the SDK's own serialization, deserialization and error
mapping still run — which is exactly what you want to be testing through.

> **The catcher sees the token request too.** With an OAuth grant `on_before_request` fires for the
> token POST as well, so a single `catcher.request` is whichever fired **last** — on a call that fails
> during auth, that is the token request, and your assertions silently target the wrong one. Keep a list
> and select by path.
>
> **If this SDK uses an OAuth grant**, the auth manager fetches a token over the *same* session before
> your operation is called. Stub the token endpoint too, or set an already-valid token on the credentials
> object — otherwise the test fails on the token request rather than on the call you meant to exercise.
> See **python-authentication**.

## Test a success path

```python
def test_returns_deserialized_body():
    client, _ = client_returning(200, '{"id": 123}', session_factory)

    result = client.{controller}.{operation}()

    assert result.body.{attr} == 123
```

Assert on `result.body` — every operation returns an `ApiResponse` envelope, so
reading a model attribute straight off `result` raises (see **python-calling-endpoints**). Remember that an
attribute the model lists in `_optionals` is **absent**
rather than `None` when the stubbed body omits it (see **python-models**), so assert with
`getattr(result.body, '{attr}', None)` where that applies.

## Test an error path

Non-2xx raises `ApiException`, or a typed subclass when the operation's `doc/controllers/` page lists
one (see **python-error-handling**):

```python
import pytest
from paypalserversdk.exceptions.api_exception import ApiException

def test_raises_on_non_2xx():
    client, _ = client_returning(422, '{"message": "bad input"}', session_factory)

    with pytest.raises(ApiException) as excinfo:
        client.{controller}.{operation}()

    assert excinfo.value.response_code == 422
```

For an operation with a typed exception, assert on that class instead — catching the base would also
pass if the SDK stopped raising the typed one, which is the regression the test exists to catch.

## Assert the outgoing request

**`doc/` does not carry an operation's HTTP verb or URL**, and you need both to stub a transport. The
reliable source is the operation's own request builder: grep `.path(`, `.http_method(` and `.server(` in
`paypalserversdk/controllers/*.py`.

The catcher's `on_before_request` receives the SDK's `HttpRequest`, so verb, URL, headers, query
parameters and body are all assertable without a network:

```python
def test_sends_expected_request():
    client, catcher = client_returning(200, '{}', session_factory)

    client.{controller}.{operation}({arg}='value')       # or ({'{arg}': 'value'}) — see below

    assert catcher.request.query_url.endswith('/expected/path')
    # query_parameters is None here — the query string is already folded into query_url,
    # and list-valued parameters arrive URL-encoded (`include%5B%5D=`).
    assert '{arg}=value' in catcher.request.query_url
```

**Read the `def` line before you write the call.** Operations come in two parameter shapes — keyword
arguments, or a single `options` dict keyed by the same names — and which one an operation uses is fixed
at generation time. Only one direction fails loudly: keyword arguments to an `options`-shaped operation
are a `TypeError` on the spot, but a dict passed positionally to a keyword-shaped one **binds to its
first parameter and sends a wrong request that your assertions may happily pass** (see
**python-calling-endpoints**).

Where a given parameter lands — path, `query_parameters`, `headers`, `parameters` (form/body) or `files`
— depends on how the operation declares it. Print the captured `HttpRequest` once if you are unsure.

## Retries do not apply to your stubbed session

When you pass your own `http_client_instance` and leave `override_http_client_configuration` at its
default, the SDK **returns without touching your session's adapters** — so `max_retries`,
`retry_statuses` and `retry_methods` have no effect on it. A stubbed 5xx fails on the first attempt
because your adapter was left alone, not because retries were disabled. Set `max_retries=0` anyway so
the intent is explicit and the test still holds if someone later flips the override.

The corollary: **you cannot verify retry behaviour through this seam.** A mock adapter bypasses the
retry machinery entirely, so a "stub 503 then 200 and count calls" test records one attempt whatever
you configure. Test retry policy against a real transport, or not at all.

## Notes

- **Reach for a fake client, not a fake controller.** Controllers are lazy properties on the client, so
  a stubbed client is all your code under test needs; there is nothing else to patch.
- **Inject the client** into the code under test rather than constructing it inside — see the DI note in
  **python-client-initialization**. Where that is not possible, patch the module attribute that holds
  the shared client.
- Prefer testing through the SDK over asserting on your own wrapper's calls: the interesting failures
  (wrong wire name, a `oneOf` that rejects your value before the request, an absent optional attribute)
  only appear when the SDK's own serialization runs.

## Next

That is the last step of the workflow. If you have not read **python-configuration-resilience** yet, read it before you ship — its subject is the client's defaults, which apply whether or not you set anything.
