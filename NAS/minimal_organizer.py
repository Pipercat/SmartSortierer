#!/usr/bin/env python3
"""
📁 Minimal Document Organizer (ohne externe Dependencies)
Nur mit Python Standard Library + Ollama API calls
"""

import os
import json
import time
import shutil
import hashlib
from pathlib import Path
from datetime import datetime
import http.server
import socketserver
from urllib.parse import urlparse, parse_qs
import urllib.request
import threading

class SimpleDocumentOrganizer:
    def __init__(self, nas_path="~/NAS"):
        self.nas_path = Path(nas_path).expanduser()
        self.inbox_path = self.nas_path / "inbox"
        self.ablage_path = self.nas_path / "ablage"
        self.processed_path = self.nas_path / "processed"
        
        # Ensure paths exist
        self.inbox_path.mkdir(parents=True, exist_ok=True)
        self.processed_path.mkdir(parents=True, exist_ok=True)
        
        # Get available target folders
        self.target_folders = self._get_target_folders()
        
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
    
    def extract_text(self, file_path):
        """Einfache Text-Extraktion nur für TXT und Dateinamen-Info"""
        file_path = Path(file_path)
        
        try:
            if file_path.suffix.lower() in ['.txt', '.md']:
                with open(file_path, 'r', encoding='utf-8') as f:
                    content = f.read()
                return content[:1000]
            else:
                # Für PDF/DOCX nur Dateiname als Fallback
                return f"Dateiname: {file_path.name}\nDateityp: {file_path.suffix}"
        
        except Exception as e:
            return f"Dateiname: {file_path.name}\nFehler: {str(e)}"
    
    def get_folder_suggestions_llm(self, text_content):
        """LLM-Vorschläge via Ollama API"""
        prompt = f"""Du bist ein Ablage-Assistent.

Dokumentinhalt:
{text_content}

Verfügbare Zielordner:
{chr(10).join(f'- {folder}' for folder in self.target_folders)}

Aufgabe: Analysiere den Inhalt und schlage die 3 passendsten Ordner vor.
Antworte nur als JSON:
[
  {{"folder": "Ordnername", "reason": "Grund", "confidence": 0.8}},
  {{"folder": "Ordnername", "reason": "Grund", "confidence": 0.5}},
  {{"folder": "Ordnername", "reason": "Grund", "confidence": 0.2}}
]"""

        try:
            # Ollama API Call mit Standard urllib
            data = json.dumps({
                'model': 'llama3:8b',
                'prompt': prompt,
                'stream': False,
                'options': {'temperature': 0.3}
            }).encode('utf-8')
            
            req = urllib.request.Request(
                'http://localhost:11434/api/generate',
                data=data,
                headers={'Content-Type': 'application/json'}
            )
            
            with urllib.request.urlopen(req, timeout=20) as response:
                result = json.loads(response.read().decode())
                llm_response = result.get('response', '').strip()
                
                # Parse JSON
                if '```' in llm_response:
                    llm_response = llm_response.split('```')[1]
                    if llm_response.startswith('json'):
                        llm_response = llm_response[4:]
                
                suggestions = json.loads(llm_response.strip())
                
                # Validieren
                valid = []
                for item in suggestions[:3]:
                    if isinstance(item, dict) and 'folder' in item:
                        if item['folder'] in self.target_folders:
                            valid.append({
                                'folder': item['folder'],
                                'reason': str(item.get('reason', 'KI-Vorschlag'))[:80],
                                'confidence': float(item.get('confidence', 0.5))
                            })
                
                # Prüfe ob Vorschläge gut genug sind (Confidence >= 0.6)
                good_suggestions = [s for s in valid if s['confidence'] >= 0.6]
                if len(good_suggestions) >= 2:
                    return valid
                else:
                    return self.get_folder_creation_suggestions(text_content)
        
        except Exception as e:
            print(f"❌ LLM Fehler: {e}")
            return self.get_fallback_suggestions(text_content)
    
    def get_fallback_suggestions(self, text_content):
        """Einfache Keyword-basierte Fallback-Vorschläge"""
        keywords = {
            'Rechnungen': ['rechnung', 'invoice', 'betrag', 'eur', '€', 'mwst', 'ust'],
            'Bank': ['iban', 'bic', 'überweisung', 'konto', 'bank', 'sparkasse'],
            'Vertraege': ['vertrag', 'contract', 'vereinbarung', 'bedingungen'],
            'Auto': ['kfz', 'auto', 'fahrzeug', 'versicherung', 'werkstatt', 'tüv'],
            'Arbeit': ['arbeit', 'gehalt', 'firma', 'unternehmen', 'job', 'lohn']
        }
        
        text_lower = text_content.lower()
        scores = {}
        
        for folder, words in keywords.items():
            if folder in self.target_folders:
                score = sum(1 for word in words if word in text_lower)
                if score > 0:
                    scores[folder] = score
        
        # Top 2 Treffer
        sorted_folders = sorted(scores.items(), key=lambda x: x[1], reverse=True)
        
        suggestions = []
        for folder, score in sorted_folders[:2]:
            suggestions.append({
                'folder': folder,
                'reason': f'Schlüsselwörter erkannt',
                'confidence': min(0.8, score * 0.3)
            })
        
        # Auffüllen mit Sonstiges
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
        
        # Wenn auch Fallback nicht gut genug ist, schlage neue Ordner vor
        good_fallback = [s for s in suggestions if s['confidence'] >= 0.5]
        if len(good_fallback) >= 2:
            return suggestions[:3]
        else:
            return self.get_folder_creation_suggestions(text_content)
    
    def get_folder_creation_suggestions(self, text_content):
        """Schlage neue Ordner vor, wenn keine passenden gefunden werden"""
        prompt = f"""Du bist ein Ablage-Assistent. Der Dokumentinhalt passt zu keinem der vorhandenen Ordner.

Dokumentinhalt:
{text_content}

Vorhandene Ordner:
{chr(10).join(f'- {folder}' for folder in self.target_folders)}

Aufgabe: Schlage 3 neue, sinnvolle Ordnernamen vor, die für dieses Dokument passend wären.
Berücksichtige dabei auch mögliche Unterordner.

Antworte nur als JSON:
[
  {{"folder": "Neuer Ordnername", "subfolder": "Optional: Unterordner", "reason": "Warum dieser Ordner sinnvoll ist", "confidence": 0.8}},
  {{"folder": "Neuer Ordnername", "subfolder": null, "reason": "Grund", "confidence": 0.7}},
  {{"folder": "Neuer Ordnername", "subfolder": "Unterordner", "reason": "Grund", "confidence": 0.6}}
]"""

        try:
            # LLM Call für neue Ordnervorschläge
            data = json.dumps({
                'model': 'llama3:8b',
                'prompt': prompt,
                'stream': False,
                'options': {'temperature': 0.4}
            }).encode('utf-8')
            
            req = urllib.request.Request(
                'http://localhost:11434/api/generate',
                data=data,
                headers={'Content-Type': 'application/json'}
            )
            
            with urllib.request.urlopen(req, timeout=20) as response:
                result = json.loads(response.read().decode())
                llm_response = result.get('response', '').strip()
                
                # Parse JSON
                if '```' in llm_response:
                    llm_response = llm_response.split('```')[1]
                    if llm_response.startswith('json'):
                        llm_response = llm_response[4:]
                
                suggestions = json.loads(llm_response.strip())
                
                # Format für Frontend
                creation_suggestions = []
                for item in suggestions[:3]:
                    if isinstance(item, dict) and 'folder' in item:
                        folder_name = item['folder']
                        subfolder = item.get('subfolder')
                        
                        # Vollständiger Pfad wenn Unterordner
                        if subfolder:
                            full_path = f"{folder_name}/{subfolder}"
                            display_name = f"📁 {folder_name} / {subfolder}"
                        else:
                            full_path = folder_name
                            display_name = f"📁 {folder_name}"
                        
                        creation_suggestions.append({
                            'folder': display_name,
                            'folder_path': full_path,
                            'reason': str(item.get('reason', 'Neuer Ordner-Vorschlag'))[:100],
                            'confidence': float(item.get('confidence', 0.7)),
                            'is_new': True
                        })
                
                return creation_suggestions
        
        except Exception as e:
            print(f"❌ LLM Ordner-Erstellung Fehler: {e}")
            return self.get_default_creation_suggestions(text_content)
    
    def get_default_creation_suggestions(self, text_content):
        """Fallback: Standard neue Ordner basierend auf Inhalt"""
        text_lower = text_content.lower()
        suggestions = []
        
        # Intelligente Kategorisierung
        if any(word in text_lower for word in ['rechnung', 'invoice', 'betrag', 'eur', '€']):
            suggestions.append({
                'folder': '📁 Neue Rechnungen',
                'folder_path': 'Neue Rechnungen', 
                'reason': 'Rechnungsinhalt erkannt',
                'confidence': 0.8,
                'is_new': True
            })
        
        if any(word in text_lower for word in ['vertrag', 'contract', 'vereinbarung']):
            suggestions.append({
                'folder': '📁 Verträge / Neue Kategorie',
                'folder_path': 'Verträge/Neue Kategorie',
                'reason': 'Vertragsinhalt erkannt', 
                'confidence': 0.7,
                'is_new': True
            })
        
        # Standard-Fallbacks
        if len(suggestions) < 3:
            remaining = [
                {
                    'folder': '📁 Dokumente / Neue Kategorie',
                    'folder_path': 'Dokumente/Neue Kategorie',
                    'reason': 'Allgemeine Dokumentenablage',
                    'confidence': 0.5,
                    'is_new': True
                },
                {
                    'folder': '📁 Temporär / Zu Sortieren',
                    'folder_path': 'Temporär/Zu Sortieren',
                    'reason': 'Temporäre Ablage für spätere Sortierung',
                    'confidence': 0.4,
                    'is_new': True
                }
            ]
            suggestions.extend(remaining[:3-len(suggestions)])
        
        return suggestions[:3]
    
    def create_folder(self, folder_path):
        """Erstelle neuen Ordner (mit Unterordnern wenn nötig)"""
        full_path = self.ablage_path / folder_path
        full_path.mkdir(parents=True, exist_ok=True)
        
        # Aktualisiere verfügbare Ordner
        self.target_folders = self._get_target_folders()
        
        return str(full_path)
    
    def move_file(self, filename, target_folder, is_new_folder=False):
        """Verschiebe Datei (erstelle Ordner falls nötig)"""
        source = self.inbox_path / filename
        
        # Unterstütze Pfade mit / für Unterordner
        target_dir = self.ablage_path / target_folder
        target_dir.mkdir(parents=True, exist_ok=True)
        
        # Aktualisiere Ordnerliste wenn neuer Ordner
        if is_new_folder:
            self.target_folders = self._get_target_folders()
        
        target_file = target_dir / filename
        if target_file.exists():
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            name, ext = filename.rsplit('.', 1) if '.' in filename else (filename, '')
            target_file = target_dir / f"{name}_{timestamp}.{ext}" if ext else target_dir / f"{name}_{timestamp}"
        
        shutil.move(str(source), str(target_file))
        print(f"✅ {filename} → {target_folder}" + (" (neuer Ordner)" if is_new_folder else ""))
        return str(target_file)

class SimpleHTTPHandler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, organizer=None, **kwargs):
        self.organizer = organizer
        super().__init__(*args, **kwargs)
    
    def do_GET(self):
        if self.path == '/':
            self.send_response(200)
            self.send_header('Content-type', 'text/html; charset=utf-8')
            self.end_headers()
            
            # Hole aktuelle Dateien
            pending_files = {}
            for file_path in self.organizer.inbox_path.glob('*'):
                if file_path.is_file() and not file_path.name.startswith('.'):
                    text = self.organizer.extract_text(file_path)
                    suggestions = self.organizer.get_folder_suggestions_llm(text)
                    
                    pending_files[file_path.name] = {
                        'text_preview': text[:200] + "..." if len(text) > 200 else text,
                        'suggestions': suggestions
                    }
            
            # Moderne UI laden
            try:
                with open('templates/modern_ui.html', 'r', encoding='utf-8') as f:
                    html = f.read()
                # Ersetze Platzhalter mit aktuellen Daten
                html = html.replace('{{pending_files_count}}', str(len(pending_files)))
                html = html.replace('{{inbox_path}}', str(self.organizer.inbox_path))
                
                # Moderne UI erfolgreich geladen - direkt zurückgeben
                self.wfile.write(html.encode('utf-8'))
                return
                
            except FileNotFoundError:
                # Fallback zur alten UI
                html = f"""<!DOCTYPE html>
<html lang="de">
<head>
    <meta charset="UTF-8">
    <title>📁 Document Organizer</title>
    <style>
        body {{ font-family: -apple-system, sans-serif; margin: 40px; background: #f5f5f5; }}
        .card {{ background: white; padding: 20px; margin: 20px 0; border-radius: 8px; box-shadow: 0 2px 8px rgba(0,0,0,0.1); }}
        .file-name {{ font-size: 1.2em; font-weight: bold; margin-bottom: 10px; }}
        .preview {{ background: #f8f9fa; padding: 10px; border-radius: 4px; margin: 10px 0; font-family: monospace; }}
        .suggestion {{ padding: 10px; margin: 5px 0; background: #e3f2fd; border-radius: 4px; cursor: pointer; }}
        .suggestion:hover {{ background: #bbdefb; }}
        .btn {{ padding: 10px 20px; margin: 5px; border: none; border-radius: 4px; cursor: pointer; }}
        .btn-primary {{ background: #2196f3; color: white; }}
        select {{ padding: 8px; margin: 10px 0; width: 100%; }}
        .status {{ text-align: center; color: #666; padding: 20px; }}
    </style>
</head>
<body>
    <h1>📁 Smart Document Organizer</h1>
    <div class="status">Inbox: {self.organizer.inbox_path} | {len(pending_files)} Dateien</div>
"""
            
            if pending_files:
                for filename, info in pending_files.items():
                    html += f"""
                    <div class="card">
                        <div class="file-name">📄 {filename}</div>
                        <div class="preview">{info['text_preview']}</div>
                        <h4>🧠 KI-Vorschläge:</h4>
"""
                    for i, sugg in enumerate(info['suggestions'], 1):
                        html += f"""
                        <div class="suggestion" onclick="moveFile('{filename}', '{sugg['folder']}')">
                            {i}. 📁 {sugg['folder']} ({sugg['confidence']:.1f}) - {sugg['reason']}
                        </div>
"""
                    
                    html += f"""
                        <p>Oder manuell wählen:</p>
                        <select onchange="if(this.value) moveFile('{filename}', this.value)">
                            <option value="">-- Ordner auswählen --</option>
"""
                    for folder in self.organizer.target_folders:
                        html += f'<option value="{folder}">📁 {folder}</option>'
                    
                    html += """
                        </select>
                    </div>
"""
            else:
                html += '<div class="status"><h2>🎉 Keine Dateien zu bearbeiten</h2><p>Wirf neue Dateien in den Inbox!</p></div>'
            
            html += """
    <script>
        function moveFile(filename, folder) {
            if(confirm(`${filename} nach ${folder} verschieben?`)) {
                fetch('/move', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/x-www-form-urlencoded'},
                    body: `filename=${encodeURIComponent(filename)}&folder=${encodeURIComponent(folder)}`
                })
                .then(() => location.reload())
                .catch(err => alert('Fehler: ' + err));
            }
        }
    </script>
</body>
</html>"""
            
            self.wfile.write(html.encode('utf-8'))
        
        elif self.path == '/status':
            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self.end_headers()
            
            files = [f.name for f in self.organizer.inbox_path.glob('*') if f.is_file()]
            response = {'pending': len(files), 'files': files}
            self.wfile.write(json.dumps(response).encode('utf-8'))
        
        else:
            self.send_error(404)
    
    def do_POST(self):
        if self.path == '/api/analyze':
            content_length = int(self.headers['Content-Length'])
            post_data = self.rfile.read(content_length)
            
            try:
                data = json.loads(post_data.decode('utf-8'))
                filename = data['filename']
                file_path = self.organizer.inbox_path / filename
                
                text = self.organizer.extract_text(file_path)
                suggestions = self.organizer.get_folder_suggestions_llm(text)
                
                self.send_response(200)
                self.send_header('Content-type', 'application/json')
                self.send_header('Access-Control-Allow-Origin', '*')
                self.end_headers()
                
                response = json.dumps({
                    'success': True,
                    'suggestions': suggestions,
                    'text_preview': text[:200] + "..." if len(text) > 200 else text
                })
                self.wfile.write(response.encode('utf-8'))
                
            except Exception as e:
                self.send_error_response(str(e))
                
        elif self.path == '/api/move':
            content_length = int(self.headers['Content-Length'])
            post_data = self.rfile.read(content_length)
            
            try:
                data = json.loads(post_data.decode('utf-8'))
                filename = data['filename']
                folder_data = data['folder']
                
                # Unterscheide zwischen normalem Ordner und neuem Ordner
                if isinstance(folder_data, dict) and folder_data.get('is_new'):
                    # Neuer Ordner: verwende folder_path
                    target_folder = folder_data['folder_path']
                    is_new_folder = True
                else:
                    # Bestehender Ordner: entferne Emoji
                    target_folder = str(folder_data).replace('🗂 ', '')
                    is_new_folder = False
                
                result_path = self.organizer.move_file(filename, target_folder, is_new_folder)
                
                self.send_response(200)
                self.send_header('Content-type', 'application/json')
                self.send_header('Access-Control-Allow-Origin', '*')
                self.end_headers()
                
                response = json.dumps({
                    'success': True,
                    'message': f'Datei verschoben nach {target_folder}' + (' (neuer Ordner erstellt)' if is_new_folder else ''),
                    'target_path': result_path,
                    'folder_created': is_new_folder
                })
                self.wfile.write(response.encode('utf-8'))
                
            except Exception as e:
                self.send_error_response(str(e))
        
        elif self.path == '/move':
            content_length = int(self.headers['Content-Length'])
            post_data = self.rfile.read(content_length).decode('utf-8')
            params = parse_qs(post_data)
            
            filename = params.get('filename', [''])[0]
            folder = params.get('folder', [''])[0]
            
            try:
                self.organizer.move_file(filename, folder)
                self.send_response(200)
                self.send_header('Content-type', 'text/plain')
                self.end_headers()
                self.wfile.write(b'OK')
            except Exception as e:
                self.send_error(500, str(e))
    
    def send_error_response(self, error_message):
        self.send_response(500)
        self.send_header('Content-type', 'application/json')
        self.send_header('Access-Control-Allow-Origin', '*')
        self.end_headers()
        
        response = json.dumps({
            'success': False,
            'error': error_message
        })
        self.wfile.write(response.encode('utf-8'))

def start_web_server(organizer, port=8080):
    """Starte minimalen Web Server"""
    handler = lambda *args, **kwargs: SimpleHTTPHandler(*args, organizer=organizer, **kwargs)
    
    with socketserver.TCPServer(("", port), handler) as httpd:
        print(f"🌐 Web-UI läuft auf http://localhost:{port}")
        print(f"📱 Auch erreichbar auf http://192.168.178.129:{port}")
        httpd.serve_forever()

if __name__ == '__main__':
    print("🚀 Minimaler Document Organizer startet...")
    
    organizer = SimpleDocumentOrganizer()
    
    # Test ob Ollama läuft
    try:
        urllib.request.urlopen('http://localhost:11434/api/tags', timeout=2)
        print("✅ Ollama läuft")
    except:
        print("❌ Ollama nicht erreichbar - nur Fallback-Modus")
    
    print("\n📂 Lege Dateien in ~/NAS/inbox/ ab")
    print("🌐 Öffne http://localhost:8080 im Browser")
    print()
    
    start_web_server(organizer)