---
name: 'python-error-handling'
description: 'Handle errors from the PayPal Server SDK Python SDK. Load before your first `try/except` around a call, or when translating SDK errors into your own. The raised class won''t tell you the status code is on `response_code`, that a typed subclass''s attributes may be unassigned when the error body isn''t a JSON object, or that catching the base class first swallows typed errors.'
---

# Error handling for an APIMatic Python SDK

Operations **raise on non-success responses**. Everything raised by the SDK derives from `ApiException`
(`paypalserversdk/exceptions/api_exception.py`), which carries:

| Attribute | Meaning |
| --- | --- |
| `response_code` | the HTTP status code — **not** `status_code` |
| `reason` | the generated error message for the case that matched |
| `response` | the `HttpResponse`: `status_code`, `reason_phrase`, `headers`, `text`, `request` |

The raised class comes in **two shapes**, depending on the operation:

- **Typed subclass (Case A)** — the API documents an error model for that status, so a
  `{Name}Exception(ApiException)` exists under `paypalserversdk/exceptions/` and its fields are unboxed
  onto the exception instance.
- **Base `ApiException` (Case B)** — no error model for that response, so what you catch is
  `ApiException` itself.

Which shape an operation uses is a property of this API's definition, not a rule of thumb: an SDK can
register a typed class for every documented status *and* for `default`, leaving no operation that raises
the base class. Read the mapping rather than assuming either shape — a `ApiException` handler
written for Case B still catches a typed instance, and then reads none of its unboxed fields.

## Which exception does an endpoint raise?

Grep `.local_error(` in the controller's own module under `paypalserversdk/controllers/`. Each
call registers one status — or `default` — against the class raised for it, and that registration is
what the SDK actually does.

If you also have the SDK's **source repository** (see **python-getting-started**), the operation's page
under `doc/controllers/` ends with an **Errors** table carrying the same mapping in prose. It is a
convenience, not the source of truth: it is absent from the installed package, and **no table — or no
page for that controller at all — is not proof that nothing typed is raised.**

A status no `.local_error(` covers falls through to the SDK's global default case, generated as a single
`default` entry naming a message and an exception class — the base `ApiException` unless the
spec documents a global error model, in which case a typed subclass sits there instead. Read
`BaseController.global_errors` on the `BaseController` class in
`paypalserversdk/controllers/` for the class and the wording rather than assuming
either.

## Catch the exception

### Case A — the operation has a typed exception

```python
from paypalserversdk.exceptions.api_exception import ApiException
from paypalserversdk.exceptions.{name}_exception import {Name}Exception

try:
    result = client.{controller}.{operation}()
except {Name}Exception as e:
    # typed fields, unboxed from the error body — read the class for their names
    print(e.response_code, getattr(e, '{typed_field}', None))
except ApiException as e:
    print(e.response_code, e.response.text)
```

**Order matters.** `{Name}Exception` subclasses `ApiException`, so an `except ApiException` placed first
swallows every typed error and the typed branch never runs. List the typed classes first, base last.

### Case B — the operation raises `ApiException`

```python
from paypalserversdk.exceptions.api_exception import ApiException

try:
    result = client.{controller}.{operation}()
except ApiException as e:
    print(f'HTTP {e.response_code}: {e.reason}')
    print(e.response.text)                       # raw body
    print(e.response.headers.get('Retry-After')) # response headers live here
```

`e.response.text` is the **raw body string**; nothing has parsed it for you. Use
`APIHelper.json_deserialize(e.response.text)` (or `json.loads`) if you need it structured, and be ready
for it not to be JSON at all.

## The typed-exception trap

A typed exception unboxes the error body in its `__init__`, but only after checking that the parsed body
is a JSON **object**. When the server returns an empty body, HTML from a proxy, or a bare JSON scalar —
exactly what a gateway timeout or a WAF block looks like — **the typed attributes are never assigned**.
Reading `e.{typed_field}` then raises `AttributeError` *from inside your except block*, replacing a
useful error with a confusing one. Always reach for them with `getattr(e, '{typed_field}', None)`, and
fall back to `e.response.text`.

## Not every failure is an `ApiException`

- **Transport failures** — connection refused, DNS failure, TLS error, read timeout — come out of the
  underlying `requests` transport, not as `ApiException`. Catch them separately (or let them propagate)
  rather than assuming an `except ApiException` covers a network outage.

  > **A read timeout and a refused connection arrive as the same class — a plain `ConnectionError` —
  > and for a write that distinction is the whole question.** A refused connection never delivered the
  > request; a read timeout means the server may have processed it and you simply did not hear back.
  > Nothing you can configure separates them, so treat a `ConnectionError` on a non-idempotent call as
  > **outcome unknown**.

- **Credentials the auth scheme cannot satisfy** raise
  `apimatic_core.exceptions.auth_validation_exception.AuthValidationException`, which is **not** an
  `ApiException` subclass. An `except ApiException` around your calls therefore
  **does not catch an authentication failure** — it propagates unhandled. Give it its own `except`, or
  let it escape as the configuration bug it is. Three things follow from where it is raised:

  1. It is raised **before the request is sent**, so a non-idempotent call definitely did not happen —
     unlike a transport `ConnectionError`, where the outcome is unknown.
  2. Its message is the scheme's fixed `error_message` (e.g. `"BasicAuth: username or password is
     undefined."`), so a wrong credential, an expired one and a token endpoint that is down all read
     the same. Grep that string in `paypalserversdk/http/auth/` to find the scheme it came from.
  3. For an **OAuth grant** the underlying failure is worse hidden: the automatic pre-call token fetch
     catches the provider's own exception, hands back the previously held token — `None` on a first
     call — and what you see is the fixed message above, with the real status gone. Calling
     `fetch_token()` **explicitly at startup** raises the SDK's OAuth provider exception instead, which
     carries the token endpoint's status and body, and turns "token is undefined or expired" into the
     `401` it actually was. `ls paypalserversdk/exceptions/` for that class — its casing is generated
     per SDK. See **python-authentication**.
- **Client-side validation of a oneOf/anyOf parameter** fails *before* any request is sent, so the
  traceback points at your call site with no `response` to inspect — see **python-models**.

Because these arrive as different types, a bare `except ApiException` around your integration is not a
catch-all. Decide deliberately what the other branches do.

## Reporting

`ApiException.__str__` renders as `{Name}Exception(status_code=..., message=...)`, and typed subclasses
append their unboxed fields. **But some typed subclasses read those unboxed attributes in `__str__`
without guarding them** — the generator is inconsistent, so check the class before you rely on it. Where
it is unguarded and the body was not a JSON object, `str(e)` raises `AttributeError` in exactly the
gateway/WAF case above. Log `f'{e.response_code}: {e.reason}'` instead, or guard `str(e)` with `try`.
Keep `e.response.text` out of logs that might contain user data.

## Notes

- The status code is also on `e.response.status_code`; `e.response_code` is the same value and is what
  the generated code and docs use.
- Retries for transient statuses happen **before** the exception reaches you, but only for the methods
  and status codes configured on the client, whose defaults are fixed when the SDK is generated. Errors
  from a method outside that set surface with no retry at all. See
  **python-configuration-resilience**.
- The status code of a **successful** call is already on `result.status_code`. See **python-calling-endpoints**.

## Next

- Step 6, retries, timeout, proxy, transport, environment and logging → **python-configuration-resilience**
- Step 7, stubbing the SDK → **python-testing**

Retry and timeout behaviour is named above only where an error surfaces it. The **defaults** — what this client does when you configure nothing — belong to **python-configuration-resilience**, and reading them here is not a substitute for reading them there.
