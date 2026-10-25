"""Development check of chunker.estimate_tokens against Anthropic's own count (#123): not a test, it calls the API.

    cd backend && venv/bin/python scripts/token_calibration.py

Takes the most prose-heavy and the most table-heavy chunks of the filings in data/filings (see chunk_report.py), counts
each with messages.count_tokens for claude-haiku-5-5 (free, but needs ANTHROPIC_API_KEY in .env) and prints the
estimate against the real count. The estimate should be above the real count for every chunk, by roughly 10 to 20%.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import anthropic  # noqa: E402

import config  # noqa: E402
from scripts.chunk_report import filings  # noqa: E402
from secrets_guard import mask_secrets  # noqa: E402
from supply_chain import chunker  # noqa: E402

MODEL = "claude-haiku-5-5"
PER_KIND = 6


def table_share(text):
    """The share of the text in table rows (lines with cells)."""
    return sum(len(line) for line in text.split("\n") if " | " in line) / max(len(text), 1)


def count(client, text):
    return client.messages.count_tokens(model=MODEL, messages=[{"role": "user", "content": text}]).input_tokens


def main():
    if not config.anthropic_api_key():
        print("No ANTHROPIC_API_KEY in .env")
        return
    client = anthropic.Anthropic(api_key=config.anthropic_api_key())
    chunks = []
    for folder, form, primary in filings():
        for c in chunker.chunk_filing(folder, form, primary):
            if c.tokens >= 2_000:
                chunks.append((table_share(c.text), Path(folder).parts[-2], c))
    chunks.sort(key=lambda row: row[0])
    picked, seen = [], set()
    for row in chunks[:PER_KIND * 3] + chunks[::-1][:PER_KIND * 3]:  # one chunk per filing at each end
        if row[1] not in seen and sum(1 for p in picked if (p[0] > 0.3) == (row[0] > 0.3)) < PER_KIND:
            picked.append(row)
            seen.add(row[1])
    try:
        overhead = count(client, "x") - 1  # the message wrapper's own tokens
        print(f"{'tables':>6} {'estimate':>9} {'real':>9} {'ratio':>6}  chunk")
        ratios = []
        for share, _, c in sorted(picked, key=lambda row: row[0]):
            real = count(client, c.text) - overhead
            ratios.append(c.tokens / real)
            print(f"{share:6.0%} {c.tokens:9,} {real:9,} {c.tokens / real:6.2f}  {c.document} {c.section[:60]}")
        print(f"\nratio estimate / real: lowest {min(ratios):.2f}, highest {max(ratios):.2f}, mean {sum(ratios) / len(ratios):.2f}")
    except anthropic.APIError as exc:
        print(f"Count failed: {mask_secrets(str(exc))}")


if __name__ == "__main__":
    main()
