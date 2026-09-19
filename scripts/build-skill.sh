#!/usr/bin/env bash
# Package the skill as a zip for agents that install skills by upload.
#
# The Agent Skills format wants a single top-level folder with SKILL.md at its
# root, so the zip is built from the skill directory itself. Symlinks are
# dereferenced: a zip that carries a symlink arrives as a broken link on the
# other side.
#
#   scripts/build-skill.sh            -> dist/jyotish-reading.zip
#   scripts/build-skill.sh /tmp/out   -> /tmp/out/jyotish-reading.zip

set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
skill="$root/plugins/jyotish/skills/jyotish-reading"
out="${1:-$root/dist}"
name="jyotish-reading"

if [ ! -f "$skill/SKILL.md" ]; then
    echo "нет $skill/SKILL.md" >&2
    exit 1
fi

# Limits of the format, checked before packing rather than on upload.
max_zip=$((50 * 1024 * 1024))
max_file=$((25 * 1024 * 1024))
max_files=500

staging="$(mktemp -d)"
trap 'rm -rf "$staging"' EXIT
cp -RL "$skill" "$staging/$name"
find "$staging/$name" -name '__pycache__' -type d -prune -exec rm -rf {} +
find "$staging/$name" -name '.DS_Store' -delete

count=$(find "$staging/$name" -type f | wc -l)
if [ "$count" -gt "$max_files" ]; then
    echo "файлов $count, предел формата $max_files" >&2
    exit 1
fi
while IFS= read -r file; do
    size=$(wc -c < "$file")
    if [ "$size" -gt "$max_file" ]; then
        echo "файл больше 25 МБ: ${file#$staging/}" >&2
        exit 1
    fi
done < <(find "$staging/$name" -type f)

mkdir -p "$out"
archive="$out/$name.zip"
rm -f "$archive"
(cd "$staging" && zip -qr "$archive" "$name")

size=$(wc -c < "$archive")
if [ "$size" -gt "$max_zip" ]; then
    echo "архив больше 50 МБ, предел формата" >&2
    exit 1
fi

echo "$archive"
echo "  файлов: $count, размер: $(( (size + 1023) / 1024 )) КБ"
