"""Default (English) error messages, mirroring ``zod/locales/en``."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from ._util import format_number, get_parsed_type, join_values, stringify

SIZABLE: dict[str, dict[str, str]] = {
    "string": {"unit": "characters", "verb": "to have"},
    "file": {"unit": "bytes", "verb": "to have"},
    "array": {"unit": "items", "verb": "to have"},
    "set": {"unit": "items", "verb": "to have"},
    "map": {"unit": "entries", "verb": "to have"},
}

NOUNS: dict[str, str] = {
    "regex": "input",
    "email": "email address",
    "url": "URL",
    "emoji": "emoji",
    "uuid": "UUID",
    "uuidv4": "UUIDv4",
    "uuidv6": "UUIDv6",
    "uuidv7": "UUIDv7",
    "nanoid": "nanoid",
    "guid": "GUID",
    "cuid": "cuid",
    "cuid2": "cuid2",
    "ulid": "ULID",
    "xid": "XID",
    "ksuid": "KSUID",
    "datetime": "ISO datetime",
    "date": "ISO date",
    "time": "ISO time",
    "duration": "ISO duration",
    "ipv4": "IPv4 address",
    "ipv6": "IPv6 address",
    "mac": "MAC address",
    "cidrv4": "IPv4 range",
    "cidrv6": "IPv6 range",
    "base64": "base64-encoded string",
    "base64url": "base64url-encoded string",
    "json_string": "JSON string",
    "e164": "E.164 number",
    "currency_code": "currency code",
    "credit_card": "credit card number",
    "iban": "IBAN",
    "jwt": "JWT",
    "hostname": "hostname",
    "hex": "hexadecimal string",
    "template_literal": "input",
    "lowercase": "lowercase string",
    "uppercase": "uppercase string",
}


def parsed_type_of_issue(issue: Mapping[str, Any]) -> str:
    received = issue.get("received")
    if received is not None:
        return received
    return get_parsed_type(issue.get("input"))


def en_error(issue: Mapping[str, Any]) -> str:
    code = issue.get("code")
    if code == "invalid_type":
        return f"Invalid input: expected {issue.get('expected')}, received {parsed_type_of_issue(issue)}"
    if code == "invalid_value":
        values = list(issue.get("values", []))
        if len(values) == 1:
            return f"Invalid input: expected {stringify(values[0])}"
        return f"Invalid option: expected one of {join_values(values, '|')}"
    if code == "too_big":
        adj = "exactly " if issue.get("exact") else ("<=" if issue.get("inclusive") else "<")
        origin = issue.get("origin") or "value"
        sizing = SIZABLE.get(origin)
        maximum = format_number(issue.get("maximum"))
        if sizing:
            return f"Too big: expected {origin} {sizing['verb']} {adj}{maximum} {sizing['unit']}"
        return f"Too big: expected {origin} to be {adj}{maximum}"
    if code == "too_small":
        adj = "exactly " if issue.get("exact") else (">=" if issue.get("inclusive") else ">")
        origin = issue.get("origin") or "value"
        sizing = SIZABLE.get(origin)
        minimum = format_number(issue.get("minimum"))
        if sizing:
            return f"Too small: expected {origin} {sizing['verb']} {adj}{minimum} {sizing['unit']}"
        return f"Too small: expected {origin} to be {adj}{minimum}"
    if code == "invalid_format":
        fmt = issue.get("format")
        if fmt == "starts_with":
            return f"Invalid string: must start with {stringify(issue.get('prefix'))}"
        if fmt == "ends_with":
            return f"Invalid string: must end with {stringify(issue.get('suffix'))}"
        if fmt == "includes":
            return f"Invalid string: must include {stringify(issue.get('includes'))}"
        if fmt == "regex":
            return f"Invalid string: must match pattern {issue.get('pattern')}"
        return f"Invalid {NOUNS.get(str(fmt), fmt)}"
    if code == "not_multiple_of":
        return f"Invalid number: must be a multiple of {format_number(issue.get('divisor'))}"
    if code == "unrecognized_keys":
        keys = list(issue.get("keys", []))
        plural = "s" if len(keys) > 1 else ""
        return f"Unrecognized key{plural}: {join_values(keys, ', ')}"
    if code == "invalid_key":
        return f"Invalid key in {issue.get('origin')}"
    if code == "invalid_union":
        options = issue.get("options")
        if options:
            return "Invalid discriminator value. Expected " + " | ".join(f"'{o}'" for o in options)
        if issue.get("inclusive") is False:
            return "Invalid input: more than one option matched"
        return "Invalid input"
    if code == "invalid_element":
        return f"Invalid value in {issue.get('origin')}"
    return "Invalid input"


en = en_error
