#!/bin/bash

# GenesManager Render-Stable build script
# Minimalistyczny i niezawodny pod Render

set -e

# Aktualizacja pakietów i instalacja podstawowych narzędzi
apt-get update
apt-get install -y wget unzip curl chromium chromium-driver

# Instalacja pakietów Pythona
pip install --upgrade pip
pip install -r requirements.txt

# ✅ Zamiast ręcznej instalacji Chromedriver, korzystamy z webdriver-manager
# Selenium sam pobierze kompatybilny driver podczas uruchomienia

# 🔹 Dodatkowa informacja w logach:
echo "Build zakończony pomyślnie. Gotowy do uruchomienia pipeline'u Render-Stable."
