"""One-shot: fix mojibake and move mid-file Shopify import to top."""
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1] / "backend" / "app"

REPLACEMENTS = [
    ("\ufeff", ""),
    ("â€”", "-"),
    ("â€“", "-"),
    ("â€\"", "-"),
    ("â†’", "->"),
    ("â”€", "-"),
    ("Â", ""),
]


def clean(text: str) -> str:
    for a, b in REPLACEMENTS:
        text = text.replace(a, b)
    text = re.sub(r"â.{0,2}", "", text)
    return text


def main():
    for name in ("shopify_actions.py", "shopify_sync.py", "integration_actions.py"):
        p = ROOT / name
        t = p.read_text(encoding="utf-8", errors="replace")
        t = clean(t)
        p.write_text(t, encoding="utf-8")
        print("cleaned", name, "lines", t.count("\n") + 1)

    ia = ROOT / "integration_actions.py"
    t = ia.read_text(encoding="utf-8")
    # remove mid-file import
    t = t.replace(
        "\n# Shopify lives in shopify_actions.py (keeps this file under control)\n"
        "from .shopify_actions import shopify_action as _shopify  # noqa: F401\n\n",
        "\n",
    )
    if "from .shopify_actions import shopify_action as _shopify" not in t:
        t = t.replace(
            "import httpx\n\n# Note:",
            "import httpx\n\nfrom .shopify_actions import shopify_action as _shopify\n\n# Note:",
        )
    ia.write_text(t, encoding="utf-8")
    print("integration_actions import fixed")
    print(ia.read_text(encoding="utf-8")[:250])


if __name__ == "__main__":
    main()
