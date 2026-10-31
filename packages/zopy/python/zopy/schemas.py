"""Concrete schema classes (``ZodString``, ``ZodObject`` ...)."""

from __future__ import annotations

import base64 as _b64
import datetime as _dt
import enum as _enum
import ipaddress
import json as _json
import math
import re
import unicodedata
from collections.abc import Awaitable, Callable, Iterable, Mapping
from types import MappingProxyType
from typing import Any, Generic, Literal, LiteralString, Self, TypeVar, cast, overload
from urllib.parse import urlsplit

from . import regexes
from ._util import (
    AttrDict,
    is_awaitable,
    is_plain_number,
    normalize_params,
)
from .core import Check, Payload, RefinementCtx, ZodType, _close, _takes_ctx, aborted, overwrite_check
from .errors import ZodAsyncError, ZodEncodeError, ZodError

T = TypeVar("T")
K = TypeVar("K")
V = TypeVar("V")
L = TypeVar("L")
E = TypeVar("E")
LS = TypeVar("LS", bound=LiteralString)
C = TypeVar("C")
N = TypeVar("N", int, float)

# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #


def _await_all(items: list[Any]) -> Awaitable[list[Any]]:
    async def gather() -> list[Any]:
        out = []
        for item in items:
            out.append(await item if is_awaitable(item) else item)
        return out

    return gather()


def _then(result: Any, fn: Callable[[Any], Any]) -> Any:
    """Apply ``fn`` to ``result``, awaiting first when needed."""
    if is_awaitable(result):

        async def chain() -> Any:
            out = fn(await result)
            return await out if is_awaitable(out) else out

        return chain()
    return fn(result)


def _invalid_type(payload: Payload, inst: Any, expected: str, **extra: Any) -> Payload:
    payload.push(inst, {"code": "invalid_type", "expected": expected, "input": payload.value, **extra})
    return payload


def _size_check(
    kind: str,
    origin: str,
    *,
    minimum: Any = None,
    maximum: Any = None,
    inclusive: bool = True,
    exact: bool = False,
    params: Mapping[str, Any] | None = None,
    size_of: Callable[[Any], Any] = len,
) -> Check:
    params = dict(params or {})

    def run(payload: Payload, check: Check, inst: Any) -> None:
        size = size_of(payload.value)
        # A value that cannot be compared with a bound (a naive vs an aware datetime, a date vs a
        # datetime) fails it, so safeParse reports an issue instead of raising.
        try:
            too_small = minimum is not None and (size < minimum if inclusive else size <= minimum)
        except TypeError:
            too_small = True
        try:
            too_big = maximum is not None and (size > maximum if inclusive else size >= maximum)
        except TypeError:
            too_big = True
        if too_small:
            check.issue(
                payload,
                {
                    "origin": origin,
                    "code": "too_small",
                    "minimum": minimum,
                    "inclusive": inclusive,
                    "exact": exact,
                    "input": payload.value,
                },
                inst,
            )
        if too_big:
            check.issue(
                payload,
                {
                    "origin": origin,
                    "code": "too_big",
                    "maximum": maximum,
                    "inclusive": inclusive,
                    "exact": exact,
                    "input": payload.value,
                },
                inst,
            )

    json_: dict[str, Any] = {}
    if minimum is not None:
        json_["minimum"] = minimum
    if maximum is not None:
        json_["maximum"] = maximum
    return Check(
        kind,
        run,
        error=params.get("error"),
        abort=bool(params.get("abort", False)),
        params={
            "minimum": minimum,
            "maximum": maximum,
            "inclusive": inclusive,
            "origin": origin,
            "exact": exact,
        },
        json=json_,
    )


def _format_check(
    fmt: str,
    test: Callable[[str], bool],
    params: Mapping[str, Any] | None = None,
    *,
    pattern: Any = None,
    extra: Mapping[str, Any] | None = None,
    opts: Mapping[str, Any] | None = None,
    python: bool = False,
) -> Check:
    """``opts`` are compile hints for the Rust engine; ``python=True`` forces the Python check."""
    params = dict(params or {})

    def run(payload: Payload, check: Check, inst: Any) -> None:
        if not test(payload.value):
            raw = {"origin": "string", "code": "invalid_format", "format": fmt, "input": payload.value}
            if pattern is not None:
                raw["pattern"] = _pattern_str(pattern)
            raw.update(extra or {})
            check.issue(payload, raw, inst)

    return Check(
        fmt,
        run,
        error=params.get("error"),
        abort=bool(params.get("abort", False)),
        params={
            "format": fmt,
            "pattern": pattern,
            "opts": dict(opts or {}),
            "python": python,
            **(extra or {}),
        },
    )


def _pattern_str(pattern: Any) -> str:
    if isinstance(pattern, re.Pattern):
        flags = ""
        if pattern.flags & re.IGNORECASE:
            flags += "i"
        if pattern.flags & re.MULTILINE:
            flags += "m"
        if pattern.flags & re.DOTALL:
            flags += "s"
        return f"/{pattern.pattern}/{flags}"
    return f"/{pattern}/"


def _compile(pattern: Any) -> re.Pattern[str]:
    return pattern if isinstance(pattern, re.Pattern) else re.compile(pattern)


def _is_optional_marker(schema: ZodType[Any]) -> bool:
    return schema._optin == "optional"


# --------------------------------------------------------------------------- #
# Primitives
# --------------------------------------------------------------------------- #


class ZodString(ZodType[str]):
    _type = "string"

    def _parse(self, payload: Payload) -> Payload:
        value = payload.value
        if self._def.get("coerce") and value is not None:
            if isinstance(value, bool):
                payload.value = "true" if value else "false"
            elif isinstance(value, float) and value.is_integer() and math.isfinite(value):
                payload.value = str(int(value))
            else:
                payload.value = str(value)
            return payload
        if isinstance(value, str):
            return payload
        return _invalid_type(payload, self, "string")

    # -- size ------------------------------------------------------------- #
    def min(self, minimum: int, params: Any = None, **kwargs: Any) -> Self:
        return self._add_check(
            _size_check("min_length", "string", minimum=minimum, params=normalize_params(params, kwargs))
        )

    def max(self, maximum: int, params: Any = None, **kwargs: Any) -> Self:
        return self._add_check(
            _size_check("max_length", "string", maximum=maximum, params=normalize_params(params, kwargs))
        )

    def length(self, length: int, params: Any = None, **kwargs: Any) -> Self:
        return self._add_check(
            _size_check(
                "length_equals",
                "string",
                minimum=length,
                maximum=length,
                exact=True,
                params=normalize_params(params, kwargs),
            )
        )

    def nonempty(self, params: Any = None, **kwargs: Any) -> Self:
        return self.min(1, params, **kwargs)

    # -- formats ----------------------------------------------------------- #
    def _format(
        self, fmt: str, test: Callable[[str], bool], params: Any = None, kwargs: Any = None, **opts: Any
    ) -> Self:
        schema = self._add_check(_format_check(fmt, test, normalize_params(params, kwargs), **opts))
        if schema._def.get("format") is None:
            schema._def["format"] = fmt
        return schema

    def regex(self, pattern: Any, params: Any = None, **kwargs: Any) -> Self:
        compiled = _compile(pattern)
        return self._format(
            "regex", lambda v: compiled.search(v) is not None, params, kwargs, pattern=compiled
        )

    # Formats are top-level functions (``z.email()``, ``z.iso.datetime()``, ...) as in Zod 4; these
    # private builders back them. The Zod 3 method forms (``z.string().email()``) are not provided.
    def _email(self, params: Any = None, **kwargs: Any) -> Self:
        p = normalize_params(params, kwargs)
        pattern = _compile(p.pop("pattern", regexes.email))
        custom = pattern is not regexes.email
        return self._format(
            "email", lambda v: pattern.search(v) is not None, p, None, pattern=pattern, python=custom
        )

    def _url(self, params: Any = None, **kwargs: Any) -> Self:
        p = normalize_params(params, kwargs)
        hostname_re = p.pop("hostname", None)
        protocol_re = p.pop("protocol", None)
        normalize = p.pop("normalize", False)

        def test(v: str) -> bool:
            try:
                parts = urlsplit(v)
            except ValueError:
                return False
            if not parts.scheme or not parts.netloc:
                return False
            if hostname_re is not None and not _compile(hostname_re).search(parts.hostname or ""):
                return False
            return protocol_re is None or bool(_compile(protocol_re).search(parts.scheme))

        custom = hostname_re is not None or protocol_re is not None
        schema = self._format("url", test, p, None, python=custom)
        if normalize:
            schema = schema.overwrite(lambda v: v.strip())
        return schema

    def _httpUrl(self, params: Any = None, **kwargs: Any) -> Self:  # noqa: N802
        p = normalize_params(params, kwargs)
        p["protocol"] = re.compile(r"^https?$")
        p["hostname"] = regexes.domain
        return self._url(p)

    def _emoji(self, params: Any = None, **kwargs: Any) -> Self:
        return self._format(
            "emoji", lambda v: regexes.emoji.search(v) is not None, params, kwargs, pattern=regexes.emoji
        )

    def _uuid(self, params: Any = None, **kwargs: Any) -> Self:
        p = normalize_params(params, kwargs)
        version = p.pop("version", None)
        if isinstance(version, str):
            version = int(version.lstrip("v"))
        pattern = regexes.uuid(version)
        fmt = f"uuidv{version}" if version else "uuid"
        return self._format(
            fmt, lambda v: pattern.search(v) is not None, p, None, pattern=pattern, opts={"version": version}
        )

    def _uuidv4(self, params: Any = None, **kwargs: Any) -> Self:
        return self._uuid({**normalize_params(params, kwargs), "version": 4})

    def _uuidv6(self, params: Any = None, **kwargs: Any) -> Self:
        return self._uuid({**normalize_params(params, kwargs), "version": 6})

    def _uuidv7(self, params: Any = None, **kwargs: Any) -> Self:
        return self._uuid({**normalize_params(params, kwargs), "version": 7})

    def _guid(self, params: Any = None, **kwargs: Any) -> Self:
        return self._format(
            "guid", lambda v: regexes.guid.search(v) is not None, params, kwargs, pattern=regexes.guid
        )

    def _nanoid(self, params: Any = None, **kwargs: Any) -> Self:
        return self._format(
            "nanoid", lambda v: regexes.nanoid.search(v) is not None, params, kwargs, pattern=regexes.nanoid
        )

    def _cuid(self, params: Any = None, **kwargs: Any) -> Self:
        return self._format(
            "cuid", lambda v: regexes.cuid.search(v) is not None, params, kwargs, pattern=regexes.cuid
        )

    def _cuid2(self, params: Any = None, **kwargs: Any) -> Self:
        return self._format(
            "cuid2", lambda v: regexes.cuid2.search(v) is not None, params, kwargs, pattern=regexes.cuid2
        )

    def _ulid(self, params: Any = None, **kwargs: Any) -> Self:
        return self._format(
            "ulid", lambda v: regexes.ulid.search(v) is not None, params, kwargs, pattern=regexes.ulid
        )

    def _xid(self, params: Any = None, **kwargs: Any) -> Self:
        return self._format(
            "xid", lambda v: regexes.xid.search(v) is not None, params, kwargs, pattern=regexes.xid
        )

    def _ksuid(self, params: Any = None, **kwargs: Any) -> Self:
        return self._format(
            "ksuid", lambda v: regexes.ksuid.search(v) is not None, params, kwargs, pattern=regexes.ksuid
        )

    def _base64(self, params: Any = None, **kwargs: Any) -> Self:
        return self._format(
            "base64", lambda v: regexes.base64.search(v) is not None, params, kwargs, pattern=regexes.base64
        )

    def _base64url(self, params: Any = None, **kwargs: Any) -> Self:
        return self._format(
            "base64url",
            lambda v: regexes.base64url.search(v) is not None,
            params,
            kwargs,
            pattern=regexes.base64url,
        )

    def _hex(self, params: Any = None, **kwargs: Any) -> Self:
        return self._format(
            "hex", lambda v: regexes.hex_.search(v) is not None, params, kwargs, pattern=regexes.hex_
        )

    def _hostname(self, params: Any = None, **kwargs: Any) -> Self:
        return self._format(
            "hostname",
            lambda v: regexes.hostname.search(v) is not None,
            params,
            kwargs,
            pattern=regexes.hostname,
        )

    def _e164(self, params: Any = None, **kwargs: Any) -> Self:
        return self._format(
            "e164", lambda v: regexes.e164.search(v) is not None, params, kwargs, pattern=regexes.e164
        )

    def _jwt(self, params: Any = None, **kwargs: Any) -> Self:
        p = normalize_params(params, kwargs)
        alg = p.pop("alg", None)

        def test(v: str) -> bool:
            parts = v.split(".")
            if len(parts) != 3:
                return False
            try:
                header_b = parts[0] + "=" * (-len(parts[0]) % 4)
                header = _json.loads(_b64.urlsafe_b64decode(header_b))
            except Exception:
                return False
            if not isinstance(header, dict) or ("typ" in header and header["typ"] != "JWT"):
                return False
            if "alg" not in header:
                return False
            return alg is None or header["alg"] == alg

        return self._format("jwt", test, p, None, extra={"alg": alg} if alg else None, opts={"alg": alg})

    def _hash(self, alg: str, params: Any = None, **kwargs: Any) -> Self:
        p = normalize_params(params, kwargs)
        enc = p.pop("enc", "hex")
        pattern = regexes.hash_(alg, enc)
        return self._format(
            alg, lambda v: pattern.search(v) is not None, p, None, pattern=pattern, opts={"enc": enc}
        )

    def _mac(self, params: Any = None, **kwargs: Any) -> Self:
        p = normalize_params(params, kwargs)
        delimiter = p.pop("delimiter", ":")
        pattern = regexes.mac(delimiter)
        return self._format(
            "mac",
            lambda v: pattern.search(v) is not None,
            p,
            None,
            pattern=pattern,
            opts={"delimiter": delimiter},
        )

    def _creditCard(self, params: Any = None, **kwargs: Any) -> Self:  # noqa: N802
        return self._format("credit_card", _is_credit_card, params, kwargs)

    def _currencyCode(self, params: Any = None, **kwargs: Any) -> Self:  # noqa: N802
        return self._format("currency_code", lambda v: v in CURRENCY_CODES, params, kwargs)

    def _iban(self, params: Any = None, **kwargs: Any) -> Self:
        return self._format("iban", _is_iban, params, kwargs)

    def _stringFormat(self, name: str, check: Any, params: Any = None, **kwargs: Any) -> Self:  # noqa: N802
        if isinstance(check, (str, re.Pattern)):
            compiled = _compile(check)
            return self._format(
                name, lambda v: compiled.search(v) is not None, params, kwargs, pattern=compiled, python=True
            )
        return self._format(name, lambda v: bool(check(v)), params, kwargs, python=True)

    def _ipv4(self, params: Any = None, **kwargs: Any) -> Self:
        return self._format(
            "ipv4", lambda v: regexes.ipv4.search(v) is not None, params, kwargs, pattern=regexes.ipv4
        )

    def _ipv6(self, params: Any = None, **kwargs: Any) -> Self:
        return self._format("ipv6", lambda v: _is_ip(v, 6), params, kwargs, pattern=regexes.ipv6)

    def _cidrv4(self, params: Any = None, **kwargs: Any) -> Self:
        return self._format(
            "cidrv4", lambda v: regexes.cidrv4.search(v) is not None, params, kwargs, pattern=regexes.cidrv4
        )

    def _cidrv6(self, params: Any = None, **kwargs: Any) -> Self:
        return self._format("cidrv6", lambda v: _is_cidr(v, 6), params, kwargs)

    # -- ISO 8601 ---------------------------------------------------------- #
    def _datetime(self, params: Any = None, **kwargs: Any) -> Self:
        p = normalize_params(params, kwargs)
        precision = p.pop("precision", None)
        offset = bool(p.pop("offset", False))
        local = bool(p.pop("local", False))
        pattern = regexes.datetime(precision, offset, local)
        return self._format(
            "datetime",
            lambda v: pattern.search(v) is not None,
            p,
            None,
            pattern=pattern,
            opts={"precision": precision, "offset": offset, "local": local},
        )

    def _date(self, params: Any = None, **kwargs: Any) -> Self:
        return self._format(
            "date", lambda v: regexes.date.search(v) is not None, params, kwargs, pattern=regexes.date
        )

    def _time(self, params: Any = None, **kwargs: Any) -> Self:
        p = normalize_params(params, kwargs)
        precision = p.pop("precision", None)
        pattern = regexes.time(precision)
        return self._format(
            "time",
            lambda v: pattern.search(v) is not None,
            p,
            None,
            pattern=pattern,
            opts={"precision": precision},
        )

    def _duration(self, params: Any = None, **kwargs: Any) -> Self:
        return self._format(
            "duration",
            lambda v: regexes.duration.search(v) is not None,
            params,
            kwargs,
            pattern=regexes.duration,
        )

    # -- substring checks -------------------------------------------------- #
    def includes(self, value: str, params: Any = None, **kwargs: Any) -> Self:
        p = normalize_params(params, kwargs)
        position = p.pop("position", None)

        def test(v: str) -> bool:
            return v.find(value, position or 0) != -1

        return self._add_check(_format_check("includes", test, p, extra={"includes": value}))

    def startsWith(self, value: str, params: Any = None, **kwargs: Any) -> Self:  # noqa: N802
        return self._add_check(
            _format_check(
                "starts_with",
                lambda v: v.startswith(value),
                normalize_params(params, kwargs),
                extra={"prefix": value},
            )
        )

    def endsWith(self, value: str, params: Any = None, **kwargs: Any) -> Self:  # noqa: N802
        return self._add_check(
            _format_check(
                "ends_with",
                lambda v: v.endswith(value),
                normalize_params(params, kwargs),
                extra={"suffix": value},
            )
        )

    def lowercase(self, params: Any = None, **kwargs: Any) -> Self:
        return self._add_check(
            _format_check(
                "lowercase",
                lambda v: regexes.lowercase.search(v) is not None,
                normalize_params(params, kwargs),
                pattern=regexes.lowercase,
            )
        )

    def uppercase(self, params: Any = None, **kwargs: Any) -> Self:
        return self._add_check(
            _format_check(
                "uppercase",
                lambda v: regexes.uppercase.search(v) is not None,
                normalize_params(params, kwargs),
                pattern=regexes.uppercase,
            )
        )

    starts_with = startsWith
    ends_with = endsWith

    # -- transforms -------------------------------------------------------- #
    def trim(self) -> Self:
        return self._add_check(overwrite_check(lambda v: v.strip(), op="trim"))

    def toLowerCase(self) -> Self:  # noqa: N802
        return self._add_check(overwrite_check(lambda v: v.lower(), op="toLowerCase"))

    def toUpperCase(self) -> Self:  # noqa: N802
        return self._add_check(overwrite_check(lambda v: v.upper(), op="toUpperCase"))

    def normalize(self, form: Literal["NFC", "NFD", "NFKC", "NFKD"] = "NFC") -> Self:
        return self._add_check(
            overwrite_check(lambda v: unicodedata.normalize(form, v), op="normalize", form=form)
        )

    to_lower_case = toLowerCase
    to_upper_case = toUpperCase

    # -- introspection ----------------------------------------------------- #
    @property
    def format(self) -> str | None:
        return self._def.get("format")

    @property
    def minLength(self) -> int | None:  # noqa: N802
        values = [c.params.get("minimum") for c in self._def["checks"] if c.params.get("minimum") is not None]
        return max(values) if values else None

    @property
    def maxLength(self) -> int | None:  # noqa: N802
        values = [c.params.get("maximum") for c in self._def["checks"] if c.params.get("maximum") is not None]
        return min(values) if values else None


def _luhn(digits: str) -> bool:
    total = 0
    for i, ch in enumerate(reversed(digits)):
        d = ord(ch) - 48
        if i % 2 == 1:
            d *= 2
            if d > 9:
                d -= 9
        total += d
    return total % 10 == 0


def _is_credit_card(value: str) -> bool:
    if not regexes.credit_card_shape.search(value):
        return False
    digits = value.replace(" ", "").replace("-", "")
    return 12 <= len(digits) <= 19 and _luhn(digits)


def _is_iban(value: str) -> bool:
    if not regexes.iban_shape.search(value):
        return False
    rearranged = value[4:] + value[:4]
    numeric = "".join(str(ord(c) - 55) if c.isalpha() else c for c in rearranged)
    return int(numeric) % 97 == 1


# ISO 4217 active codes (withdrawn codes such as ANG are intentionally absent).
CURRENCY_CODES = frozenset(
    [
        "AED",
        "AFN",
        "ALL",
        "AMD",
        "AOA",
        "ARS",
        "AUD",
        "AWG",
        "AZN",
        "BAM",
        "BBD",
        "BDT",
        "BGN",
        "BHD",
        "BIF",
        "BMD",
        "BND",
        "BOB",
        "BOV",
        "BRL",
        "BSD",
        "BTN",
        "BWP",
        "BYN",
        "BZD",
        "CAD",
        "CDF",
        "CHE",
        "CHF",
        "CHW",
        "CLF",
        "CLP",
        "CNY",
        "COP",
        "COU",
        "CRC",
        "CUP",
        "CVE",
        "CZK",
        "DJF",
        "DKK",
        "DOP",
        "DZD",
        "EGP",
        "ERN",
        "ETB",
        "EUR",
        "FJD",
        "FKP",
        "GBP",
        "GEL",
        "GHS",
        "GIP",
        "GMD",
        "GNF",
        "GTQ",
        "GYD",
        "HKD",
        "HNL",
        "HTG",
        "HUF",
        "IDR",
        "ILS",
        "INR",
        "IQD",
        "IRR",
        "ISK",
        "JMD",
        "JOD",
        "JPY",
        "KES",
        "KGS",
        "KHR",
        "KMF",
        "KPW",
        "KRW",
        "KWD",
        "KYD",
        "KZT",
        "LAK",
        "LBP",
        "LKR",
        "LRD",
        "LSL",
        "LYD",
        "MAD",
        "MDL",
        "MGA",
        "MKD",
        "MMK",
        "MNT",
        "MOP",
        "MRU",
        "MUR",
        "MVR",
        "MWK",
        "MXN",
        "MXV",
        "MYR",
        "MZN",
        "NAD",
        "NGN",
        "NIO",
        "NOK",
        "NPR",
        "NZD",
        "OMR",
        "PAB",
        "PEN",
        "PGK",
        "PHP",
        "PKR",
        "PLN",
        "PYG",
        "QAR",
        "RON",
        "RSD",
        "RUB",
        "RWF",
        "SAR",
        "SBD",
        "SCR",
        "SDG",
        "SEK",
        "SGD",
        "SHP",
        "SLE",
        "SOS",
        "SRD",
        "SSP",
        "STN",
        "SVC",
        "SYP",
        "SZL",
        "THB",
        "TJS",
        "TMT",
        "TND",
        "TOP",
        "TRY",
        "TTD",
        "TWD",
        "TZS",
        "UAH",
        "UGX",
        "USD",
        "USN",
        "UYI",
        "UYU",
        "UYW",
        "UZS",
        "VED",
        "VES",
        "VND",
        "VUV",
        "WST",
        "XAF",
        "XAG",
        "XAU",
        "XBA",
        "XBB",
        "XBC",
        "XBD",
        "XCD",
        "XCG",
        "XDR",
        "XOF",
        "XPD",
        "XPF",
        "XPT",
        "XSU",
        "XTS",
        "XUA",
        "XXX",
        "YER",
        "ZAR",
        "ZMW",
        "ZWG",
    ]
)


def _is_ip(value: str, version: int | None) -> bool:
    try:
        addr = ipaddress.ip_address(value)
    except ValueError:
        return False
    return version is None or addr.version == version


def _is_cidr(value: str, version: int | None) -> bool:
    if "/" not in value:
        return False
    try:
        net = ipaddress.ip_network(value, strict=False)
    except ValueError:
        return False
    return version is None or net.version == version


class _ZodNumeric(ZodType[N], Generic[N]):
    """Shared checks for ``ZodNumber`` (float) and ``ZodBigInt`` (int)."""

    _type = "number"

    def _parse(self, payload: Payload) -> Payload:
        value = payload.value
        if self._def.get("coerce"):
            value = _coerce_number(value)
            payload.value = value
        if is_plain_number(value) and math.isfinite(value):
            return payload
        received = None
        if is_plain_number(value):
            received = "NaN" if math.isnan(value) else ("Infinity" if value > 0 else "-Infinity")
        extra = {"received": received} if received else {}
        return _invalid_type(payload, self, "number", **extra)

    def _bound(
        self,
        kind: str,
        *,
        minimum: Any = None,
        maximum: Any = None,
        inclusive: bool = True,
        params: Any = None,
        kwargs: Any = None,
    ) -> Self:
        return self._add_check(
            _size_check(
                kind,
                self._type,
                minimum=minimum,
                maximum=maximum,
                inclusive=inclusive,
                params=normalize_params(params, kwargs),
                size_of=lambda v: v,
            )
        )

    def gt(self, value: float, params: Any = None, **kwargs: Any) -> Self:
        return self._bound("greater_than", minimum=value, inclusive=False, params=params, kwargs=kwargs)

    def gte(self, value: float, params: Any = None, **kwargs: Any) -> Self:
        return self._bound("greater_than", minimum=value, inclusive=True, params=params, kwargs=kwargs)

    def lt(self, value: float, params: Any = None, **kwargs: Any) -> Self:
        return self._bound("less_than", maximum=value, inclusive=False, params=params, kwargs=kwargs)

    def lte(self, value: float, params: Any = None, **kwargs: Any) -> Self:
        return self._bound("less_than", maximum=value, inclusive=True, params=params, kwargs=kwargs)

    min = gte
    max = lte

    def positive(self, params: Any = None, **kwargs: Any) -> Self:
        return self.gt(0, params, **kwargs)

    def nonnegative(self, params: Any = None, **kwargs: Any) -> Self:
        return self.gte(0, params, **kwargs)

    def negative(self, params: Any = None, **kwargs: Any) -> Self:
        return self.lt(0, params, **kwargs)

    def nonpositive(self, params: Any = None, **kwargs: Any) -> Self:
        return self.lte(0, params, **kwargs)

    def multipleOf(self, divisor: float, params: Any = None, **kwargs: Any) -> Self:  # noqa: N802
        p = normalize_params(params, kwargs)

        def run(payload: Payload, check: Check, inst: Any) -> None:
            if not _is_multiple_of(payload.value, divisor):
                check.issue(
                    payload,
                    {
                        "origin": self._type,
                        "code": "not_multiple_of",
                        "divisor": divisor,
                        "input": payload.value,
                    },
                    inst,
                )

        return self._add_check(
            Check(
                "multiple_of",
                run,
                error=p.get("error"),
                params={"divisor": divisor},
                json={"multipleOf": divisor},
            )
        )

    step = multipleOf
    multiple_of = multipleOf

    def int(self, params: Any = None, **kwargs: Any) -> ZodInt:
        """Integer-only schema with ``int`` output (``5.0`` is accepted and returned as ``5``)."""
        p = normalize_params(params, kwargs)
        d = dict(self._def)
        d["format"] = d.get("format") or "safeint"
        if p.get("error") is not None:
            d["intError"] = p["error"]
        return ZodInt(**d)

    @property
    def format(self) -> str | None:
        return self._def.get("format")


class ZodNumber(_ZodNumeric[float]):
    _type = "number"


class ZodInt(_ZodNumeric[int]):
    """``z.int()`` / ``z.number().int()``: a number schema whose output is ``int``."""

    _type = "number"

    def _parse(self, payload: Payload) -> Payload:
        result = super()._parse(payload)
        if aborted(result):
            return result
        v = result.value
        if isinstance(v, float):
            if not v.is_integer():
                raw: dict[str, Any] = {"expected": "int", "code": "invalid_type", "input": v}
                if self._def.get("intError") is not None:
                    raw["_check_error"] = self._def["intError"]
                result.push(self, raw)
                return result
            v = int(v)
            result.value = v
        limit = 2**53 - 1
        if self._def.get("format") in (None, "safeint") and not (-limit <= v <= limit):
            raw = {
                "origin": "number",
                "code": "too_big" if v > 0 else "too_small",
                "maximum" if v > 0 else "minimum": limit if v > 0 else -limit,
                "inclusive": True,
                "input": v,
                "continue": True,
            }
            if self._def.get("intError") is not None:
                raw["_check_error"] = self._def["intError"]
            result.push(self, raw)
        return result


def _coerce_number(value: Any) -> Any:
    if value is None:
        return math.nan
    if isinstance(value, bool):
        return 1 if value else 0
    if is_plain_number(value):
        return value
    if isinstance(value, str):
        text = value.strip()
        if text == "":
            return 0
        try:
            if regexes.integer.match(text):
                return int(text)
            return float(text)
        except ValueError:
            return math.nan
    if isinstance(value, _dt.datetime):
        return value.timestamp()
    try:
        return float(value)
    except (TypeError, ValueError):
        return math.nan


def _is_multiple_of(value: Any, divisor: Any) -> bool:
    if isinstance(value, int) and isinstance(divisor, int):
        return divisor != 0 and value % divisor == 0
    v_dec = _decimal_places(value)
    d_dec = _decimal_places(divisor)
    step = max(v_dec, d_dec)
    factor = 10**step
    return round(value * factor) % round(divisor * factor) == 0


def _decimal_places(value: Any) -> int:
    text = repr(float(value))
    if "e" in text or "E" in text:
        mantissa, exp = text.lower().split("e")
        dec = len(mantissa.split(".")[1]) if "." in mantissa else 0
        return max(0, dec - int(exp))
    return len(text.split(".")[1]) if "." in text else 0


class ZodBigInt(_ZodNumeric[int]):
    _type = "bigint"

    def _parse(self, payload: Payload) -> Payload:
        value = payload.value
        if self._def.get("coerce"):
            try:
                value = int(value)
            except (TypeError, ValueError):
                return _invalid_type(payload, self, "bigint")
            payload.value = value
        if isinstance(value, int) and not isinstance(value, bool):
            return payload
        return _invalid_type(payload, self, "bigint")


class ZodBoolean(ZodType[bool]):
    _type = "boolean"

    def _parse(self, payload: Payload) -> Payload:
        value = payload.value
        if self._def.get("coerce"):
            payload.value = bool(value)
            return payload
        if isinstance(value, bool):
            return payload
        return _invalid_type(payload, self, "boolean")


class ZodDate(ZodType[_dt.datetime]):
    _type = "date"

    def _parse(self, payload: Payload) -> Payload:
        value = payload.value
        if self._def.get("coerce"):
            value = _coerce_date(value)
            payload.value = value
        if isinstance(value, (_dt.datetime, _dt.date)):
            return payload
        return _invalid_type(payload, self, "date")

    def min(self, minimum: Any, params: Any = None, **kwargs: Any) -> Self:
        return self._add_check(
            _size_check(
                "greater_than",
                "date",
                minimum=minimum,
                params=normalize_params(params, kwargs),
                size_of=lambda v: v,
            )
        )

    def max(self, maximum: Any, params: Any = None, **kwargs: Any) -> Self:
        return self._add_check(
            _size_check(
                "less_than",
                "date",
                maximum=maximum,
                params=normalize_params(params, kwargs),
                size_of=lambda v: v,
            )
        )

    @property
    def minDate(self) -> Any:  # noqa: N802
        values = [c.params.get("minimum") for c in self._def["checks"] if c.params.get("minimum") is not None]
        return max(values) if values else None

    @property
    def maxDate(self) -> Any:  # noqa: N802
        values = [c.params.get("maximum") for c in self._def["checks"] if c.params.get("maximum") is not None]
        return min(values) if values else None


def _coerce_date(value: Any) -> Any:
    if isinstance(value, (_dt.datetime, _dt.date)):
        return value
    if isinstance(value, str):
        text = value.strip()
        try:
            return _dt.datetime.fromisoformat(text.replace("Z", "+00:00") if text.endswith("Z") else text)
        except ValueError:
            try:
                return _dt.datetime.combine(_dt.date.fromisoformat(text), _dt.time())
            except ValueError:
                return None
    if is_plain_number(value):
        # Milliseconds since the epoch, truncated, as JavaScript's new Date(n) reads them.
        try:
            return _EPOCH + _dt.timedelta(milliseconds=math.trunc(value))
        except (OverflowError, ValueError):
            return None
    return None


_EPOCH = _dt.datetime(1970, 1, 1, tzinfo=_dt.timezone.utc)


class ZodUndefined(ZodType[None]):
    _type = "undefined"

    def _parse(self, payload: Payload) -> Payload:
        if payload.value is None:
            return payload
        return _invalid_type(payload, self, "undefined")

    @property
    def _optin(self) -> str | None:
        return "optional"

    @property
    def _optout(self) -> str | None:
        return "optional"


class ZodNull(ZodType[None]):
    _type = "null"

    def _parse(self, payload: Payload) -> Payload:
        if payload.value is None:
            return payload
        return _invalid_type(payload, self, "null")


class ZodVoid(ZodUndefined):
    _type = "void"

    def _parse(self, payload: Payload) -> Payload:
        if payload.value is None:
            return payload
        return _invalid_type(payload, self, "void")


class ZodAny(ZodType[Any]):
    _type = "any"

    def _parse(self, payload: Payload) -> Payload:
        return payload

    @property
    def _optin(self) -> str | None:
        return "optional"

    @property
    def _optout(self) -> str | None:
        return "optional"


class ZodUnknown(ZodAny):
    _type = "unknown"


class ZodNever(ZodType[Any]):
    _type = "never"

    def _parse(self, payload: Payload) -> Payload:
        return _invalid_type(payload, self, "never")


class ZodNaN(ZodType[float]):
    _type = "nan"

    def _parse(self, payload: Payload) -> Payload:
        value = payload.value
        if isinstance(value, float) and math.isnan(value):
            return payload
        return _invalid_type(payload, self, "nan")


class ZodSymbol(ZodType[Any]):
    """Python has no symbols; this accepts nothing (kept for API parity)."""

    _type = "symbol"

    def _parse(self, payload: Payload) -> Payload:
        return _invalid_type(payload, self, "symbol")


# --------------------------------------------------------------------------- #
# Literals & enums
# --------------------------------------------------------------------------- #


def _literal_equal(a: Any, b: Any) -> bool:
    if isinstance(a, bool) or isinstance(b, bool):
        return type(a) is type(b) and a == b
    if is_plain_number(a) and is_plain_number(b):
        return a == b
    if a is None or b is None:
        return a is b
    if type(a) is not type(b) and not (isinstance(a, _enum.Enum) or isinstance(b, _enum.Enum)):
        return False
    try:
        return bool(a == b)
    except Exception:
        return False


class ZodLiteral(ZodType[L], Generic[L]):
    _type = "literal"

    def _parse(self, payload: Payload) -> Payload:
        for v in self._def["values"]:
            if _literal_equal(payload.value, v):
                return payload
        payload.push(
            self, {"code": "invalid_value", "values": list(self._def["values"]), "input": payload.value}
        )
        return payload

    @property
    def values(self) -> list[L]:
        return list(self._def["values"])

    @property
    def value(self) -> L:
        values = self._def["values"]
        if len(values) != 1:
            raise ValueError("This schema contains multiple valid literal values. Use `.values` instead.")
        return values[0]

    @property
    def _optin(self) -> str | None:
        return "optional" if any(v is None for v in self._def["values"]) else None

    @property
    def _optout(self) -> str | None:
        return self._optin


class ZodEnum(ZodType[E], Generic[E]):
    _type = "enum"

    def _parse(self, payload: Payload) -> Payload:
        value = payload.value
        entries: dict[Any, Any] = self._def["entries"]
        for v in entries.values():
            if isinstance(v, _enum.Enum):
                # Enum-class schemas accept the member or its value and return the member.
                if value is v or (not isinstance(value, _enum.Enum) and _literal_equal(value, v.value)):
                    payload.value = v
                    return payload
            elif _literal_equal(value, v):
                return payload
        values = [v.value if isinstance(v, _enum.Enum) else v for v in entries.values()]
        payload.push(self, {"code": "invalid_value", "values": values, "input": value})
        return payload

    @property
    def enum(self) -> AttrDict:
        return AttrDict(self._def["entries"])

    @property
    def options(self) -> list[E]:
        return list(self._def["entries"].values())

    # Like ``z.enum``, both take a tuple so the type checker keeps literals. ``extract`` narrows the
    # output to the given values; ``exclude`` cannot (Python types have no literal subtraction), so
    # it keeps the original output type.
    @overload
    def extract(self, values: tuple[LS, ...], params: Any = None, **kwargs: Any) -> ZodEnum[LS]: ...

    @overload
    def extract(self, values: tuple[L, ...], params: Any = None, **kwargs: Any) -> ZodEnum[L]: ...

    def extract(self, values: tuple[Any, ...], params: Any = None, **kwargs: Any) -> ZodEnum[Any]:
        wanted = self._known_values(values, "extract")
        entries = {k: v for k, v in self._def["entries"].items() if v in wanted or k in wanted}
        return ZodEnum(entries=entries, **normalize_params(params, kwargs))

    def exclude(self, values: tuple[E, ...], params: Any = None, **kwargs: Any) -> ZodEnum[E]:
        unwanted = self._known_values(values, "exclude")
        entries = {k: v for k, v in self._def["entries"].items() if v not in unwanted and k not in unwanted}
        return ZodEnum(entries=entries, **normalize_params(params, kwargs))

    def _known_values(self, values: Any, method: str) -> list[Any]:
        if not isinstance(values, tuple):
            raise TypeError(f'.{method}() takes a tuple, e.g. .{method}(("a",))')
        entries: dict[Any, Any] = self._def["entries"]
        for value in values:
            if value not in entries and value not in entries.values():
                raise ValueError(f"Key {value!r} not found in enum")
        return list(values)


def _enum_entries(values: Any) -> dict[Any, Any]:
    if isinstance(values, type) and issubclass(values, _enum.Enum):
        return dict(values.__members__)
    if isinstance(values, Mapping):
        return dict(values)
    entries: dict[Any, Any] = {}
    for v in cast("Iterable[Any]", values):
        if isinstance(v, _enum.Enum):
            entries[v.name] = v
        else:
            entries[v] = v
    return entries


# --------------------------------------------------------------------------- #
# Arrays & tuples
# --------------------------------------------------------------------------- #


class ZodArray(ZodType[list[T]], Generic[T]):
    _type = "array"

    def _parse(self, payload: Payload) -> Any:
        value = payload.value
        if not isinstance(value, (list, tuple)):
            return _invalid_type(payload, self, "array")
        element: ZodType[Any] = self._def["element"]
        results = [element._run(payload.child(item, i)) for i, item in enumerate(value)]

        def finish(results: list[Payload]) -> Payload:
            out = []
            for r in results:
                payload.merge(r)
                out.append(r.value)
            payload.value = out
            return payload

        if any(is_awaitable(r) for r in results):
            return _then(_await_all(results), finish)
        return finish(cast("list[Payload]", results))

    @property
    def element(self) -> ZodType[T]:
        return self._def["element"]

    def min(self, minimum: int, params: Any = None, **kwargs: Any) -> Self:
        return self._add_check(
            _size_check("min_length", "array", minimum=minimum, params=normalize_params(params, kwargs))
        )

    def max(self, maximum: int, params: Any = None, **kwargs: Any) -> Self:
        return self._add_check(
            _size_check("max_length", "array", maximum=maximum, params=normalize_params(params, kwargs))
        )

    def length(self, length: int, params: Any = None, **kwargs: Any) -> Self:
        return self._add_check(
            _size_check(
                "length_equals",
                "array",
                minimum=length,
                maximum=length,
                exact=True,
                params=normalize_params(params, kwargs),
            )
        )

    def nonempty(self, params: Any = None, **kwargs: Any) -> Self:
        return self.min(1, params, **kwargs)

    def unwrap(self) -> ZodType[T]:
        return self._def["element"]


class ZodTuple(ZodType[T], Generic[T]):
    """Output is a Python ``tuple``; pass a Python tuple of schemas for positional typing."""

    _type = "tuple"

    def _parse(self, payload: Payload) -> Any:
        value = payload.value
        if not isinstance(value, (list, tuple)):
            return _invalid_type(payload, self, "tuple")
        items: list[ZodType[Any]] = self._def["items"]
        rest: ZodType[Any] | None = self._def.get("rest")
        optional_tail = 0
        for item in reversed(items):
            if _is_optional_marker(item):
                optional_tail += 1
            else:
                break
        if len(value) > len(items) and rest is None:
            payload.push(
                self,
                {
                    "code": "too_big",
                    "origin": "array",
                    "maximum": len(items),
                    "inclusive": True,
                    "input": value,
                    "continue": True,
                },
            )
        if len(value) < len(items) - optional_tail:
            payload.push(
                self,
                {
                    "code": "too_small",
                    "origin": "array",
                    "minimum": len(items) - optional_tail,
                    "inclusive": True,
                    "input": value,
                    "continue": True,
                },
            )
            return payload
        results: list[Any] = []
        for i, schema in enumerate(items):
            if i >= len(value):
                if _is_optional_marker(schema):
                    continue
                results.append(schema._run(payload.child(None, i, missing=True)))
            else:
                results.append(schema._run(payload.child(value[i], i)))
        if rest is not None:
            for i in range(len(items), len(value)):
                results.append(rest._run(payload.child(value[i], i)))

        def finish(results: list[Payload]) -> Payload:
            out = []
            for r in results:
                payload.merge(r)
                out.append(r.value)
            payload.value = tuple(out)
            return payload

        if any(is_awaitable(r) for r in results):
            return _then(_await_all(results), finish)
        return finish(cast("list[Payload]", results))

    @property
    def items(self) -> list[ZodType[Any]]:
        return list(self._def["items"])

    def rest(self, schema: ZodType[Any]) -> ZodTuple[tuple[Any, ...]]:
        return ZodTuple(**{**self._def, "rest": schema})


# --------------------------------------------------------------------------- #
# Objects
# --------------------------------------------------------------------------- #


class ZodObject(ZodType[T], Generic[T]):
    """Object schema; ``class X(z.Object)`` builds one whose output type ``T`` is the class."""

    _type = "object"

    def __init__(self, **definition: Any) -> None:
        definition.setdefault("shape", {})
        definition.setdefault("catchall", None)  # None=strip, ZodNever=strict, ZodUnknown=loose
        super().__init__(**definition)

    # -- parsing ----------------------------------------------------------- #
    def _parse(self, payload: Payload) -> Any:
        value = payload.value
        if not isinstance(value, Mapping):
            return _invalid_type(payload, self, "object")
        shape: dict[str, ZodType[Any]] = self._def["shape"]
        catchall: ZodType[Any] | None = self._def["catchall"]
        results: list[tuple[str, bool, Any]] = []
        for key, schema in shape.items():
            missing = key not in value
            if missing and schema._optin == "optional" and schema._optout == "optional":
                # Absent optional key: nothing to validate, nothing to emit.
                continue
            child = payload.child(None if missing else value[key], key, missing=missing)
            results.append((key, missing, schema._run(child)))

        extra_keys = [k for k in value if k not in shape]
        if catchall is not None and extra_keys:
            if isinstance(catchall, ZodNever):
                payload.push(self, {"code": "unrecognized_keys", "keys": extra_keys, "input": value})
            else:
                for key in extra_keys:
                    results.append((key, False, catchall._run(payload.child(value[key], key))))

        object_class = self._def.get("objectClass")
        if object_class is self:  # a z.Object class: its own _parse builds the instance
            object_class = None

        def finish(results: list[tuple[str, bool, Payload]]) -> Payload:
            out: dict[str, Any] = {}
            for key, missing, r in results:
                payload.merge(r)
                if r.value is None and missing:
                    continue
                out[key] = r.value
            if object_class is not None and not aborted(payload):
                # Same as the Rust engine: an instance holding the keys the output has (an absent
                # optional field stays absent and reads as None).
                instance = object.__new__(object_class)
                vars(instance).update(out)
                payload.value = instance
                return payload
            payload.value = out
            return payload

        if any(is_awaitable(r) for _, _, r in results):

            async def gather() -> Payload:
                resolved = []
                for key, missing, r in results:
                    resolved.append((key, missing, await r if is_awaitable(r) else r))
                return finish(resolved)

            return gather()
        return finish(cast("list[tuple[str, bool, Payload]]", results))

    # -- shape manipulation ------------------------------------------------ #
    @property
    def shape(self) -> dict[str, ZodType[Any]]:
        return dict(self._def["shape"])

    def keyof(self) -> ZodEnum[str]:
        return ZodEnum(entries={k: k for k in self._def["shape"]})

    def catchall(self, schema: ZodType[Any]) -> Self:
        return self._clone(catchall=schema)

    def __getitem__(self, key: str) -> ZodType[Any]:
        return self._def["shape"][key]


class ZodRecord(ZodType[dict[K, V]], Generic[K, V]):
    _type = "record"

    def _parse(self, payload: Payload) -> Any:
        value = payload.value
        if not isinstance(value, Mapping):
            return _invalid_type(payload, self, "record")
        key_type: ZodType[Any] = self._def["keyType"]
        value_type: ZodType[Any] = self._def["valueType"]
        results: list[tuple[Any, Any, Any]] = []
        exhaustive_values = (
            _exhaustive_values(key_type) if self._def.get("mode") not in ("partial",) else None
        )
        if exhaustive_values is not None:
            for k in exhaustive_values:
                missing = k not in value
                results.append(
                    (
                        k,
                        True,
                        value_type._run(payload.child(None if missing else value[k], k, missing=missing)),
                    )
                )
            extra = [k for k in value if not any(_literal_equal(k, e) for e in exhaustive_values)]
            if extra and self._def.get("mode") == "loose":
                for k in extra:
                    results.append((k, True, payload.child(value[k], k)))
            elif extra:
                payload.push(self, {"code": "unrecognized_keys", "keys": extra, "input": value})
            return self._finish(payload, results)
        for k, v in value.items():
            key_result = key_type._run(payload.sibling(k))
            if is_awaitable(key_result):
                raise TypeError("Async key schemas are not supported in records")
            if key_result.issues:
                if self._def.get("mode") == "loose":
                    # looseRecord: keys that don't match pass through unchanged
                    results.append((k, True, payload.child(v, k)))
                    continue
                payload.push(
                    self,
                    {
                        "origin": "record",
                        "code": "invalid_key",
                        "issues": [dict(i) for i in key_result.issues],
                        "input": k,
                        "path": [k],
                    },
                )
                results.append((k, False, payload.child(v, k)))
                continue
            results.append((key_result.value, True, value_type._run(payload.child(v, k))))
        return self._finish(payload, results)

    def _finish(self, payload: Payload, results: list[tuple[Any, bool, Any]]) -> Any:
        def finish(resolved: list[tuple[Any, bool, Payload]]) -> Payload:
            out: dict[Any, Any] = {}
            for key, _ok, r in resolved:
                payload.merge(r)
                if r.value is None and getattr(r, "missing", False):
                    continue
                out[key] = r.value
            payload.value = out
            return payload

        if any(is_awaitable(r) for _, _, r in results):

            async def gather() -> Payload:
                return finish([(k, ok, await r if is_awaitable(r) else r) for k, ok, r in results])

            return gather()
        return finish(cast("list[tuple[Any, bool, Payload]]", results))

    @property
    def keyType(self) -> ZodType[K]:  # noqa: N802
        return self._def["keyType"]

    @property
    def valueType(self) -> ZodType[V]:  # noqa: N802
        return self._def["valueType"]

    keySchema = keyType  # noqa: N815
    valueSchema = valueType  # noqa: N815


def _exhaustive_values(schema: ZodType[Any]) -> list[Any] | None:
    if isinstance(schema, ZodEnum):
        return list(schema._def["entries"].values())
    if isinstance(schema, ZodLiteral):
        return list(schema._def["values"])
    if isinstance(schema, ZodUnion):
        values: list[Any] = []
        for option in schema._def["options"]:
            sub = _exhaustive_values(option)
            if sub is None:
                return None
            values.extend(sub)
        return values
    if isinstance(schema, ZodPipe):
        return _exhaustive_values(schema._def["in_"])
    return None


class ZodMap(ZodType[dict[K, V]], Generic[K, V]):
    _type = "map"

    def _parse(self, payload: Payload) -> Any:
        value = payload.value
        if not isinstance(value, Mapping):
            return _invalid_type(payload, self, "map")
        key_type: ZodType[Any] = self._def["keyType"]
        value_type: ZodType[Any] = self._def["valueType"]
        results = []
        for k, v in value.items():
            results.append((k, key_type._run(payload.child(k, k)), value_type._run(payload.child(v, k))))

        def finish(resolved: list[tuple[Any, Payload, Payload]]) -> Payload:
            out: dict[Any, Any] = {}
            for original_key, kr, vr in resolved:
                if kr.issues:
                    payload.push(
                        self,
                        {
                            "origin": "map",
                            "code": "invalid_key",
                            "input": value,
                            "issues": [dict(i) for i in kr.issues],
                            "path": [original_key],
                        },
                    )
                if vr.issues:
                    payload.merge(vr)
                if not kr.issues and not vr.issues:
                    out[kr.value] = vr.value
            payload.value = out
            return payload

        if any(is_awaitable(kr) or is_awaitable(vr) for _, kr, vr in results):

            async def gather() -> Payload:
                return finish(
                    [
                        (k, await kr if is_awaitable(kr) else kr, await vr if is_awaitable(vr) else vr)
                        for k, kr, vr in results
                    ]
                )

            return gather()
        return finish(cast("list[tuple[Any, Payload, Payload]]", results))

    @property
    def keyType(self) -> ZodType[K]:  # noqa: N802
        return self._def["keyType"]

    @property
    def valueType(self) -> ZodType[V]:  # noqa: N802
        return self._def["valueType"]

    def min(self, minimum: int, params: Any = None, **kwargs: Any) -> Self:
        return self._add_check(
            _size_check("min_size", "map", minimum=minimum, params=normalize_params(params, kwargs))
        )

    def max(self, maximum: int, params: Any = None, **kwargs: Any) -> Self:
        return self._add_check(
            _size_check("max_size", "map", maximum=maximum, params=normalize_params(params, kwargs))
        )

    def size(self, size: int, params: Any = None, **kwargs: Any) -> Self:
        return self._add_check(
            _size_check(
                "size_equals",
                "map",
                minimum=size,
                maximum=size,
                exact=True,
                params=normalize_params(params, kwargs),
            )
        )


class ZodSet(ZodType[set[T]], Generic[T]):
    _type = "set"

    def _parse(self, payload: Payload) -> Any:
        value = payload.value
        if not isinstance(value, (set, frozenset)):
            return _invalid_type(payload, self, "set")
        value_type: ZodType[Any] = self._def["valueType"]
        results = [value_type._run(payload.sibling(item)) for item in value]

        def finish(resolved: list[Payload]) -> Payload:
            out: set[Any] = set()
            for r in resolved:
                if r.issues:
                    payload.push(
                        self,
                        {
                            "origin": "set",
                            "code": "invalid_element",
                            "input": value,
                            "issues": [dict(i) for i in r.issues],
                        },
                    )
                else:
                    out.add(r.value)
            payload.value = frozenset(out) if isinstance(value, frozenset) else out
            return payload

        if any(is_awaitable(r) for r in results):
            return _then(_await_all(results), finish)
        return finish(cast("list[Payload]", results))

    @property
    def valueType(self) -> ZodType[T]:  # noqa: N802
        return self._def["valueType"]

    def min(self, minimum: int, params: Any = None, **kwargs: Any) -> Self:
        return self._add_check(
            _size_check("min_size", "set", minimum=minimum, params=normalize_params(params, kwargs))
        )

    def max(self, maximum: int, params: Any = None, **kwargs: Any) -> Self:
        return self._add_check(
            _size_check("max_size", "set", maximum=maximum, params=normalize_params(params, kwargs))
        )

    def size(self, size: int, params: Any = None, **kwargs: Any) -> Self:
        return self._add_check(
            _size_check(
                "size_equals",
                "set",
                minimum=size,
                maximum=size,
                exact=True,
                params=normalize_params(params, kwargs),
            )
        )

    def nonempty(self, params: Any = None, **kwargs: Any) -> Self:
        return self.min(1, params, **kwargs)


# --------------------------------------------------------------------------- #
# Unions & intersections
# --------------------------------------------------------------------------- #


class ZodUnion(ZodType[T], Generic[T]):
    _type = "union"

    def _parse(self, payload: Payload) -> Any:
        options: list[ZodType[Any]] = self._def["options"]
        results = [option._run(payload.sibling(payload.value)) for option in options]

        def finish(resolved: list[Payload]) -> Payload:
            for r in resolved:
                if not r.issues:
                    payload.value = r.value
                    return payload
            nonaborted = [r for r in resolved if not aborted(r)]
            if len(nonaborted) == 1:
                payload.value = nonaborted[0].value
                payload.merge(nonaborted[0])
                return payload
            payload.push(
                self,
                {
                    "code": "invalid_union",
                    "errors": [[dict(i) for i in r.issues] for r in resolved],
                    "input": payload.value,
                },
            )
            return payload

        if any(is_awaitable(r) for r in results):
            return _then(_await_all(results), finish)
        return finish(cast("list[Payload]", results))

    @property
    def options(self) -> list[ZodType[T]]:
        return list(self._def["options"])

    @property
    def _optin(self) -> str | None:
        return "optional" if any(o._optin == "optional" for o in self._def["options"]) else None

    @property
    def _optout(self) -> str | None:
        return "optional" if any(o._optout == "optional" for o in self._def["options"]) else None


class ZodXor(ZodUnion[T]):
    """Exclusive union: exactly one option must accept the input (``z.xor``)."""

    _type = "union"

    def __init__(self, **definition: Any) -> None:
        super().__init__(**definition)
        self._def["inclusive"] = False

    def _parse(self, payload: Payload) -> Any:
        options: list[ZodType[Any]] = self._def["options"]
        results = [option._run(payload.sibling(payload.value)) for option in options]

        def finish(resolved: list[Payload]) -> Payload:
            matches = [i for i, r in enumerate(resolved) if not r.issues]
            if len(matches) == 1:
                payload.value = resolved[matches[0]].value
                return payload
            if not matches:
                payload.push(
                    self,
                    {
                        "code": "invalid_union",
                        "errors": [[dict(i) for i in r.issues] for r in resolved],
                        "input": payload.value,
                    },
                )
                return payload
            payload.push(
                self,
                {
                    "code": "invalid_union",
                    "errors": [],
                    "inclusive": False,
                    "matches": matches,
                    "input": payload.value,
                },
            )
            return payload

        if any(is_awaitable(r) for r in results):
            return _then(_await_all(results), finish)
        return finish(cast("list[Payload]", results))


def _discriminator_values(schema: ZodType[Any]) -> list[Any] | None:
    if isinstance(schema, (ZodLiteral, ZodEnum)):
        return _exhaustive_values(schema)
    if isinstance(
        schema, (ZodOptional, ZodNullable, ZodDefault, ZodReadonly, ZodCatch, ZodNonOptional, ZodPrefault)
    ):
        inner = _discriminator_values(schema._def["innerType"])
        if inner is None:
            return None
        if isinstance(schema, (ZodOptional, ZodNullable, ZodDefault)):
            return [*inner, None]
        return inner
    if isinstance(schema, ZodUndefined | ZodNull):
        return [None]
    if isinstance(schema, ZodUnion):
        values: list[Any] = []
        for o in schema._def["options"]:
            sub = _discriminator_values(o)
            if sub is None:
                return None
            values.extend(sub)
        return values
    if isinstance(schema, ZodPipe):
        return _discriminator_values(schema._def["in_"])
    return None


class ZodDiscriminatedUnion(ZodUnion[T]):
    _type = "union"

    def __init__(self, **definition: Any) -> None:
        super().__init__(**definition)
        self._def["discriminatorMap"] = self._build_map()

    def _build_map(self) -> list[tuple[list[Any], ZodType[Any]]]:
        disc = self._def["discriminator"]
        mapping: list[tuple[list[Any], ZodType[Any]]] = []
        for option in self._def["options"]:
            shape = _object_shape(option)
            if shape is None or disc not in shape:
                raise ValueError(f'Invalid discriminated union option at index "{len(mapping)}"')
            values = _discriminator_values(shape[disc])
            if values is None:
                raise ValueError(f'Invalid discriminated union option at index "{len(mapping)}"')
            mapping.append((values, option))
        return mapping

    def _parse(self, payload: Payload) -> Any:
        value = payload.value
        if not isinstance(value, Mapping):
            return _invalid_type(payload, self, "object")
        disc = self._def["discriminator"]
        disc_value = value.get(disc)
        for values, option in self._def["discriminatorMap"]:
            if any(_literal_equal(disc_value, v) for v in values):
                result = option._run(payload)
                return result
        if self._def.get("unionFallback"):
            return super()._parse(payload)
        payload.push(
            self,
            {
                "code": "invalid_union",
                "errors": [],
                "note": "No matching discriminator",
                "discriminator": disc,
                "options": self._discriminator_options(),
                "input": value,
                "path": [disc],
            },
        )
        return payload

    def _discriminator_options(self) -> list[Any]:
        seen: list[Any] = []
        for values, _ in self._def["discriminatorMap"]:
            for v in values:
                if v is not None and v not in seen:
                    seen.append(v)
        return seen

    def getDiscriminatedOption(self, value: Any) -> ZodObject[Any]:  # noqa: N802
        hits = [
            option
            for values, option in self._def["discriminatorMap"]
            if any(_literal_equal(value, v) for v in values)
        ]
        if not hits:
            raise KeyError(f"{value!r} is not a declared discriminator value")
        if len(hits) > 1:
            raise ValueError(f"Ambiguous discriminator value {value!r}: {len(hits)} options accept it")
        return hits[0]

    get_discriminated_option = getDiscriminatedOption

    @property
    def discriminator(self) -> str:
        return self._def["discriminator"]


def _object_shape(schema: ZodType[Any]) -> dict[str, ZodType[Any]] | None:
    if isinstance(schema, ZodObject):
        return schema._def["shape"]
    if isinstance(schema, (ZodOptional, ZodNullable, ZodDefault, ZodReadonly, ZodLazy)):
        inner = schema._def.get("innerType") if not isinstance(schema, ZodLazy) else schema._inner
        return _object_shape(inner) if inner is not None else None
    if isinstance(schema, ZodPipe):
        return _object_shape(schema._def["in_"])
    return None


# --------------------------------------------------------------------------- #
# Wrappers
# --------------------------------------------------------------------------- #


class _Wrapper(ZodType[T], Generic[T]):
    @property
    def innerType(self) -> ZodType[Any]:  # noqa: N802
        return self._def["innerType"]

    def unwrap(self) -> ZodType[Any]:
        return self._def["innerType"]

    @property
    def _optin(self) -> str | None:
        return self._def["innerType"]._optin

    @property
    def _optout(self) -> str | None:
        return self._def["innerType"]._optout


class ZodOptional(_Wrapper[T | None], Generic[T]):
    _type = "optional"

    def _parse(self, payload: Payload) -> Any:
        inner: ZodType[Any] = self._def["innerType"]
        if payload.value is None and inner._optin != "defaulted":
            # Only a defaulted inner schema substitutes a value for absence.
            return payload
        return inner._run(payload)

    @property
    def _optin(self) -> str | None:
        return "defaulted" if self._def["innerType"]._optin == "defaulted" else "optional"

    @property
    def _optout(self) -> str | None:
        return "optional"


class ZodExactOptional(ZodOptional[T]):
    """Key may be absent, but an explicit ``None`` is passed to the inner schema (``exactOptional``)."""

    _type = "optional"

    def _parse(self, payload: Payload) -> Any:
        return self._def["innerType"]._run(payload)

    @property
    def _optin(self) -> str | None:
        return "optional"


class ZodNullable(_Wrapper[T | None], Generic[T]):
    _type = "nullable"

    def _parse(self, payload: Payload) -> Any:
        inner: ZodType[Any] = self._def["innerType"]
        if payload.value is None and inner._optin != "defaulted":
            return payload
        return inner._run(payload)


class ZodNonOptional(_Wrapper[T]):
    _type = "nonoptional"

    def _parse(self, payload: Payload) -> Any:
        inner: ZodType[Any] = self._def["innerType"]
        result = inner._run(payload)

        def finish(r: Payload) -> Payload:
            if r.value is None and not r.issues:
                r.push(self, {"code": "invalid_type", "expected": "nonoptional", "input": r.value})
            return r

        return _then(result, finish)

    @property
    def _optin(self) -> str | None:
        return None

    @property
    def _optout(self) -> str | None:
        return None


def _resolve_default(value: Any) -> Any:
    return value() if callable(value) and not isinstance(value, ZodType) else value


class ZodDefault(_Wrapper[T]):
    _type = "default"

    def _parse(self, payload: Payload) -> Any:
        inner: ZodType[Any] = self._def["innerType"]
        if payload.ctx.direction == "backward":
            return inner._run(payload)
        if payload.value is None:
            payload.value = _resolve_default(self._def["defaultValue"])
            return payload
        result = inner._run(payload)

        def finish(r: Payload) -> Payload:
            if r.value is None:
                r.value = _resolve_default(self._def["defaultValue"])
            return r

        return _then(result, finish)

    @property
    def defaultValue(self) -> T:  # noqa: N802
        return _resolve_default(self._def["defaultValue"])

    def removeDefault(self) -> ZodType[Any]:  # noqa: N802
        return self._def["innerType"]

    @property
    def _optin(self) -> str | None:
        return "defaulted"

    @property
    def _optout(self) -> str | None:
        return None


class ZodPrefault(ZodDefault[T]):
    _type = "prefault"

    def _parse(self, payload: Payload) -> Any:
        inner: ZodType[Any] = self._def["innerType"]
        if payload.ctx.direction == "backward":
            return inner._run(payload)
        if payload.value is None:
            payload.value = _resolve_default(self._def["defaultValue"])
        return inner._run(payload)


class ZodCatch(_Wrapper[T]):
    _type = "catch"

    def _parse(self, payload: Payload) -> Any:
        inner: ZodType[Any] = self._def["innerType"]
        if payload.ctx.direction == "backward":
            return inner._run(payload)
        result = inner._run(payload.sibling(payload.value))

        def finish(r: Payload) -> Payload:
            if r.issues:
                catch_value = self._def["catchValue"]
                if callable(catch_value) and not isinstance(catch_value, ZodType):
                    ctx = AttrDict(error=ZodError(list(r.issues)), input=payload.value, issues=list(r.issues))
                    payload.value = catch_value(ctx)
                else:
                    payload.value = catch_value
            else:
                payload.value = r.value
            return payload

        return _then(result, finish)

    @property
    def catchValue(self) -> Any:  # noqa: N802
        return self._def["catchValue"]

    def removeCatch(self) -> ZodType[Any]:  # noqa: N802
        return self._def["innerType"]

    @property
    def _optin(self) -> str | None:
        return "optional"

    @property
    def _optout(self) -> str | None:
        return None


def _freeze(value: Any) -> Any:
    from .declarative import Object

    if isinstance(value, Object):
        object.__setattr__(value, "_zod_frozen", True)
        return value
    if isinstance(value, dict):
        return MappingProxyType(value)
    if isinstance(value, list):
        return tuple(value)
    if isinstance(value, set):
        return frozenset(value)
    return value


class ZodReadonly(_Wrapper[T]):
    _type = "readonly"

    def _parse(self, payload: Payload) -> Any:
        inner: ZodType[Any] = self._def["innerType"]
        result = inner._run(payload)

        def finish(r: Payload) -> Payload:
            r.value = _freeze(r.value)
            return r

        return _then(result, finish)


class ZodLazy(ZodType[T], Generic[T]):
    _type = "lazy"

    def __init__(self, **definition: Any) -> None:
        super().__init__(**definition)
        self._cached: ZodType[T] | None = None

    @property
    def _inner(self) -> ZodType[T]:
        cached = self._cached
        if cached is None:
            cached = self._def["getter"]()
            self._cached = cached
        return cached

    def _parse(self, payload: Payload) -> Any:
        return self._inner._run(payload)

    def unwrap(self) -> ZodType[T]:
        return self._inner

    @property
    def schema(self) -> ZodType[T]:
        return self._inner

    @property
    def _optin(self) -> str | None:
        return self._inner._optin

    @property
    def _optout(self) -> str | None:
        return self._inner._optout


# --------------------------------------------------------------------------- #
# Effects: transform / pipe / preprocess / codec
# --------------------------------------------------------------------------- #


class ZodTransform(ZodType[T], Generic[T]):
    _type = "transform"

    def _parse(self, payload: Payload) -> Any:
        if payload.ctx.direction == "backward":
            raise ZodEncodeError("ZodTransform")
        fn = self._def["transform"]
        ctx = RefinementCtx(payload, None, self)
        result = fn(payload.value, ctx) if _takes_ctx(fn) else fn(payload.value)
        if is_awaitable(result) and not payload.ctx.async_:
            _close(result)
            raise ZodAsyncError()

        def finish(out: Any) -> Payload:
            payload.value = out
            return payload

        return _then(result, finish)


def _stop_pipe(payload: Payload, start: int) -> bool:
    """Zod's ``handlePipeResult``: any issue from one side of a pipe (or codec) stops it before the
    next side runs, and aborts the payload (so the pipe's own checks are skipped too)."""
    if len(payload.issues) <= start:
        return False
    for issue in payload.issues[start:]:
        issue.pop("continue", None)
    return True


class ZodPipe(ZodType[T], Generic[T]):
    _type = "pipe"

    def _parse(self, payload: Payload) -> Any:
        left: ZodType[Any] = self._def["in_"]
        right: ZodType[Any] = self._def["out"]
        if payload.ctx.direction == "backward":
            left, right = right, left
        start = len(payload.issues)
        result = left._run(payload)

        def finish(l: Payload) -> Any:
            if _stop_pipe(l, start):
                return l
            return right._run(l)

        return _then(result, finish)

    @property
    def in_(self) -> ZodType[Any]:
        return self._def["in_"]

    @property
    def out(self) -> ZodType[T]:
        return self._def["out"]

    @property
    def _optin(self) -> str | None:
        return self._def["in_"]._optin

    @property
    def _optout(self) -> str | None:
        return self._def["out"]._optout


class ZodCodec(ZodPipe[T]):
    _type = "pipe"

    def _parse(self, payload: Payload) -> Any:
        direction = payload.ctx.direction
        if direction == "forward":
            first: ZodType[Any] = self._def["in_"]
            second: ZodType[Any] = self._def["out"]
            fn = self._def["transform"]
        else:
            first = self._def["out"]
            second = self._def["in_"]
            fn = self._def["reverseTransform"]
        start = len(payload.issues)
        result = first._run(payload)

        def finish(l: Payload) -> Any:
            if _stop_pipe(l, start):
                return l
            ctx = RefinementCtx(l, None, self)
            transformed = fn(l.value, ctx) if _takes_ctx(fn) else fn(l.value)

            def after(out: Any) -> Any:
                if _stop_pipe(l, start):
                    return l
                l.value = out
                return second._run(l)

            return _then(transformed, after)

        return _then(result, finish)


def invert_codec(codec: ZodCodec) -> ZodCodec:
    d = codec._def
    return ZodCodec(
        in_=d["out"], out=d["in_"], transform=d["reverseTransform"], reverseTransform=d["transform"]
    )


class ZodCustom(ZodType[T], Generic[T]):
    _type = "custom"

    def _parse(self, payload: Payload) -> Any:
        fn = self._def.get("fn")
        if fn is None:
            return payload
        ctx = RefinementCtx(payload, None, self)
        result = fn(payload.value, ctx) if _takes_ctx(fn) else fn(payload.value)

        def finish(ok: Any) -> Payload:
            if not ok:
                raw: dict[str, Any] = {
                    "code": "custom",
                    "input": payload.value,
                    "continue": not self._def.get("abort", False),
                }
                if self._def.get("path"):
                    raw["path"] = list(self._def["path"])
                if self._def.get("params") is not None:
                    raw["params"] = self._def["params"]
                payload.push(self, raw)
            return payload

        return _then(result, finish)


class ZodInstanceOf(ZodCustom[C]):
    _type = "custom"

    def _parse(self, payload: Payload) -> Any:
        cls = self._def["cls"]
        if isinstance(payload.value, cls):
            return payload
        payload.push(
            self,
            {
                "code": "custom",
                "input": payload.value,
                "message": self._def.get("defaultMessage") or f"Input not instance of {cls.__name__}",
            },
        )
        return payload

    def properties(self, shape: Mapping[str, ZodType[Any]]) -> Self:
        return self.check(*properties_checks(shape))


def _get_property(value: Any, key: Any) -> tuple[bool, Any]:
    if isinstance(value, Mapping):
        return (key in value, value.get(key))
    try:
        return (True, getattr(value, key))
    except AttributeError:
        try:
            return (True, value[key])
        except Exception:
            return (False, None)


def property_check(key: Any, schema: ZodType[Any]) -> Check:
    """``z.property(key, schema)``: validate one attribute/item in place; the value is not replaced."""

    def run(payload: Payload, check: Check, inst: Any) -> Any:
        present, prop = _get_property(payload.value, key)
        child = payload.child(prop, key, missing=not present)
        result = schema._run(child)

        def finish(r: Payload) -> None:
            payload.merge(r)

        return _then(result, finish)

    return Check("property", run, params={"property": key, "schema": schema})


def properties_checks(shape: Mapping[str, ZodType[Any]]) -> list[Check]:
    """``z.properties({...})``: one ``property_check`` per entry (spread into ``.check(...)``)."""
    return [property_check(k, v) for k, v in shape.items()]


# --------------------------------------------------------------------------- #
# Function schemas (``z.function({input, output}).implement(fn)``)
# --------------------------------------------------------------------------- #


class ZodFunction:
    def __init__(
        self,
        input: Any = None,  # noqa: A002 (Zod's option name)
        output: ZodType[Any] | None = None,
        **kwargs: Any,
    ) -> None:
        args = input
        if isinstance(args, Mapping):
            params = args
            args = params.get("input")
            output = params.get("output")
        if args is None:
            args = ZodArray(element=ZodUnknown())
        elif isinstance(args, (list, tuple)):
            args = ZodTuple(items=list(args), rest=None)
        self._input: ZodType[Any] = args
        self._output: ZodType[Any] = output if output is not None else ZodUnknown()

    @property
    def input(self) -> ZodType[Any]:
        return self._input

    @property
    def output(self) -> ZodType[Any]:
        return self._output

    def implement(self, fn: Callable[..., Any]) -> Callable[..., Any]:
        def wrapped(*args: Any) -> Any:
            parsed = self._input.parse(list(args))
            result = fn(*parsed)
            return self._output.parse(result)

        wrapped.__name__ = getattr(fn, "__name__", "implemented")
        wrapped.__wrapped__ = fn  # type: ignore[attr-defined]
        return wrapped

    def implementAsync(self, fn: Callable[..., Any]) -> Callable[..., Any]:  # noqa: N802
        async def wrapped(*args: Any) -> Any:
            parsed = await self._input.parseAsync(list(args))
            result = fn(*parsed)
            if is_awaitable(result):
                result = await result
            return await self._output.parseAsync(result)

        wrapped.__name__ = getattr(fn, "__name__", "implemented")
        return wrapped

    implement_async = implementAsync

    def __call__(self, fn: Callable[..., Any]) -> Callable[..., Any]:
        return self.implement(fn)


# --------------------------------------------------------------------------- #
# Misc: stringbool, json
# --------------------------------------------------------------------------- #


class ZodStringBool(ZodType[bool]):
    _type = "pipe"

    def _parse(self, payload: Payload) -> Payload:
        value = payload.value
        if payload.ctx.direction == "backward":
            if isinstance(value, bool):
                payload.value = "true" if value else "false"
                return payload
            return _invalid_type(payload, self, "boolean")
        if not isinstance(value, str):
            return _invalid_type(payload, self, "string")
        truthy = self._def["truthy"]
        falsy = self._def["falsy"]
        key = value if self._def.get("case") == "sensitive" else value.lower()
        if key in truthy:
            payload.value = True
        elif key in falsy:
            payload.value = False
        else:
            payload.push(
                self,
                {
                    "code": "invalid_value",
                    "expected": "stringbool",
                    "values": [*truthy, *falsy],
                    "input": value,
                },
            )
        return payload


class ZodFile(ZodType[bytes]):
    _type = "file"

    def _parse(self, payload: Payload) -> Payload:
        if isinstance(payload.value, (bytes, bytearray)) or hasattr(payload.value, "read"):
            return payload
        return _invalid_type(payload, self, "file")

    def min(self, minimum: int, params: Any = None, **kwargs: Any) -> Self:
        return self._add_check(
            _size_check(
                "min_size",
                "file",
                minimum=minimum,
                params=normalize_params(params, kwargs),
                size_of=_file_size,
            )
        )

    def max(self, maximum: int, params: Any = None, **kwargs: Any) -> Self:
        return self._add_check(
            _size_check(
                "max_size",
                "file",
                maximum=maximum,
                params=normalize_params(params, kwargs),
                size_of=_file_size,
            )
        )

    def mime(self, types: Any, params: Any = None, **kwargs: Any) -> Self:
        return self


def _file_size(value: Any) -> int:
    if isinstance(value, (bytes, bytearray)):
        return len(value)
    try:
        import os

        return os.fstat(value.fileno()).st_size
    except Exception:
        return 0
