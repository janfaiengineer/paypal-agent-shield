# Authentication reference (APIMatic Python)

Every auth scheme shape you can meet in one of these SDKs. Every scheme **except custom
authentication** produces a handler class *and* a `{Scheme}Credentials` class in one module under
`paypalserversdk/http/auth/`, and for those only the **credentials class and the client kwarg** concern
you. Custom authentication generates the handler alone — no credentials class to build and no
`doc/auth/` page to read (see *Custom authentication* below). Note that **custom *header* and custom
*query-parameter* schemes are not that case**: they are ordinary API-key schemes with a credentials
class and a page, covered below. The module name, the class name, the argument names and the kwarg name
are all derived from the scheme's name in the spec — with one override, that an SDK whose *only* scheme
is OAuth 2 gets `o_auth_2.py`/`OAuth2` whatever the spec called it. So the snippets below are shaped
correctly but are not necessarily spelled correctly for your SDK — `doc/auth/` carries a page per scheme
*except* custom authentication, with the exact import line for this one.

Every credentials class has the same three-part surface:

- `__init__(...)` — one argument per auth parameter; **required ones raise `ValueError` when `None`**.
- `clone_with(...)` — returns a **new** instance with selected values replaced.
- `from_environment()` — a classmethod that builds the object from `UPPER_SNAKE` environment
  variables, returning `None` if any required variable is missing.

## Basic

```python
from paypalserversdk.http.auth.{basic_module} import {BasicCredentials}

PaypalServersdkClient(
    {basic}_credentials={BasicCredentials}({username_arg}='...', {password_arg}='...')
)
```

Sends `Authorization: Basic base64(username:password)`.

## Custom header / custom query parameter (API key)

One argument per generated auth parameter, named after the spec's parameter name (non-identifier
characters become underscores, so a header called `api-key` becomes `api_key`). Whether the values go
into headers or the query string is fixed by the scheme:

```python
from paypalserversdk.http.auth.{header_module} import {HeaderCredentials}   # header placement
from paypalserversdk.http.auth.{query_module} import {QueryCredentials}     # query placement

PaypalServersdkClient(
    {header}_credentials={HeaderCredentials}({param}='...', {other_param}='...')
)
```

## OAuth 2.0 — bearer token

```python
from paypalserversdk.http.auth.{bearer_module} import {BearerCredentials}

PaypalServersdkClient(
    {bearer}_credentials={BearerCredentials}({access_token_arg}='...')
)
```

## OAuth 2.0 — client credentials grant (machine-to-machine)

```python
from paypalserversdk.http.auth.{ccg_module} import {CcgCredentials}

PaypalServersdkClient(
    {ccg}_credentials={CcgCredentials}(
        o_auth_client_id='...',
        o_auth_client_secret='...',
        # optional:
        # o_auth_scopes=[...]            only when the API declares scopes
        # o_auth_token=<OAuthToken>      a token you already hold
        # o_auth_on_token_update=...     callback(token) fired whenever the token changes
        # o_auth_token_provider=...      callback(last_token, auth_manager) -> token
        # o_auth_clock_skew=0            seconds of slack when checking expiry
    )
)
```

The SDK fetches the token when an endpoint that needs it is called, and refreshes it on expiry.

**Persisting the token.** `o_auth_on_token_update` is called with the new token every time it changes —
use it to write the token wherever you keep it. `o_auth_token_provider` is called when the current token
is missing or expired and is handed `(last_token, auth_manager)`; return a stored token, or call
`auth_manager.fetch_token()` to obtain a fresh one:

```python
def token_provider(last_token, auth_manager):
    token = load_token()
    return token if token is not None else auth_manager.fetch_token()

PaypalServersdkClient(
    {ccg}_credentials={CcgCredentials}(
        o_auth_client_id='...', o_auth_client_secret='...',
        o_auth_token_provider=token_provider,
        o_auth_on_token_update=save_token,
    )
)
```

## OAuth 2.0 — authorization code grant (3-legged)

The redirect flow is driven by you, through the auth manager the client exposes as a property.

```python
from paypalserversdk.http.auth.{acg_module} import {AcgCredentials}

client = PaypalServersdkClient(
    {acg}_credentials={AcgCredentials}(
        o_auth_client_id='...',
        o_auth_client_secret='...',
        o_auth_redirect_uri='https://app.example.com/callback',
        # o_auth_scopes=[...]           only when the API declares scopes
        # o_auth_token=<OAuthToken>     to restore a stored token
    )
)

# 1. send the user here; they come back to your redirect URI with ?code=...
auth_url = client.{o_auth_acg}.get_authorization_url()

# 2. exchange the code, then rebuild the client around the new token
token = client.{o_auth_acg}.fetch_token(code)
credentials = client.config.{o_auth_acg}_credentials.clone_with(o_auth_token=token)
client = PaypalServersdkClient(config=client.config.clone_with({o_auth_acg}_credentials=credentials))
```

Refreshing follows the same shape:

```python
if client.{o_auth_acg}.is_token_expired():
    token = client.{o_auth_acg}.refresh_token()
    # ...clone_with and rebuild the client exactly as above
```

An **explicit** `fetch_token()` / `refresh_token()` raises the SDK's OAuth provider exception (name and
module are generated per SDK — grep `exceptions/` for it, the casing varies). But on the **automatic**
fetch, which is the path every ordinary integration takes, that exception never reaches you: the auth
manager catches it, the token stays unset, and what surfaces is
`apimatic_core.exceptions.auth_validation_exception.AuthValidationException` — **not** a subclass of
`ApiException`, so an `except ApiException` ladder misses it entirely. It is the likeliest OAuth failure
in production, and it is lossy: the message is the handler's static text, so the token endpoint's own
response body is discarded and a bad secret looks identical to an outage. Call `fetch_token()` explicitly
at startup if you need to tell them apart — and catch `ApiException` alongside the OAuth
provider exception, since a token-endpoint status the SDK maps to neither still raises the base class.
**This applies to every grant type, not just this one.**

## OAuth 2.0 — resource owner password grant

```python
from paypalserversdk.http.auth.{ropcg_module} import {RopcgCredentials}

client = PaypalServersdkClient(
    {ropcg}_credentials={RopcgCredentials}(
        o_auth_client_id='...', o_auth_client_secret='...',
        o_auth_username='...', o_auth_password='...',
    )
)

token = client.{o_auth_ropcg}.fetch_token()
```

Then `clone_with` the token onto the credentials and rebuild the client, as in the ACG flow.

## Custom authentication

This is the *custom authentication* scheme type specifically — **not** the custom header / custom query
schemes above, which are ordinary API-key schemes. You can tell them apart by the module: this one holds
the handler class **and nothing else** — no `{Scheme}Credentials` class to build and no `doc/auth/`
page — even though the `{scheme}_credentials` kwarg still exists on the client. The handler is
constructed from the whole `Configuration` and ships with `TODO` markers and an empty `auth_params`: the
credential wiring is left for whoever maintains the SDK to fill in. **Read that file before assuming it
authenticates anything.**

## Multiple / combined schemes

An SDK whose API uses more than one scheme exposes a separate credentials kwarg per scheme; set every
one the operations you call require. Which operations require which scheme (and whether they are
combined with AND or OR) is documented per operation in `doc/controllers/`.

## Credentials from the environment

Each credentials class has a `from_environment()` classmethod reading one variable per auth parameter,
named by upper-snake-casing the parameter. When the API has **more than one** scheme the variable is
additionally prefixed with the scheme name — `O_AUTH_CCG_O_AUTH_CLIENT_ID` rather than
`O_AUTH_CLIENT_ID`. **Grep `from_environment` in the scheme's module for the literal names** rather than
deriving them.

> **Check the literal names before relying on this.** With a single scheme the names are unprefixed —
> `USERNAME` and `PASSWORD` for Basic, for instance. `USERNAME` is always set by the OS on Windows, so
> `from_environment()` will silently pick up your login name instead of failing. If the names are
> generic, set credentials explicitly rather than through the environment factory.

`Configuration.from_environment()` (and `PaypalServersdkClient.from_environment()`) calls each scheme's
`from_environment()` for you, so a fully env-configured client needs no credentials code at all:

```python
client = PaypalServersdkClient.from_environment(dotenv_path='/path/to/.env')
```

> **The grants below are not exhaustive, and their manager methods differ.** An implicit-grant scheme,
> for instance, exposes `get_authorization_url` and `is_token_expired` but **no** `fetch_token` or
> `refresh_token` — calling the nearest-looking section's method is an `AttributeError`. Read the
> manager class this SDK actually generates (`client.{scheme}`) before calling anything on it.

## No auth

An API with no security scheme generates no `http/auth/` package and no credentials kwargs — there is
nothing to set.

## Discovering what a specific SDK uses

1. List the `*_credentials` parameters on `Configuration.__init__` in `paypalserversdk/configuration.py`
   — this is the **source of truth** for what the SDK accepts.
2. Open the scheme's module under `paypalserversdk/http/auth/` for the credentials class and the
   arguments its `__init__` takes.
3. Only if you also have the SDK's **source repository** (see **python-getting-started**): the matching
   page under `doc/auth/` repeats the credential names, the client kwarg and a ready-made snippet.
   Custom authentication is the only scheme with no page.
