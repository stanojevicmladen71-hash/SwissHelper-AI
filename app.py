import os, json, base64, io
from flask import Flask, request, render_template, jsonify, send_file
from openai import OpenAI
from pypdf import PdfReader, PdfWriter

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 15 * 1024 * 1024

MODEL = os.getenv("OPENAI_MODEL", "gpt-5.6-luna")

client = OpenAI() if os.getenv("OPENAI_API_KEY") else None

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
                    "explanation": {"type": "string"},
                    "what_to_enter": {"type": "string"},
                    "missing_information": {"type": "string"}
                },
                "required": ["field", "explanation", "what_to_enter", "missing_information"]
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
- Bei Formularen: Felder einzeln erkennen. form_fields muss den sichtbaren bzw. erkannten Feldnamen, eine Erklärung, was einzutragen ist, und fehlende Angaben enthalten.
- Niemals behaupten, ein gescanntes/nicht ausfüllbares PDF direkt ausgefüllt zu haben.
"""

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
    """Read the real AcroForm structure without changing the original PDF."""
    reader = PdfReader(io.BytesIO(file_bytes))
    fields = reader.get_fields() or {}
    result = []
    for name, field in fields.items():
        try:
            ft = str(field.get("/FT", "")); flags = int(field.get("/Ff", 0) or 0)
            value = field.get("/V", "") or ""; kind = "text"; options = []
            if ft == "/Btn":
                kind = "radio" if flags & 32768 else ("button" if flags & 65536 else "checkbox")
            elif ft == "/Ch":
                kind = "choice"
                for opt in (field.get("/Opt", []) or []):
                    if isinstance(opt, (list, tuple)) and len(opt) >= 2: options.append({"value":str(opt[0]),"label":str(opt[1])})
                    else: options.append({"value":str(opt),"label":str(opt)})
            if kind in ("radio", "checkbox"):
                try:
                    for kid_ref in (field.get("/Kids", []) or []):
                        kid=kid_ref.get_object(); ap=kid.get("/AP", {}) or {}; normal=ap.get("/N", {}) if hasattr(ap,"get") else {}
                        if hasattr(normal,"keys"):
                            for state in normal.keys():
                                state=str(state)
                                if state != "/Off" and not any(o["value"]==state for o in options): options.append({"value":state,"label":state.lstrip("/")})
                except Exception: pass
            result.append({"name":str(name),"label":str(field.get("/TU") or field.get("/T") or name),"type":kind,"value":str(value).lstrip("/"),"options":options,"required":bool(flags & 2)})
        except Exception: continue
    return {"fillable":bool(result),"page_count":len(reader.pages),"fields":result}

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
- Sage bei jedem Feld, was die Person eintragen muss.
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
    result = json.loads(response.output_text)
    if mime == "application/pdf":
        try: result["pdf_meta"] = extract_pdf_fields(file_bytes)
        except Exception: result["pdf_meta"] = {"fillable":False,"page_count":0,"fields":[]}
    else: result["pdf_meta"] = {"fillable":False,"page_count":0,"fields":[]}
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
    f=request.files.get("form")
    if not f: return jsonify({"error":"Kein Formular."}),400
    if f.mimetype!="application/pdf": return jsonify({"error":"Direktes Ausfüllen ist nur für PDF-Dateien möglich."}),400
    try:
        data=f.read(); reader=PdfReader(io.BytesIO(data)); fields=reader.get_fields() or {}
        if not fields: return jsonify({"error":"Dieses PDF enthält keine ausfüllbaren PDF-Felder. Das Original bleibt unverändert; für Scans steht die Feld-für-Feld-Hilfe zur Verfügung."}),400
        values=json.loads(request.form.get("field_values","{}") or "{}")
        if not isinstance(values,dict): return jsonify({"error":"Ungültige Felddaten."}),400
        writer=PdfWriter(); writer.append(reader)
        mapping={}
        for name,value in values.items():
            if name not in fields or value is None: continue
            field=fields[name]; ft=str(field.get("/FT","")); flags=int(field.get("/Ff",0) or 0); value=str(value)
            if ft=="/Btn":
                if flags & 65536: continue
                mapping[name]=value if value else "/Off"
            else: mapping[name]=value
        if mapping: writer.update_page_form_field_values(None,mapping,auto_regenerate=False,flatten=False)
        output=io.BytesIO(); writer.write(output); output.seek(0)
        return send_file(output,mimetype="application/pdf",as_attachment=True,download_name="SwissHelper_Originalformular_ausgefuellt.pdf")
    except Exception as exc: return jsonify({"error":str(exc)}),500

TRANSLATION_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "title": {"type": "string"},
        "translation": {"type": "string"},
        "legal_title": {"type": "string"},
        "legal_requirements": {"type": "string"},
        "next_title": {"type": "string"},
        "next_steps": {"type": "array", "items": {"type": "string"}},
        "source_title": {"type": "string"},
        "sources": {"type": "array", "items": {"type": "string"}}
    },
    "required": ["title", "translation", "legal_title", "legal_requirements", "next_title", "next_steps", "source_title", "sources"]
}

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
        content = file_content(f.read(), f.mimetype, f.filename)
        prompt = f"""
Übersetze das hochgeladene Dokument vollständig in {target}.
Ausgangsland: {source_country}
Zielland: {target_country}
Verwendungszweck: {purpose}

Zusätzlich:
1. Erkläre in der Zielsprache kurz, welche Form der Anerkennung/Übersetzung für den konkreten Zweck verlangt werden kann.
2. Gib nur die für diesen Zweck relevanten rechtlichen/behördlichen Hinweise wieder; nicht das ganze Gesetz.
3. Gib konkrete nächste Schritte in der Zielsprache an.
4. Gib alle Überschriften (title, legal_title, next_title, source_title) vollständig in der Zielsprache aus.
5. Nutze Websuche für aktuelle offizielle Anforderungen und nenne nur Quellen, die du tatsächlich gefunden hast.
6. Behaupte nicht, dass SwissHelper selbst eine amtlich beglaubigte Übersetzung erstellt.
"""
        response = client.responses.create(
            model=MODEL,
            tools=[{"type": "web_search"}],
            instructions=INSTRUCTIONS,
            input=[{"role": "user", "content":[{"type":"input_text","text":prompt}, content]}],
            text={"format":{"type":"json_schema","name":"swisshelper_translation","strict":True,"schema":TRANSLATION_SCHEMA}},
            store=False
        )
        return jsonify(json.loads(response.output_text))
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500

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
