# enforce-type

Independent pure-Python compiled validation for ordinary type annotations.
Python 3.14+, no runtime dependencies, no required model base class.

```sh
python -m pip install enforce-type==0.1.0
```

```python
from dataclasses import dataclass
from enforce_type import compile_type

@dataclass
class User:
    name: str
    age: int
    active: bool = True

users = compile_type(User)
user = users.load({"name": "Ella", "age": 34})
assert users.check(user) is user
assert users.dump(user) == {"name": "Ella", "age": 34, "active": True}
assert users.load_partial({"active": False}) == {"active": False}
```

Compile at application setup, then reuse the plan. Annotation resolution happens
during compilation; value operations execute immutable nodes with their own
invocation-local scratch state. Plans can be shared across concurrent callers.
Version 0.1.0 provides a synchronous engine; async I/O rules and bounded async
batches are future work. No thread or event loop starts automatically.

## Four explicit operations

| Operation | Contract |
| --- | --- |
| `check(value)` | Validate a native Python value and return that same object. |
| `load(data, mode="json")` | Validate decoded data and construct Python values. |
| `dump(value, mode="json")` | Validate native values and serialize supported data. |
| `load_partial(data, mode="json")` | Validate supplied dataclass fields and return a change dictionary. |

`load` and `dump` also accept `mode="python"`. The default JSON mode operates on
decoded Python data; it does not parse JSON text or enforce HTTP/media/body rules.
`check` always validates native Python types without conversion. Mutable dataclass
assignments are not automatically enforced; call a plan at the desired boundary.

```python
from uuid import UUID

identity = compile_type(UUID)
value = identity.load("00000000-0000-0000-0000-000000000001")
assert identity.dump(value) == "00000000-0000-0000-0000-000000000001"
assert identity.load(value, mode="python") is value

point = compile_type(tuple[float, float])
assert point.load([12.5, 17.2]) == (12.5, 17.2)
```

## Supported types and modes

| Annotation | Native Python | JSON load / dump |
| --- | --- | --- |
| `str`, `bool`, `int`, `None` | Exact primitive types | Same, with valid Unicode strings |
| `float` | Actual finite float | Load finite integer/float numbers; dump a native float |
| UUID | Actual UUID | UUID string representation |
| Enum | Actual member | Finite primitive member value |
| Literal | Type-sensitive choices, including supported enum members | Corresponding value representation |
| Union / nullable | First successful compiled branch | Same, with branch-specific construction |
| `list[T]` | Built-in list | Array / list |
| `tuple[A, B]`, `tuple[T, ...]` | Fixed or variadic built-in tuple | Array / list |
| `dict[K, V]` | Built-in dictionary with supported scalar keys | Keys must actually be strings |
| dataclass | Instance with valid declared fields | Construct from / serialize to a field dictionary |

Primitive rules are strict. `True` does not pass for `int`, and `"42"` does not
become an integer. A native float contract rejects integer objects during `check`,
Python-mode load, and dump. JSON loading accepts an integer number for a float
field and returns a float. NaN and infinity are rejected in every mode.

Python-mode load requires native UUIDs, enums and tuples; it can also construct
dataclasses from dictionaries. Python-mode dump turns dataclasses into dictionaries
while retaining native UUIDs/enums/tuples. Loading/dumping containers creates new
containers. Existing native dataclass instances supplied to Python-mode load are
validated and returned unchanged; this is not a general deep-copy facility.

Dictionary keys are always type-checked without conversion, preventing entry
collisions. Thus `dict[int, str]` works in Python mode but cannot load `{"1":"x"}`
as an integer-keyed dictionary or dump integer keys to JSON. Dynamic key names are
omitted from errors. Python strings may contain surrogates; JSON load/dump rejects
them. Union branch errors remain isolated and unsuccessful branches collapse into
one stable union issue. Ambiguous unions use the order exposed by Python's typing
system; prefer unambiguous contracts.

Unsupported annotations raise `SchemaError` at compilation. The initial release
rejects Any, bare containers, empty-tuple annotations, sets, abstract collections,
TypedDict, TypeVar/generic models, PEP 695 alias objects, NewType, Callable/Protocol,
recursive models and general coercion. Assignment aliases
that already resolve to supported types work. There is no implicit Any fallback.

## Ordinary dataclasses

Nested, inherited, frozen, slots and keyword-only dataclasses work. `fields` is an
immutable tuple of `FieldInfo(name, annotation, required, init,
has_default_factory)` descriptions. ClassVars and properties are not fields.
Subclasses are accepted during instance checking, but dump includes only the
fields declared by the compiled model.

Defaults/factories run through ordinary construction and the complete result is
validated after `__post_init__`. Invalid supplied fields prevent that model's
construction. `init=False` fields are checked/dumped after construction and reject
input; they need to be populated by the model. InitVars, class-wide `init=False`
and incompatible constructor signatures are unsupported.

Constructors, factories and attribute access are application code. Keep them fast
and free of external side effects; validation cannot roll back those effects.
Ordinary failures become value-free issues. Control-flow BaseExceptions propagate.
Compile trusted schemas only: resolving annotations can execute Python code.

Partial loading does not construct the root model, run its factories, supply
omitted defaults, assign attributes, or enforce cross-field constructor invariants.
Supplied nested models are complete values and can apply their own defaults.
Applying changes and validating the resulting object remain caller responsibilities:

```python
from dataclasses import replace

changes = users.load_partial({"active": False})
updated = replace(user, **changes)
users.check(updated)
```

## Annotation constraints

Use immutable `Min`, `Max` and `Length` rules with `typing.Annotated`:

```python
from typing import Annotated
from enforce_type import Length, Max, Min

quantity = compile_type(Annotated[int, Min(0), Max(999)])
name = compile_type(Annotated[str, Length(min=1, max=100)])
assert quantity.load(12) == 12
assert name.check("Ella") == "Ella"
```

`Min` and `Max` are inclusive finite numeric bounds for `int` or `float`.
`Length(min=0, max=None)` counts Unicode code points for strings and entries for
supported lists, tuples and dictionaries. Rules apply to every operation,
including nested values, dictionary keys, defaults and post-init results. Bounds
apply to native values after JSON conversion. Length failures prevent element
construction; configured item limits still take precedence. Annotated wrappers
do not consume extra runtime depth.

Rules compose in declaration order. Invalid configurations, contradictory bounds,
inapplicable rules and unknown Annotated metadata raise `SchemaError` at compile
time. Apply rules inside nullable/union branches, such as
`Annotated[int, Min(0)] | None`. Error codes are `min`, `max`, `min_length` and
`max_length`, with static expected-type labels that omit inputs and bounds.

An `id` is an ordinary field. Persistence, immutable identities, authorization and
read/write visibility are caller-owned policies. All declared fields are included
in dump. Unrelated dataclass metadata is ignored; the `enforce_type` metadata
namespace is reserved and currently rejected rather than silently appearing
enforced.

## Structured errors and bounds

```python
from enforce_type import Limits, ValidationError, compile_type

counts = compile_type(list[int], limits=Limits(max_items=100, max_errors=2))
try:
    counts.load(["wrong"])
except ValidationError as error:
    assert error.issues[0].as_dict() == {
        "path": [0], "code": "type", "expected": "int"
    }
```

Issues are immutable, ordered data: path, code and a static expected-type label.
Messages/issues omit submitted values and unknown or dynamic dictionary keys;
dictionary paths use `"*"`. Python tracebacks remain normal Python tracebacks, so
applications should not expose traceback locals to clients.

Codes include type, missing, unknown_field, init_field, length, finite, uuid,
unicode, enum, literal, union, json_key, depth, collection_size, construction and
attribute. Invalid schema/configuration raises `SchemaError` separately.

Default limits are depth 32, 1,000 entries per container or full-model fields, and
20 issues per call. Oversized structures fail before element traversal; reaching
the issue cap stops further work. Partial input limits apply to supplied fields.
Compilation has a separate 64-level type-graph bound, including reused subtrees.
Bounds do not limit already allocated input bytes, total application memory, or
arbitrary constructor execution. Do not mutate shared inputs/model definitions
while another call is validating them. User factories are responsible for their
own thread safety. Threaded reuse is verified; CPU speedups are not claimed.

## Development

```sh
uv sync --locked
uv run --frozen python examples/users.py
uv run --frozen python -W error::ResourceWarning -m unittest discover -s tests -v
uv run --frozen python scripts/check_distribution.py
```

CI tests Linux, macOS and Windows/Python 3.14. Distribution checks use exact
allowlists, verify metadata and zero runtime requirements, rebuild the source
distribution, and run independent wheel/source installations outside the checkout.
Release publishing uses `release.yaml`, environment `pypi` and OIDC; verified
artifacts are the exact uploaded files.

The [Project](https://github.com/orgs/outside-labs/projects/15) and
[issues](https://github.com/outside-labs/enforce_type/issues) track future constraints,
coercion, broader typing, async rules/batches, function enforcement and JSON Schema.
The package remains independent of expose-api and its validation infrastructure.
License terms have not yet been specified.
