"""Regular expressions ported from ``zod/core/regexes.ts``."""

from __future__ import annotations

import re

cuid = re.compile(r"^[cC][^\s-]{8,}$")
cuid2 = re.compile(r"^[0-9a-z]+$")
ulid = re.compile(r"^[0-9A-HJKMNP-TV-Za-hjkmnp-tv-z]{26}$")
xid = re.compile(r"^[0-9a-vA-V]{20}$")
ksuid = re.compile(r"^[A-Za-z0-9]{27}$")
nanoid = re.compile(r"^[a-zA-Z0-9_-]{21}$")

duration = re.compile(
    r"^P(?:(\d+W)|(?!.*W)(?=\d|T\d)(\d+Y)?(\d+M)?(\d+D)?(T(?=\d)(\d+H)?(\d+M)?(\d+([.,]\d+)?S)?)?)$"
)
extended_duration = re.compile(
    r"^[-+]?P(?!$)(?:(?:[-+]?\d+Y)|(?:[-+]?\d+[.,]\d+Y$))?(?:(?:[-+]?\d+M)|(?:[-+]?\d+[.,]\d+M$))?"
    r"(?:(?:[-+]?\d+W)|(?:[-+]?\d+[.,]\d+W$))?(?:(?:[-+]?\d+D)|(?:[-+]?\d+[.,]\d+D$))?"
    r"(?:T(?=[\d+-])(?:(?:[-+]?\d+H)|(?:[-+]?\d+[.,]\d+H$))?(?:(?:[-+]?\d+M)|(?:[-+]?\d+[.,]\d+M$))?"
    r"(?:[-+]?\d+(?:[.,]\d+)?S)?)??$"
)

guid = re.compile(r"^([0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})$")


def uuid(version: int | None = None) -> re.Pattern[str]:
    if version is None:
        return re.compile(
            r"^([0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[1-8][0-9a-fA-F]{3}-[89abAB][0-9a-fA-F]{3}-[0-9a-fA-F]{12}"
            r"|00000000-0000-0000-0000-000000000000|ffffffff-ffff-ffff-ffff-ffffffffffff)$"
        )
    return re.compile(
        rf"^([0-9a-fA-F]{{8}}-[0-9a-fA-F]{{4}}-{version}[0-9a-fA-F]{{3}}-[89abAB][0-9a-fA-F]{{3}}-[0-9a-fA-F]{{12}})$"
    )


uuid4 = uuid(4)
uuid6 = uuid(6)
uuid7 = uuid(7)

email = re.compile(
    r"^(?!\.)(?!.*\.\.)([A-Za-z0-9_'+\-\.]*)[A-Za-z0-9_+-]@([A-Za-z0-9][A-Za-z0-9\-]*\.)+[A-Za-z]{2,}$"
)
html5_email = re.compile(
    r"^[a-zA-Z0-9.!#$%&'*+/=?^_`{|}~-]+@[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?"
    r"(?:\.[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?)*$"
)
rfc5322_email = re.compile(
    r"^(([^<>()\[\]\\.,;:\s@\"]+(\.[^<>()\[\]\\.,;:\s@\"]+)*)|(\".+\"))@"
    r"((\[[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}\])|(([a-zA-Z\-0-9]+\.)+[a-zA-Z]{2,}))$"
)
unicode_email = re.compile(r"^[^\s@\"]{1,64}@[^\s@]{1,255}$")

# Python's ``re`` has no \p{Extended_Pictographic}; approximate with ranges.
emoji = re.compile(
    "^(?:[\U0001f000-\U0001faff☀-➿⌀-⏿⬀-⯿〰〽㊗㊙©®™ℹ‍️\U000e0020-\U000e007f\U0001f1e6-\U0001f1ff⃣]|[0-9#*]️?⃣)+$"  # noqa: RUF001
)

ipv4 = re.compile(
    r"^(?:(?:25[0-5]|2[0-4][0-9]|1[0-9][0-9]|[1-9][0-9]|[0-9])\.){3}"
    r"(?:25[0-5]|2[0-4][0-9]|1[0-9][0-9]|[1-9][0-9]|[0-9])$"
)
ipv6 = re.compile(
    r"^(([0-9a-fA-F]{1,4}:){7}[0-9a-fA-F]{1,4}|([0-9a-fA-F]{1,4}:){1,7}:|([0-9a-fA-F]{1,4}:){1,6}:[0-9a-fA-F]{1,4}"
    r"|([0-9a-fA-F]{1,4}:){1,5}(:[0-9a-fA-F]{1,4}){1,2}|([0-9a-fA-F]{1,4}:){1,4}(:[0-9a-fA-F]{1,4}){1,3}"
    r"|([0-9a-fA-F]{1,4}:){1,3}(:[0-9a-fA-F]{1,4}){1,4}|([0-9a-fA-F]{1,4}:){1,2}(:[0-9a-fA-F]{1,4}){1,5}"
    r"|[0-9a-fA-F]{1,4}:(:[0-9a-fA-F]{1,4}){1,6}|:((:[0-9a-fA-F]{1,4}){1,7}|:)"
    r"|fe80:(:[0-9a-fA-F]{0,4}){0,4}%[0-9a-zA-Z]{1,}"
    r"|::(ffff(:0{1,4}){0,1}:){0,1}((25[0-5]|(2[0-4]|1{0,1}[0-9]){0,1}[0-9])\.){3}(25[0-5]|(2[0-4]|1{0,1}[0-9]){0,1}[0-9])"
    r"|([0-9a-fA-F]{1,4}:){1,4}:((25[0-5]|(2[0-4]|1{0,1}[0-9]){0,1}[0-9])\.){3}(25[0-5]|(2[0-4]|1{0,1}[0-9]){0,1}[0-9]))$"
)
cidrv4 = re.compile(
    r"^((25[0-5]|2[0-4][0-9]|1[0-9][0-9]|[1-9][0-9]|[0-9])\.){3}"
    r"(25[0-5]|2[0-4][0-9]|1[0-9][0-9]|[1-9][0-9]|[0-9])\/([0-9]|[1-2][0-9]|3[0-2])$"
)

base64 = re.compile(r"^$|^(?:[0-9a-zA-Z+/]{4})*(?:(?:[0-9a-zA-Z+/]{2}==)|(?:[0-9a-zA-Z+/]{3}=))?$")
base64url = re.compile(r"^[A-Za-z0-9_-]*$")

hostname = re.compile(
    r"^(?=.{1,253}\.?$)[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?(?:\.[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?)*\.?$"
)
domain = re.compile(r"^([a-zA-Z0-9-]+\.)*[a-zA-Z0-9-]+$")
e164 = re.compile(r"^\+(?:[0-9]){6,14}[0-9]$")

_date_source = (
    r"(?:(?:\d\d[2468][048]|\d\d[13579][26]|\d\d0[48]|[02468][048]00|[13579][26]00)-02-29"
    r"|\d{4}-(?:(?:0[13578]|1[02])-(?:0[1-9]|[12]\d|3[01])|(?:0[469]|11)-(?:0[1-9]|[12]\d|30)"
    r"|(?:02)-(?:0[1-9]|1\d|2[0-8])))"
)
date = re.compile(f"^{_date_source}$")


def _time_source(precision: int | None = None) -> str:
    if precision == -1:
        secs = ""
    elif precision is None:
        secs = r"(?::[0-5]\d(?:\.\d+)?)?"
    elif precision == 0:
        secs = r":[0-5]\d"
    else:
        secs = rf":[0-5]\d\.\d{{{precision}}}"
    return rf"(?:[01]\d|2[0-3]):[0-5]\d{secs}"


def time(precision: int | None = None) -> re.Pattern[str]:
    return re.compile(f"^{_time_source(precision)}$")


def datetime(precision: int | None = None, offset: bool = False, local: bool = False) -> re.Pattern[str]:
    opts = ["Z"]
    if offset:
        opts.append(r"([+-]\d{2}:\d{2})")
    if local:
        opts.append("")
    tz = "(?:" + "|".join(opts) + ")"
    return re.compile(f"^{_date_source}T(?:{_time_source(precision)}){tz}$")


lowercase = re.compile(r"^[^A-Z]*$")
uppercase = re.compile(r"^[^a-z]*$")
hex_ = re.compile(r"^[0-9a-fA-F]*$")

string = re.compile(r"^[\s\S]*$")
number = re.compile(r"^-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?$")
integer = re.compile(r"^-?\d+$")
boolean = re.compile(r"^(?:true|false)$", re.IGNORECASE)


# camelCase aliases matching ``z.regexes.*`` in Zod
html5Email = html5_email  # noqa: N816
rfc5322Email = rfc5322_email  # noqa: N816
unicodeEmail = unicode_email  # noqa: N816
browserEmail = html5_email  # noqa: N816

_HASH_HEX = {"md5": 32, "sha1": 40, "sha256": 64, "sha384": 96, "sha512": 128}
_HASH_B64 = {"md5": 24, "sha1": 28, "sha256": 44, "sha384": 64, "sha512": 88}
_HASH_B64URL = {"md5": 22, "sha1": 27, "sha256": 43, "sha384": 64, "sha512": 86}


def hash_(alg: str, enc: str = "hex") -> re.Pattern[str]:
    if alg not in _HASH_HEX:
        raise ValueError(f"Unknown hash algorithm: {alg!r}")
    if enc == "hex":
        return re.compile(rf"^[0-9a-fA-F]{{{_HASH_HEX[alg]}}}$")
    if enc == "base64":
        n = _HASH_B64[alg]
        return re.compile(rf"^(?=.{{{n}}}$)[A-Za-z0-9+/]+={{0,2}}$")
    if enc == "base64url":
        return re.compile(rf"^[A-Za-z0-9_-]{{{_HASH_B64URL[alg]}}}$")
    raise ValueError(f"Unknown hash encoding: {enc!r}")


def mac(delimiter: str = ":") -> re.Pattern[str]:
    d = re.escape(delimiter)
    return re.compile(rf"^(?:(?:[0-9A-F]{{2}}{d}){{5}}[0-9A-F]{{2}}|(?:[0-9a-f]{{2}}{d}){{5}}[0-9a-f]{{2}})$")


credit_card_shape = re.compile(r"^\d+(?:[ -]\d+)*$")
iban_shape = re.compile(r"^[A-Z]{2}\d{2}[A-Z0-9]{11,30}$")
currency_code = re.compile(r"^[A-Z]{3}$")
