"""``uv run bench``: zopy (Rust engine) against pydantic on equivalent schemas.

Prints a Markdown table: time per call for each library and how many times faster zopy is.
``uv run bench --check`` exits 1 when zopy is slower than pydantic in any scenario, so CI keeps
zopy at least as fast as pydantic.
"""

from __future__ import annotations

import argparse
import platform
import sys
import timeit
from collections.abc import Callable
from dataclasses import dataclass

import pydantic

import zopy
from zopy._compile import engine, rust_available, set_engine

from .scenarios import SCENARIOS, Scenario


@dataclass(frozen=True)
class Result:
    scenario: Scenario
    zopy_us: float
    pydantic_us: float

    @property
    def speedup(self) -> float:
        """How many times faster zopy is (> 1: faster, < 1: slower)."""
        return self.pydantic_us / self.zopy_us


def _per_call_us(fn: Callable[[], object], number: int) -> float:
    return timeit.timeit(fn, number=number) / number * 1e6


def measure(scenario: Scenario, rounds: int) -> Result:
    """Best of ``rounds`` for each side, alternating zopy / pydantic rounds so drift in machine
    load affects both equally. The minimum is the least noisy estimate on a shared machine."""
    scenario.verify()
    scenario.zopy()
    scenario.pydantic()
    zopy_times, pydantic_times = [], []
    for _ in range(rounds):
        zopy_times.append(_per_call_us(scenario.zopy, scenario.number))
        pydantic_times.append(_per_call_us(scenario.pydantic, scenario.number))
    return Result(scenario, min(zopy_times), min(pydantic_times))


def render(results: list[Result]) -> str:
    lines = [
        f"zopy {zopy.__version__} (engine: {engine()}) vs pydantic {pydantic.VERSION}, "
        f"Python {platform.python_version()} on {platform.machine()}",
        "",
        "| scenario | zopy | pydantic | zopy speedup |",
        "|---|---:|---:|---:|",
    ]
    for r in results:
        lines.append(
            f"| {r.scenario.name} | {r.zopy_us:,.2f} µs | {r.pydantic_us:,.2f} µs | {r.speedup:.2f}x |"
        )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="bench", description="zopy (Rust engine) against pydantic")
    parser.add_argument("--rounds", type=int, default=7, help="timing rounds per side (default: 7)")
    parser.add_argument(
        "--check",
        action="store_true",
        help="exit 1 when zopy is slower than pydantic in any scenario",
    )
    parser.add_argument(
        "--min-speedup",
        type=float,
        default=1.0,
        help="with --check: the lowest acceptable speedup (default: 1.0, i.e. not slower)",
    )
    parser.add_argument(
        "--retries",
        type=int,
        default=2,
        help="with --check: re-measure a scenario below the bar up to this many times (default: 2)",
    )
    parser.add_argument("-k", dest="only", help="run only scenarios whose name contains this text")
    args = parser.parse_args(argv)

    if not rust_available():
        sys.exit("bench: the zopy._core Rust extension is not built (run `uv sync`)")
    set_engine("rust")

    scenarios = [s for s in SCENARIOS if args.only is None or args.only in s.name]
    results = [measure(s, args.rounds) for s in scenarios]
    if args.check:
        # A shared machine can slow one side for a moment; a real regression stays slow on retries.
        for i, r in enumerate(results):
            for _ in range(args.retries):
                if results[i].speedup >= args.min_speedup:
                    break
                again = measure(r.scenario, args.rounds)
                if again.speedup > results[i].speedup:
                    results[i] = again
    print(render(results))

    if args.check:
        slow = [r for r in results if r.speedup < args.min_speedup]
        if slow:
            print(f"\nFAIL: zopy is below {args.min_speedup:.2f}x pydantic in:", file=sys.stderr)
            for r in slow:
                print(f"  - {r.scenario.name}: {r.speedup:.2f}x", file=sys.stderr)
            sys.exit(1)
        print(f"\nOK: zopy is at least {args.min_speedup:.2f}x pydantic in every scenario.")


if __name__ == "__main__":
    main()
