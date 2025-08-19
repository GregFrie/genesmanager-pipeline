#!/usr/bin/env bash
set -euo pipefail

echo "==> Update base and tools"
apt-get update
apt-get install -y wget gnupg unzip curl ca-certificates

echo "==> Install Google Chrome"
# Nowsza metoda dodania klucza (bez apt-key)
install -d -m 0755 /etc/apt/keyrings
curl -fsSL https://dl.google.com/linux/linux_signing_key.pub | tee /etc/apt/keyrings/google-linux-signing-key.pub >/dev/null
chmod a+r /etc/apt/keyrings/google-linux-signing-key.pub
echo "deb [arch=amd64 signed-by=/etc/apt/keyrings/google-linux-signing-key.pub] http://dl.google.com/linux/chrome/deb/ stable main" \
  > /etc/apt/sources.list.d/google-chrome.list

apt-get update
apt-get install -y google-chrome-stable \
  # przydatne runtime libs dla headless Chrome
  fonts-liberation libasound2 libatk-bridge2.0-0 libatk1.0-0 libcups2 \
  libdbus-1-3 libdrm2 libgbm1 libnspr4 libnss3 libx11-6 libx11-xcb1 \
  libxcb1 libxcomposite1 libxcursor1 libxdamage1 libxext6 libxfixes3 \
  libxi6 libxkbcommon0 libxrandr2 libxshmfence1 libxss1 libxtst6

echo "==> Install matching ChromeDriver"
# Pobieramy WERSJĘ GŁÓWNĄ (major), bo endpoint LATEST_RELEASE oczekuje np. 126
CHROME_VERSION_FULL=$(google-chrome-stable --version | grep -oE '[0-9.]+' | head -1)
CHROME_MAJOR=$(echo "$CHROME_VERSION_FULL" | cut -d. -f1)

CHROMEDRIVER_VERSION=$(curl -fsS "https://chromedriver.storage.googleapis.com/LATEST_RELEASE_${CHROME_MAJOR}")
echo "Chrome: $CHROME_VERSION_FULL  |  ChromeDriver: $CHROMEDRIVER_VERSION"

curl -fsSL "https://chromedriver.storage.googleapis.com/${CHROMEDRIVER_VERSION}/chromedriver_linux64.zip" -o /tmp/chromedriver.zip
unzip -o /tmp/chromedriver.zip -d /usr/local/bin
chmod +x /usr/local/bin/chromedriver
rm -f /tmp/chromedriver.zip

# Zmienne środowiskowe (część frameworków/hostów z tego korzysta)
export CHROME_BIN=/usr/bin/google-chrome
export CHROMEDRIVER=/usr/local/bin/chromedriver

echo "==> Upgrade pip & install Python deps"
python -m pip install --upgrade pip
pip install --no-cache-dir -r requirements.txt

echo "==> Build complete"
