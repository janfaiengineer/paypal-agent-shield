---
name: 'python-models'
description: 'Build and read the non-obvious model shapes of the PayPal Server SDK Python SDK — optionals, enums, oneOf/anyOf unions, dates, collections, `additional_properties`. Load when a field is anything but a plain string or number, or when an attribute you expected is missing. The class body won''t tell you an omitted optional is *absent* from the instance, not `None` — `hasattr`, not `is None`, is the check.'
---

# Working with models in an APIMatic Python SDK

Most request/response data are plain Python objects under
`paypalserversdk/models/` (covered in `python-calling-endpoints`). This skill covers the **non-obvious
model shapes** that trip integrations up. The patterns are generic across APIMatic Python SDKs; take the
real names from your SDK source.



> `doc/models/*.md` carries one page per model — field table, types, and a **Default** column. Read it
> alongside the class body; `doc/models/containers/` covers union types.

## Anatomy of a generated model

Each model class carries two or three class-level tables that tell you everything about its wire
behaviour — `_nullables` is generated only for models that have a nullable attribute:

- `_names` — maps the Python attribute name to the **API property name**. When the two differ (`mtype`
  for a property called `type`, `person_type` for `personType`), this is the mapping that explains it.
- `_optionals` — the attributes that may be omitted.

Plus a `from_dictionary(dictionary)` classmethod, which is how the SDK deserializes responses. You
rarely call it directly, but it is the definitive answer to how a given field is parsed.

## Optional attributes: absent, not `None`

An attribute in `_optionals` defaults to `APIHelper.SKIP`, and the constructor **only assigns it when
you pass something else**. So on both the request and the response side:

```python
model = {Model}({required_attr}=1)     # {optional_attr} never assigned — unless it has a spec default

model.{optional_attr}                  # -> AttributeError, not None
hasattr(model, '{optional_attr}')      # -> False   <- the correct check
getattr(model, '{optional_attr}', None)
```

Reaching straight for `model.{optional_attr}` on a response is the single most common way to turn a
perfectly good API call into an `AttributeError`. Use `hasattr` / `getattr(..., default)` for anything
listed in `_optionals`. Attributes that are *not* optional are always assigned, defaulting to `None`.

> **A falsy value can come back absent too.** For a plain scalar optional, `from_dictionary` tests
> truthiness rather than key presence, so a present `0` or `""` lands as absent. Boolean, model-typed
> and nullable optionals test `if "key" in dictionary` instead and survive. Read the attribute's line in
> `from_dictionary` when a falsy value matters to you rather than assuming either rule.

## Union types (oneOf / anyOf)

**Check this SDK has any before reading on:** `ls paypalserversdk/utilities/`. No
`union_type_lookup.py` there means the API declares no `oneOf`/`anyOf` type and nothing below is
generated — no validation runs, and the field is an ordinary attribute. Skip to the next section.

Python unions have **no wrapper class and no factory helpers**. A union-typed parameter or attribute
simply holds one of the variant values — a model instance, or a primitive:

```python
result = client.{controller}.{operation}({Variant}({attr}='...'))       # shape 1
result = client.{controller}.{operation}({'{param}': {Variant}(...)})   # shape 2
```

How the variant goes in is the *operation's* parameter shape, not the union's — read the `def` line
first (see **python-calling-endpoints**).

Read them back by narrowing with `isinstance`:

```python
if isinstance(result.body, {Variant}):
    ...
```

The variants for a given union are listed in its page under **`doc/models/containers/`** — that page is
the only place the union is named; there is no corresponding `.py` file.

### The failure mode to know about

**Only a union that is a direct operation parameter is validated.** A union nested inside a request
body model is serialized as-is, with no check — the common case, and the failure then comes back from
the server. Grep `.validator(` in `paypalserversdk/controllers/` to see which operations validate.

A union parameter is validated **client-side, when you make the call**, before any HTTP request goes
out: the request builder runs the value through `UnionTypeLookUp` (in
`paypalserversdk/utilities/union_type_lookup.py`). A value that matches none of the variants — or, for
`oneOf`, matches more than one — fails there, so the traceback points at your call rather than at the
server. Read the union's page under `doc/models/containers/` and, when a discriminator is involved, set
it explicitly before debugging anything else.


## Polymorphic models

**Check this SDK has any before reading on:** `grep -rl discriminator paypalserversdk/models/`. No hits
means every generated model is a plain `class X(object)` with no subtype, nothing below applies, and a
subtype-named import will raise `ModuleNotFoundError`.

A model with subtypes deserializes by **discriminator**: `{Base}.from_dictionary` reads the
discriminator attribute and returns the matching subclass, so an operation documented as returning
`{Base}` can hand you a `{Subtype}`. Check with `isinstance` before reading subtype-only attributes, and
read the base class to find the discriminator's name — it is an ordinary attribute, listed in `_names`
like any other. A base and every subtype derived from it are emitted into **one module, named after the
base** — there is no `models/{subtype}.py`, so an import built from the subtype's own name raises
`ModuleNotFoundError`. Import the subtype from the base's module; the import line on
`doc/models/{subtype}.md` already points there.

## Collections

List attributes are plain Python lists, maps are plain dicts — assign them directly:

```python
model = {Model}(
    {list_attr}=['A', 'B'],
    {map_attr}={'key': 'value'},
)
```

## Dates and date-times

**Check first whether this SDK converts dates at all:**
`grep -rl apply_datetime_converter paypalserversdk/models/`. No hits means **every temporal field is a
plain `str`** — passed through verbatim in both directions, with no wrapper, no parsing and no format
checking. You format and parse it yourself, in whatever format the API documents. That is a common
outcome, and everything below this paragraph then does not apply to your SDK.

Where the grep *does* hit: a plain `date` field is a `datetime.date`, and a date-**time** field is
wrapped in one of the `APIHelper` classes so the SDK knows which wire format to write —
`APIHelper.RFC3339DateTime`, `APIHelper.HttpDateTime` or `APIHelper.UnixDateTime`. The model's
constructor applies the right wrapper via `APIHelper.apply_datetime_converter`, so you pass an ordinary
`datetime` and read the wrapper back. Each wrapper has `from_datetime` / `from_value`.

> **Pass timezone-aware datetimes.** The wrappers do not agree on how to treat a naive one:
> `RFC3339DateTime` writes it verbatim, while `HttpDateTime` reinterprets it as *local* time and labels
> the result GMT. The same naive `datetime` therefore goes on the wire shifted by your host's UTC offset
> in one field and unshifted in another, with nothing to signal it. Build datetimes with an explicit
> `tzinfo` and convert to UTC yourself.

## Enums

Enums are plain classes, **not** `enum.Enum`, whose members are the raw wire values:

```python
from paypalserversdk.models.{enum_module} import {EnumType}

{EnumType}.MEMBER == 'member_value'      # True — the member *is* the value
```

So a plain string or integer is interchangeable with the member, and comparing a response attribute to
`{EnumType}.MEMBER` with `==` works. `{EnumType}.from_value(value, default=None)` converts leniently
(case-insensitive, falling back to `default`) for values that come in from configuration or user input.

## Unknown / future fields

Models declare their attributes explicitly, and unknown JSON fields are **dropped** on deserialization —
unless the model was generated with an `additional_properties` bag, in which case they land there as a
`dict`. Check the model's `__init__` for an `additional_properties` parameter; if it has none and you
need an unmodeled field, regenerate the SDK or parse that response yourself.

## Next

- Step 5, errors and status codes → **python-error-handling**
- Back to the call that returned this shape → **python-calling-endpoints**
