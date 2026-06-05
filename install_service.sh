#!/bin/bash
# ============================================================
#  DEGEN-BOT — Installazione servizio macOS (launchd)
#  Eseguire dal Mac mini dopo aver clonato il repo
#
#  Uso:  bash install_service.sh
# ============================================================
set -e

BOLD='\033[1m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

BOT_DIR="$(cd "$(dirname "$0")" && pwd)"
PLIST_LABEL="com.oliverpace.degen-bot"
PLIST_PATH="$HOME/Library/LaunchAgents/$PLIST_LABEL.plist"
LOG_DIR="$BOT_DIR/logs"
PYTHON="$BOT_DIR/venv/bin/python3"

echo -e "${BOLD}⚡ DEGEN-BOT — Setup servizio macOS${NC}"
echo "   Directory: $BOT_DIR"
echo ""

# ── 1. Python disponibile? ──────────────────────────────────
if ! command -v python3 &>/dev/null; then
    echo -e "${RED}✗ python3 non trovato. Installa Python da https://python.org${NC}"
    exit 1
fi
echo -e "${GREEN}✓ Python3:${NC} $(python3 --version)"

# ── 2. Virtual environment ──────────────────────────────────
if [ ! -d "$BOT_DIR/venv" ]; then
    echo "  Creo virtual environment..."
    python3 -m venv "$BOT_DIR/venv"
fi
echo -e "${GREEN}✓ Virtual environment OK${NC}"

# ── 3. Dipendenze ───────────────────────────────────────────
echo "  Installo dipendenze..."
"$BOT_DIR/venv/bin/pip" install -r "$BOT_DIR/requirements.txt" -q
echo -e "${GREEN}✓ Dipendenze installate${NC}"

# ── 4. Credenziali Telegram ─────────────────────────────────
SECRETS="$BOT_DIR/secrets_tg.py"
if [ ! -f "$SECRETS" ] || grep -q '""' "$SECRETS"; then
    echo ""
    echo -e "${YELLOW}Inserisci le credenziali Telegram:${NC}"
    read -p "  TELEGRAM_TOKEN:   " TG_TOKEN
    read -p "  TELEGRAM_CHAT_ID: " TG_CHAT

    cat > "$SECRETS" << EOF
TELEGRAM_TOKEN   = "$TG_TOKEN"
TELEGRAM_CHAT_ID = "$TG_CHAT"
EOF
    echo -e "${GREEN}✓ Credenziali salvate${NC}"
else
    echo -e "${GREEN}✓ Credenziali già presenti${NC}"
fi

# ── 5. Cartella log ─────────────────────────────────────────
mkdir -p "$LOG_DIR"
echo -e "${GREEN}✓ Cartella log: $LOG_DIR${NC}"

# ── 6. Crea plist launchd ───────────────────────────────────
mkdir -p "$HOME/Library/LaunchAgents"

cat > "$PLIST_PATH" << EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>$PLIST_LABEL</string>

    <key>ProgramArguments</key>
    <array>
        <string>$PYTHON</string>
        <string>$BOT_DIR/main.py</string>
    </array>

    <key>WorkingDirectory</key>
    <string>$BOT_DIR</string>

    <key>RunAtLoad</key>
    <true/>

    <key>KeepAlive</key>
    <true/>

    <key>ThrottleInterval</key>
    <integer>30</integer>

    <key>StandardOutPath</key>
    <string>$LOG_DIR/output.log</string>

    <key>StandardErrorPath</key>
    <string>$LOG_DIR/error.log</string>
</dict>
</plist>
EOF

echo -e "${GREEN}✓ Plist creato: $PLIST_PATH${NC}"

# ── 7. Carica servizio ──────────────────────────────────────
# Rimuovi eventuale versione precedente
launchctl unload "$PLIST_PATH" 2>/dev/null || true
launchctl load -w "$PLIST_PATH"

echo ""
echo -e "${BOLD}${GREEN}✅ DEGEN-BOT installato come servizio di sistema!${NC}"
echo ""
echo "  Avvio automatico: ad ogni login del Mac mini"
echo "  Riavvio automatico: se crasha"
echo "  Log: tail -f $LOG_DIR/output.log"
echo ""
echo -e "  ${BOLD}Comandi utili:${NC}"
echo "   Stato:  launchctl list | grep degen"
echo "   Stop:   launchctl unload $PLIST_PATH"
echo "   Start:  launchctl load -w $PLIST_PATH"
echo "   Log:    tail -f $LOG_DIR/output.log"
echo ""
echo "  Controlla Telegram — il bot ti ha già scritto! 📱"
