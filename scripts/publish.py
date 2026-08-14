#!/usr/bin/env python3
"""
publish.py — Obsidian research-vault  →  Quartz content/notes

Exports only the notes whose frontmatter contains `publish: true`.

What it does:
  1. scans the vault for markdown files with publish: true
  2. normalises filenames to safe slugs   (Material Intelligence — Draft.md -> material-intelligence-draft.md)
  3. rewrites [[wikilinks]] to point at the new slugs, keeping the original text as alias
  4. copies embedded images into content/attachments/
  5. strips private frontmatter fields before writing
  6. fully regenerates content/notes/ and content/attachments/ each run,
     so unpublishing a note in Obsidian removes it from the site

Everything else in content/ (index.md, maps/, ...) is hand-written and never touched.

Usage:
    python3 publish.py            # export
    python3 publish.py --dry-run  # show what would happen
"""

import re
import shutil
import sys
import unicodedata
from pathlib import Path

# ---------------------------------------------------------------- config
VAULT = Path.home() / "research-vault"
SITE = Path.home() / "rethinksci-gif.github.io"

OUT_NOTES = SITE / "content" / "notes"
OUT_ASSETS = SITE / "content" / "attachments"

# frontmatter keys that must never reach the public site
DROP_KEYS = {"publish", "private", "private-notes", "source-private", "cssclasses"}

# folders inside the vault that are never scanned
SKIP_DIRS = {".obsidian", ".trash", ".git", "templates", "_private"}

IMAGE_EXT = {".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp", ".avif", ".pdf"}

DRY_RUN = "--dry-run" in sys.argv


# ---------------------------------------------------------------- helpers
def slugify(name: str) -> str:
    """'Material Intelligence — Draft' -> 'material-intelligence-draft'"""
    name = unicodedata.normalize("NFKD", name)
    name = name.encode("ascii", "ignore").decode("ascii")
    name = re.sub(r"[^A-Za-z0-9]+", "-", name)
    return re.sub(r"-{2,}", "-", name).strip("-").lower() or "untitled"


def split_frontmatter(text: str):
    """returns (frontmatter_lines, body). frontmatter_lines is [] if none."""
    if not text.startswith("---"):
        return [], text
    lines = text.splitlines()
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            return lines[1:i], "\n".join(lines[i + 1:])
    return [], text


def frontmatter_has_publish(fm_lines) -> bool:
    for line in fm_lines:
        if re.match(r"^publish\s*:\s*true\s*$", line.strip(), re.I):
            return True
    return False


def clean_frontmatter(fm_lines):
    """drop private keys and their indented continuation lines"""
    out, dropping = [], False
    for line in fm_lines:
        if line[:1] in (" ", "\t", "-") and dropping:
            continue
        key = line.split(":", 1)[0].strip().lower()
        dropping = key in DROP_KEYS
        if not dropping:
            out.append(line)
    return out


# ---------------------------------------------------------------- collect
if not VAULT.exists():
    sys.exit(f"vault not found: {VAULT}")
if not (SITE / "content").exists():
    sys.exit(f"site content/ not found: {SITE / 'content'}")

sources, slug_map = [], {}          # slug_map: original stem -> slug
for md in sorted(VAULT.rglob("*.md")):
    if any(p in SKIP_DIRS for p in md.relative_to(VAULT).parts[:-1]):
        continue
    fm, body = split_frontmatter(md.read_text(encoding="utf-8"))
    if not frontmatter_has_publish(fm):
        continue
    slug = slugify(md.stem)
    if slug in slug_map.values():                       # collision guard
        slug = f"{slug}-{len(slug_map)}"
    slug_map[md.stem] = slug
    sources.append((md, fm, body, slug))

if not sources:
    sys.exit("no notes with `publish: true` found — nothing to do")


# ---------------------------------------------------------------- rewrite
WIKILINK = re.compile(r"(!?)\[\[([^\]\[|#]+)(#[^\]|]+)?(\|[^\]]+)?\]\]")
MDIMAGE = re.compile(r"!\[([^\]]*)\]\(([^)]+)\)")
assets_needed = set()


def find_asset(filename: str):
    hits = list(VAULT.rglob(filename))
    return hits[0] if hits else None


def rewrite(match):
    bang, target, heading, alias = match.groups()
    target, heading, alias = target.strip(), heading or "", alias or ""
    if bang:                                            # ![[embed]]
        if Path(target).suffix.lower() in IMAGE_EXT:
            src = find_asset(Path(target).name)
            if src:
                assets_needed.add(src)
                return f"![]( /attachments/{src.name} )".replace(" ", "")
        return ""                                       # note transclusion: drop
    slug = slug_map.get(target)
    if slug is None:
        return alias.lstrip("|") or target              # unpublished -> plain text
    return f"[[notes/{slug}{heading}{alias or '|' + target}]]"


def rewrite_md_image(match):
    alt, path = match.groups()
    if path.startswith(("http://", "https://", "/")):
        return match.group(0)
    src = find_asset(Path(path).name)
    if not src:
        return match.group(0)
    assets_needed.add(src)
    return f"![{alt}](/attachments/{src.name})"


# ---------------------------------------------------------------- write
if not DRY_RUN:
    shutil.rmtree(OUT_NOTES, ignore_errors=True)
    shutil.rmtree(OUT_ASSETS, ignore_errors=True)
    OUT_NOTES.mkdir(parents=True, exist_ok=True)
    OUT_ASSETS.mkdir(parents=True, exist_ok=True)

for md, fm, body, slug in sources:
    body = WIKILINK.sub(rewrite, body)
    body = MDIMAGE.sub(rewrite_md_image, body)
    fm = clean_frontmatter(fm)
    text = "---\n" + "\n".join(fm).strip() + "\n---\n" + body.rstrip() + "\n"
    print(f"  {md.relative_to(VAULT)}  ->  content/notes/{slug}.md")
    if not DRY_RUN:
        (OUT_NOTES / f"{slug}.md").write_text(text, encoding="utf-8")

for src in sorted(assets_needed):
    print(f"  {src.relative_to(VAULT)}  ->  content/attachments/{src.name}")
    if not DRY_RUN:
        shutil.copy2(src, OUT_ASSETS / src.name)

print(f"\n{len(sources)} notes, {len(assets_needed)} assets"
      + ("  (dry run, nothing written)" if DRY_RUN else ""))
print("next:  cd ~/rethinksci-gif.github.io && git add content && "
      "git commit -m 'Publish notes' && git push")
