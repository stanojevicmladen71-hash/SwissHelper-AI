import os, json, tempfile
from pathlib import Path
from flask import Flask, request, jsonify, send_from_directory, send_file
BASE=Path(__file__).resolve().parent
app=Flask(__name__)
try:
    from pypdf import PdfReader
except Exception:
    PdfReader=None
OPENAI_KEY=os.getenv("OPENAI_API_KEY","").strip()
MODEL=os.getenv("OPENAI_MODEL","gpt-5.6-luna")
LANG_NAMES={"Deutsch":"German","Serbisch":"Serbian","Bosnisch":"Bosnian","Kroatisch":"Croatian","Englisch":"English","Italienisch":"Italian","Albanisch":"Albanian","Polnisch":"Polish","Französisch":"French","Slowakisch":"Slovak","Rumänisch":"Romanian","Spanisch":"Spanish","Griechisch":"Greek","Ungarisch":"Hungarian","Tschechisch":"Czech","Mazedonisch":"Macedonian","Bulgarisch":"Bulgarian","Türkisch":"Turkish","Slowenisch":"Slovenian","Portugiesisch":"Portuguese"}
SWISS_SOURCES={"Ausländerausweis verlängern":[("ch.ch – Ausländer in der Schweiz","https://www.ch.ch/de/auslaender-in-der-schweiz/")],"Führerausweis umtauschen":[("ch.ch – Führerausweis","https://www.ch.ch/de/fuehrerausweis/")],"In die Schweiz ziehen":[("ch.ch – Einreise und Aufenthalt","https://www.ch.ch/de/auswandern-und-in-die-schweiz-einwandern/einreise-und-aufenthalt-in-der-schweiz/")],"Arbeitsbewilligung":[("SEM – Arbeit","https://www.sem.admin.ch/sem/de/home/themen/arbeit.html")],"Familiennachzug":[("ch.ch – Familiennachzug","https://www.ch.ch/de/familie-und-partnerschaft/familiennachzug/")],"Bei der Gemeinde anmelden":[("ch.ch","https://www.ch.ch/")],"Krankenkasse":[("ch.ch – Krankenkasse","https://www.ch.ch/de/versicherungen-und-vorsorge/krankenkasse/")],"Steuererklärung":[("ch.ch – Steuern","https://www.ch.ch/de/steuern-und-finanzen/steuern/")],"Kinderzulage":[("AHV/IV – Familienzulagen","https://www.ahv-iv.ch/de/Sozialversicherungen/Familienzulagen")],"Ausbildungszulage":[("AHV/IV – Familienzulagen","https://www.ahv-iv.ch/de/Sozialversicherungen/Familienzulagen")],"Welche Unterlagen brauche ich?":[("ch.ch","https://www.ch.ch/")],"Ich weiß nicht, was ich machen muss":[("ch.ch","https://www.ch.ch/")]}
def extract_pdf(path):
    if not PdfReader:return ""
    try:
        r=PdfReader(str(path));return "\n".join((p.extract_text() or "") for p in r.pages)[:30000]
    except Exception:return ""
def pdf_fields(path):
    if not PdfReader:return []
    try:
        r=PdfReader(str(path));fields=r.get_fields() or {};return [{"name":str(k),"description":str(v.get('/TU') or v.get('/TM') or "")} for k,v in fields.items()]
    except Exception:return []
def ai_text(prompt):
    if not OPENAI_KEY:return None
    try:
        from openai import OpenAI
        return OpenAI(api_key=OPENAI_KEY).responses.create(model=MODEL,input=prompt).output_text or ""
    except Exception:return None
def json_ai(prompt):
    txt=ai_text(prompt)
    if not txt:return None
    try:return json.loads(txt)
    except Exception:
        txt=txt.replace("```json","").replace("```","").strip()
        try:return json.loads(txt)
        except Exception:return None
@app.get("/")
def home():return send_from_directory(BASE,"index.html")
@app.get("/healthz")
def health():return jsonify(status="ok",ai_enabled=bool(OPENAI_KEY))
@app.post("/analyze")
def analyze():
    f=request.files.get("document");lang=request.form.get("language","Deutsch")
    if not f:return jsonify(error="Kein Dokument ausgewählt."),400
    suffix=Path(f.filename or "upload").suffix.lower()
    with tempfile.NamedTemporaryFile(delete=False,suffix=suffix) as t:f.save(t.name);p=Path(t.name)
    try:
        text=extract_pdf(p) if suffix==".pdf" else ""
        prompt="Analyze this official document. Answer in %s. Return ONLY JSON with keys document_type,sender,topic,deadline,simple_explanation,tasks,next_steps,required_documents,warnings. Do not invent facts.\nDOCUMENT TEXT:\n%s"%(LANG_NAMES.get(lang,lang),text)
        data=json_ai(prompt)
        if data:return jsonify(data)
        return jsonify(document_type="PDF/Dokument" if suffix==".pdf" else "Bilddokument",sender="Nicht automatisch erkannt",topic="Dokumentanalyse",deadline="Nicht automatisch erkannt",simple_explanation="Für die vollständige KI-Analyse kann auf Render OPENAI_API_KEY hinterlegt werden.",tasks=["Originaldokument prüfen","Erkannte Angaben kontrollieren"],next_steps=["Fehlende Angaben ergänzen","Zuständige Stelle anhand offizieller Quellen prüfen"],required_documents=["Originaldokument"],warnings=["Testversion: keine behördliche Entscheidung."])
    finally:
        try:p.unlink()
        except:pass
@app.post("/translate-document")
def translate():
    body=request.get_json(silent=True) or {}
    lang=request.form.get("target_language") or body.get("target_language","Deutsch")
    source=request.form.get("source_country") or body.get("source_country","")
    target=request.form.get("target_country") or body.get("target_country","")
    purpose=request.form.get("purpose") or body.get("purpose","")
    original=body.get("original_text","") if request.is_json else ""
    if not original and request.files.get("translationFile"):
        f=request.files["translationFile"]
        with tempfile.NamedTemporaryFile(delete=False,suffix=Path(f.filename or "upload").suffix) as t:f.save(t.name);p=Path(t.name)
        try:original=extract_pdf(p) if p.suffix.lower()==".pdf" else ""
        finally:
            try:p.unlink()
            except:pass
    if not original:return jsonify(error="Kein Text bzw. kein lesbarer PDF-Text gefunden."),400
    prompt="Translate professionally into %s. Preserve names, numbers, dates and legal terminology. Source country=%s; target country=%s; purpose=%s. Return only translation.\n\n%s"%(LANG_NAMES.get(lang,lang),source,target,purpose,original[:30000])
    result=ai_text(prompt)
    if result is None:return jsonify(error="Für die professionelle KI-Übersetzung muss auf Render OPENAI_API_KEY hinterlegt werden."),503
    return jsonify(translation=result)
@app.post("/form-helper")
def form_helper():
    f=request.files.get("form");lang=request.form.get("language","Deutsch");action=request.form.get("action","explain")
    if not f:return jsonify(error="Kein Formular ausgewählt."),400
    suffix=Path(f.filename or "upload").suffix.lower()
    with tempfile.NamedTemporaryFile(delete=False,suffix=suffix) as t:f.save(t.name);p=Path(t.name)
    try:
        text=extract_pdf(p) if suffix==".pdf" else "";fields=pdf_fields(p) if suffix==".pdf" else []
        if action=="fill":return jsonify(document_type="Ausfüllbares PDF" if fields else "PDF / Scan",fields=fields,fill_note=("Ausfüllbare PDF-Felder wurden erkannt. Die Werte können Feld für Feld vorbereitet werden." if fields else "Dieses Dokument enthält keine technisch erkennbaren PDF-Formularfelder. Es wird Feld für Feld manuell unterstützt; OCR für Scans ist als nächster Ausbauschritt vorgesehen."))
        prompt="You are a multilingual form helper. Answer in %s. Return ONLY JSON with keys document_type,simple_explanation,next_steps,required_documents,tasks,warnings,deadline. Do not invent requirements.\nFORM TEXT:\n%s"%(LANG_NAMES.get(lang,lang),text[:30000])
        data=json_ai(prompt)
        if data:return jsonify(data)
        return jsonify(document_type="Formular",simple_explanation="Formular erkannt. Für die inhaltliche KI-Erklärung muss OPENAI_API_KEY hinterlegt sein.",next_steps=["Formular öffnen","Pflichtfelder prüfen","Unterlagen anhand des Originals kontrollieren"],required_documents=["Originalformular"],tasks=["Formular vollständig lesen","Fehlende Angaben sammeln"],warnings=["Keine rechtlichen Anforderungen erfinden."],deadline="Nicht automatisch erkannt")
    finally:
        try:p.unlink()
        except:pass
@app.post("/fill-pdf")
def fill_pdf():
    f=request.files.get("form")
    if not f:return jsonify(error="Kein Formular ausgewählt."),400
    if not PdfReader:return jsonify(error="PDF-Verarbeitung ist auf diesem Server nicht verfügbar."),500
    try:values=json.loads(request.form.get("values","{}"))
    except Exception:return jsonify(error="Ungültige Formularwerte."),400
    suffix=Path(f.filename or "form.pdf").suffix.lower()
    if suffix!=".pdf":return jsonify(error="Direktes Ausfüllen ist nur für PDF-Formulare möglich."),400
    with tempfile.NamedTemporaryFile(delete=False,suffix=".pdf") as t:f.save(t.name);src=Path(t.name)
    out=src.with_name(src.stem+"_filled.pdf")
    try:
        reader=PdfReader(str(src))
        fields=reader.get_fields() or {}
        if not fields:return jsonify(error="Dieses PDF hat keine technisch ausfüllbaren Formularfelder. Bitte die Feld-für-Feld-Hilfe verwenden."),400
        from pypdf import PdfWriter
        writer=PdfWriter()
        writer.clone_document_from_reader(reader)
        names=list(fields.keys())
        mapped={names[int(k)]:v for k,v in values.items() if str(k).isdigit() and int(k)<len(names) and v is not None}
        for page in writer.pages: writer.update_page_form_field_values(page,mapped,auto_regenerate=True)
        with open(out,"wb") as fh:writer.write(fh)
        return send_file(out,as_attachment=True,download_name="SwissHelper_ausgefuelltes_Formular.pdf",mimetype="application/pdf")
    except Exception as e:
        return jsonify(error="Das PDF konnte nicht ausgefüllt werden: "+str(e)),500
    finally:
        try:src.unlink()
        except:pass

@app.post("/swiss-helper")
def swiss_helper():
    d=request.get_json(silent=True) or {};topic=d.get("topic","");lang=d.get("language","Deutsch");src=SWISS_SOURCES.get(topic,[("ch.ch","https://www.ch.ch/")])
    steps={"Ausländerausweis verlängern":["Aufenthaltsstatus und zuständigen Kanton prüfen","Frist und zuständige Behörde prüfen","Offizielles Formular bzw. Online-Verfahren verwenden"],"Führerausweis umtauschen":["Ausländischen Führerausweis und Wohnsitzstatus prüfen","Zuständige kantonale Stelle prüfen","Offizielles Gesuch und verlangte Unterlagen vorbereiten"],"In die Schweiz ziehen":["Staatsangehörigkeit und Aufenthaltszweck bestimmen","Einreise- und Aufenthaltsregeln des Ziellandes prüfen","Arbeits-/Familienunterlagen und Anmeldung vorbereiten"]}.get(topic,["Persönliche Situation und zuständige Stelle bestimmen","Aktuelle offizielle Anforderungen prüfen","Formular und Unterlagen vorbereiten"])
    return jsonify(summary="Test-Workflow für: %s. Sprache: %s."%(topic,LANG_NAMES.get(lang,lang)),steps=steps,sources=[{"name":n,"url":u} for n,u in src])
if __name__=="__main__":app.run(host="0.0.0.0",port=int(os.getenv("PORT","10000")))
