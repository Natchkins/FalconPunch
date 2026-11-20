"""Publish a Smash Night release to GitHub.

    .venv\\Scripts\\python.exe release.py [--notes "what changed"] [--no-build] [--no-tag]

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


def ensure_tag(tag, version, push=True):
    if git("rev-parse", "-q", "--verify", f"refs/tags/{tag}").returncode != 0:
        r = git("tag", "-a", tag, "-m", f"Smash Night v{version}")
        if r.returncode != 0:
            sys.exit(f"git tag failed: {r.stderr}")
        print(f"== tagged {tag}")
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
    args = ap.parse_args()
    version = build_release.app_version()
    tag = f"v{version}"
    dirty = git("status", "--porcelain").stdout.strip()
    if dirty:
        print("!! working tree has uncommitted changes — the release is "
              "built from the files on disk, the tag points at HEAD.")
    tok = token()
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
