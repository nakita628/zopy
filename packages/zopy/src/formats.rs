//! String format validators ported from `zod/core/regexes.ts`.
//!
//! Patterns that need look-around use `fancy_regex`; everything else uses `regex`.

use std::net::{IpAddr, Ipv4Addr, Ipv6Addr};
use std::sync::LazyLock;

use base64::Engine as _;
use regex::Regex;

/// Options collected from the Python check parameters.
#[derive(Debug, Default, Clone)]
pub struct FormatOptions {
    pub version: Option<u8>,
    pub precision: Option<i32>,
    pub offset: bool,
    pub local: bool,
    pub alg: Option<String>,
    pub enc: Option<String>,
    pub delimiter: Option<String>,
}

/// A compiled format check.
#[derive(Debug)]
pub enum Format {
    Re(Regex),
    Fancy(fancy_regex::Regex),
    /// Zod's email regex with `(?!\.)(?!.*\.\.)` handled outside the regex.
    Email(Regex),
    Ipv4,
    Ipv6,
    Ip,
    Cidrv4,
    Cidrv6,
    Cidr,
    Url,
    Jwt(Option<String>),
    CreditCard,
    CurrencyCode,
    Iban,
}

const DATE_SOURCE: &str = r"(?:(?:\d\d[2468][048]|\d\d[13579][26]|\d\d0[48]|[02468][048]00|[13579][26]00)-02-29|\d{4}-(?:(?:0[13578]|1[02])-(?:0[1-9]|[12]\d|3[01])|(?:0[469]|11)-(?:0[1-9]|[12]\d|30)|(?:02)-(?:0[1-9]|1\d|2[0-8])))";

fn time_source(precision: Option<i32>) -> String {
    let secs = match precision {
        Some(-1) => String::new(),
        None => r"(?::[0-5]\d(?:\.\d+)?)?".to_string(),
        Some(0) => r":[0-5]\d".to_string(),
        Some(p) => format!(r":[0-5]\d\.\d{{{p}}}"),
    };
    format!(r"(?:[01]\d|2[0-3]):[0-5]\d{secs}")
}

static EMOJI: LazyLock<Regex> = LazyLock::new(|| {
    Regex::new(
        "^(?:[\\x{1F000}-\\x{1FAFF}\\x{2600}-\\x{27BF}\\x{2300}-\\x{23FF}\\x{2B00}-\\x{2BFF}\\x{3030}\\x{303D}\\x{3297}\\x{3299}\
         \\x{A9}\\x{AE}\\x{2122}\\x{2139}\\x{200D}\\x{FE0F}\\x{E0020}-\\x{E007F}\\x{1F1E6}-\\x{1F1FF}\\x{20E3}]\
         |[0-9#*]\\x{FE0F}?\\x{20E3})+$",
    )
    .expect("emoji regex")
});

static CREDIT_CARD_SHAPE: LazyLock<Regex> =
    LazyLock::new(|| Regex::new(r"^\d+(?:[ -]\d+)*$").expect("regex"));
static IBAN_SHAPE: LazyLock<Regex> =
    LazyLock::new(|| Regex::new(r"^[A-Z]{2}\d{2}[A-Z0-9]{11,30}$").expect("regex"));

const CURRENCY_CODES: &[&str] = &[
    "AED", "AFN", "ALL", "AMD", "AOA", "ARS", "AUD", "AWG", "AZN", "BAM", "BBD", "BDT", "BGN",
    "BHD", "BIF", "BMD", "BND", "BOB", "BOV", "BRL", "BSD", "BTN", "BWP", "BYN", "BZD", "CAD",
    "CDF", "CHE", "CHF", "CHW", "CLF", "CLP", "CNY", "COP", "COU", "CRC", "CUP", "CVE", "CZK",
    "DJF", "DKK", "DOP", "DZD", "EGP", "ERN", "ETB", "EUR", "FJD", "FKP", "GBP", "GEL", "GHS",
    "GIP", "GMD", "GNF", "GTQ", "GYD", "HKD", "HNL", "HTG", "HUF", "IDR", "ILS", "INR", "IQD",
    "IRR", "ISK", "JMD", "JOD", "JPY", "KES", "KGS", "KHR", "KMF", "KPW", "KRW", "KWD", "KYD",
    "KZT", "LAK", "LBP", "LKR", "LRD", "LSL", "LYD", "MAD", "MDL", "MGA", "MKD", "MMK", "MNT",
    "MOP", "MRU", "MUR", "MVR", "MWK", "MXN", "MXV", "MYR", "MZN", "NAD", "NGN", "NIO", "NOK",
    "NPR", "NZD", "OMR", "PAB", "PEN", "PGK", "PHP", "PKR", "PLN", "PYG", "QAR", "RON", "RSD",
    "RUB", "RWF", "SAR", "SBD", "SCR", "SDG", "SEK", "SGD", "SHP", "SLE", "SOS", "SRD", "SSP",
    "STN", "SVC", "SYP", "SZL", "THB", "TJS", "TMT", "TND", "TOP", "TRY", "TTD", "TWD", "TZS",
    "UAH", "UGX", "USD", "USN", "UYI", "UYU", "UYW", "UZS", "VED", "VES", "VND", "VUV", "WST",
    "XAF", "XAG", "XAU", "XBA", "XBB", "XBC", "XBD", "XCD", "XCG", "XDR", "XOF", "XPD", "XPF",
    "XPT", "XSU", "XTS", "XUA", "XXX", "YER", "ZAR", "ZMW", "ZWG",
];

fn re(pattern: &str) -> Option<Format> {
    Regex::new(pattern).ok().map(Format::Re)
}

fn fancy(pattern: &str) -> Option<Format> {
    fancy_regex::Regex::new(pattern).ok().map(Format::Fancy)
}

impl Format {
    /// Compile a user regex (already translated from Python syntax). `fancy_regex` is only used
    /// for look-around and backreferences, so ordinary patterns keep `regex`'s linear-time engine.
    pub fn pattern(source: &str) -> Option<Format> {
        if let Some(f) = re(source) {
            return Some(f);
        }
        let needs_fancy = ["(?=", "(?!", "(?<=", "(?<!"]
            .iter()
            .any(|p| source.contains(p))
            || source
                .as_bytes()
                .windows(2)
                .any(|w| w[0] == b'\\' && w[1].is_ascii_digit() && w[1] != b'0');
        if needs_fancy {
            fancy(source)
        } else {
            None
        }
    }

    /// Build the validator for a Zod format name. Returns `None` for unknown formats,
    /// which the caller then validates in Python instead.
    pub fn new(name: &str, opts: &FormatOptions) -> Option<Format> {
        match name {
            // Zod's pattern minus its two look-aheads, which `is_match` checks directly so the
            // linear-time `regex` engine can run the rest.
            "email" => Some(Format::Email(Regex::new(
                r"^([A-Za-z0-9_'+\-\.]*)[A-Za-z0-9_+-]@([A-Za-z0-9][A-Za-z0-9\-]*\.)+[A-Za-z]{2,}$",
            )
            .ok()?)),
            "uuid" => match opts.version {
                None => re(
                    r"^([0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[1-8][0-9a-fA-F]{3}-[89abAB][0-9a-fA-F]{3}-[0-9a-fA-F]{12}|00000000-0000-0000-0000-000000000000|ffffffff-ffff-ffff-ffff-ffffffffffff)$",
                ),
                Some(v) => re(&format!(
                    r"^([0-9a-fA-F]{{8}}-[0-9a-fA-F]{{4}}-{v}[0-9a-fA-F]{{3}}-[89abAB][0-9a-fA-F]{{3}}-[0-9a-fA-F]{{12}})$"
                )),
            },
            "uuidv4" => Format::new(
                "uuid",
                &FormatOptions {
                    version: Some(4),
                    ..Default::default()
                },
            ),
            "uuidv6" => Format::new(
                "uuid",
                &FormatOptions {
                    version: Some(6),
                    ..Default::default()
                },
            ),
            "uuidv7" => Format::new(
                "uuid",
                &FormatOptions {
                    version: Some(7),
                    ..Default::default()
                },
            ),
            "guid" => re(
                r"^([0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})$",
            ),
            "cuid" => re(r"^[cC][^\s-]{8,}$"),
            "cuid2" => re(r"^[0-9a-z]+$"),
            "ulid" => re(r"^[0-9A-HJKMNP-TV-Za-hjkmnp-tv-z]{26}$"),
            "xid" => re(r"^[0-9a-vA-V]{20}$"),
            "ksuid" => re(r"^[A-Za-z0-9]{27}$"),
            "nanoid" => re(r"^[a-zA-Z0-9_-]{21}$"),
            "emoji" => Some(Format::Re(EMOJI.clone())),
            "ipv4" => Some(Format::Ipv4),
            "ipv6" => Some(Format::Ipv6),
            "ip" => match opts.version {
                Some(4) => Some(Format::Ipv4),
                Some(6) => Some(Format::Ipv6),
                _ => Some(Format::Ip),
            },
            "cidrv4" => Some(Format::Cidrv4),
            "cidrv6" => Some(Format::Cidrv6),
            "cidr" => match opts.version {
                Some(4) => Some(Format::Cidrv4),
                Some(6) => Some(Format::Cidrv6),
                _ => Some(Format::Cidr),
            },
            "base64" => {
                re(r"^$|^(?:[0-9a-zA-Z+/]{4})*(?:(?:[0-9a-zA-Z+/]{2}==)|(?:[0-9a-zA-Z+/]{3}=))?$")
            }
            "base64url" => re(r"^[A-Za-z0-9_-]*$"),
            "hex" => re(r"^[0-9a-fA-F]*$"),
            "hostname" => fancy(
                r"^(?=.{1,253}\.?$)[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?(?:\.[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?)*\.?$",
            ),
            "e164" => re(r"^\+(?:[0-9]){6,14}[0-9]$"),
            "jwt" => Some(Format::Jwt(opts.alg.clone())),
            "date" => re(&format!("^{DATE_SOURCE}$")),
            "time" => re(&format!("^{}$", time_source(opts.precision))),
            "datetime" => {
                let mut tz = vec!["Z".to_string()];
                if opts.offset {
                    tz.push(r"([+-]\d{2}:\d{2})".to_string());
                }
                if opts.local {
                    tz.push(String::new());
                }
                re(&format!(
                    "^{DATE_SOURCE}T(?:{})(?:{})$",
                    time_source(opts.precision),
                    tz.join("|")
                ))
            }
            "duration" => fancy(
                r"^P(?:(\d+W)|(?!.*W)(?=\d|T\d)(\d+Y)?(\d+M)?(\d+D)?(T(?=\d)(\d+H)?(\d+M)?(\d+([.,]\d+)?S)?)?)$",
            ),
            "lowercase" => re(r"^[^A-Z]*$"),
            "uppercase" => re(r"^[^a-z]*$"),
            "mac" => {
                let d = regex::escape(opts.delimiter.as_deref().unwrap_or(":"));
                re(&format!(
                    r"^(?:(?:[0-9A-F]{{2}}{d}){{5}}[0-9A-F]{{2}}|(?:[0-9a-f]{{2}}{d}){{5}}[0-9a-f]{{2}})$"
                ))
            }
            "md5" | "sha1" | "sha256" | "sha384" | "sha512" => {
                hash_format(name, opts.enc.as_deref().unwrap_or("hex"))
            }
            "url" => Some(Format::Url),
            "credit_card" => Some(Format::CreditCard),
            "currency_code" => Some(Format::CurrencyCode),
            "iban" => Some(Format::Iban),
            _ => None,
        }
    }

    /// Run the check.
    pub fn is_match(&self, value: &str) -> bool {
        match self {
            Format::Re(r) => r.is_match(value),
            Format::Fancy(r) => r.is_match(value).unwrap_or(false),
            Format::Email(r) => {
                !value.starts_with('.') && !value.contains("..") && r.is_match(value)
            }
            Format::Ipv4 => is_ipv4(value),
            Format::Ipv6 => value.parse::<Ipv6Addr>().is_ok(),
            Format::Ip => is_ipv4(value) || value.parse::<Ipv6Addr>().is_ok(),
            Format::Cidrv4 => is_cidr(value, Some(4)),
            Format::Cidrv6 => is_cidr(value, Some(6)),
            Format::Cidr => is_cidr(value, None),
            Format::Url => url::Url::parse(value).is_ok_and(|u| u.host().is_some()),
            Format::Jwt(alg) => is_jwt(value, alg.as_deref()),
            Format::CreditCard => is_credit_card(value),
            Format::CurrencyCode => CURRENCY_CODES.binary_search(&value).is_ok(),
            Format::Iban => is_iban(value),
        }
    }
}

fn hash_format(alg: &str, enc: &str) -> Option<Format> {
    let (hex, b64, b64url) = match alg {
        "md5" => (32, 24, 22),
        "sha1" => (40, 28, 27),
        "sha256" => (64, 44, 43),
        "sha384" => (96, 64, 64),
        "sha512" => (128, 88, 86),
        _ => return None,
    };
    match enc {
        "hex" => re(&format!(r"^[0-9a-fA-F]{{{hex}}}$")),
        "base64" => fancy(&format!(r"^(?=.{{{b64}}}$)[A-Za-z0-9+/]+={{0,2}}$")),
        "base64url" => re(&format!(r"^[A-Za-z0-9_-]{{{b64url}}}$")),
        _ => None,
    }
}

fn is_ipv4(value: &str) -> bool {
    // Reject leading zeros like Zod's regex does; std accepts "01.2.3.4" on some versions.
    value.split('.').count() == 4
        && value.split('.').all(|part| {
            !part.is_empty()
                && part.len() <= 3
                && part.bytes().all(|b| b.is_ascii_digit())
                && (part == "0" || !part.starts_with('0'))
        })
        && value.parse::<Ipv4Addr>().is_ok()
}

fn is_cidr(value: &str, version: Option<u8>) -> bool {
    let Some((addr, prefix)) = value.split_once('/') else {
        return false;
    };
    let Ok(prefix) = prefix.parse::<u8>() else {
        return false;
    };
    if prefix > 0 && value[value.find('/').unwrap_or(0) + 1..].starts_with('0') {
        return false;
    }
    match addr.parse::<IpAddr>() {
        Ok(IpAddr::V4(_)) => version != Some(6) && prefix <= 32 && is_ipv4(addr),
        Ok(IpAddr::V6(_)) => version != Some(4) && prefix <= 128,
        Err(_) => false,
    }
}

fn is_jwt(value: &str, alg: Option<&str>) -> bool {
    let mut parts = value.split('.');
    let (Some(header), Some(_payload), Some(_sig), None) =
        (parts.next(), parts.next(), parts.next(), parts.next())
    else {
        return false;
    };
    let Ok(bytes) =
        base64::engine::general_purpose::URL_SAFE_NO_PAD.decode(header.trim_end_matches('='))
    else {
        return false;
    };
    let Ok(json) = serde_json::from_slice::<serde_json::Value>(&bytes) else {
        return false;
    };
    let Some(obj) = json.as_object() else {
        return false;
    };
    if let Some(typ) = obj.get("typ") {
        if typ != "JWT" {
            return false;
        }
    }
    match (obj.get("alg").and_then(|a| a.as_str()), alg) {
        (None, _) => false,
        (Some(_), None) => true,
        (Some(found), Some(expected)) => found == expected,
    }
}

fn luhn(digits: &str) -> bool {
    let mut total = 0u32;
    for (i, ch) in digits.bytes().rev().enumerate() {
        let mut d = u32::from(ch - b'0');
        if i % 2 == 1 {
            d *= 2;
            if d > 9 {
                d -= 9;
            }
        }
        total += d;
    }
    total % 10 == 0
}

fn is_credit_card(value: &str) -> bool {
    if !CREDIT_CARD_SHAPE.is_match(value) {
        return false;
    }
    let digits: String = value.chars().filter(char::is_ascii_digit).collect();
    (12..=19).contains(&digits.len()) && luhn(&digits)
}

fn is_iban(value: &str) -> bool {
    if !IBAN_SHAPE.is_match(value) {
        return false;
    }
    let rearranged = format!("{}{}", &value[4..], &value[..4]);
    let mut remainder: u32 = 0;
    for ch in rearranged.chars() {
        let digits = if ch.is_ascii_alphabetic() {
            (u32::from(ch.to_ascii_uppercase()) - 55).to_string()
        } else {
            ch.to_string()
        };
        for d in digits.chars() {
            remainder = (remainder * 10 + d.to_digit(10).unwrap_or(0)) % 97;
        }
    }
    remainder == 1
}

#[cfg(test)]
mod tests {
    use super::*;

    fn check(name: &str, value: &str) -> bool {
        Format::new(name, &FormatOptions::default())
            .expect("known format")
            .is_match(value)
    }

    #[test]
    fn email_matches_zod_lookahead_pattern() {
        let zod = fancy_regex::Regex::new(
            r"^(?!\.)(?!.*\.\.)([A-Za-z0-9_'+\-\.]*)[A-Za-z0-9_+-]@([A-Za-z0-9][A-Za-z0-9\-]*\.)+[A-Za-z]{2,}$",
        )
        .expect("regex");
        for value in [
            "a@b.co",
            ".a@b.co",
            "a..b@c.co",
            "a.b@c.co",
            "a@b..co",
            "a@b.c",
            "a\n@b.co",
            "a@b.co\n",
            "a+b_c'd@x-y.example.org",
            "-@a.bc",
            "a.@b.co",
            "",
            "@b.co",
        ] {
            assert_eq!(
                check("email", value),
                zod.is_match(value).expect("match"),
                "{value:?}"
            );
        }
    }

    #[test]
    fn emails_and_ids() {
        assert!(check("email", "a@b.co"));
        assert!(!check("email", "nope"));
        assert!(check("uuid", "123e4567-e89b-12d3-a456-426614174000"));
        assert!(!check("uuidv4", "123e4567-e89b-12d3-a456-426614174000"));
        assert!(check("nanoid", "V1StGXR8_Z5jdHi6B-myT"));
        assert!(check("emoji", "🎉🎉"));
        assert!(!check("emoji", "a"));
    }

    #[test]
    fn network() {
        assert!(check("ipv4", "192.168.0.1"));
        assert!(!check("ipv4", "01.2.3.4"));
        assert!(check("ipv6", "2001:db8::1"));
        assert!(check("cidrv4", "10.0.0.0/8"));
        assert!(!check("cidrv4", "10.0.0.0/33"));
        assert!(check("url", "https://example.com/x?y=1"));
        assert!(!check("url", "not a url"));
        assert!(check("e164", "+819012345678"));
        assert!(check("mac", "00:1A:2B:3C:4D:5E"));
        assert!(!check("mac", "00:1a:2B:3c:4d:5e"));
    }

    #[test]
    fn iso_8601() {
        assert!(check("date", "2024-02-29"));
        assert!(!check("date", "2023-02-29"));
        assert!(check("datetime", "2024-01-01T00:00:00Z"));
        assert!(!check("datetime", "2024-01-01T00:00:00+09:00"));
        let offset = Format::new(
            "datetime",
            &FormatOptions {
                offset: true,
                ..Default::default()
            },
        )
        .unwrap();
        assert!(offset.is_match("2024-01-01T00:00:00+09:00"));
        assert!(check("time", "12:34:56.789"));
        assert!(check("duration", "P3Y6M4DT12H30M5S"));
    }

    #[test]
    fn finance() {
        assert!(check("credit_card", "4111 1111 1111 1111"));
        assert!(!check("credit_card", "4111111111111112"));
        assert!(check("iban", "DE89370400440532013000"));
        assert!(!check("iban", "DE89370400440532013001"));
        assert!(check("currency_code", "JPY"));
        assert!(!check("currency_code", "ANG"));
        assert!(check("jwt", "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.e30.abc"));
        let sha = Format::new(
            "sha256",
            &FormatOptions {
                enc: Some("base64url".into()),
                ..Default::default()
            },
        )
        .unwrap();
        assert!(sha.is_match("47DEQpj8HBSa-_TImW-5JCeuQeRkm5NMpJWZG3hSuFU"));
    }
}
