# 📁 Smart Document Organizer

Lokales Ablage-System mit LLM-basierten Ordner-Vorschlägen.

## 🎯 Was macht das System?

1. **Dateien in Inbox werfen** → System liest Inhalt
2. **3 passende Ordner werden vorgeschlagen** → Du wählst einen
3. **Datei wird automatisch verschoben** → Fertig!

Alles läuft **lokal** auf deinem Mac mini mit Ollama.

## 🚀 Quick Start (lokal oder GitHub Codespaces)

```bash
# 1. Dependencies installieren
python3 -m venv .venv
source .venv/bin/activate
pip install -r NAS/requirements.txt

# 2. System starten
python3 NAS/document_organizer.py

# 3. Web-UI öffnen
open http://localhost:8080
```

## 📂 Ordnerstruktur

```
~/NAS/
├── inbox/              ← Dateien hier reinwerfen
├── ablage/
│   ├── Rechnungen/
│   ├── Vertraege/
│   ├── Bank/
│   ├── Arbeit/
│   ├── Schule/
│   ├── Privat/
│   ├── Anleitungen/
│   ├── Auto/
│   └── Sonstiges/
└── processed/          ← System-Logs
```

## 🧠 LLM Requirements

- **Ollama** mit `qwen2.5:7b-instruct` oder `qwen2.5:3b-instruct` (Standard)
- Läuft komplett lokal (keine Cloud)
- Antwortet immer in strukturiertem JSON

Optional kannst du das Modell und die URL über Umgebungsvariablen steuern:

```bash
export OLLAMA_URL="http://localhost:11434/api/generate"
export OLLAMA_MODEL="qwen2.5:7b-instruct"
export OLLAMA_TIMEOUT=30
```

## 📁 Projektstruktur

```
SmartSortierer/
├── NAS/
│   ├── document_organizer.py
│   ├── requirements.txt
│   ├── setup_mac.sh
│   └── templates/
│       └── index.html
└── README.md
```

## ⚡ Features

- ✅ PDF/DOCX/TXT Text-Extraktion
- ✅ 3 Ordner-Vorschläge mit Begründung
- ✅ Web-UI für einfache Auswahl
- ✅ Automatisches File-Monitoring
- ✅ Lern-Effekt (bessere Vorschläge über Zeit)
