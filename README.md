# SwissHelper AI V26 – Korrigierter Gesamtstand

Diese Version wurde nicht nur an einer einzelnen Stelle geändert, sondern als Gesamtstand geprüft.

## Sprachsteuerung
- 25 UI-Sprachen.
- Die gewählte Sprache steuert die komplette sichtbare Oberfläche.
- Serbisch: Lateinisch und Kyrillisch.
- Mazedonisch: Kyrillisch und Latinica.
- Bulgarisch: Kyrillisch und Latinica.
- Sprachliste und Ländernamen werden in der ausgewählten Sprache angezeigt.
- Region/Stadt-Bezeichnungen bleiben konsistent mit der gewählten UI-Sprache.

## A4 / PDF
- Ergebnisblöcke sind für A4 aufgebaut.
- Der PDF-Button erzeugt die PDF-Datei direkt als Download; es wird kein Browser-Druckdialog benötigt.
- Die PDF-Erzeugung verwendet A4 (210 × 297 mm) und getrennte A4-Ergebnisblöcke.

## Formular-Helfer
- Ein echtes ausfüllbares PDF wird als Original-PDF verarbeitet.
- Die Originalseiten, Seitengrößen, Feldnamen und Formularstruktur bleiben erhalten.
- Es werden nur die echten PDF-Formularfelder befüllt.
- Das ausgefüllte Ergebnis wird direkt als PDF heruntergeladen.
- Bei nicht ausfüllbaren/scannbaren Formularen wird keine Ersatzvorlage erzeugt; stattdessen bleibt die Feld-für-Feld-Hilfe verfügbar.
- Die Erklärung kann in der ausgewählten UI-Sprache erfolgen; das Originalformular selbst bleibt in seiner Originalsprache.

## Technischer Test
Die AcroForm-Logik wurde mit einem mehrseitigen A4-Testformular geprüft: Seitenanzahl, A4-Seitengröße und PDF-Feldnamen blieben beim Befüllen erhalten.

## Render
- Dockerfile und render.yaml sind enthalten.
- `OPENAI_API_KEY` bleibt ausschließlich als Render-Umgebungsvariable vorgesehen und darf nicht in den Quellcode eingetragen werden.
