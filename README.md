# SwissHelper AI – Universal V18

Mehrsprachiger Länder-, Behörden-, Dokument-, Übersetzungs- und Formular-Helfer.

## V18 Änderungen
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
