#!/bin/bash
# Rimuove il servizio launchd DEGEN-BOT
PLIST="$HOME/Library/LaunchAgents/com.oliverpace.degen-bot.plist"
launchctl unload "$PLIST" 2>/dev/null && echo "✓ Servizio fermato" || echo "Servizio non attivo"
rm -f "$PLIST" && echo "✓ Plist rimosso"
echo "DEGEN-BOT disinstallato."
