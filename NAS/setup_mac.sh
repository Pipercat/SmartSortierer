#!/bin/bash

# 🚀 Smart Document Organizer - Mac mini Setup
# Installiert alles was du brauchst für lokale Dokumenten-Ablage

set -e

echo "📁 Setting up Smart Document Organizer for Mac mini..."
echo

# 1. Check if Homebrew is installed
if ! command -v brew &> /dev/null; then
    echo "❌ Homebrew nicht gefunden. Bitte installiere es zuerst:"
    echo "   /bin/bash -c \"\$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)\""
    exit 1
fi

echo "✅ Homebrew gefunden"

# 2. Install Ollama if not present
if ! command -v ollama &> /dev/null; then
    echo "📦 Installiere Ollama..."
    brew install ollama
else
    echo "✅ Ollama bereits installiert"
fi

# 3. Create virtual environment and install dependencies
echo "📦 Erstelle Python Virtual Environment..."
python3 -m venv venv
source venv/bin/activate

echo "📦 Installiere Python Dependencies..."
pip install watchdog flask requests PyPDF2 python-docx

# 4. Create folder structure
echo "📂 Erstelle Ordnerstruktur..."

NAS_DIR="$HOME/NAS"
mkdir -p "$NAS_DIR/inbox"
mkdir -p "$NAS_DIR/ablage/Rechnungen"
mkdir -p "$NAS_DIR/ablage/Vertraege"
mkdir -p "$NAS_DIR/ablage/Bank"
mkdir -p "$NAS_DIR/ablage/Arbeit"
mkdir -p "$NAS_DIR/ablage/Schule"
mkdir -p "$NAS_DIR/ablage/Privat"
mkdir -p "$NAS_DIR/ablage/Anleitungen"
mkdir -p "$NAS_DIR/ablage/Auto"
mkdir -p "$NAS_DIR/ablage/Sonstiges"
mkdir -p "$NAS_DIR/processed"

echo "✅ Ordnerstruktur erstellt unter: $NAS_DIR"

# 5. Start Ollama service
echo "🧠 Starte Ollama Service..."
ollama serve &
OLLAMA_PID=$!

# Wait for Ollama to start
sleep 3

# 6. Download LLM model
echo "📥 Lade LLM Modell (qwen2.5:7b-instruct)..."
echo "   Dies kann einige Minuten dauern..."
ollama pull qwen2.5:7b-instruct

# 7. Test Ollama
echo "🧪 Teste Ollama..."
RESPONSE=$(curl -s -X POST http://localhost:11434/api/generate \
    -H "Content-Type: application/json" \
    -d '{
        "model": "qwen2.5:7b-instruct",
        "prompt": "Say hello in one word",
        "stream": false
    }')

if echo "$RESPONSE" | grep -q "response"; then
    echo "✅ Ollama funktioniert!"
else
    echo "❌ Ollama Test fehlgeschlagen"
    exit 1
fi

# 8. Create launch script
cat > start_organizer.sh << 'EOF'
#!/bin/bash
echo "🚀 Starting Smart Document Organizer..."
echo "📂 Inbox: ~/NAS/inbox/"
echo "🌐 Web-UI: http://localhost:8080"
echo

# Start Ollama if not running
if ! pgrep -f "ollama serve" > /dev/null; then
    echo "🧠 Starting Ollama..."
    ollama serve &
    sleep 2
fi

# Start Python organizer
python3 document_organizer.py
EOF

chmod +x start_organizer.sh

# 9. Create sample test file
echo "📄 Erstelle Test-Datei..."
cat > "$NAS_DIR/inbox/test_rechnung.txt" << 'EOF'
Rechnung Nr. 2024-001
Datum: 08.01.2026

An: Max Mustermann
    Musterstraße 123
    12345 Musterstadt

Rechnungsposition:
- Webhosting Service     89,90 EUR
- Domain Renewal        12,50 EUR
                       --------
Gesamt:               102,40 EUR
MwSt. 19%:             19,46 EUR
                       --------
Endbetrag:            121,86 EUR

Zahlbar bis: 31.01.2026
IBAN: DE89 1234 5678 9012 3456 78
BIC: DEUTDEFF
Verwendungszweck: Rechnung 2024-001

Vielen Dank für Ihr Vertrauen!
EOF

echo "✅ Test-Rechnung erstellt: $NAS_DIR/inbox/test_rechnung.txt"

echo
echo "🎉 Setup komplett!"
echo
echo "📋 Nächste Schritte:"
echo "   1. ./start_organizer.sh"
echo "   2. http://localhost:8080 öffnen"
echo "   3. Test-Datei wird automatisch verarbeitet"
echo
echo "💡 Tipp: Weitere Dateien in ~/NAS/inbox/ werfen für mehr Tests"
echo "📂 Inbox-Pfad: $NAS_DIR/inbox/"