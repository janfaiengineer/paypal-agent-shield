---
name: 'python-getting-started'
description: 'Entry point for integrating the PayPal Server SDK Python SDK (APIMatic-generated, apimatic-core over `requests`). Carries the SDK''s identity — package, client class, environments, base exception — the generated source layout, and the placeholder legend the companion skills use. Load this first, before any other python-* skill.'
---

# Getting started with an APIMatic-generated Python SDK

This is the **SDK-specific** reference and grounding layer, and the entry into the companion `python-*`
skills. The SDK is built on the shared `apimatic-core` runtime packages, with `requests` as the
transport. For the general patterns that apply
to *any* such SDK (client setup, auth, calling endpoints, models, error handling, retries, testing), see
the companion API-agnostic skills: `python-client-initialization`, `python-authentication`,
`python-calling-endpoints`, `python-models`, `python-error-handling`,
`python-configuration-resilience`, `python-testing`.

> **Before writing any integration code, locate the SDK source on disk** (see the *SDK source* section
> below) and read it to confirm every signature, attribute, enum, and exception type as you go. The
> source is obtained exactly as that section describes. Do **not** vendor or edit it inside your project;
> regenerate the SDK instead if something needs to change.

## SDK identity

| | |
| --- | --- |
| API | `PayPal Server SDK` |
| Runtime dependencies | `apimatic-core`, `apimatic-core-interfaces`, `apimatic-requests-client-adapter`, `python-dotenv` — see `dependencies` in `pyproject.toml` (mirrored in `requirements.txt`) |
| pip distribution | `paypal-server-sdk` (version `2.4.0`) — the `name` under `[project]` in `pyproject.toml` |
| Import package | `paypalserversdk` — the top-level directory beside `pyproject.toml`; **not necessarily the same string as the pip distribution id** |
| Install | `pip install paypal-server-sdk` |
| Client | `PaypalServersdkClient` in `paypalserversdk/paypal_serversdk_client.py`, constructed with **keyword arguments** |
| Configuration | a `Configuration` object in `paypalserversdk/configuration.py`; pass its fields as client kwargs, or build one and pass `config=` |
| Auth | when the API declares a scheme: `{Scheme}Credentials` objects under `paypalserversdk/http/auth/`, passed as `{scheme}_credentials=` kwargs — **except custom *authentication***, the one scheme whose module holds a lone handler class with `auth_params = {}` and `TODO` markers and no credentials class (custom *header* and custom *query-parameter* schemes are ordinary API-key schemes and do get one). No `http/auth/` directory means no auth — see **python-authentication** |
| Environment | an `Environment` enum (and a `Server` enum) in `paypalserversdk/configuration.py` — read them for the real member names |
| Controllers | `{Resource}Controller` classes reached as **properties on the client** (`client.{controller}`), not constructed by you |
| Return type | an **`ApiResponse` envelope** — the payload is on `.body`, with `.status_code`, `.headers`, `.text` and `.errors` alongside |
| Logging | built in only when generated with logging — check for `paypalserversdk/logging/` and a `logging_configuration` client parameter |
| Base exception | `ApiException` in `paypalserversdk/exceptions/api_exception.py` — raised on non-2xx; see **python-error-handling** |
| Transport | `requests`, wrapped by `RequestsClient` from `apimatic-requests-client-adapter` |

Both were recorded with this SDK, so they are the coordinates a consumer installs rather than whatever this build happened to produce. Pin them as they stand.

## Package layout

Everything lives under the import package `paypalserversdk/`:

- `paypalserversdk/paypal_serversdk_client.py` — `PaypalServersdkClient`: the constructor, the controller properties,
  `from_environment(...)`, and (for OAuth) the auth-manager properties.
- `paypalserversdk/configuration.py` — the `Configuration` class (its `__init__` parameters **and their
  defaults**), `clone_with`, `create_http_client`, the `environments` map, `get_base_uri`, the
  `Environment` and `Server` enums (only when the SDK generates models), and `from_environment`'s
  environment-variable names.
- `paypalserversdk/controllers/` — one `{Resource}Controller` per API group, each extending
  `BaseController`.
- `paypalserversdk/models/` — plain classes for models and enums. **A module is not always one class,
  and not every documented type has a module of its own name.** Three things put a documented type
  somewhere other than `models/{model}.py`: a digit-prefixed name is re-cased (`P24PaymentObject` ->
  `p_24_payment_object.py`); a **subtype is emitted into its base's module**, so it has no file of its
  own; and a type the API documents as an *error* model gets no `models/` module at all — its class
  lives in `paypalserversdk/exceptions/`, and its `doc/models/{model}.md` page is the one kind that
  carries no import line. Take the import line from that page for everything else. **This is where
  attribute names, the `_names` wire-name map, optionality, and enum members live.**
- `paypalserversdk/exceptions/` — `api_exception.py` (the base `ApiException`) plus one module per typed
  error model the API documents.
- `paypalserversdk/http/` — `api_response.py` (the `ApiResponse` envelope),
  `http_call_back.py`, `http_request.py`, `http_response.py`,
  `proxy_settings.py`, `http_method_enum.py`, and `http/auth/` when the API uses authentication.
- `paypalserversdk/utilities/` — `file_wrapper.py`, plus `union_type_lookup.py` (only when the API has
  oneOf/anyOf types) and `pagination/` (only when it has paginated operations).
- `paypalserversdk/api_helper.py` — `APIHelper`, including the `SKIP` sentinel and the date-time
  wrappers. **The class body is empty — do not read this file to decide what it offers.** It is
  `class APIHelper(CoreApiHelper)`, a docstring and nothing else, so every member you call is inherited
  and grepping the generated file finds nothing. That absence is not evidence a member is missing;
  follow the import into `apimatic-core` to read one.
  **The base is imported under an alias** (`from apimatic_core.utilities.api_helper import ApiHelper as
  CoreApiHelper`), so grepping for its real name in this file also comes up empty.
- `paypalserversdk/logging/` — `LoggingConfiguration` and the request/response halves, when generated.

## Install

This SDK is published out of `https://github.com/paypal/PayPal-Python-Server-SDK`, branch `main` — take that branch explicitly rather than the repository default, which is not necessarily where this SDK is released from. Which registry that pipeline pushes to is a property of the pipeline rather than of the SDK. Try the install command below as-is first: if it resolves, the package is on the public registry and there is nothing further to configure. Only if it 404s do you need the feed — take it from the repository's publish workflow, or from whoever owns the pipeline, and configure that registry before retrying.

Install into a **virtual environment**: the SDK pins `apimatic-core*` versions and will otherwise
fight whatever else is installed machine-wide.

```bash
pip install paypal-server-sdk
```

If that points at a path rather than an index, it is because this SDK was not published — install from
the unpacked directory you were given (the one containing `pyproject.toml`).

Record it wherever the consuming project declares its dependencies — `requirements.txt`, or
`[project].dependencies` in its own `pyproject.toml` — pinned, because regenerating the SDK bumps the
version and an unpinned entry moves the surface silently:

```
paypal-server-sdk==2.4.0
```

Confirm what resolved — pip treats an already-satisfied requirement as nothing to do:

```bash
pip show paypal-server-sdk
```

```python
from paypalserversdk.paypal_serversdk_client import PaypalServersdkClient
from paypalserversdk.configuration import Environment
from paypalserversdk.exceptions.api_exception import ApiException
```

**Imports are full module paths.** The package's `__init__.py` only declares an `__all__` of submodule
names — it re-exports no classes — so `from paypalserversdk import PaypalServersdkClient` does **not** work.
Import each name from the module that defines it, exactly as the `doc/` snippets do.

## SDK source — read it in place

You will constantly need to confirm real constructor/method signatures, model attributes, enum members
and exception types, and the **only reliable way** is to read the SDK source.

Clone it and read the clone — it is the source this pack documents:

```bash
git clone --filter=blob:none --branch main https://github.com/paypal/PayPal-Python-Server-SDK
```

**The clone is a branch; your install is pinned.** Check out the tag matching `2.4.0`, the version installed above before you read anything from it — a branch keeps moving after a release is cut, so the default checkout can be a different SDK than the one you compile against, and nothing in the tree will tell you. `git ls-remote --tags` lists what the repository offers; if no tag matches, treat every signature you read as unconfirmed rather than assuming it carried over. Clone it outside your project directory and treat it as read-only. It is a reference, not a dependency: what you build against is the package installed above, never this checkout.

An existing copy, if you already have one, is in whichever of these applies:

- the **unpacked SDK directory** you were given (the one containing `pyproject.toml` and
  `paypalserversdk/`); or
- the installed package inside your virtual environment's `site-packages/paypalserversdk/`.

Treat it as a read-only reference and grep it locally.

Layout — grep here first:

- `pyproject.toml` — the pip `name`, `version`, `requires-python`, and the `apimatic-*` dependencies.
- `paypalserversdk/configuration.py` — the `Configuration.__init__` parameters and defaults, the
  `environments` map, the env-var names in `from_environment`, and the `Environment`/`Server` enums
  (only when the SDK generates models — without them the map is keyed by plain strings).
- `paypalserversdk/paypal_serversdk_client.py` — the client constructor and the controller properties.
- `paypalserversdk/controllers/*.py` — operation methods and their real parameter names.
- `paypalserversdk/models/` — model attributes, the `_names` map, and enum members.
- `paypalserversdk/exceptions/` — the base `ApiException` and any typed subclasses.
- `README.md` and `doc/` — a generated, human-readable index: `doc/client.md`, `doc/auth/*.md`,
  `doc/controllers/*.md`, `doc/models/*.md`, `doc/models/containers/*.md`,
  `doc/environment-based-client-initialization.md`, `doc/proxy-settings.md`, `doc/http-response.md`,
  `doc/api-helper.md`, and `doc/api-response.md` when the SDK wraps responses. In the repository, it is the fastest way to find an operation, its
  parameters, its error table, and a copy-pasteable snippet; then open the `.py` file for the exact
  signature. **It is not in the installed package** — `site-packages/paypalserversdk/` holds the
  importable module and nothing else, so `pip install` never puts `doc/` on disk. One `ls` of that
  parent settles it. With only the package, `paypalserversdk/controllers/` is the equivalent
  starting point and the operation's own signature replaces the snippet.

## Placeholder legend

Samples across these skills write `{...}` for a name that differs per API. **They are never literal** —
resolve each one from this SDK's source before you write code. Anything already concrete for this SDK
(distribution name, module, client class, API name) is spelled out for you; if it is still in braces, it
is yours to look up.

| Placeholder | Stands for | Resolve it from |
| --- | --- | --- |
| `{controller}` | the client property a controller hangs off, as in `client.{controller}` | the `@LazyProperty` definitions on the client class |
| `{Resource}` | the stem a controller class name is built from — it is always written `{Resource}Controller`, never alone | a class name in the SDK's `controllers/` folder, with its `Controller` ending removed |
| `{operation}` | an operation method on a controller | the controller class body, or the operation list in `doc/controllers/` |
| `{param}`, `{required_param}`, `{optional_param}`, `{enum_param}`, `{arg}` | one parameter of the operation you are calling | that operation's signature; optional operation parameters default to `None` or the spec's default — the `APIHelper.SKIP` sentinel is a *model constructor* thing |
| `{Model}` | a generated model class | the SDK's `models/` folder |
| `{attr}`, `{required_attr}`, `{optional_attr}`, `{typed_field}` | one attribute of a model | that model's `__init__` signature |
| `{EnumType}`, `{MEMBER}` | a generated enum and one of its members | the SDK's `models/`; `{MEMBER}` also covers `Environment` members in `configuration.py`, where that enum is generated |
| `{Variant}`, `{VariantA}`, `{VariantB}` | a oneOf/anyOf union variant | the union's module under `models/` |
| `{Name}` | an `Environment` member (where that enum is generated — otherwise the plain string that keys the `environments` map), or a model class, depending on context | `configuration.py` or `models/` — the surrounding sentence says which |
| `{Scheme}`, `{scheme}` | an auth scheme, as it names the `{Scheme}Credentials` class and the `{scheme}_credentials=` kwarg — custom *authentication* is the one scheme with the kwarg but no credentials class | the SDK's `http/auth/` folder; `doc/auth/` has a page per scheme *except* custom authentication |
| `{basic}`, `{bearer}`, `{ccg}` | the scheme key for one specific scheme, as in `{basic}_credentials=` | the client constructor's keyword arguments |
| `{basic_module}`, `{bearer_module}`, `{ccg_module}` | the module under `http/auth/` that scheme's classes live in | the file names in the SDK's `http/auth/` folder |
| `{BasicCredentials}`, `{BearerCredentials}`, `{CcgCredentials}` | that scheme's credentials class, imported from its module | the class declared in the module above |
| `{o_auth_grant}`, `{o_auth_acg}`, `{o_auth_ropcg}`, `{basic_auth_credentials}`, `{api_key_param}` | the specific credentials kwarg or field for one scheme | the client constructor signature, and `doc/auth/` |
| `{API}` | the API name as it appears in generated identifiers | the client class name in the SDK root |
| `{basic_module}`, `{api_key_module}`, `{header_module}`, `{query_module}`, `{bearer_module}`, `{ccg_module}`, `{acg_module}`, `{ropcg_module}` | the module under `http/auth/` holding one scheme's credentials class | `ls paypalserversdk/http/auth/`, or the scheme's page in `doc/auth/` |
| `{BasicCredentials}`, `{ApiKeyCredentials}`, `{HeaderCredentials}`, `{QueryCredentials}`, `{BearerCredentials}`, `{CcgCredentials}`, `{AcgCredentials}`, `{RopcgCredentials}` | one scheme's credentials class | the `class` line in that module — the name is generated from the scheme as the spec declares it |
| `{basic}`, `{api_key}`, `{header}`, `{bearer}`, `{ccg}`, `{acg}`, `{ropcg}` | the client kwarg prefix for one scheme, as in `{ccg}_credentials=` | the `*_credentials` parameters on `Configuration.__init__` |
| `{username_arg}`, `{password_arg}`, `{access_token_arg}`, `{client_id_arg}`, `{client_secret_arg}` | one constructor argument of a credentials class | that class's `__init__`, or `doc/auth/` |
| `{q}`, `{filter}`, `{placeholder}`, `{name}` | a stand-in value in an example | nothing to look up — substitute your own |

Any other `{...}` you meet is a local example; the sentence around it says what belongs there.

## Integration workflow — load the companion skill at each step

**Load the skill named for a step before you write that step's code, even where you have already read
the source.** The generated source is authoritative for the SDK's *surface*; these skills carry the
usage rules a signature cannot show, and each one names the trap that surface hides.

1. **python-client-initialization** — before you construct the client.
2. **python-authentication** — before you set credentials, and when a call returns 401 or 403.
3. **python-calling-endpoints** — before the first operation call.
4. **python-models** — as soon as a request or response field is not a plain string or number.
5. **python-error-handling** — before your first `try`/`except` around a call.
6. **python-configuration-resilience** — before you ship. Its subject is the client's *defaults*, which apply whether or not you set anything, so this step is not conditional on changing one.
7. **python-testing** — before you stub the SDK.

## Next

- Step 1, construct the client → **python-client-initialization**

Every skill below ends with the step after it, so the footers walk the workflow above in order rather than offering a menu beside it.
