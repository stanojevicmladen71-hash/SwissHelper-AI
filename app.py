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
Analysiere das hochgeladene Dokument in der Sprache: {language}.
Aktion: {action}

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
    return json.loads(response.output_text)

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
        return jsonify({"error": "Direktes Ausfüllen ist nur für PDF-Dateien möglich."}), 400

    try:
        data = f.read()
        reader = PdfReader(io.BytesIO(data))
        fields = reader.get_fields() or {}
        if not fields:
            return jsonify({"error": "Dieses PDF enthält keine ausfüllbaren PDF-Felder. Es wird als Scan behandelt."}), 400

        names = json.loads(request.form.get("field_names", "[]"))
        values = json.loads(request.form.get("values", "[]"))
        mapping = {str(n): str(v) for n, v in zip(names, values)}

        writer = PdfWriter()
        for page in reader.pages:
            writer.add_page(page)

        for name, value in mapping.items():
            if name in fields:
                writer.update_page_form_field_values(
                    writer.pages,
                    {name: value},
                    auto_regenerate=False
                )

        output = io.BytesIO()
        writer.write(output)
        output.seek(0)
        return send_file(
            output,
            mimetype="application/pdf",
            as_attachment=True,
            download_name="SwissHelper_ausgefuelltes_Formular.pdf"
        )
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500

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
Reiseziel: {d.get('destination')}
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


FAMILY_SCHEMA = {
    "type":"object","additionalProperties":False,
    "properties":{
        "title":{"type":"string"},"summary":{"type":"string"},
        "responsible_title":{"type":"string"},"responsible":{"type":"string"},
        "docs_title":{"type":"string"},"documents":{"type":"array","items":{"type":"string"}},
        "forms":{"type":"array","items":{"type":"object","additionalProperties":False,"properties":{"name":{"type":"string"},"url":{"type":"string"},"why":{"type":"string"}},"required":["name","url","why"]}},
        "next_title":{"type":"string"},"next_steps":{"type":"array","items":{"type":"string"}},
        "source_title":{"type":"string"},"sources":{"type":"array","items":{"type":"string"}}
    },
    "required":["title","summary","responsible_title","responsible","docs_title","documents","forms","next_title","next_steps","source_title","sources"]
}

@app.post("/liechtenstein-family")
def liechtenstein_family():
    d = request.get_json() or {}
    language = d.get("language", "Deutsch")
    prompt = f"""
Erstelle eine aktuelle, vorsichtige Orientierung zu Familienzulagen in Liechtenstein in der Sprache {language}.
Profil:
- Wohnsitzland: {d.get('residence_country')}
- Staatsangehörigkeit: {d.get('nationality')}
- Arbeitsland: {d.get('work_country')}
- Wohnsitzland der Kinder: {d.get('children_country')}
- Arbeitet der andere Elternteil: {d.get('spouse_work')}

Nutze vorrangig offizielle Quellen der Liechtensteinischen AHV-IV-FAK und der Liechtensteinischen Landesverwaltung.
Prüfe insbesondere: Anspruch als Grenzgänger, mögliche Konkurrenz ausländischer Familienleistungen, Differenzausgleich, zuständige Stelle und das passende offizielle Formular.
Für eine Person mit Wohnsitz in der Schweiz und Arbeit in Liechtenstein ist das offizielle Formular FZ-Ausland – Anmeldung Familienzulagen (FAK-02) besonders zu prüfen; nenne es als offizielles Formular nur, wenn es zum beschriebenen Profil passt.
Nutze als offizielle Formularquelle https://www.ahv.li/online-schalter/formulare und, falls passend, direkt https://www.ahv.li/fileadmin/user_upload/Dokumente/Online-Schalter/FORM/AHV-IV-FAK-FORM-4-02--Anmeldung_FZ_Ausland.pdf.
Keine definitive Anspruchszusage geben; kennzeichne, welche Punkte die FAK anhand des konkreten Familien- und Beschäftigungsfalls prüfen muss.
Alle Überschriften und Antworten vollständig in der gewünschten Sprache.
"""
    try:
        result = web_json(prompt, "swisshelper_liechtenstein_family", FAMILY_SCHEMA)
        forms = [f for f in (result.get("forms") or []) if str(f.get("url", "")).startswith(("https://www.ahv.li/", "https://www.llv.li/"))]
        residence = str(d.get("residence_country", ""))
        work = str(d.get("work_country", ""))
        if residence == "Schweiz" and work == "Liechtenstein":
            forms.insert(0, {"name":"FZ-Ausland – Anmeldung Familienzulagen (FAK-02)","url":"https://www.ahv.li/fileadmin/user_upload/Dokumente/Online-Schalter/FORM/AHV-IV-FAK-FORM-4-02--Anmeldung_FZ_Ausland.pdf","why":"Offizielles Formular für Grenzgänger/Kurzaufenthalter; die konkrete Zuständigkeit und die Beilagen müssen anhand des Einzelfalls geprüft werden."})
        elif residence == "Liechtenstein":
            forms.insert(0, {"name":"FZ-Inland – Anmeldung Familienzulagen (FAK-01)","url":"https://www.ahv.li/fileadmin/user_upload/Dokumente/Online-Schalter/FORM/AHV-IV-FAK-FORM-4-01--Anmeldung_FZ-Inland.pdf","why":"Offizielles Formular für Personen mit Wohnsitz in Liechtenstein; konkrete Voraussetzungen und Beilagen anhand des Einzelfalls prüfen."})
        forms.append({"name":"AHV-IV-FAK – Formulare","url":"https://www.ahv.li/online-schalter/formulare","why":"Offizielle Übersicht der aktuellen Formulare und Online-Anträge."})
        # Keep order but remove duplicate URLs.
        seen = set(); result["forms"] = [f for f in forms if not (f.get("url") in seen or seen.add(f.get("url")))]
        return jsonify(result)
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT","10000")))
