import os
import io
import re
import json
from typing import Optional, Dict, Any, List

from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool
from dotenv import load_dotenv

from PyPDF2 import PdfReader
from pdfminer.high_level import extract_text as pdfminer_extract_text
from bs4 import BeautifulSoup

import google.generativeai as genai

load_dotenv()

# ============================== Config Gemini ==============================
GOOGLE_API_KEY = os.environ.get("GOOGLE_API_KEY")
if not GOOGLE_API_KEY:
    raise RuntimeError("Defina GOOGLE_API_KEY no ambiente (.env ou variável).")

genai.configure(api_key=GOOGLE_API_KEY)
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-1.5-flash")
MODEL = genai.GenerativeModel(model_name=GEMINI_MODEL)

# ============================== Schema (JSON) ==============================
EMAIL_JSON_SCHEMA = {
    "type": "object",
    "properties": {
        "category": {"type": "string", "enum": ["Produtivo", "Improdutivo"]},
        "intent": {
            "type": "string",
            "enum": ["status", "anexo", "suporte", "dúvida", "felicitações", "agradecimento", "outros"]
        },
        "confidence": {"type": "number"},
        "suggested_reply": {"type": "string"}
    },
    "required": ["category", "intent", "confidence", "suggested_reply"]
}

# ============================== Instruções + Few-shots ==============================
SYSTEM_INSTRUCTIONS = """\
Você é um assistente de triagem de e-mails corporativos.
Objetivos:
1) Classificar o e-mail em: Produtivo OU Improdutivo.
2) Identificar a intenção: status | anexo | suporte | dúvida | felicitações | agradecimento | outros.
3) Sugerir uma resposta curta, clara e profissional em PT-BR.
4) Responder SOMENTE em JSON válido conforme o schema fornecido (sem texto extra).
Regras:
- "Produtivo": pede ação, informação ou exige resposta específica (suporte, status, dúvida, envio/validação de anexo).
- "Improdutivo": social/curto sem ação (felicitações, agradecimentos).
- 'confidence' deve ser 0..1 e refletir sua certeza.
"""

FEW_SHOTS = [
    {
        "email": "Poderiam informar o status do chamado 12345? Preciso da previsão.",
        "json": {
            "category": "Produtivo",
            "intent": "status",
            "confidence": 0.93,
            "suggested_reply": "Olá! Obrigado pelo contato. Vamos verificar o andamento do chamado 12345 e retornamos com uma atualização ainda hoje."
        }
    },
    {
        "email": "Segue em anexo o contrato para validação, por favor confirmar recebimento.",
        "json": {
            "category": "Produtivo",
            "intent": "anexo",
            "confidence": 0.90,
            "suggested_reply": "Olá! Recebemos o anexo e iniciaremos a validação. Assim que concluirmos, retornaremos com os próximos passos."
        }
    },
    {
        "email": "Estou com erro no sistema e preciso de suporte urgente.",
        "json": {
            "category": "Produtivo",
            "intent": "suporte",
            "confidence": 0.91,
            "suggested_reply": "Sinto pelo transtorno. Para agilizar, poderia informar print do erro e o horário aproximado da ocorrência? Vamos priorizar a análise."
        }
    },
    {
        "email": "Feliz Natal para toda a equipe!",
        "json": {
            "category": "Improdutivo",
            "intent": "felicitações",
            "confidence": 0.96,
            "suggested_reply": "Muito obrigado pelos votos! Desejamos ótimas festas e permanecemos à disposição."
        }
    },
    {
        "email": "Obrigado pela ajuda!",
        "json": {
            "category": "Improdutivo",
            "intent": "agradecimento",
            "confidence": 0.88,
            "suggested_reply": "Nós que agradecemos! Ficamos à disposição para o que precisar."
        }
    },
]

# ============================== Limpeza de e-mail ==============================
HEADER_RE = re.compile(r"^(from|de|to|para|subject|assunto|date|data|cc|bcc|reply-to|message-id|received)\s*:", re.I)

def strip_html(text: str) -> str:
    return BeautifulSoup(text, "html.parser").get_text(" ", strip=True)

def clean_email_text(raw: str) -> str:
    """Limpa e normaliza texto de e-mail removendo ruídos e formatação desnecessária."""
    if not raw or not isinstance(raw, str):
        return ""
    
    # Remover HTML se presente
    if "<html" in raw.lower() or "<div" in raw.lower() or "<br" in raw.lower():
        raw = strip_html(raw)
    
    lines = []
    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        if HEADER_RE.match(line):
            continue
        # Pular citações
        if line.startswith(">"):
            continue
        if len(line) < 3:
            continue
        lines.append(line)
    
    if not lines:
        return ""
    
    text = " ".join(lines)
    text = re.sub(r"https?://\S+", " ", text)
    text = re.sub(r"[^\w\s\-.,!?;:()]", " ", text)
    text = re.sub(r"\s{2,}", " ", text)
    text = text.strip()
    
    if len(text) < 10:
        return ""
    
    return text

# ============================== PDF (.pdf) ==============================
def read_pdf(data: bytes) -> str:
    """Lê PDF usando múltiplas estratégias para máxima compatibilidade."""
    content = ""
    
    try:
        reader = PdfReader(io.BytesIO(data))
        content = "".join((page.extract_text() or "") for page in reader.pages)
        if content.strip():
            print("PDF lido com sucesso usando PyPDF2")
            return content
    except Exception as e:
        print(f"PyPDF2 falhou: {str(e)}")
    
    try:
        content = pdfminer_extract_text(io.BytesIO(data)) or ""
        if content.strip():
            print("PDF lido com sucesso usando pdfminer")
            return content
    except Exception as e:
        print(f"pdfminer falhou: {str(e)}")
    
    try:
        text_content = data.decode('utf-8', errors='ignore')
        if text_content and len(text_content.strip()) > 100:
            print("PDF decodificado como texto UTF-8")
            return text_content
    except Exception as e:
        print(f"Decodificação UTF-8 falhou: {str(e)}")
    
    try:
        text_content = data.decode('latin-1', errors='ignore')
        if text_content and len(text_content.strip()) > 100:
            print("PDF decodificado como texto Latin-1")
            return text_content
    except Exception as e:
        print(f"Decodificação Latin-1 falhou: {str(e)}")
    
    print("Todas as estratégias de leitura de PDF falharam")
    return ""

def read_file_bytes_to_text(filename: str, data: bytes) -> str:
    if filename.lower().endswith(".pdf"):
        return read_pdf(data)
    try:
        return data.decode("utf-8", errors="ignore")
    except Exception:
        return data.decode("latin-1", errors="ignore")

# ============================== Prompt builder ==============================
def normalize_intent(v: str) -> str:
    if not v: return "outros"
    v = v.strip().lower()
    mapping = {"duvida": "dúvida", "agradecimentos": "agradecimento",
               "felicitacao": "felicitações", "felicitacoes": "felicitações"}
    v = mapping.get(v, v)
    return v if v in {"status","anexo","suporte","dúvida","felicitações","agradecimento","outros"} else "outros"

def build_user_prompt(email_text: str) -> str:
    few = "\n\n".join(
        f"Exemplo {i+1}:\nE-mail:\n{ex['email']}\nJSON:\n{json.dumps(ex['json'], ensure_ascii=False)}"
        for i, ex in enumerate(FEW_SHOTS)
    )
    return (
        f"{SYSTEM_INSTRUCTIONS}\n\n"
        f"{few}\n\n"
        f"Agora, analise este e-mail e responda SOMENTE JSON válido conforme o schema:\n"
        f"E-mail:\n-----\n{email_text}\n-----\n"
    )

def parse_json_strict(text: str) -> Dict[str, Any]:
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        raise ValueError("Resposta não contém JSON.")
    return json.loads(text[start:end+1])

def classify_with_gemini(email_text: str) -> Dict[str, Any]:
    prompt = [{"role": "user", "parts": [build_user_prompt(email_text)]}]
    resp = MODEL.generate_content(
        prompt,
        generation_config=genai.types.GenerationConfig(
            response_mime_type="application/json",
            response_schema=EMAIL_JSON_SCHEMA,
            temperature=0.2,
            max_output_tokens=512
        )
    )
    output_text = getattr(resp, "text", None)
    if not output_text:
        try: output_text = resp.candidates[0].content.parts[0].text
        except Exception: raise RuntimeError("Não foi possível ler a resposta do Gemini.")

    data = parse_json_strict(output_text)
    category = data.get("category", "Improdutivo")
    if category not in {"Produtivo","Improdutivo"}: category = "Improdutivo"
    intent = normalize_intent(data.get("intent"))
    conf = float(data.get("confidence", 0.7))
    reply = (data.get("suggested_reply") or "").strip() or "Obrigado pela mensagem!"
    return {"category": category, "confidence": conf,
            "suggested_reply": reply, "metadata": {"intent": intent}}

# ============================== FastAPI ==============================
app = FastAPI(title="Email Analyzer - Gemini Flash", version="3.2.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/health")
def health():
    return {"status": "ok", "model": GEMINI_MODEL}

@app.post("/api/analyze")
async def analyze(text: Optional[str] = Form(None), file: Optional[UploadFile] = File(None)):
    if not text and not file:
        raise HTTPException(status_code=400, detail="Envie um texto ou um arquivo .txt/.pdf.")
    if file is not None:
        filename = file.filename or ""
        data = await file.read()
        if not filename.lower().endswith((".pdf",".txt")):
            raise HTTPException(status_code=415, detail="Formato não suportado. Envie .txt ou .pdf.")
        raw = read_file_bytes_to_text(filename, data)
    else:
        raw = text or ""
    content = clean_email_text(raw)
    if not content:
        raise HTTPException(status_code=400, detail="Conteúdo vazio.")
    result = await run_in_threadpool(classify_with_gemini, content)
    return JSONResponse(result)

@app.post("/api/analyze_batch")
async def analyze_batch(
    texts: Optional[str] = Form(None), 
    files: Optional[List[UploadFile]] = File(None)
):
    items: List[Dict[str, Any]] = []
    
    if texts:
        try:
            arr = json.loads(texts)
            if not isinstance(arr, list):
                raise ValueError("Campo 'texts' deve ser uma lista")
        except Exception as e:
            raise HTTPException(
                status_code=400, 
                detail=f"Campo 'texts' deve ser JSON válido (lista de strings). Erro: {str(e)}"
            )
        
        for i, t in enumerate(arr):
            if isinstance(t, str) and t.strip():
                items.append({"id": f"text-{i}", "content": clean_email_text(t)})
    
    if files:
        for i, f in enumerate(files):
            try:
                name = f.filename or f"file-{i}"
                if not name.lower().endswith((".pdf", ".txt")):
                    continue
                
                data = await f.read()
                if not data:
                    continue
                    
                content = read_file_bytes_to_text(name, data)
                if content:
                    cleaned_content = clean_email_text(content)
                    if cleaned_content:
                        items.append({"id": name, "content": cleaned_content})
                    else:
                        print(f"Arquivo {name} não gerou conteúdo válido após limpeza")
                else:
                    print(f"Arquivo {name} não pôde ser lido")
                    
            except Exception as e:
                print(f"Erro ao processar arquivo {f.filename}: {str(e)}")
                continue
    
    if not items:
        raise HTTPException(
            status_code=400, 
            detail="Nenhum item válido para analisar. Verifique se os arquivos são .txt/.pdf válidos e contêm texto."
        )
    
    print(f"Processando {len(items)} itens: {[item['id'] for item in items]}")
    
    results = []
    for item in items:
        try:
            result = await run_in_threadpool(classify_with_gemini, item["content"])
            result["id"] = item["id"]
            results.append(result)
        except Exception as e:
            print(f"Erro ao processar item {item['id']}: {str(e)}")
            results.append({
                "id": item["id"],
                "category": "Improdutivo",
                "confidence": 0.0,
                "suggested_reply": f"Erro ao processar: {str(e)}",
                "metadata": {"intent": "outros"}
            })
    
    return JSONResponse({"count": len(results), "results": results})
