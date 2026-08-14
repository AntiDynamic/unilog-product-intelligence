"""Generate aggregate Phase 3 diagnostics from the real UniHack input CSV."""

import argparse

from unilog_product_intelligence.deterministic.diagnostics import write_diagnostic


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input_csv")
    parser.add_argument("--output", default="docs/research/phase-3-diagnostic.json")
    args = parser.parse_args()
    write_diagnostic(args.input_csv, args.output)


if __name__ == "__main__":
    main()
