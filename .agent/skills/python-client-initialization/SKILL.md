---
name: 'python-client-initialization'
description: 'Construct and configure the PayPal Server SDK Python SDK client. Load before calling `PaypalServersdkClient(...)`, building a `Configuration`, choosing an `Environment`, or wiring the client into an app. The signature won''t tell you transport settings are flat rather than nested, that controllers are properties you read rather than classes you construct, or that one client should be built once and reused.'
---

# Initializing an APIMatic-generated Python SDK client

Package and class names below are concrete for this SDK; replace the remaining `{...}` placeholders
with the real names from its source:

- `{Resource}Controller` — a controller class in `paypalserversdk/controllers/`.
- `{controller}` — the property that exposes it on the client.

## The shape: flat keyword arguments

> Settings are flat keyword arguments on the client constructor — there is no nested options object.

```python
from paypalserversdk.paypal_serversdk_client import PaypalServersdkClient
from paypalserversdk.configuration import Environment

client = PaypalServersdkClient(
    environment=Environment.{MEMBER},
    # auth credential objects — see python-authentication
    timeout=30,          # transport timeout; see python-configuration-resilience
    max_retries=0,
)
```

There is **no builder and no nested options object** — retries, timeout, proxy and the credential
objects all sit directly on the constructor. Open `Configuration.__init__` in
`paypalserversdk/configuration.py` for the exact parameter set **and its defaults**; it varies per API
but always includes `http_client_instance`, `override_http_client_configuration`, `http_call_back`,
`logging_configuration`,
`timeout`, `max_retries`, `backoff_factor`, `retry_statuses`, `retry_methods`, `proxy_settings` and
`environment`, plus the credential objects for the schemes the API uses and any server parameters the
base-URL template needs. `doc/client.md` tabulates the same list with the generated defaults.

The client forwards every one of those to a `Configuration` it creates internally. To build the
configuration yourself, pass it as `config=` instead — the other kwargs are then ignored:

```python
from paypalserversdk.configuration import Configuration

config = Configuration(environment=Environment.{MEMBER}, timeout=30)
client = PaypalServersdkClient(config=config)
```

The live configuration is available afterwards as `client.config`.

## Choosing the environment / base URL

Environments are members of the `Environment` enum in `paypalserversdk/configuration.py`, and each API
server is a member of the `Server` enum beside it. **Read both enums for the real member names before
naming one.**

Do not assume a particular member exists — there may
be no `PRODUCTION` at all. A name also does **not** imply a live host: match each member to the URL it
actually resolves to in the `Configuration.environments` map, not to what its name suggests.

The base URL is **derived** from the selected environment and server by `Configuration.get_base_uri`.
Some SDKs expose server parameters (e.g. a port, or a
template variable) as their own `Configuration` arguments that feed the URL template; `get_base_uri`
shows exactly which. To point the SDK at a mock or proxy that no `Environment` member covers, see
**python-configuration-resilience**.

> **Pass no `environment` and you still get one.** It is a defaulted keyword argument, and the default
> was chosen by the API definition rather than by you — **it may be the live environment**, and nothing
> warns or fails. Read the `environment=` default on `Configuration.__init__` in
> `paypalserversdk/configuration.py` to see which member your SDK starts from.
>
> **Two separate traps beyond that.** The enum's members are numbered in declaration order
> (`= 0`, `= 1`, …), and `Environment.from_value` accepts an **int** as well as a string — so passing
> `0`, or an id that arrived as a number, selects the **first member listed**, which need not be the
> constructor's default. And `from_value` returns its `default` argument for anything it does not
> recognise rather than raising, so a typo resolves to `None` and travels on silently. Convert through
> `from_value` only when you then check the result.

## Configuration from environment variables / a .env file

Both the client and `Configuration` expose a `from_environment` classmethod. It calls
`load_dotenv(...)` first, so a `.env` file is read before the process environment is consulted:

```python
client = PaypalServersdkClient.from_environment()                          # default .env discovery
client = PaypalServersdkClient.from_environment(dotenv_path='/path/to/.env')
```

Any keyword you pass alongside overrides what the environment supplied — the resolved configuration is
run through `clone_with(**overrides)`:

```python
client = PaypalServersdkClient.from_environment(timeout=10)
```

The variable names are `UPPER_SNAKE` and are read literally in `Configuration.from_environment` —
`ENVIRONMENT`, `TIMEOUT`, `MAX_RETRIES`, `BACKOFF_FACTOR`, `RETRY_STATUSES`, `RETRY_METHODS`,
`OVERRIDE_HTTP_CLIENT_CONFIGURATION`, the `PROXY_*` set, plus one per server parameter and per auth
credential. **Grep that method** for the exact list; `doc/environment-based-client-initialization.md`
shows a sample `.env`.

## Accessing controllers — they are properties, not constructors

Each controller is exposed as a lazy property on the client. Do **not** construct a controller yourself:

```python
controller = client.{controller}          # e.g. client.{resource}
result = controller.{operation}()
```

Each one is declared `@LazyProperty`, so the controller is built on first access rather than at client
construction. `doc/client.md` lists every controller property and the class it returns; the client
module itself is the source of truth. Calling operations is covered in **python-calling-endpoints**.

OAuth grant types add a second kind of property: OAuth-using SDKs expose the auth manager itself (e.g.
`client.{o_auth_grant}`) for fetching and refreshing tokens — see **python-authentication**.

## Custom HTTP session, proxy, and callbacks

- `http_client_instance` accepts your own `requests.Session` (or an `HttpClientProvider`
  implementation), letting you control connection pooling, TLS and adapters. Pair it with
  `override_http_client_configuration=True` when you want the SDK's timeout/retry settings applied on
  top of it.
- `proxy_settings` takes a `ProxySettings` object from `paypalserversdk/http/proxy_settings.py`
  (`address`, plus optional `port`, `username`, `password`); `ProxySettings.from_environment()` builds
  one from the `PROXY_*` variables.
- `http_call_back` takes an object implementing `on_before_request(request)` /
  `on_after_response(response)` — the supported hook for observing the raw request and response. See
  **python-testing**.

> **Configuration is read at construction, and its fields are read-only.** Every field the generator
> declares on `Configuration` — `environment`, the server parameters, each `*_credentials` — is an
> `@property` with no setter, so `client.config.{attr} = ...` raises `AttributeError` — worded
> `property '{attr}' of 'Configuration' object has no setter` on Python 3.11+ and `can't set attribute`
> on the earlier versions these SDKs still support (`requires-python = ">=3.7"`). Where an assignment
> does land it is still inert: the client reads its configuration once, in `__init__`. Build a new client, or
> `clone_with` a new `Configuration`, instead. This bites hardest in tests — an `http_call_back` attached
> after the fact leaves you with an empty catcher.

## Client lifetime and reuse

The client builds its `Configuration` and its `GlobalConfiguration` **once**, in `__init__`, and its
controller properties are memoised — treat the client as **long-lived**. Construct it once at startup
and reuse it for the process lifetime; do **not** build a new client per request (that discards
connection pooling and any cached OAuth token).

```python
# startup — construct once:
api_client = PaypalServersdkClient(environment=Environment.{MEMBER})  # + auth

# elsewhere — reuse:
result = api_client.{controller}.{operation}()
```

To produce a variant with a few settings changed (for instance to attach a freshly fetched OAuth token),
call `client.config.clone_with(...)` and build a new client around the result — `clone_with` returns a
**new** `Configuration` rather than mutating the original, and the client does not re-read its config
after construction:

```python
config = client.config.clone_with(timeout=5)
client = PaypalServersdkClient(config=config)
```

## Next

- Configure authentication → **python-authentication**
- Make your first call → **python-calling-endpoints**
- Tune retries/timeouts/proxy → **python-configuration-resilience**
