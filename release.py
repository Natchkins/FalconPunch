"""Publish a Smash Night release to GitHub.

    .venv\\Scripts\\python.exe release.py [--bump patch|minor|major]
                                        [--notes "what changed"] [--no-build] [--no-tag]

0. with --bump, raises APP_VERSION, commits and pushes it (every release
   after the first needs this — a tag is never reused for new code)
1. reads APP_VERSION from smash_night.py  -> tag v<version>
2. builds release/SmashNight-win64.zip + SmashNight-Setup.exe (build_release.py)
3. creates the annotated git tag and pushes it (skip with --no-tag)
4. creates the GitHub release (or reuses an existing one for that tag)
   with github_token.txt and uploads both assets, replacing same-named
   ones.

Installed copies see the new tag through the in-app Update button.
"""
import argparse
import os
import re
import subprocess
import sys

import requests

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import build_release  # noqa: E402

REPO = "Natchkins/FalconPunch"
API = "https://api.github.com"


def token():
    for var in ("GITHUB_TOKEN", "GH_TOKEN"):
        if os.environ.get(var):
            return os.environ[var].strip()
    path = os.path.join(HERE, "github_token.txt")
    if os.path.isfile(path):
        for line in open(path, encoding="utf-8"):
            line = line.strip()
            if line and not line.startswith("#"):
                return line
    sys.exit("No GitHub token: put one in github_token.txt (repo scope) "
             "or set GITHUB_TOKEN.")


def gh(method, url, tok, **kw):
    headers = {"Authorization": f"Bearer {tok}",
               "Accept": "application/vnd.github+json",
               "X-GitHub-Api-Version": "2022-11-28"}
    headers.update(kw.pop("headers", {}))
    r = requests.request(method, url, headers=headers, timeout=600, **kw)
    if r.status_code >= 300:
        sys.exit(f"GitHub {method} {url} -> {r.status_code}: {r.text[:400]}")
    return r


def git(*args):
    return subprocess.run(["git", *args], cwd=HERE, capture_output=True,
                          text=True)


def bump_version(part):
    """Raise APP_VERSION in smash_night.py (patch / minor / major), commit
    that file and push the branch.  Returns the new version."""
    path = os.path.join(HERE, "smash_night.py")
    src = open(path, encoding="utf-8").read()
    old = build_release.app_version()
    nums = [int(n) for n in re.findall(r"\d+", old)[:3]]
    nums += [0] * (3 - len(nums))
    i = ("major", "minor", "patch").index(part)
    nums[i] += 1
    nums[i + 1:] = [0] * (2 - i)
    new = ".".join(str(n) for n in nums)
    src, n = re.subn(r'^(APP_VERSION\s*=\s*")[^"]+(")',
                     lambda m: m.group(1) + new + m.group(2), src,
                     count=1, flags=re.M)
    if n != 1:
        sys.exit("APP_VERSION not found in smash_night.py")
    with open(path, "w", encoding="utf-8", newline="") as f:
        f.write(src)
    for args in (("add", "smash_night.py"),
                 ("commit", "-m", f"Release v{new}", "--", "smash_night.py"),
                 ("push", "origin", "HEAD")):
        r = git(*args)
        if r.returncode != 0:
            sys.exit(f"git {args[0]} failed: {r.stderr or r.stdout}")
    print(f"== version {old} -> {new} (committed and pushed)")
    return new


def ensure_tag(tag, version, push=True):
    head = git("rev-parse", "HEAD").stdout.strip()
    r = git("rev-parse", "-q", "--verify", f"refs/tags/{tag}^{{commit}}")
    if r.returncode != 0:
        r = git("tag", "-a", tag, "-m", f"Smash Night v{version}")
        if r.returncode != 0:
            sys.exit(f"git tag failed: {r.stderr}")
        print(f"== tagged {tag}")
    elif r.stdout.strip() != head:
        # Releasing new code under an old version would leave installed
        # copies unable to see it (the updater compares version numbers).
        sys.exit(f"{tag} already exists on an older commit — this version "
                 f"was already released.  Run again with --bump patch "
                 f"(or minor / major) to publish the current code.")
    if push:
        r = git("push", "origin", tag)
        if r.returncode != 0 and "already exists" not in r.stderr:
            sys.exit(f"git push tag failed: {r.stderr}")
        print(f"== pushed {tag}")


def get_or_create_release(tok, tag, version, notes):
    r = requests.get(f"{API}/repos/{REPO}/releases/tags/{tag}",
                     headers={"Authorization": f"Bearer {tok}"}, timeout=60)
    if r.status_code == 200:
        rel = r.json()
        print(f"== release {tag} exists (#{rel['id']}); updating assets")
        if notes:
            gh("PATCH", rel["url"], tok, json={"body": notes})
        return rel
    rel = gh("POST", f"{API}/repos/{REPO}/releases", tok, json={
        "tag_name": tag, "name": f"Smash Night v{version}",
        "body": notes or f"Smash Night v{version}",
        "draft": False, "prerelease": False, "make_latest": "true",
    }).json()
    print(f"== created release {rel['html_url']}")
    return rel


def upload_assets(tok, rel, paths):
    existing = {a["name"]: a for a in rel.get("assets", [])}
    upload_url = rel["upload_url"].split("{", 1)[0]
    for path in paths:
        name = os.path.basename(path)
        if name in existing:
            gh("DELETE", existing[name]["url"], tok)
            print(f"   replaced old {name}")
        with open(path, "rb") as f:
            data = f.read()
        gh("POST", f"{upload_url}?name={name}", tok, data=data,
           headers={"Content-Type": "application/octet-stream"})
        print(f"   uploaded {name} ({len(data) / 1e6:.1f} MB)")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--notes", default="", help="release notes (markdown)")
    ap.add_argument("--no-build", action="store_true",
                    help="reuse release/ as built")
    ap.add_argument("--no-tag", action="store_true",
                    help="don't create/push the git tag")
    ap.add_argument("--bump", choices=("patch", "minor", "major"),
                    help="raise APP_VERSION first (commits + pushes it)")
    args = ap.parse_args()
    tok = token()
    if args.bump:
        if args.no_build:
            sys.exit("--bump changes the version baked into the build; "
                     "it can't be combined with --no-build")
        bump_version(args.bump)
    version = build_release.app_version()
    tag = f"v{version}"
    dirty = git("status", "--porcelain").stdout.strip()
    if dirty:
        print("!! working tree has uncommitted changes — the release is "
              "built from the files on disk, the tag points at HEAD.")
    if not args.no_build:
        build_release.main()
    assets = [os.path.join(build_release.OUT, build_release.ZIP_NAME),
              os.path.join(build_release.OUT, build_release.SETUP_NAME)]
    for a in assets:
        if not os.path.isfile(a):
            sys.exit(f"missing asset {a} — run without --no-build")
    if not args.no_tag:
        ensure_tag(tag, version)
    rel = get_or_create_release(tok, tag, version, args.notes)
    upload_assets(tok, rel, assets)
    print(f"== done: {rel['html_url']}")


if __name__ == "__main__":
    main()
