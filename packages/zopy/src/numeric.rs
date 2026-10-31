//! Numeric helpers mirroring Zod's JavaScript behaviour.

/// JavaScript's `Number.MAX_SAFE_INTEGER`.
pub const MAX_SAFE_INTEGER: i128 = 9_007_199_254_740_991;

/// `Number.isSafeInteger` for an already-integral value.
pub fn is_safe_integer(value: i128) -> bool {
    (-MAX_SAFE_INTEGER..=MAX_SAFE_INTEGER).contains(&value)
}

/// Number of digits after the decimal point in the shortest round-trip representation.
fn decimal_places(value: f64) -> u32 {
    let text = format!("{value}");
    match text.find('.') {
        Some(idx) => (text.len() - idx - 1) as u32,
        None => 0,
    }
}

/// Zod's `multipleOf` check: exact for integers, decimal-scaled for floats
/// (so `0.3` is a multiple of `0.1`).
pub fn is_multiple_of(value: f64, divisor: f64) -> bool {
    if divisor == 0.0 || !value.is_finite() || !divisor.is_finite() {
        return false;
    }
    if value.fract() == 0.0 && divisor.fract() == 0.0 {
        return (value as i128) % (divisor as i128) == 0;
    }
    let step = decimal_places(value).max(decimal_places(divisor));
    let factor = 10f64.powi(i32::try_from(step).unwrap_or(i32::MAX));
    let scaled_value = (value * factor).round();
    let scaled_divisor = (divisor * factor).round();
    if scaled_divisor == 0.0 {
        return false;
    }
    scaled_value % scaled_divisor == 0.0
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn multiple_of_handles_decimals() {
        assert!(is_multiple_of(0.3, 0.1));
        assert!(is_multiple_of(19.99, 0.01));
        assert!(!is_multiple_of(19.999, 0.01));
        assert!(is_multiple_of(15.0, 5.0));
        assert!(!is_multiple_of(7.0, 5.0));
        assert!(!is_multiple_of(1.0, 0.0));
    }

    #[test]
    fn safe_integer_bounds() {
        assert!(is_safe_integer(MAX_SAFE_INTEGER));
        assert!(!is_safe_integer(MAX_SAFE_INTEGER + 1));
        assert!(is_safe_integer(-MAX_SAFE_INTEGER));
    }
}
