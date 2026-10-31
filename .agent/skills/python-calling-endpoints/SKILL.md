---
name: 'python-calling-endpoints'
description: 'Call operations on the PayPal Server SDK Python SDK. Load before your first call, and when building a request body or reading a response. The signature won''t tell you the controller is a property rather than something you construct, that operations come in two parameter shapes (plain arguments, or a single `options` dict), or that every response arrives wrapped in an `ApiResponse`, payload on `.body`.'
---

# Calling endpoints on an APIMatic Python SDK

> **`doc/` is in the SDK's repository, not in the installed package.** Every pointer to
> `doc/controllers/` or `doc/client.md` below assumes you have the repository checked out. Where you
> only have the installed artifact — the common case — the equivalent source is the operation's own signature in `paypalserversdk/controllers/`, and it is
> authoritative in a way the docs are not.

Operations are **synchronous methods on a controller you reach as a property of the client** — you do
not construct the controller:

```python
from paypalserversdk.paypal_serversdk_client import PaypalServersdkClient

client = PaypalServersdkClient(...)
result = client.{controller}.{operation}(...)
```

Controllers live in `paypalserversdk/controllers/`, one file per API group, each extending
`BaseController`. **Grep that directory** for an operation and read its `def` line — the
signature there is the one you have to satisfy. Operation names follow no fixed verb/resource pattern,
so take the real name from the source.

Where you also have the SDK's **source repository** (see **python-getting-started**), `doc/client.md`
lists every controller property and the class it returns, and each `doc/controllers/*.md` page lists that
controller's operations, parameters, response type and errors. Those pages are prose over the same
generated code, and they ship with the repository rather than the installed package.

## Method signature convention

Every operation is a plain synchronous method, but **operations come in two parameter shapes. Read the
`def` line before calling one** — guessing wrong raises `TypeError` in one direction and, in the other,
binds your dict to the first parameter and sends a wrong request with no error at all.

**Shape 1 — plain parameters**, in the order the spec declares them. Required ones have no default;
optional ones default to `None` or to the default the spec gives:

```python
def {operation}(self, {required_param}, {optional_param}=None, {param_with_default}=10):

result = client.{controller}.{operation}({required_param}=value, {optional_param}='search text')
```

**Shape 2 — a single `options` dict**, keyed by those same parameter names:

```python
def {operation}(self, options=dict()):

result = client.{controller}.{operation}({'{required_param}': value, '{optional_param}': 'search text'})
```

Both shapes occur in the same SDK; which one an operation uses is fixed at generation time. Open the
method and look — the operation's `doc/controllers/` page also shows the real call form.

- **In shape 1, pass optional parameters by keyword.** Skipping one positionally is a bug waiting to
  happen, and naming them survives the parameter list changing on regeneration.
- **`options` is not a request-options bag.** It carries the operation's own parameters. Neither shape
  has a timeout override, cancellation token, or per-call transport setting — the client's transport
  settings apply to every call it makes. See **python-configuration-resilience**.
- **There is no async variant.** Every operation blocks. To call concurrently, use threads or run the
  call in an executor.
- **Read the real parameter names from `paypalserversdk/controllers/`** — they come straight from the
  operation's own parameter names, converted to snake_case, not from any fixed convention.
- Methods **raise `ApiException`** (or a typed subclass) on a non-2xx response — see
  `python-error-handling`.

## Building request models

A request body parameter takes a model instance from `paypalserversdk/models/`. Model constructors are
also positional-or-keyword; pass by keyword:

```python
from paypalserversdk.models.{model_module} import {Model}

body = {Model}(
    {required_attr}=value,
    {optional_attr}=value,     # omit entirely to leave it out of the request
)

result = client.{controller}.{operation}(body)              # shape 1
result = client.{controller}.{operation}({'body': body})    # shape 2 — keyed by its parameter name
```

**The body is a parameter like any other**, so the operation's own shape decides how it goes in — read
the `def` line (see *Method signature convention* above). Passing the model positionally to a shape-2
operation binds it to `options`, and the first `options.get(...)` inside the request builder raises
`AttributeError` from inside the SDK, with nothing pointing back at your call.

An attribute the model lists in `_optionals` defaults to the `APIHelper.SKIP` sentinel, and the
constructor **skips the assignment entirely** when it sees that sentinel — so an omitted optional
attribute is *absent from the instance*, not `None`, and nothing for it is serialized. That distinction
matters when you read a response back; see **python-models**.

A request body's **shape varies**: some models are flat, others nest an inner model. Open the model
module for its real attributes and which of them are in `_optionals`.

## Enums

Generated enums are plain classes whose members are the **raw wire values** — `{EnumType}.MEMBER` *is*
the string (or integer), so you can pass either:

```python
{enum_param}={EnumType}.MEMBER
{enum_param}='server_provided_value'   # equivalent when it is a known value
```

## Files

File parameters take a `FileWrapper` from `paypalserversdk/utilities/file_wrapper.py`, which pairs the
stream with its content type:

```python
from paypalserversdk.utilities.file_wrapper import FileWrapper

with open('report.pdf', 'rb') as stream:
    result = client.{controller}.{operation}(FileWrapper(stream, 'application/pdf'))
```

## Union types, collections, and dates

Some parameters are not plain scalars: oneOf/anyOf union types, lists and dicts, and wrapped date-time
values. If a request parameter or response attribute is one of these, see **python-models** for how to
build and read it.

## Reading the response

Every operation returns an **`ApiResponse` envelope** — the payload is on
`result.body`, never on `result` itself:

```python
result = client.{controller}.{operation}()

result.body            # the deserialized payload
result.status_code     # HTTP status
result.headers         # response headers
result.text            # raw body
result.is_success()    # / .is_error(), .errors
```

**Go through `.body`.** Iterating `result` or reading a model attribute straight off it raises —
`TypeError` and `AttributeError` respectively — and that is the most common first-call mistake.
`doc/api-response.md` documents the envelope.

**The payload type varies per operation** — read the `Returns:` line in the method's docstring, or the
*Response Type* section of its `doc/controllers/` page. Each bullet below describes
`result.body`, never `result`:

- **A model** — use its attributes directly (`result.body.{attr}`).
- **A list of models** — iterate `result.body`.
- **A primitive** (`str`, `int`, `bool`, …) — use it as-is.
- **`None`** — an operation with no response body leaves `.body` empty.
- **A union** — one of several types; narrow with `isinstance` (see **python-models**).

## Paginated operations

**No operation in this API is paginated**, so the SDK ships no `paypalserversdk/utilities/pagination/`
package and no operation returns a `PagedIterable`. There is nothing to iterate lazily and no `.pages()`
to call — do not write against either.

That is a statement about **this API definition**, not about the provider. An API can page its results
and still declare no pagination strategy, in which case the SDK models the paging parameters as ordinary
operation parameters and hands you one page per call. So when you need more than one page:

- **Take the paging parameters off the operation's own signature** in
  `paypalserversdk/controllers/` — they are keyword arguments like any other, and their names come
  from the API definition rather than from a convention.
- **Take the continuation value off the response model**, not from a counter you keep yourself. A page
  number you increment cannot tell you when to stop; the response can, through whatever total, cursor or
  next-link field the model declares.
- **Stop on what the response says**, and bound the loop anyway — a loop that only ends when a page comes
  back empty will run forever against an API that repeats its last page.

## Worked example — a list/GET call

```python
# Signature (illustrative):
#   def {operation}(self, {filter}=None, {q}=None, page=1, per_page=None)

try:
    result = client.{controller}.{operation}(
        {filter}={EnumType}.MEMBER,
        {q}='search text',
        page=1,
    )
    for item in result.body:
        print(item.{attr})
except ApiException as e:
    print(e.response_code, e.response.text)
```

## Finding the right method in the SDK source

- Every operation lives on a controller class in `paypalserversdk/controllers/`, one file per API
  group. `ls` that directory to find the group, then read the class off its `class` line and the method
  off its `def` line.
- Request/response models and enums live under `paypalserversdk/models/`; exception types under
  `paypalserversdk/exceptions/`.
- Each method's docstring names its parameter types and its `Returns:` type — that is the fastest
  in-source answer to "what does this give me back?".

## Next

- Union types, collections, dates, enums → **python-models**
- Errors and status codes → **python-error-handling**
- Pagination, retries, timeouts → **python-configuration-resilience**
