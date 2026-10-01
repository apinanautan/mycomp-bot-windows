#!/usr/bin/env bash
set -euo pipefail
root="$(cd "$(dirname "$0")/.." && pwd)"
version="$(tr -d '\r\n' < "$root/VERSION")"
mkdir -p "$root/dist"
git -C "$root" archive --format=zip --prefix=mycomp-bot-windows/ \
  --output="$root/dist/MyComp-Bot-Windows-$version.zip" HEAD
cp "$root/Install MyComp Bot.bat" "$root/dist/Install-MyComp-Bot.bat"
printf 'Packaged MyComp Bot %s in dist/\n' "$version"
