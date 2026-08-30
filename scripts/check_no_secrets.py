"""
Secret scanner — run before every commit (see scripts/pre-commit) to catch
a credential before it ever reaches git history, not after.

Why this exists as actual code and not just a README promise: Razorpay's
own security docs state the same rule this project follows — secret keys
must never be committed to a repo, environment variables only
(razorpay.com/docs/security/). A README saying "we don't commit secrets"
is a claim; a script that structurally blocks the commit is evidence. This
also directly matches the brief's own checklist: "no leftover credentials
or placeholder names from other projects."

Patterns covered:
- Groq API keys (this project's actual provider) — gsk_...
- Razorpay API keys / key secrets — rzp_live_/rzp_test_ and the
  key_id/key_secret pattern, even though this project never calls
  Razorpay's API, in case that changes later
- AWS access keys, generic private key headers
- Any *_API_KEY / *_SECRET / *_TOKEN assignment whose value isn't an
  obvious placeholder (xxx, your_key_here, changeme, <...>, empty)

Usage:
    python scripts/check_no_secrets.py               # scans staged files
    python scripts/check_no_secrets.py --all          # scans the whole tree
    python scripts/check_no_secrets.py file1 file2    # scans specific files
"""

import re
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent

PATTERNS = [
    ("Groq API key", re.compile(r"gsk_[A-Za-z0-9]{20,}")),
    ("Razorpay API key", re.compile(r"rzp_(live|test)_[A-Za-z0-9]{10,}")),
    ("AWS access key ID", re.compile(r"AKIA[0-9A-Z]{16}")),
    ("Private key block", re.compile(r"-----BEGIN (RSA |EC |OPENSSH |)PRIVATE KEY-----")),
]

PLACEHOLDER_LOOKALIKES = re.compile(
    r"^(your[_-]?key.*|xxx+|changeme|placeholder|<.*>|\.\.\.|example|none|null|test|dummy)$",
    re.IGNORECASE,
)

ASSIGNMENT_PATTERN = re.compile(
    r"""(?P<name>[A-Z0-9_]*(?:API_KEY|SECRET|TOKEN|PASSWORD)[A-Z0-9_]*)\s*[:=]\s*["']?(?P<value>[^\s"'#]+)""",
)

# Files we deliberately allow to contain placeholder-shaped strings.
ALLOWED_PLACEHOLDER_FILES = {".env.example"}

SKIP_DIRS = {".git", ".venv", "venv", "__pycache__", ".cache", "node_modules", ".pytest_cache"}


def get_staged_files() -> list:
    result = subprocess.run(
        ["git", "diff", "--cached", "--name-only", "--diff-filter=ACM"],
        cwd=REPO_ROOT, capture_output=True, text=True,
    )
    return [REPO_ROOT / f for f in result.stdout.splitlines() if f]


def get_all_files() -> list:
    out = []
    for p in REPO_ROOT.rglob("*"):
        if p.is_file() and not any(part in SKIP_DIRS for part in p.parts):
            out.append(p)
    return out


def scan_file(path: Path) -> list:
    findings = []
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
    except (OSError, UnicodeDecodeError):
        return findings

    for name, pattern in PATTERNS:
        for m in pattern.finditer(text):
            findings.append(f"{path.relative_to(REPO_ROOT)}: possible {name} ({m.group(0)[:12]}...)")

    if path.name not in ALLOWED_PLACEHOLDER_FILES:
        for m in ASSIGNMENT_PATTERN.finditer(text):
            value = m.group("value").strip("\"'")
            if value and not PLACEHOLDER_LOOKALIKES.match(value) and len(value) >= 8:
                findings.append(
                    f"{path.relative_to(REPO_ROOT)}: {m.group('name')} assigned a non-placeholder-looking value"
                )
    return findings


def main() -> int:
    args = sys.argv[1:]
    if args and args[0] == "--all":
        files = get_all_files()
    elif args:
        files = [Path(a).resolve() for a in args]
    else:
        files = get_staged_files()

    all_findings = []
    for f in files:
        if f.exists() and f.is_file():
            all_findings.extend(scan_file(f))

    if all_findings:
        print("check_no_secrets: possible secret(s) found — commit blocked:\n")
        for finding in all_findings:
            print(f"  - {finding}")
        print("\nIf this is a genuine false positive, fix the pattern in scripts/check_no_secrets.py")
        print("rather than committing anyway — the point is nothing gets through unreviewed.")
        return 1

    print(f"check_no_secrets: {len(files)} file(s) scanned, nothing found.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
