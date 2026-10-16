#!/bin/bash
# Builds ibc/dist/ for the Mac app: IBC (downloaded from its GitHub release and checked against a
# known SHA-256, so no third-party binary is committed) plus our StdinLauncher, which passes the
# IBKR username and password to IBC over stdin instead of a file or the command line.
set -euo pipefail
cd "$(dirname "$0")"

IBC_VERSION=3.24.2
IBC_SHA256=2449ef36d758ea56c6ca15fc6b6c4cbe626c8f0a95e36f6455c717ee390add93
ZIP=cache/IBCMacos-$IBC_VERSION.zip

mkdir -p cache dist
if [[ ! -f $ZIP ]]; then
  curl --fail --location --silent --show-error -o "$ZIP.part" \
    "https://github.com/IbcAlpha/IBC/releases/download/$IBC_VERSION/IBCMacos-$IBC_VERSION.zip"
  mv "$ZIP.part" "$ZIP"
fi
if [[ $(shasum -a 256 "$ZIP" | cut -d' ' -f1) != "$IBC_SHA256" ]]; then
  rm -f "$ZIP"
  echo "IBC download doesn't match the expected SHA-256; deleted it" >&2
  exit 1
fi
unzip -o -q "$ZIP" IBC.jar LICENSE.txt -d dist
mv dist/LICENSE.txt dist/IBC-LICENSE.txt

# Gateway's bundled Java is 17, so compile for 17 with any JDK 17 or newer
JAVAC=""
for candidate in "$(command -v javac || true)" /opt/homebrew/opt/openjdk/bin/javac /usr/local/opt/openjdk/bin/javac; do
  if [[ -x $candidate ]] && "$candidate" --release 17 -version >/dev/null 2>&1; then JAVAC=$candidate; break; fi
done
if [[ -z $JAVAC ]]; then
  echo "Needs a JDK 17 or newer to compile the launcher (brew install openjdk)" >&2
  exit 1
fi
rm -rf build && mkdir build
"$JAVAC" --release 17 -cp dist/IBC.jar -d build launcher/portfolio/StdinLauncher.java
(cd build && jar cf ../dist/portfolio-launcher.jar portfolio 2>/dev/null || "$(dirname "$JAVAC")/jar" cf ../dist/portfolio-launcher.jar portfolio)
rm -rf build
echo "Built $(pwd)/dist: $(ls dist | tr '\n' ' ')"
