---
name: 'python-authentication'
description: 'Set credentials on the PayPal Server SDK Python SDK. Load before configuring any auth scheme — Basic, API key in header or query, bearer token, or an OAuth 2 grant. The kwarg name won''t tell you it takes a constructed `{Scheme}Credentials` object, that missing required values raise `ValueError` at construction, or how a fetched OAuth token is re-attached.'
---

# Authenticating an APIMatic Python SDK client

How you authenticate depends on the security scheme(s) the API uses. APIMatic generates **one keyword
argument per scheme** on the client (and on `Configuration`), and — for every scheme except custom
authentication — **a credentials class to pass to it**, under `paypalserversdk/http/auth/`. You build
the object and pass it in when constructing the client (see `python-client-initialization`).

> **Custom authentication is the exception.** Its module holds only the handler class (e.g.
> `class CustomAuth(HeaderAuth)`), constructed from the whole `Configuration` and shipped as a stub with
> an empty `auth_params` and `# TODO` comments where the credential values belong. There is **no
> `{Scheme}Credentials` class to build**, even though the `{scheme}_credentials` keyword argument still
> exists on the client. Nothing here is configurable from your application: custom authentication means
> *the SDK itself* has to be completed or regenerated. **A custom *header* or custom *query-parameter*
> scheme is not this case** — those are ordinary API-key schemes with a credentials class and a
> `doc/auth/` page. Check the scheme's module for a credentials class before writing the call.

## What this SDK declares

Copy these names verbatim — they are this SDK's, not an example:

| Scheme | Import | Client kwarg | Required arguments | `from_environment()` reads |
| --- | --- | --- | --- | --- |
| `ClientCredentialsAuth` | `from paypalserversdk.http.auth.o_auth_2 import ClientCredentialsAuthCredentials` | `client_credentials_auth_credentials=` | `o_auth_client_id`, `o_auth_client_secret` | `O_AUTH_CLIENT_ID`, `O_AUTH_CLIENT_SECRET` |

Every one of those names is derived from the **scheme's name in the spec**, not from the module it lands
in, so no two of them need to agree and none can be inferred from another. The module, the credentials
class and the client's auth-manager property routinely differ — `client.oauth_2` sitting alongside
`o_auth_2.py` and a `ClientCredentialsAuthCredentials` class is one SDK, not a mistake. Guessing a kwarg
costs a `TypeError` at client construction.

> **`from_environment()` does not read the variable names the API's own documentation uses.** The keys
> in the table are generated from the scheme's parameter names; a vendor that documents
> `ACME_CLIENT_ID` while the SDK reads `CLIENT_ID` leaves `from_environment()` finding nothing and
> returning `None`, with no error raised. Set the names in the table, or pass the credentials
> explicitly.

The snippets below show the **shape** — a credentials object you construct and pass as its own kwarg —
with `{placeholders}` for the identifiers in the table above. The `*_credentials` parameters on
`Configuration.__init__` in `paypalserversdk/configuration.py` are the final word on what this client
accepts; only the schemes your API actually uses are generated.

## Basic auth

```python
import os

from paypalserversdk.http.auth.{basic_module} import {BasicCredentials}
from paypalserversdk.paypal_serversdk_client import PaypalServersdkClient

client = PaypalServersdkClient(
    {basic}_credentials={BasicCredentials}(
        username=os.environ['{API}_USERNAME'],
        password=os.environ['{API}_PASSWORD'],
    )
)
```

## API key — header or query parameter

The key is sent as a header or a query parameter; which one, and under what name, is fixed by the
generated scheme. The credentials class takes **one argument per generated auth parameter**, named after
the parameter in the spec — read `doc/auth/` for the real names:

```python
from paypalserversdk.http.auth.{api_key_module} import {ApiKeyCredentials}

client = PaypalServersdkClient(
    {api_key}_credentials={ApiKeyCredentials}(
        {api_key_param}=os.environ['{API}_KEY'],
    )
)
```

## OAuth 2.0 bearer token

```python
from paypalserversdk.http.auth.{bearer_module} import {BearerCredentials}

client = PaypalServersdkClient(
    {bearer}_credentials={BearerCredentials}(
        access_token=os.environ['{API}_ACCESS_TOKEN'],
    )
)
```

## OAuth 2.0 — client credentials

```python
from paypalserversdk.http.auth.{ccg_module} import {CcgCredentials}

client = PaypalServersdkClient(
    {ccg}_credentials={CcgCredentials}(
        {client_id_arg}=os.environ['{API}_CLIENT_ID'],
        {client_secret_arg}=os.environ['{API}_CLIENT_SECRET'],
    )
)
```

The SDK fetches the token on the first call that needs it and refreshes it when it expires. To persist
the token across restarts, or to hand the SDK a token you already hold, pass the
`o_auth_on_token_update` and `o_auth_token_provider` callbacks. They are **constructor arguments of the
credentials class**, not parameters of the client or `Configuration` — reading
`Configuration.__init__` will not show them — and they keep those exact names whatever the scheme is
called. See [reference.md](reference.md) for the other grants.

> **Do not compute `expiry` yourself.** The SDK compares it against a clock that is the host's *local*
> time read as if it were UTC, so it is displaced from the real epoch by the host's UTC offset. A token
> the SDK fetched and checks in one process is self-consistent — it stamps and compares with the same
> clock — but an `expiry` you derive from a correct UTC epoch is judged against a skewed one, and a
> token restored on a host whose offset differs from the one that saved it is judged against the
> difference between them. Erring early wastes a refresh; erring late hands an expired token to the API
> and surfaces as a `401` your own bookkeeping said could not happen.
>
> So let the SDK stamp `expiry`: pass a token you received from it back unchanged, and use
> `oAuthOnTokenUpdate` to persist whatever it hands you rather than constructing the value. Treat a
> token restored across timezones as unreliable.

## More schemes

For OAuth 2 **authorization code** (the redirect flow, including `get_authorization_url`,
`fetch_token`, `is_token_expired` and `refresh_token`), **resource-owner password**, **custom
authentication**, **multiple schemes**, and reading credentials from the environment, see
[reference.md](reference.md).

## Notes

- **Every argument the credentials class marks as required is validated in `__init__`** — passing
  `None` raises `ValueError` immediately, at client construction, not at the first call.
- A given SDK only exposes the credentials classes and kwargs for the schemes its API uses; the class
  names and their argument names are generated per-API, which is why the samples above carry
  `{...}` placeholders.
- Credentials are set when the client is constructed. To change them later, build a new credentials
  object (or call `clone_with(...)` on the existing one), pass it through
  `client.config.clone_with(...)`, and construct a new client from that configuration — mutating the
  live client does not work.
- Each credentials class has a `from_environment()` classmethod that builds it from a fixed set of
  `UPPER_SNAKE` variables — see [reference.md](reference.md).

## Next

- Step 3, make your first call → **python-calling-endpoints**
- A call that comes back `401` or `403` → **python-error-handling**
