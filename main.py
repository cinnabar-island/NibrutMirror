import requests
import json
import re
import argparse
import os
import time

DEFAULT_OUTPUT = "releases.json"
GITHUB_API = "https://api.github.com"


def get_headers(token):
    headers = {
        "Accept": "application/vnd.github+json"
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def handle_rate_limit(response):
    if response.status_code == 403:
        remaining = response.headers.get("X-RateLimit-Remaining")
        if remaining == "0":
            reset = int(response.headers.get("X-RateLimit-Reset", time.time() + 60))
            wait_time = max(reset - int(time.time()), 1)
            print(f"Rate limited. Waiting {wait_time}s...")
            time.sleep(wait_time)
            return True
    return False


def fetch_releases(owner, repo, token):
    url = f"{GITHUB_API}/repos/{owner}/{repo}/releases"
    releases = []
    page = 1
    headers = get_headers(token)

    while True:
        response = requests.get(
            url,
            headers=headers,
            params={"page": page, "per_page": 100},
            timeout=15
        )

        if handle_rate_limit(response):
            continue

        response.raise_for_status()
        data = response.json()

        if not data:
            break

        releases.extend(data)

        if len(data) < 100:
            break

        page += 1

    return releases


def extract_numbers(s):
    return [int(x) for x in re.findall(r'\d+', s or "")]


def clean_version_name(tag):
    m = re.search(r'\d.*', tag or "")
    return m.group(0) if m else tag


# Keyword matching
def match_keyword(text, keywords):
    text = (text or "").lower()
    for kw in keywords:
        if kw.lower() in text:
            return kw.lower()
    return None


# Group versions by keyword
def extract_versions_grouped(releases, keywords):
    groups = {}

    for rel in releases:
        tag = rel.get("tag_name", "")
        name = rel.get("name", "")

        for asset in rel.get("assets", []):
            if not asset["name"].lower().endswith(".apk"):
                continue

            combined_text = f"{tag} {name} {asset['name']}"
            keyword = match_keyword(combined_text, keywords) if keywords else None
            group_name = keyword if keyword else "default"

            groups.setdefault(group_name, [])

            groups[group_name].append({
                "version_name": clean_version_name(tag),
                "url": asset["browser_download_url"],
                "_parsed": extract_numbers(tag)
            })

    # Sort each group
    for group in groups.values():
        if not group:
            continue

        max_len = max(len(v["_parsed"]) for v in group)
        for v in group:
            v["_parsed"] += [0] * (max_len - len(v["_parsed"]))

        group.sort(key=lambda x: x["_parsed"])

        for i, v in enumerate(group, start=1):
            v["version"] = i
            del v["_parsed"]

    return groups


# Build app(s)
def build_json(groups, base_name, package_name=None, icon=None):
    result = []

    for group_name, versions in groups.items():
        app_name = f"{base_name} ({group_name})" if group_name != "default" else base_name

        entry = {
            "name": app_name,
            "versions": versions
        }

        if package_name:
            entry["packageName"] = package_name

        if icon:
            entry["icon"] = icon

        result.append(entry)

    return result


def main():
    parser = argparse.ArgumentParser(
        description="Fetch GitHub APK releases into JSON"
    )

    parser.add_argument("--owner", required=True)
    parser.add_argument("--repo", required=True)
    parser.add_argument("--output", default=DEFAULT_OUTPUT)
    parser.add_argument("--token", default=os.getenv("GITHUB_TOKEN"))

    parser.add_argument("--package-name")
    parser.add_argument("--icon")

    # Keywords
    parser.add_argument(
        "--keywords",
        help="Comma-separated keywords (e.g. amoled,default,tablet)"
    )

    args = parser.parse_args()

    keywords = [k.strip() for k in args.keywords.split(",")] if args.keywords else []

    releases = fetch_releases(args.owner, args.repo, args.token)
    groups = extract_versions_grouped(releases, keywords)

    data = build_json(
        groups,
        args.repo,
        package_name=args.package_name,
        icon=args.icon
    )

    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)

    total_versions = sum(len(g) for g in groups.values())
    print(f"Saved {total_versions} versions across {len(groups)} groups to {args.output}")


if __name__ == "__main__":
    main()