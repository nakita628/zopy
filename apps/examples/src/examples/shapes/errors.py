"""Error customisation and formatting."""

from __future__ import annotations

import json

from zopy import z

from ..show import ok, section


class Account(z.Object):
    name = z.string().min(1)
    email = z.email()


class Form(z.Object):
    user = Account
    tags = z.array(z.string().min(2))
    age = z.int().positive()


class Counter(z.Object):
    a = z.int()


def run() -> None:
    section('Custom messages ({"error": ...})')
    ok("string({error})", z.string({"error": "Text please"}), 1)
    ok("min(5, {error})", z.string().min(5, {"error": "At least 5"}), "a")
    ok(
        "min(5, {error: fn})",
        z.string().min(5, {"error": lambda iss: f"need {iss['minimum']}, got {len(iss['input'])}"}),
        "ab",
    )
    required_or_type = z.string({"error": lambda iss: "Required" if iss["input"] is None else "Wrong type"})
    ok("error fn: missing", required_or_type, None)
    ok("error fn: wrong type", required_or_type, 1)
    ok("per-parse error map", _PerParse(), {"a": "x"})

    section("Global error map (z.config)")
    z.config({"customError": lambda iss: "翻訳: 型が違います" if iss["code"] == "invalid_type" else None})
    ok("localized invalid_type", z.int(), "x")
    ok("other codes fall back", z.int().min(3), 1)
    z.config({"customError": None})

    section("Error shapes")
    result = Form.safeParse({"user": {"name": "", "email": "bad"}, "tags": ["ok", "x"], "age": -1})
    if result.success:
        return
    err = result.error  # ZodError
    print("  issues[0] =", json.dumps(err.issues[0], ensure_ascii=False))
    print("  prettifyError:\n" + "\n".join("    " + l for l in z.prettifyError(err).splitlines()))
    print("  treeifyError:", json.dumps(z.treeifyError(err), ensure_ascii=False))
    print("  flattenError:", json.dumps(z.flattenError(err), ensure_ascii=False))
    with_input = z.int().safeParse("x", {"reportInput": True})
    if not with_input.success:
        print("  reportInput:", with_input.error.issues[0].get("input"))
    print("  toDotPath:", z.toDotPath(["tags", 1, "weird key"]))
    try:
        Form.parse({})
    except z.ZodError as e:
        print(f"  parse() raised ZodError with {len(e.issues)} issues; str() is JSON: {str(e)[:40]!r}...")


class _PerParse:
    """Wrapper so ``ok`` can show a per-parse error map."""

    def safeParse(self, data):  # noqa: N802
        return Counter.safeParse(data, {"error": lambda iss: f"[per-parse] {iss['code']}"})
