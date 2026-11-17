"""Generate the synthetic training set for the ticket classifier:  python -m ml.generate_data

Real help-desk exports are confidential, so the model is bootstrapped on
templated tickets (subject x problem x phrasing). The output is deterministic
(fixed seed) and committed to the repo as ml/data/tickets.csv.
"""

import csv
import random
from pathlib import Path

OUT = Path(__file__).resolve().parent / "data" / "tickets.csv"
PER_CATEGORY = 200

CATEGORIES: dict[str, dict[str, list[str]]] = {
    "network": {
        "subjects": [
            "VPN", "office Wi-Fi", "LAN connection", "internet connection", "DNS", "proxy server",
            "firewall rule", "remote desktop gateway", "network drive", "video call bandwidth",
        ],
        "problems": [
            "keeps disconnecting every few minutes", "is extremely slow since morning",
            "cannot connect from home", "times out when reaching internal sites",
            "drops packets during meetings", "shows no internet access",
            "fails to resolve intranet hostnames", "is unreachable from the third floor",
        ],
    },
    "hardware": {
        "subjects": [
            "laptop", "monitor", "docking station", "keyboard", "mouse", "printer", "headset",
            "laptop battery", "webcam", "laptop charger",
        ],
        "problems": [
            "is not powering on", "stopped working after it was dropped",
            "is not detected when plugged in", "needs a replacement", "is physically damaged",
            "overheats within minutes", "flickers and then goes blank", "makes a loud grinding noise",
        ],
    },
    "software": {
        "subjects": [
            "Outlook", "Microsoft Teams", "Excel", "SAP client", "VS Code", "Jira", "Chrome browser",
            "Windows update", "Zoom", "Adobe Acrobat",
        ],
        "problems": [
            "crashes on startup", "freezes when opening large files", "fails to install with error 1603",
            "license has expired", "needs to be upgraded to the latest version",
            "shows a blank window after launch", "is not syncing", "throws an unexpected error on save",
        ],
    },
    "access": {
        "subjects": [
            "Active Directory account", "SSO login", "password", "shared folder permission",
            "GitHub organization access", "Jira project access", "MFA token", "new joiner account",
            "admin rights", "SharePoint site access",
        ],
        "problems": [
            "is locked after too many attempts", "needs a reset", "has expired and I cannot sign in",
            "is required for my new project", "needs approval from my manager",
            "is not working on my new phone", "should be revoked for a colleague who left",
            "was denied even though I am on the team",
        ],
    },
    "database": {
        "subjects": [
            "PostgreSQL production database", "MySQL replica", "reporting database", "nightly ETL job",
            "SQL query on the orders table", "database backup", "MongoDB cluster", "data warehouse load",
            "Redis cache", "staging database",
        ],
        "problems": [
            "is running very slowly", "failed with a deadlock error", "ran out of disk space",
            "has a replication lag of several minutes", "is rejecting new connections",
            "needs a restore from last night's backup", "returns inconsistent results",
            "timed out after thirty seconds",
        ],
    },
    "security": {
        "subjects": [
            "phishing email", "suspicious login alert", "malware warning", "lost company laptop",
            "antivirus alert", "unknown USB device", "suspicious attachment", "ransomware popup",
            "leaked API key", "unauthorized access attempt",
        ],
        "problems": [
            "was reported by several colleagues", "appeared on my machine this morning",
            "needs investigation by the security team", "may have exposed customer data",
            "came from an external sender pretending to be HR", "was detected on the finance server",
            "happened while I was travelling", "looks like a targeted attack",
        ],
    },
}

OPENERS = ["Hi team,", "Hello,", "Hi,", "Good morning,", "Need help -", "Since yesterday", "Quick one:", ""]
CLOSERS = [
    "Please look into it.", "Need this fixed before the client call.", "Thanks in advance.",
    "It is blocking my work.", "No rush, whenever possible.", "The whole team is affected.",
    "Kindly advise on next steps.", "",
]


def main() -> None:
    rng = random.Random(42)
    rows: set[tuple[str, str]] = set()
    for category, parts in CATEGORIES.items():
        made = 0
        while made < PER_CATEGORY:
            subject, problem = rng.choice(parts["subjects"]), rng.choice(parts["problems"])
            text = " ".join(p for p in (rng.choice(OPENERS), f"my {subject} {problem}.", rng.choice(CLOSERS)) if p)
            if (text, category) not in rows:
                rows.add((text, category))
                made += 1

    OUT.parent.mkdir(parents=True, exist_ok=True)
    ordered = sorted(rows, key=lambda r: (r[1], r[0]))
    with OUT.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["text", "category"])
        writer.writerows(ordered)
    print(f"Wrote {len(ordered)} rows to {OUT}")


if __name__ == "__main__":
    main()
