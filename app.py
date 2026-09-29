import os, json, base64, io, unicodedata
from flask import Flask, request, render_template, jsonify, send_file
from openai import OpenAI
from pypdf import PdfReader, PdfWriter
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 15 * 1024 * 1024

MODEL = os.getenv("OPENAI_MODEL", "gpt-5.6-luna")

client = OpenAI() if os.getenv("OPENAI_API_KEY") else None

# Unicode-capable font for translation PDFs (Latin, Cyrillic, Greek, etc.).
UNICODE_FONT = "Helvetica"
for _font_path in ("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", "/usr/share/fonts/dejavu/DejaVuSans.ttf"):
    if os.path.exists(_font_path):
        try:
            pdfmetrics.registerFont(TTFont("SwissHelperUnicode", _font_path))
            UNICODE_FONT = "SwissHelperUnicode"
            break
        except Exception:
            pass

SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "document_type": {"type": "string"},
        "sender": {"type": "string"},
        "topic": {"type": "string"},
        "deadline": {"type": ["string", "null"]},
        "deadline_source": {"type": "string"},
        "tasks": {"type": "array", "items": {"type": "string"}},
        "required_documents": {"type": "array", "items": {"type": "string"}},
        "simple_explanation": {"type": "string"},
        "next_steps": {"type": "array", "items": {"type": "string"}},
        "warnings": {"type": "array", "items": {"type": "string"}},
        "form_fields": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "field": {"type": "string"},
                    "translation": {"type": "string"},
                    "explanation": {"type": "string"},
                    "what_to_enter": {"type": "string"},
                    "missing_information": {"type": "string"},
                    "page": {"type": "integer"},
                    "pdf_field": {"type": ["string", "null"]},
                    "options": {"type": "array", "items": {"type": "object", "additionalProperties": False, "properties": {"original": {"type": "string"}, "translation": {"type": "string"}}, "required": ["original", "translation"]}}
                },
                "required": ["field", "translation", "explanation", "what_to_enter", "missing_information", "page", "pdf_field", "options"]
            }
        }
    },
    "required": [
        "document_type", "sender", "topic", "deadline", "deadline_source",
        "tasks", "required_documents", "simple_explanation",
        "next_steps", "warnings", "form_fields"
    ]
}

INSTRUCTIONS = """
Du bist SwissHelper AI.
Arbeite präzise, vorsichtig und mehrsprachig.

Grundregeln:
- Antworte vollständig in der vom Nutzer gewählten Sprache.
- Erfinde niemals Fristen, Gebühren, Pflichten oder Dokumente.
- Trenne den tatsächlichen Dokumentinhalt von allgemeiner Information.
- Wenn etwas im Dokument nicht lesbar oder nicht eindeutig ist, sage das ausdrücklich.
- Keine rechtliche Garantie geben.
- Bei amtlichen/rechtlichen Fragen auf die zuständige Behörde und aktuelle offizielle Quellen verweisen.
- Bei Formularen: Felder einzeln und möglichst seitenbezogen erkennen. form_fields muss den sichtbaren Original-Feldnamen, eine kurze Übersetzung des Feldnamens, eine kurze Erklärung, eine konkrete Anweisung was einzutragen ist und fehlende Angaben enthalten. page ist die Original-Seitennummer (1-basiert). pdf_field ist bei ausfüllbaren PDFs der technische PDF-Feldname, sonst null.
- Verwende ausschließlich korrektes Unicode. Niemals Ersatzzeichen wie �, Fragezeichen, Kästchen oder zufällige X/&-Zeichen anstelle von Buchstaben ausgeben. Besonders wichtig: ä, ö, ü, ß, č, ć, š, ž, đ sowie kyrillische, griechische und andere nicht-lateinische Zeichen.
- Wenn ein Auswahlwert aus dem Original-PDF technisch beschädigt erscheint, lies ihn aus dem sichtbaren Dokument neu und gib die tatsächliche Beschriftung aus. Beispiel: „männlich“ muss exakt als „männlich“ erscheinen.
- Niemals behaupten, ein gescanntes/nicht ausfüllbares PDF direkt ausgefüllt zu haben.
"""


def clean_text(value):
    """Normalize user-visible Unicode text."""
    if value is None or not isinstance(value, str):
        return value
    return unicodedata.normalize("NFC", value)

def clean_json_strings(value):
    if isinstance(value, str):
        return clean_text(value)
    if isinstance(value, list):
        return [clean_json_strings(x) for x in value]
    if isinstance(value, dict):
        return {k: clean_json_strings(v) for k, v in value.items()}
    return value

def ensure_client():
    if client is None:
        raise RuntimeError("OPENAI_API_KEY fehlt. Bitte in Render als Environment Variable setzen.")

def file_content(file_bytes, mime, filename):
    encoded = base64.b64encode(file_bytes).decode("utf-8")
    if mime == "application/pdf":
        return {
            "type": "input_file",
            "filename": filename or "document.pdf",
            "file_data": f"data:application/pdf;base64,{encoded}"
        }
    return {
        "type": "input_image",
        "image_url": f"data:{mime};base64,{encoded}",
        "detail": "high"
    }

def extract_pdf_fields(file_bytes):
    """Read the real AcroForm structure and keep page mapping/original pages intact."""
    reader = PdfReader(io.BytesIO(file_bytes))
    fields = reader.get_fields() or {}
    result = []
    by_name = {}
    for name, field in fields.items():
        try:
            ft = str(field.get("/FT", "")); flags = int(field.get("/Ff", 0) or 0)
            value = field.get("/V", "") or ""; kind = "text"; options = []
            if ft == "/Btn":
                kind = "radio" if flags & 32768 else ("button" if flags & 65536 else "checkbox")
            elif ft == "/Ch":
                kind = "choice"
                for opt in (field.get("/Opt", []) or []):
                    if isinstance(opt, (list, tuple)) and len(opt) >= 2:
                        options.append({"value": str(opt[0]), "label": str(opt[1])})
                    else:
                        options.append({"value": str(opt), "label": str(opt)})
            if kind in ("radio", "checkbox"):
                try:
                    for kid_ref in (field.get("/Kids", []) or []):
                        kid = kid_ref.get_object(); ap = kid.get("/AP", {}) or {}; normal = ap.get("/N", {}) if hasattr(ap, "get") else {}
                        if hasattr(normal, "keys"):
                            for state in normal.keys():
                                state = str(state)
                                if state != "/Off" and not any(o["value"] == state for o in options):
                                    options.append({"value": clean_text(state), "label": clean_text(state.lstrip("/"))})
                except Exception:
                    pass
            item = {"name": clean_text(str(name)), "label": clean_text(str(field.get("/TU") or field.get("/T") or name)), "type": kind,
                    "value": clean_text(str(value).lstrip("/")), "options": clean_json_strings(options), "required": bool(flags & 2), "page": None}
            result.append(item); by_name[str(name)] = item
        except Exception:
            continue

    page_fields = [[] for _ in reader.pages]
    for page_index, page in enumerate(reader.pages, start=1):
        annots = page.get("/Annots", []) or []
        for aref in annots:
            try:
                annot = aref.get_object()
                parent = annot.get("/Parent")
                parent_obj = parent.get_object() if parent else None
                name = annot.get("/T") or (parent_obj.get("/T") if parent_obj else None)
                if not name:
                    continue
                name = str(name)
                item = by_name.get(name)
                if item is None and parent_obj is not None:
                    # Sometimes get_fields exposes the fully qualified parent name.
                    for candidate_name, candidate in by_name.items():
                        if candidate_name == name or candidate_name.endswith("." + name):
                            item = candidate; name = candidate_name; break
                if item is not None:
                    item["page"] = page_index
                    if not any(x["name"] == name for x in page_fields[page_index-1]):
                        page_fields[page_index-1].append(item)
            except Exception:
                continue

    # Some PDFs expose fields without page annotations; keep them visible on page 1 rather than losing them.
    unpaged = [x for x in result if x.get("page") is None]
    for x in unpaged:
        x["page"] = 1
        page_fields[0].append(x)

    page_pdfs = []
    for page in reader.pages:
        try:
            one = PdfWriter(); one.add_page(page); buf = io.BytesIO(); one.write(buf)
            page_pdfs.append(base64.b64encode(buf.getvalue()).decode("ascii"))
        except Exception:
            page_pdfs.append("")
    full_pdf = base64.b64encode(file_bytes).decode("ascii")
    try:
        has_xfa = bool(reader.trailer.get("/Root", {}).get_object().get("/AcroForm", {}).get_object().get("/XFA"))
    except Exception:
        has_xfa = False
    return {"fillable": bool(result), "page_count": len(reader.pages), "has_xfa": has_xfa, "fields": clean_json_strings(result),
            "pages": [{"page": i+1, "fields": clean_json_strings(page_fields[i])} for i in range(len(page_fields))],
            "page_pdfs": page_pdfs, "full_pdf": full_pdf}

def analyze_document(file_bytes, mime, filename, language, action="analyze"):
    ensure_client()
    pdf_field_names = []
    if mime == "application/pdf":
        try:
            pdf_field_names = list((PdfReader(io.BytesIO(file_bytes)).get_fields() or {}).keys())
        except Exception:
            pdf_field_names = []
    field_hint = ""
    if pdf_field_names:
        field_hint = "\nDieses PDF enthält ausfüllbare PDF-Felder. Verwende für form_fields.field exakt diese internen Feldnamen, wenn sie sinnvoll zugeordnet werden können: " + ", ".join(map(str, pdf_field_names))
    prompt = f"""
Analysiere das hochgeladene Dokument vollständig in der Sprache und Schrift: {language}.
Aktion: {action}
WICHTIG FÜR DIE AUSGABE: Alle von dir erzeugten Erklärungen, Überschriften, Feldhinweise und Hinweise müssen vollständig in der gewählten Sprache erscheinen. Bei „Serbisch – Kyrillisch“ ausschließlich kyrillische Schrift verwenden. Bei „Serbisch“ ausschließlich lateinische Schrift verwenden. Bei „Mazedonisch“ ausschließlich kyrillische Schrift verwenden. Bei „Mazedonisch – Latinica“ ausschließlich lateinische Schrift verwenden. Bei „Bulgarisch“ ausschließlich kyrillische Schrift verwenden. Bei „Bulgarisch – Latinica“ ausschließlich lateinische Schrift verwenden. Niemals wegen der Sprache des Original-PDFs automatisch auf Deutsch oder eine andere Sprache wechseln. Interne PDF-Feldnamen dürfen technisch original bleiben, die sichtbare Erklärung muss aber in der gewählten Sprache/Schrift sein.

Wenn es ein Formular ist:
- Erkenne die Felder möglichst vollständig.
- Übernimm Feldbezeichnungen sinngemäss bzw. wörtlich, ohne sie umzudeuten.
- Sage bei jedem Feld in der gewählten Sprache konkret, was die Person dort eintragen muss. Beispiel: „Hier Ihren Nachnamen eintragen.“ / „Ovde unesite svoje prezime.“
- Gib page als 1-basierte Original-Seitennummer an. Bei ausfüllbaren PDFs gib pdf_field exakt als technischen Feldnamen an; wenn nicht sicher, null.
- Gib für jedes Formularfeld ein eigenes Feld „translation“ mit einer kurzen, natürlichen Übersetzung der Original-Feldbezeichnung aus. „explanation“ darf die Bedeutung kurz erklären. „what_to_enter“ muss eine konkrete Handlungsanweisung in der gewählten Sprache sein.
- Die sichtbare Originalbezeichnung darf nicht durch die Übersetzung ersetzt werden. Die UI zeigt Originalbezeichnung + kurze Übersetzung + konkrete Ausfüllanweisung.
- Bei Auswahlfeldern options ausgeben: originaler technischer/angezeigter Wert und dessen Übersetzung in der gewählten Sprache. Keine Zeichen erfinden oder beschädigen..
- Nenne nur Informationen als vorhanden, die aus dem Dokument eindeutig hervorgehen.
- Bei einem ausfüllbaren PDF: ordne die sichtbaren Felder den echten PDF-Feldnamen zu, damit das Formular technisch befüllt werden kann.
{field_hint}
"""
    response = client.responses.create(
        model=MODEL,
        instructions=INSTRUCTIONS,
        input=[{
            "role": "user",
            "content": [
                {"type": "input_text", "text": prompt},
                file_content(file_bytes, mime, filename)
            ]
        }],
        text={
            "format": {
                "type": "json_schema",
                "name": "swisshelper_document_analysis",
                "strict": True,
                "schema": SCHEMA
            }
        },
        store=False
    )
    result = clean_json_strings(json.loads(response.output_text))
    if mime == "application/pdf":
        try: result["pdf_meta"] = extract_pdf_fields(file_bytes)
        except Exception: result["pdf_meta"] = {"fillable":False,"page_count":0,"fields":[],"pages":[],"page_pdfs":[]}
    else: result["pdf_meta"] = {"fillable":False,"page_count":0,"fields":[],"pages":[],"page_pdfs":[]}
    return result

def web_json(prompt, schema_name, schema):
    ensure_client()
    response = client.responses.create(
        model=MODEL,
        tools=[{"type": "web_search"}],
        instructions=(
            "Du bist SwissHelper AI. Verwende für rechtliche/amtliche Aussagen "
            "möglichst aktuelle offizielle Quellen. Bevorzuge Behörden, Ministerien, "
            "Botschaften, Konsulate und staatliche Portale. Keine erfundenen Links. "
            "Antworte vollständig in der gewünschten Sprache."
        ),
        input=prompt,
        text={"format": {"type": "json_schema", "name": schema_name, "strict": True, "schema": schema}},
        store=False
    )
    return json.loads(response.output_text)

def source_items(items):
    return [f"{x.get('name','Quelle')}: {x.get('url','')}" for x in items if x.get("url")]

@app.get("/")
def index():
    return render_template("index.html")

@app.post("/analyze")
def analyze():
    f = request.files.get("document")
    language = request.form.get("language", "Deutsch")
    if not f:
        return jsonify({"error": "Bitte zuerst ein Dokument auswählen."}), 400
    try:
        return jsonify(analyze_document(f.read(), f.mimetype, f.filename, language))
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500

@app.post("/form-helper")
def form_helper():
    f = request.files.get("form")
    language = request.form.get("language", "Deutsch")
    action = request.form.get("action", "explain")
    if not f:
        return jsonify({"error": "Bitte zuerst ein Formular auswählen."}), 400
    try:
        return jsonify(analyze_document(f.read(), f.mimetype, f.filename, language, action))
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500

@app.post("/fill-form")
def fill_form():
    f = request.files.get("form")
    if not f:
        return jsonify({"error": "Kein Formular."}), 400
    if f.mimetype != "application/pdf":
        return jsonify({"error": "Das Originalformular muss als PDF vorliegen."}), 400
    try:
        data = f.read()
        reader = PdfReader(io.BytesIO(data))
        fields = reader.get_fields() or {}
        if not fields:
            return jsonify({"error": "Dieses PDF enthält keine ausfüllbaren PDF-Felder. Das Original kann deshalb nicht automatisch befüllt werden."}), 400

        # XFA forms can be destroyed by normal AcroForm rewriting. Fail clearly instead of returning a blank PDF.
        try:
            acro = reader.trailer.get("/Root", {}).get_object().get("/AcroForm")
            acro_obj = acro.get_object() if acro else None
            if acro_obj and acro_obj.get("/XFA"):
                return jsonify({"error": "Dieses Behördenformular verwendet XFA. Das Original wird deshalb nicht verändert, damit kein leeres oder beschädigtes PDF entsteht."}), 400
        except Exception:
            pass

        values = json.loads(request.form.get("field_values", "{}") or "{}")
        if not isinstance(values, dict):
            return jsonify({"error": "Ungültige Felddaten."}), 400

        # Clone the complete original document instead of rebuilding pages from scratch.
        # This keeps the original A4 pages, graphics, fonts and annotations intact.
        writer = PdfWriter(clone_from=reader)
        if hasattr(writer, "set_need_appearances_writer"):
            try:
                writer.set_need_appearances_writer(True)
            except Exception:
                pass

        mapping = {}
        for name, value in values.items():
            if name not in fields or value is None:
                continue
            field = fields[name]
            ft = str(field.get("/FT", ""))
            flags = int(field.get("/Ff", 0) or 0)
            value = str(value)
            if ft == "/Btn":
                if flags & 65536:  # push button, not a value field
                    continue
                mapping[name] = value if value else "/Off"
            else:
                mapping[name] = value

        if mapping:
            for page in writer.pages:
                writer.update_page_form_field_values(page, mapping, auto_regenerate=False, flatten=False)

        output = io.BytesIO()
        writer.write(output)
        output.seek(0)
        # Verify that the result is a real PDF with the same page count before sending it.
        check = PdfReader(output)
        if len(check.pages) != len(reader.pages):
            raise RuntimeError("Das ausgefüllte PDF konnte nicht korrekt erstellt werden.")
        output.seek(0)
        return send_file(output, mimetype="application/pdf", as_attachment=True,
                         download_name="SwissHelper_Originalformular_ausgefuellt.pdf")
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


TRANSLATION_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "title": {"type": "string"},
        "translation": {"type": "string"},
        "translation_pages": {"type": "array", "items": {"type": "string"}},
        "legal_title": {"type": "string"},
        "legal_requirements": {"type": "string"},
        "next_title": {"type": "string"},
        "next_steps": {"type": "array", "items": {"type": "string"}},
        "source_title": {"type": "string"},
        "sources": {"type": "array", "items": {"type": "string"}}
    },
    "required": ["title", "translation", "translation_pages", "legal_title", "legal_requirements", "next_title", "next_steps", "source_title", "sources"]
}

def _pdf_page_count(file_bytes):
    try:
        return len(PdfReader(io.BytesIO(file_bytes)).pages)
    except Exception:
        return 1

def _draw_wrapped(c, text, x, y, width, font=None, size=10.5, leading=15):
    font = font or UNICODE_FONT
    c.setFont(font, size)
    words = str(text or "").split()
    line = ""
    for word in words:
        candidate = (line + " " + word).strip()
        if c.stringWidth(candidate, font, size) <= width:
            line = candidate
        else:
            c.drawString(x, y, line)
            y -= leading
            line = word
            if y < 45:
                c.showPage(); y = A4[1]-45; c.setFont(font, size)
    if line:
        c.drawString(x, y, line); y -= leading
    return y

def build_translation_pdf(original_bytes, translation_pages, title, legal_requirements, next_steps, sources, target_language):
    out = io.BytesIO()
    original = PdfReader(io.BytesIO(original_bytes))
    writer = PdfWriter(clone_from=original)

    # Build the translated/explanation pages separately, then append them to the exact original PDF.
    extra = io.BytesIO()
    c = canvas.Canvas(extra, pagesize=A4)
    width, height = A4
    margin = 42
    usable = width - 2*margin
    pages = translation_pages or [str(title or "")]
    for idx, page_text in enumerate(pages, start=1):
        c.setTitle("SwissHelper AI – Übersetzung")
        c.setFont(UNICODE_FONT, 15)
        c.drawString(margin, height-margin, f"{title or 'Übersetzung'} – Seite {idx}")
        y = height-margin-30
        for para in str(page_text or "").split("\n"):
            y = _draw_wrapped(c, para, margin, y, usable)
            y -= 7
            if y < 55:
                c.showPage(); y = height-margin
        c.showPage()

    c.setFont(UNICODE_FONT, 15)
    c.drawString(margin, height-margin, "Praktische Erklärung")
    y = height-margin-30
    y = _draw_wrapped(c, legal_requirements, margin, y, usable)
    y -= 12
    c.setFont(UNICODE_FONT, 12); c.drawString(margin, y, "Nächste Schritte"); y -= 20
    for step in next_steps or []:
        y = _draw_wrapped(c, "• " + step, margin, y, usable)
        y -= 4
        if y < 60:
            c.showPage(); y = height-margin
    if sources:
        y -= 8; c.setFont(UNICODE_FONT, 12); c.drawString(margin, y, "Quellen"); y -= 20
        for src in sources:
            y = _draw_wrapped(c, "• " + src, margin, y, usable, size=9.5, leading=13)
            y -= 3
            if y < 60:
                c.showPage(); y = height-margin
    c.save(); extra.seek(0)
    translated_reader = PdfReader(extra)
    for page in translated_reader.pages:
        writer.add_page(page)
    writer.write(out); out.seek(0)
    return out

@app.post("/translate-document")
def translate_document():
    f = request.files.get("translationFile")
    target = request.form.get("target_language", "Deutsch")
    source_country = request.form.get("source_country", "")
    target_country = request.form.get("target_country", "")
    purpose = request.form.get("purpose", "")
    if not f:
        return jsonify({"error": "Bitte zuerst ein Dokument auswählen."}), 400

    try:
        ensure_client()
        original_bytes = f.read()
        content = file_content(original_bytes, f.mimetype, f.filename)
        page_count = _pdf_page_count(original_bytes) if f.mimetype == "application/pdf" else 1
        prompt = f"""
Übersetze das hochgeladene Dokument vollständig in {target}.
Ausgangsland: {source_country}
Zielland: {target_country}
Verwendungszweck: {purpose}
Original-Seiten: {page_count}

WICHTIG:
- translation_pages muss genau eine kurze Übersetzung pro Originalseite enthalten, in der Reihenfolge der Originalseiten.
- Erhalte Zahlen, Namen, Aktenzeichen und Fachbegriffe korrekt.
- Übersetze nicht irgendwelche Gesetze komplett.
- legal_requirements soll nur die für diesen konkreten Verwendungszweck wichtigen praktischen Anforderungen erklären.
- Formuliere konkrete nächste Schritte, z. B. ob eine notarielle Beglaubigung, Apostille, zuständige Behörde oder Gebühr relevant ist. Wenn etwas vom Land/Behörde abhängt, ausdrücklich als abhängig kennzeichnen.
- Nutze Websuche für aktuelle offizielle Anforderungen und nenne nur Quellen, die du tatsächlich gefunden hast.
- Behaupte nicht, dass SwissHelper selbst eine amtlich beglaubigte Übersetzung erstellt.
- Alle sichtbaren Texte vollständig in der Zielsprache.
"""
        response = client.responses.create(
            model=MODEL,
            tools=[{"type": "web_search"}],
            instructions=INSTRUCTIONS,
            input=[{"role": "user", "content":[{"type":"input_text","text":prompt}, content]}],
            text={"format":{"type":"json_schema","name":"swisshelper_translation","strict":True,"schema":TRANSLATION_SCHEMA}},
            store=False
        )
        result = clean_json_strings(json.loads(response.output_text))
        result["original_pdf"] = base64.b64encode(original_bytes).decode("ascii") if f.mimetype == "application/pdf" else ""
        result["original_page_count"] = page_count
        return jsonify(result)
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500

@app.post("/translation-pdf")
def translation_pdf():
    f = request.files.get("translationFile")
    if not f or f.mimetype != "application/pdf":
        return jsonify({"error":"Für die kombinierte Übersetzungs-PDF bitte das Original als PDF hochladen."}), 400
    try:
        original_bytes = f.read()
        payload = json.loads(request.form.get("translation_payload", "{}") or "{}")
        out = build_translation_pdf(
            original_bytes,
            payload.get("translation_pages") or [payload.get("translation", "")],
            payload.get("title", "Übersetzung"),
            payload.get("legal_requirements", ""),
            payload.get("next_steps", []),
            payload.get("sources", []),
            payload.get("target_language", "")
        )
        return send_file(out, mimetype="application/pdf", as_attachment=True, download_name="SwissHelper_Original_Übersetzung_Erklärung.pdf")
    except Exception as exc:
        return jsonify({"error":str(exc)}), 500


HELPER_SCHEMA = {
    "type":"object","additionalProperties":False,
    "properties":{
        "title":{"type":"string"},"summary":{"type":"string"},
        "next_title":{"type":"string"},"steps":{"type":"array","items":{"type":"string"}},
        "docs_title":{"type":"string"},"documents":{"type":"array","items":{"type":"string"}},
        "forms":{"type":"array","items":{"type":"object","additionalProperties":False,"properties":{"name":{"type":"string"},"url":{"type":"string"},"why":{"type":"string"}},"required":["name","url","why"]}},
        "source_title":{"type":"string"},"sources":{"type":"array","items":{"type":"string"}}
    },
    "required":["title","summary","next_title","steps","docs_title","documents","forms","source_title","sources"]
}

@app.post("/country-helper")
def country_helper():
    d = request.get_json() or {}
    language = d.get("language","Deutsch")
    prompt = f"""
Erstelle einen aktuellen Behörden-/Länderweg in {language}.
Herkunftsland: {d.get('source_country')}
Zielland: {d.get('target_country')}
Herkunftsregion/Stadt: {d.get('source_place')}
Zielregion/Stadt: {d.get('target_place')}
Staatsangehörigkeit: {d.get('nationality')}
Zweck: {d.get('purpose')}

Suche aktuelle offizielle Quellen. Berücksichtige:
- Einreise/Aufenthalt/Visum
- zuständige Behörde
- Voraussetzungen
- konkrete Dokumente
- offizielles Formular oder Online-Antrag, wenn vorhanden
- liefere konkrete Formularnamen und direkte offizielle URLs, sofern gefunden
- gib für jedes Formular kurz an, warum es benötigt wird
- nächste Schritte
- Hinweis, wenn Anforderungen von Kanton, Nationalität oder Zweck abhängen
- keine erfundenen Formular-URLs
"""
    try:
        return jsonify(web_json(prompt, "swisshelper_country_helper", HELPER_SCHEMA))
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500

TOUR_SCHEMA = {
    "type":"object","additionalProperties":False,
    "properties":{
        "title":{"type":"string"},"summary":{"type":"string"},
        "entry_title":{"type":"string"},"entry":{"type":"array","items":{"type":"string"}},
        "docs_title":{"type":"string"},"documents":{"type":"array","items":{"type":"string"}},
        "forms":{"type":"array","items":{"type":"object","additionalProperties":False,"properties":{"name":{"type":"string"},"url":{"type":"string"},"why":{"type":"string"}},"required":["name","url","why"]}},
        "source_title":{"type":"string"},"sources":{"type":"array","items":{"type":"string"}}
    },
    "required":["title","summary","entry_title","entry","docs_title","documents","forms","source_title","sources"]
}

@app.post("/tourism-helper")
def tourism_helper():
    d = request.get_json() or {}
    language = d.get("language","Deutsch")
    prompt = f"""
Erstelle eine aktuelle touristische Einreise-Checkliste in {language}.
Staatsangehörigkeit: {d.get('origin')}
Herkunftsregion/Stadt: {d.get('origin_place')}
Reiseziel: {d.get('destination')}
Zielregion/Stadt: {d.get('destination_place')}
Reisezweck: {d.get('purpose')}
Dauer: {d.get('duration')}
Aufenthaltsstatus im Herkunfts-/Wohnland: {d.get('residence')}

Prüfe mit aktuellen offiziellen Quellen:
- Visumpflicht/Einreise
- erlaubte Aufenthaltsdauer
- Reisepass/Identitätsdokument
- Aufenthaltstitel, falls relevant
- Rückreise-/Weiterreiseticket, finanzielle Mittel oder Unterkunftsnachweise nur wenn tatsächlich verlangt
- Reiseversicherung nur soweit offiziell/relevant
- Zoll/Grenze, wenn relevant
- besondere aktuelle Einreisevorgaben
- wenn ein offizielles Formular/Online-Antrag benötigt wird, nenne den direkten offiziellen Link und den Zweck
Nenne konkrete offizielle Quellen. Nicht spekulieren.
"""
    try:
        return jsonify(web_json(prompt, "swisshelper_tourism_helper", TOUR_SCHEMA))
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT","10000")))
