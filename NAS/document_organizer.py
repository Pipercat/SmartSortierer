#!/usr/bin/env python3
"""
🧠 Smart Document Organizer - Main Service
Überwacht Inbox, extrahiert Text, schlägt Ordner vor via lokalem LLM
"""

import os
import json
import time
import shutil
import hashlib
from pathlib import Path
from datetime import datetime
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler
from flask import Flask, render_template, request, jsonify
import requests
import threading

# Text extraction
import PyPDF2
from docx import Document

class DocumentProcessor:
    def __init__(self, nas_path="~/NAS"):
        self.nas_path = Path(nas_path).expanduser()
        self.inbox_path = self.nas_path / "inbox"
        self.ablage_path = self.nas_path / "ablage"
        self.processed_path = self.nas_path / "processed"
        self.llm_url = os.getenv("OLLAMA_URL", "http://localhost:11434/api/generate")
        self.llm_model = os.getenv("OLLAMA_MODEL", "qwen2.5:7b-instruct")
        self.llm_timeout = int(os.getenv("OLLAMA_TIMEOUT", "30"))
        
        # Ensure paths exist
        self.inbox_path.mkdir(parents=True, exist_ok=True)
        self.ablage_path.mkdir(parents=True, exist_ok=True)
        self.processed_path.mkdir(parents=True, exist_ok=True)
        
        # Get available target folders
        self.target_folders = self._get_target_folders()
        
        # Learning data
        self.learning_file = self.processed_path / "learning_data.json"
        self.learning_data = self._load_learning_data()
        
        print(f"📂 Inbox: {self.inbox_path}")
        print(f"📁 Verfügbare Zielordner: {', '.join(self.target_folders)}")
    
    def _get_target_folders(self):
        """Hole alle Ordner unter ablage/"""
        if not self.ablage_path.exists():
            return []
        
        folders = []
        for item in self.ablage_path.iterdir():
            if item.is_dir() and not item.name.startswith('.'):
                folders.append(item.name)
        
        return sorted(folders)
    
    def _load_learning_data(self):
        """Lade bisherige Entscheidungen für bessere Vorschläge"""
        if self.learning_file.exists():
            try:
                with open(self.learning_file, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except:
                pass
        return {"decisions": [], "folder_keywords": {}}
    
    def _save_learning_data(self):
        """Speichere Entscheidung für zukünftige Verbesserungen"""
        with open(self.learning_file, 'w', encoding='utf-8') as f:
            json.dump(self.learning_data, f, indent=2, ensure_ascii=False)
    
    def extract_text(self, file_path):
        """Extrahiere Text aus PDF, DOCX oder TXT"""
        file_path = Path(file_path)
        
        try:
            if file_path.suffix.lower() == '.pdf':
                return self._extract_pdf(file_path)
            elif file_path.suffix.lower() == '.docx':
                return self._extract_docx(file_path)
            elif file_path.suffix.lower() == '.doc':
                return f"DOC-Datei: {file_path.name}\nHinweis: .doc wird nicht unterstützt."
            elif file_path.suffix.lower() in ['.txt', '.md']:
                return self._extract_txt(file_path)
            else:
                return f"Dateiname: {file_path.name}\nDateityp: {file_path.suffix}"
        
        except Exception as e:
            print(f"❌ Fehler beim Text-Extrahieren aus {file_path.name}: {e}")
            return f"Dateiname: {file_path.name}\nFehler beim Lesen: {str(e)}"
    
    def _extract_pdf(self, file_path):
        """PDF Text extrahieren"""
        text = ""
        with open(file_path, 'rb') as file:
            reader = PyPDF2.PdfReader(file)
            for page in reader.pages[:3]:  # Nur erste 3 Seiten
                page_text = page.extract_text()
                if page_text:
                    text += page_text + "\n"
        
        # Begrenzen auf 2000 Zeichen für LLM
        return text[:2000] if text.strip() else f"PDF-Datei: {file_path.name}"
    
    def _extract_docx(self, file_path):
        """DOCX Text extrahieren"""
        doc = Document(file_path)
        text = ""
        for paragraph in doc.paragraphs:
            text += paragraph.text + "\n"
            if len(text) > 2000:
                break
        
        return text[:2000] if text.strip() else f"DOCX-Datei: {file_path.name}"
    
    def _extract_txt(self, file_path):
        """TXT/MD Text extrahieren"""
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()
            return content[:2000]
        except UnicodeDecodeError:
            # Fallback für andere Encodings
            try:
                with open(file_path, 'r', encoding='iso-8859-1') as f:
                    content = f.read()
                return content[:2000]
            except Exception as e:
                return f"Dateiname: {file_path.name}\nFehler beim Lesen: {str(e)}"
    
    def get_folder_suggestions(self, file_path, text_content):
        """Hole 3 Ordner-Vorschläge vom lokalen LLM"""
        if not self.target_folders:
            return [
                {"folder": "Sonstiges", "reason": "Keine Zielordner gefunden", "confidence": 0.1},
                {"folder": "Sonstiges", "reason": "Keine Zielordner gefunden", "confidence": 0.1},
                {"folder": "Sonstiges", "reason": "Keine Zielordner gefunden", "confidence": 0.1},
            ]
        
        # Erstelle Prompt mit Lern-Daten
        folder_hints = self._get_learning_hints(text_content.lower())
        
        prompt = f"""Du bist ein Ablage-Assistent für ein deutsches Dokumentensystem.

Dokumentinhalt:
{text_content}

Verfügbare Zielordner:
{chr(10).join(f'- {folder}' for folder in self.target_folders)}

{folder_hints}

Aufgabe:
Analysiere den Dokumentinhalt und schlage die 3 passendsten Ordner vor.
Berücksichtige deutsche Begriffe, Rechnungsnummern, IBANs, etc.

Antworte ausschließlich als JSON-Array:
[
  {{"folder": "Ordnername", "reason": "Kurze Begründung", "confidence": 0.85}},
  {{"folder": "Ordnername", "reason": "Kurze Begründung", "confidence": 0.60}},
  {{"folder": "Ordnername", "reason": "Kurze Begründung", "confidence": 0.35}}
]

Sortiere nach Wahrscheinlichkeit (confidence 0.0-1.0)."""

        try:
            response = requests.post(self.llm_url,
                json={
                    'model': self.llm_model,
                    'prompt': prompt,
                    'stream': False,
                    'options': {
                        'temperature': 0.3,
                        'top_p': 0.9
                    }
                },
                timeout=self.llm_timeout
            )
            
            if response.status_code == 200:
                result = response.json()
                llm_response = result.get('response', '').strip()
                
                # Parse JSON response
                return self._parse_llm_response(llm_response)
            
            else:
                print(f"❌ Ollama Error: {response.status_code}")
                return self._fallback_suggestions(text_content)
        
        except Exception as e:
            print(f"❌ LLM Fehler: {e}")
            return self._fallback_suggestions(text_content)
    
    def _get_learning_hints(self, text_lower):
        """Gib Hints basierend auf früheren Entscheidungen"""
        hints = []
        
        # Schaue nach Schlüsselwörtern aus früheren Entscheidungen
        for folder, keywords in self.learning_data.get("folder_keywords", {}).items():
            for keyword in keywords:
                if keyword.lower() in text_lower:
                    hints.append(f"Hinweis: '{keyword}' wurde früher oft in '{folder}' einsortiert.")
        
        if hints:
            return "Lern-Hinweise:\n" + "\n".join(hints[:3])
        return ""
    
    def _parse_llm_response(self, response):
        """Parse LLM JSON Response mit Fallbacks"""
        try:
            # Entferne mögliche Markdown-Blöcke
            if '```' in response:
                response = response.split('```')[1]
                if response.startswith('json'):
                    response = response[4:]
            
            # Parse JSON
            suggestions = json.loads(response.strip())
            if not isinstance(suggestions, list):
                raise ValueError("LLM Antwort ist kein JSON-Array")
            
            # Validiere Format
            valid_suggestions = []
            for item in suggestions:
                if isinstance(item, dict) and all(k in item for k in ['folder', 'reason', 'confidence']):
                    if item['folder'] in self.target_folders:
                        try:
                            confidence = float(item['confidence'])
                        except (TypeError, ValueError):
                            confidence = 0.0
                        valid_suggestions.append({
                            'folder': item['folder'],
                            'reason': str(item['reason'])[:100],
                            'confidence': max(0.0, min(1.0, confidence))
                        })
            
            # Sortiere nach Confidence
            valid_suggestions.sort(key=lambda x: x['confidence'], reverse=True)
            
            # Stelle sicher, dass wir 3 haben
            while len(valid_suggestions) < 3:
                remaining_folders = [f for f in self.target_folders 
                                   if f not in [s['folder'] for s in valid_suggestions]]
                if not remaining_folders:
                    break
                
                valid_suggestions.append({
                    'folder': remaining_folders[0],
                    'reason': 'Allgemeine Zuordnung',
                    'confidence': 0.1
                })
            
            return valid_suggestions[:3]
        
        except Exception as e:
            print(f"❌ JSON Parse Fehler: {e}")
            print(f"LLM Response: {response}")
            return self._fallback_suggestions("")
    
    def _fallback_suggestions(self, text_content):
        """Einfache Keyword-basierte Fallback-Vorschläge"""
        keywords = {
            'Rechnungen': ['rechnung', 'invoice', 'betrag', 'eur', '€', 'ustid', 'mwst'],
            'Bank': ['iban', 'bic', 'überweisung', 'konto', 'bank'],
            'Vertraege': ['vertrag', 'contract', 'vereinbarung', 'bedingungen'],
            'Auto': ['kfz', 'auto', 'fahrzeug', 'versicherung', 'werkstatt'],
            'Arbeit': ['arbeit', 'gehalt', 'firma', 'unternehmen', 'job']
        }
        
        text_lower = text_content.lower()
        scores = {}
        
        for folder, words in keywords.items():
            if folder in self.target_folders:
                score = sum(1 for word in words if word in text_lower)
                if score > 0:
                    scores[folder] = score
        
        # Sortiere nach Score
        sorted_folders = sorted(scores.items(), key=lambda x: x[1], reverse=True)
        
        suggestions = []
        for folder, score in sorted_folders[:2]:
            suggestions.append({
                'folder': folder,
                'reason': f'Schlüsselwörter gefunden',
                'confidence': min(0.7, score * 0.2)
            })
        
        # Fülle mit Sonstiges auf
        while len(suggestions) < 3:
            remaining = [f for f in self.target_folders 
                        if f not in [s['folder'] for s in suggestions]]
            if 'Sonstiges' in remaining:
                suggestions.append({
                    'folder': 'Sonstiges',
                    'reason': 'Standard-Fallback',
                    'confidence': 0.1
                })
            elif remaining:
                suggestions.append({
                    'folder': remaining[0],
                    'reason': 'Automatische Zuordnung',
                    'confidence': 0.1
                })
            else:
                break
        
        return suggestions

    def wait_for_file_ready(self, file_path, timeout=10, interval=0.2):
        """Warte, bis eine Datei vollständig geschrieben ist."""
        file_path = Path(file_path)
        end_time = time.time() + timeout
        last_size = -1
        while time.time() < end_time:
            try:
                current_size = file_path.stat().st_size
            except FileNotFoundError:
                time.sleep(interval)
                continue
            if current_size == last_size and current_size > 0:
                return True
            last_size = current_size
            time.sleep(interval)
        return False
    
    def move_file(self, file_path, target_folder):
        """Verschiebe Datei in Zielordner und lerne dazu"""
        file_path = Path(file_path)
        target_dir = self.ablage_path / target_folder
        target_dir.mkdir(exist_ok=True)
        
        # Zielname mit Timestamp bei Konflikten
        target_file = target_dir / file_path.name
        if target_file.exists():
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            name_parts = file_path.stem, timestamp, file_path.suffix
            target_file = target_dir / f"{name_parts[0]}_{name_parts[1]}{name_parts[2]}"
        
        # Verschieben
        shutil.move(str(file_path), str(target_file))
        
        # Lern-Daten aktualisieren
        self._update_learning_data(file_path.name, target_folder)
        
        print(f"✅ {file_path.name} → {target_folder}")
        return str(target_file)
    
    def _update_learning_data(self, filename, chosen_folder):
        """Speichere Entscheidung für besseres Lernen"""
        # Füge Entscheidung hinzu
        decision = {
            'timestamp': datetime.now().isoformat(),
            'filename': filename,
            'folder': chosen_folder
        }
        self.learning_data['decisions'].append(decision)
        
        # Aktualisiere Ordner-Keywords (vereinfacht)
        if chosen_folder not in self.learning_data['folder_keywords']:
            self.learning_data['folder_keywords'][chosen_folder] = []
        
        # Extrahiere einfache Keywords aus Dateiname
        keywords = filename.lower().replace('.pdf', '').replace('.docx', '').split('_')
        for keyword in keywords:
            if len(keyword) > 3 and keyword not in self.learning_data['folder_keywords'][chosen_folder]:
                self.learning_data['folder_keywords'][chosen_folder].append(keyword)
        
        # Behalte nur letzte 100 Entscheidungen
        self.learning_data['decisions'] = self.learning_data['decisions'][-100:]
        
        self._save_learning_data()

# Web App
app = Flask(__name__)
processor = DocumentProcessor()
pending_files = {}  # filename -> {path, suggestions, text_preview}

class InboxHandler(FileSystemEventHandler):
    def on_created(self, event):
        if not event.is_directory:
            # Warte, bis Datei vollständig geschrieben ist
            if processor.wait_for_file_ready(event.src_path):
                self.process_new_file(event.src_path)
            else:
                print(f"⚠️ Datei nicht vollständig geschrieben: {event.src_path}")
    
    def process_new_file(self, file_path):
        file_path = Path(file_path)
        
        # Ignoriere temporäre Dateien
        if file_path.name.startswith('.') or file_path.name.startswith('~'):
            return
        
        print(f"📄 Neue Datei: {file_path.name}")
        
        try:
            # Text extrahieren
            text_content = processor.extract_text(file_path)
            
            # Ordner-Vorschläge holen
            suggestions = processor.get_folder_suggestions(file_path, text_content)
            
            # Für Web-UI bereitstellen
            pending_files[file_path.name] = {
                'path': str(file_path),
                'suggestions': suggestions,
                'text_preview': text_content[:300] + "..." if len(text_content) > 300 else text_content,
                'timestamp': datetime.now().isoformat()
            }
            
            print(f"💡 Vorschläge für {file_path.name}:")
            for i, sugg in enumerate(suggestions, 1):
                print(f"   {i}. {sugg['folder']} ({sugg['confidence']:.2f}) - {sugg['reason']}")
        
        except Exception as e:
            print(f"❌ Fehler bei {file_path.name}: {e}")

@app.route('/')
def index():
    return render_template('index.html', 
                         pending_files=pending_files,
                         target_folders=processor.target_folders)

@app.route('/api/move_file', methods=['POST'])
def api_move_file():
    data = request.json
    filename = data.get('filename')
    target_folder = data.get('folder')
    
    if filename not in pending_files:
        return jsonify({'error': 'Datei nicht gefunden'}), 404
    
    if target_folder not in processor.target_folders:
        return jsonify({'error': 'Ungültiger Zielordner'}), 400
    
    try:
        file_info = pending_files[filename]
        new_path = processor.move_file(file_info['path'], target_folder)
        
        # Entferne aus Pending
        del pending_files[filename]
        
        return jsonify({
            'success': True,
            'message': f'Datei nach {target_folder} verschoben',
            'new_path': new_path
        })
    
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/status')
def api_status():
    return jsonify({
        'pending_count': len(pending_files),
        'target_folders': processor.target_folders,
        'inbox_path': str(processor.inbox_path)
    })

def start_file_watcher():
    """Starte Datei-Überwachung"""
    event_handler = InboxHandler()
    observer = Observer()
    observer.schedule(event_handler, str(processor.inbox_path), recursive=False)
    observer.start()
    print(f"👁️  Überwache: {processor.inbox_path}")
    return observer

if __name__ == '__main__':
    print("🚀 Smart Document Organizer startet...")
    print(f"📂 Inbox: {processor.inbox_path}")
    print(f"🌐 Web-UI: http://localhost:8080")
    print()
    
    # Starte File Watcher
    observer = start_file_watcher()
    
    try:
        # Starte Web Server
        app.run(host='0.0.0.0', port=8080, debug=False)
    except KeyboardInterrupt:
        print("\n🛑 Stoppe...")
        observer.stop()
    
    observer.join()
