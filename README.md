# SwissHelper AI – Universal V21

Mehrsprachiger Länder-, Behörden-, Dokument-, Übersetzungs- und Formular-Helfer.

## V21 Änderungen
- Zentrale Sprachsteuerung für Oberfläche, Ergebnisse und Schaltflächen.
- Serbisch: Latinica und Ćirilica.
- Mazedonisch: Кирилица und zusätzliche Latinica-Ansicht.
- Ländernamen werden in der gewählten UI-Sprache angezeigt.
- Länder-/Amtswege-Helfer und Tourismus-/Einreise-Helfer mit Land + Region/Stadt.
- Kein separater Liechtenstein-Haupthelfer mehr; Liechtenstein läuft über die normale Länder-/Tourismus-Auswahl.
- Country-/Tourism-Ergebnisse verwenden für die Überschriften und Schaltflächen die gewählte UI-Sprache.
- Formular-Helfer erkennt echte PDF-AcroForm-Felder direkt aus dem Original-PDF.
- Bei ausfüllbaren PDFs werden die Originalseiten, Positionen und Formularstruktur erhalten; nur echte PDF-Felder werden befüllt.
- Ja/Nein-, Auswahl-, Radio- und Checkbox-Felder werden entsprechend ihres PDF-Feldtyps dargestellt.
- Nicht ausfüllbare Scans bleiben bei der Feld-für-Feld-Hilfe; kein falsches 1:1-Ausfüllen.
- Druckansicht mit eigenem Vorschaufenster und X-Schaltfläche.
- A4-Drucklayout bleibt erhalten; der Browser-Druckdialog kann für „Als PDF speichern“ verwendet werden.

## Start
```bash
pip install -r requirements.txt
python app.py
```

Für Render wird `gunicorn` verwendet. `OPENAI_API_KEY` muss als Environment Variable gesetzt werden.


V21: Vollständige Lokalisierung der Auswahlfelder in Länder-/Amtswege- und Tourismus-Helfer: Länder, Regionen/Städte und Verwendungszwecke werden passend zur gewählten UI-Sprache angezeigt. Interne Werte bleiben stabil, damit die Backend-Abfragen korrekt funktionieren.


V21: Macedonian and Bulgarian are explicitly available in Cyrillic and Latin transliteration. Country, region/city, purpose and travel labels follow the selected script.


## V21
- PDF-Ergebnisse werden direkt als PDF-Datei erzeugt und heruntergeladen; der PDF-Button öffnet nicht mehr den Druckdialog.
- Formular-Helfer hält die gewählte UI-Sprache und Schrift fest.
- Formularerklärungen erzwingen die gewählte Sprache und Schrift, insbesondere Serbisch/Mazedonisch/Bulgarisch in Kyrillisch bzw. Latinica.
- Ausfüllbare Original-PDFs bleiben 1:1 erhalten und werden direkt als ausgefülltes Originalformular ausgegeben.
