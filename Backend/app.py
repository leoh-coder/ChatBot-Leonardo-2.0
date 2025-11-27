from __future__ import annotations
import os
import re
from datetime import date, datetime, timedelta
from typing import Dict, List, Optional, Tuple
from dotenv import load_dotenv
load_dotenv()

from fastapi import Depends, FastAPI, HTTPException, Query, status
from fastapi.middleware.cors import CORSMiddleware
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain_google_genai import ChatGoogleGenerativeAI
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import func, select
from sqlalchemy.orm import Session 
from db import Base, engine, get_db
from models import Conversation, Message, Todo
from tools import rag_text
from tools import todo as todo_tool

#Configs
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
if not GEMINI_API_KEY:
    raise RuntimeError("Defina GEMINI_API_KEY (ou GOOGLE_API_KEY) no .env")

MODEL_NAME = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")

#Memoria
SHORT_MEMORY_LIMIT = 20
memory_cache: Dict[int, Dict[str, object]] = {}
GLOBAL_MEMORY: Dict[int, Dict[str, str]] = {}

MONEY_HINTS = {"dinheiro", "valor", "preco", "preço", "total", "faturamento", "ticket"}

WELCOME_TEXT = (
    "Olá! Posso resumir documentos (RAG), cuidar de tarefas To-Do "
    "(criar, listar, concluir, editar/excluir com regras) ou só conversar. O que você precisa?"
)
BLOCKED_REPLY = "Essa tarefa já foi concluída e não pode mais ser alterada ou excluída."

# Palavras To-Do e do Doc
TODO_CREATE_WORDS = (
    "adicionar", "adicione", "adiciona", "criar", "crie",
    "incluir", "inclua", "inserir", "insira", "colocar", "coloque",
)
TODO_UPDATE_WORDS = (
    "editar", "edite", "alterar", "atualizar", "atualiza",
    "adiar", "mudar", "postergar", "remarcar", "reagendar",
)
TODO_FINISH_WORDS = (
    "concluir", "conclua", "finalizar", "finaliza",
    "encerrar", "encerre", "terminar", "termina",
    "fechar", "feche", "marcar como concluida", "marcar como concluído",
)
TODO_DELETE_WORDS = ("excluir", "apagar", "remover", "deletar", "delete")
TODO_LIST_WORDS = ("listar", "liste", "mostrar", "mostre", "quais", "minhas tarefas", "tarefas")
TODO_GRAPH_WORDS = ("grafico", "gráfico", "status das tarefas")

TODO_KEYWORDS = set().union(
    TODO_CREATE_WORDS,
    TODO_UPDATE_WORDS,
    TODO_FINISH_WORDS,
    TODO_DELETE_WORDS,
    TODO_LIST_WORDS,
    TODO_GRAPH_WORDS,
    ("tarefa", "to-do", "todo", "lista"),
)

DOC_KEYWORDS = ["documento", "texto", "relatório", "resuma", "trecho", "no arquivo", "o texto", "e-book", "ebook", "pdf", "arquivo"]

#LLM
llm = ChatGoogleGenerativeAI(
    model=MODEL_NAME,
    google_api_key=GEMINI_API_KEY,
    temperature=0.2,
    convert_system_message_to_human=True,
)

app = FastAPI(title="ChatBot-Leonardo")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Schemas 
class ConversationCreate(BaseModel):
    title: str = Field(..., min_length=1, max_length=200)

class ConversationUpdate(BaseModel):
    title: str = Field(..., min_length=1, max_length=200)

class ChatPayload(BaseModel):
    conversation_id: int
    text: Optional[str] = Field(None, min_length=1)
    message: Optional[str] = Field(None, min_length=1)
    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    @model_validator(mode="after")
    def ensure_text(self):
        self.text = self.text or self.message
        if not self.text:
            raise ValueError("mensagem obrigatória.")
        return self

class TodoCreatePayload(BaseModel):
    title: str = Field(..., min_length=1)
    description: Optional[str] = None
    due_date: Optional[datetime] = None
    status: Optional[str] = Field(default="aberta", pattern="^(aberta|em_andamento|concluida)$")

class TodoUpdatePayload(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    due_date: Optional[datetime] = None
    status: Optional[str] = Field(default=None, pattern="^(aberta|em_andamento|concluida)$")
    model_config = ConfigDict(extra="forbid")

#
def _format_datetime(value: Optional[datetime]) -> Optional[str]:
    if value is None:
        return None
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)

def _format_brl(value: object) -> str:
    try:
        numero = float(value)
    except Exception:
        return str(value)
    if 2000 <= numero < 2100 and float(numero).is_integer():
        return str(int(numero))
    texto = f"{numero:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return f"R$ {texto}"

def _clean_assistant_text(text: Optional[str]) -> str:
    if not text:
        return ""
    cleaned = text.replace("*", "").replace("`", "")
    return cleaned.strip()

def _ensure_brl_text(text: Optional[str], context_hint: Optional[str] = None) -> str:
    if not text:
        return ""
    hint = (context_hint or "").lower()
    if hint not in MONEY_HINTS:
        return text.strip()
    money_pattern = re.compile(r"(?<!\d)(\d{1,3}(?:\.\d{3})*(?:,\d+)?|\d+(?:\.\d+)?)(?!\d)")
    def _sub(match: re.Match[str]) -> str:
        bruto = match.group(1)
        antes = match.string[max(0, match.start() - 3) : match.start()]
        if "R$" in antes:
            return bruto
        normalizado = bruto.replace(".", "").replace(",", ".")
        try:
            numero = float(normalizado)
        except Exception:
            return bruto
        if 2000 <= numero < 2100 and float(numero).is_integer():
            return bruto
        return _format_brl(numero)
    return money_pattern.sub(_sub, text).strip()

def _guess_money_hint(text: str) -> Optional[str]:
    lowered = (text or "").lower()
    for palavra in MONEY_HINTS:
        if palavra in lowered:
            return palavra
    return None

def _record_global_name(conversation_id: int, nome: str) -> None:
    if not nome:
        return
    GLOBAL_MEMORY[conversation_id] = {"nome": nome}

def _find_known_name(conversation_id: Optional[int] = None) -> Optional[str]:
    if conversation_id is not None:
        nome = GLOBAL_MEMORY.get(conversation_id, {}).get("nome")
        if nome:
            return nome
    for cid in sorted(GLOBAL_MEMORY.keys(), reverse=True):
        nome = GLOBAL_MEMORY[cid].get("nome")
        if nome:
            return nome
    return None

def _is_name_question(text: str) -> bool:
    t = (text or "").lower()
    return bool(re.search(r"qual\s+(?:é|e|o)\s+meu\s+nome", t, re.IGNORECASE))

def _history_messages(db: Session, conversation_id: int, limit: int = 20) -> List[Message]:
    stmt = (
        select(Message)
        .where(Message.conversation_id == conversation_id)
        .order_by(Message.id.desc())
        .limit(limit)
    )
    history = list(db.scalars(stmt))
    history.reverse()
    return history

def _extract_name(text: str) -> Optional[str]:
    achado = re.search(r"meu nome é\s+([A-Za-zÀ-ÿ\s]+)", text, re.IGNORECASE)
    if not achado:
        return None
    nome = achado.group(1).strip()
    nome = re.split(r"[.!?,;]", nome)[0].strip()
    return nome or None

def _remember(conversation_id: int, role: str, texto: str) -> Dict[str, object]:
    registro = memory_cache.setdefault(conversation_id, {"recent": [], "nome": None})
    recente = registro.get("recent") or []
    recente = (recente + [f"{role}: {texto}"]) if texto else recente
    registro["recent"] = recente[-SHORT_MEMORY_LIMIT:]
    if role == "user":
        nome = _extract_name(texto)
        if nome:
            registro["nome"] = nome
            _record_global_name(conversation_id, nome)
    return registro

#intenção e datas e outros
def _detect_intent(text: str) -> str:
    lowered = (text or "").lower()

    if any(word in lowered for word in ["e-book", "ebook", "documento", "texto", "arquivo", "pdf"]):
        return "doc"

    if any(word in lowered for word in TODO_KEYWORDS):
        return "todo"

    return "chat"

def _human_due_date(due_date: Optional[datetime]) -> str:
    if not due_date:
        return ""
    return due_date.strftime("%d/%m/%Y %H:%M")

def _extract_time(text: str) -> Optional[Tuple[int, int]]:
    m = re.search(r"\b(?:às|as)\s+(\d{1,2})(?::(\d{2}))?", text, re.IGNORECASE)
    if not m:
        m = re.search(r"\b(\d{1,2})(?::(\d{2}))?\s*h\b", text, re.IGNORECASE)
    if not m:
        return None

    hour = int(m.group(1))
    minute = int(m.group(2)) if m.group(2) else 0
    hour = max(0, min(23, hour))
    minute = max(0, min(59, minute))

    return hour, minute


_WEEKMAP = {
    "segunda": 0, "terca": 1, "terça": 1, "quarta": 2,
    "quinta": 3, "sexta": 4, "sabado": 5, "sábado": 5, "domingo": 6
}

def _next_weekday(base: datetime, target_weekday: int) -> datetime:
    diff = (target_weekday - base.weekday()) % 7
    if diff == 0:
        diff = 7
    return base + timedelta(days=diff)

def _extract_due_date(text: str) -> Optional[datetime]:
    lowered = (text or "").lower()
    now = datetime.now()
    base = now

    if "depois de amanhã" in lowered:
        base = now + timedelta(days=2)
    elif "amanhã" in lowered:
        base = now + timedelta(days=1)
    elif "hoje" in lowered:
        base = now
    else:
        for k, idx in _WEEKMAP.items():
            if re.search(rf"\b{k}\b", lowered):
                base = _next_weekday(now, idx)
                break
        else:
            m = re.search(r"(\d{1,2})/(\d{1,2})(?:/(\d{2,4}))?", text)
            if m:
                d, mo, y = int(m.group(1)), int(m.group(2)), m.group(3)
                yv = int(y) if y else now.year
                try:
                    base = base.replace(year=yv, month=max(1, min(12, mo)), day=max(1, min(31, d)))
                except ValueError:
                    return None
            else:
                return None

    hour_info = _extract_time(text) or (9, 0)
    return base.replace(hour=hour_info[0], minute=hour_info[1], second=0, microsecond=0)

def _extract_date_filter(text: str) -> Optional[date]:
    due = _extract_due_date(text)
    return due.date() if due else None

def _extract_title(text: str) -> Optional[str]:
    if not text:
        return None
    quoted = re.findall(r"[\"“']([^\"”']+)[\"”']", text)
    if quoted:
        return quoted[0].strip()

    t = text.strip()

    verbos = "|".join([*TODO_CREATE_WORDS, *TODO_UPDATE_WORDS])
    t = re.sub(rf"\b(?:{verbos})\b", "", t, flags=re.IGNORECASE)

    t = re.sub(r"\btarefa[s]?\b", "", t, flags=re.IGNORECASE)
    t = re.sub(r"\bpara\b.*$", "", t, flags=re.IGNORECASE)
    t = re.sub(r"\bàs\s+\d{1,2}(?::\d{2})?\b", "", t, flags=re.IGNORECASE)
    t = re.sub(r"\b\d{1,2}[:h]\d{0,2}\b", "", t, flags=re.IGNORECASE)
    t = re.sub(r"\b\d{1,2}/\d{1,2}(?:/\d{2,4})?\b", "", t, flags=re.IGNORECASE)
    for k in _WEEKMAP.keys():
        t = re.sub(rf"\b{k}\b", "", t, flags=re.IGNORECASE)
    t = re.sub(r"\b(hoje|amanhã|depois de amanhã)\b", "", t, flags=re.IGNORECASE)

    t = re.sub(r"\s+", " ", t).strip()
    return t[:80] if t else None

def _find_todo_by_title(db: Session, title: Optional[str]) -> Optional[Todo]:
    if not title:
        return None
    t = title.strip().lower()
    stmt = (
        select(Todo)
        .where(func.lower(Todo.title) == t)
        .order_by(Todo.id.desc())
    )
    found = db.scalars(stmt).first()
    if found:
        return found
    stmt2 = (
        select(Todo)
        .where(Todo.title.ilike(f"%{t}%"))
        .order_by(Todo.id.desc())
    )
    return db.scalars(stmt2).first()

#To-Do 
def _handle_todo_chat(text: str, db: Session) -> str:
    lowered = (text or "").lower()
    action = "list"

    if any(w in lowered for w in TODO_DELETE_WORDS):
        action = "delete"
    elif any(w in lowered for w in TODO_FINISH_WORDS):
        action = "finish"
    elif any(w in lowered for w in TODO_CREATE_WORDS):
        action = "create"
    elif any(w in lowered for w in TODO_UPDATE_WORDS):
        action = "update"
    elif any(w in lowered for w in TODO_GRAPH_WORDS):
        action = "stats"
    elif any(w in lowered for w in TODO_LIST_WORDS):
        action = "list"

    alvo_cache: Optional[Todo] = None
    if action in ("finish", "update", "delete"):
        titulo = _extract_title(text)
        alvo_cache = _find_todo_by_title(db, titulo)
        if not alvo_cache:
            return "Não achei essa tarefa."
        if alvo_cache.status == "concluida":
            if action == "finish":
                return f"A tarefa '{alvo_cache.title}' já está concluída."
            return BLOCKED_REPLY

    try:
        if action == "create":
            titulo = _extract_title(text) or "tarefa sem nome"
            due = _extract_due_date(text)
            todo = todo_tool.create_todo(
                db,
                title=titulo,
                description=text,
                due_date=due,
                status="aberta",
            )
            prazo = f" para { _human_due_date(due) }" if due else ""
            return f"Tarefa '{todo['title']}' criada{prazo}."
        if action == "list":
            filtro_status = None
            if "conclu" in lowered:
                filtro_status = "concluida"
            elif "abert" in lowered or "pendente" in lowered:
                filtro_status = "aberta"


            filtro_data = _extract_date_filter(text)
            tarefas = todo_tool.list_todos(
                db,
                status=filtro_status,
                target_date=filtro_data,
            )

            if not tarefas:
                return "Nenhuma tarefa encontrada."

            linhas: List[str] = []
            for t in tarefas[:10]:
                due_txt = (
                    f" — { _human_due_date(datetime.fromisoformat(t['due_date'])) }"
                    if t["due_date"]
                    else ""
                )
                linhas.append(f"- {t['title']} ({t['status']}){due_txt}")

            resposta = "Tarefas:\n" + "\n".join(linhas)
            if len(tarefas) >= 3:
                resposta += (
                    "\n\nVou te mostrar um gráfico com o status das suas tarefas."
                )

            return resposta
        
        if action == "finish" and alvo_cache:
            atualizado = todo_tool.update_todo(db, alvo_cache.id, status="concluida")
            return f"Tarefa '{atualizado['title']}' marcada como concluída."
        if action == "update" and alvo_cache:
            novo_prazo = _extract_due_date(text)
            novo_titulo = _extract_title(text)
            kwargs: Dict[str, object] = {}
            if novo_prazo is not None:
                kwargs["due_date"] = novo_prazo
            else:
                kwargs["due_date"] = todo_tool._MISSING
            if novo_titulo and novo_titulo.lower() != alvo_cache.title.lower():
                kwargs["title"] = novo_titulo
            atualizado = todo_tool.update_todo(db, alvo_cache.id, **kwargs)
            prazo_txt = (
                f" com prazo { _human_due_date(novo_prazo) }" if novo_prazo else ""
            )
            return f"Tarefa '{atualizado['title']}' atualizada{prazo_txt}."
        if action == "delete" and alvo_cache:
            todo_tool.delete_todo(db, alvo_cache.id)
            return f"Tarefa '{alvo_cache.title}' removida."
        if action == "stats":
            stats = todo_tool.stats_por_status(db)
            abertas = stats.get("aberta", 0)
            concluidas = stats.get("concluida", 0)
            return (
                "Status das suas tarefas:\n"
                f"- Abertas: {abertas}\n"
                f"- Concluídas: {concluidas}"
            )


    except todo_tool.TodoError as exc:
        if getattr(exc, "status_code", 400) == 409:
            return BLOCKED_REPLY
        return exc.detail

    return "OK, cuidarei disso."

# LLM
def _build_messages(
    memoria: Dict[str, object],
    history: List[Message],
    context_extra: str,
    question: str,
) -> List[SystemMessage | HumanMessage | AIMessage]:
    nome = memoria.get("nome")
    system = (
        "Você é um assistente estudantil, direto e gentil. "
        "Fale em português do Brasil e cite fontes quando usar documentos."
    )
    messages: List[SystemMessage | HumanMessage | AIMessage] = [SystemMessage(content=system)]

    resumo = "\n".join(memoria.get("recent", [])[-SHORT_MEMORY_LIMIT:])
    if resumo:
        messages.append(HumanMessage(content=f"Contexto recente:\n{resumo}"))

    if context_extra:
        messages.append(HumanMessage(content=f"Trechos relevantes:\n{context_extra}"))

    for msg in history[-SHORT_MEMORY_LIMIT:]:
        content = msg.text or ""
        if msg.role == "user":
            messages.append(HumanMessage(content=content))
        else:
            messages.append(AIMessage(content=content))

    pergunta = question
    if nome:
        pergunta = f"O usuário {nome} disse: {question}"
    messages.append(HumanMessage(content=pergunta))
    return messages

def _run_llm(conversation_id: int, question: str, memoria: Dict[str, object], db: Session, context_extra: str = "") -> str:
    history = _history_messages(db, conversation_id)
    messages = _build_messages(memoria, history, context_extra, question)
    try:
        result = llm.invoke(messages)
        reply = getattr(result, "content", "") or ""
    except Exception:
        raise HTTPException(status_code=503, detail="Falha ao consultar o modelo.")
        reply = _clean_assistant_text(reply)
    nome = memoria.get("nome")
    if nome and reply:
        inicio = reply.strip().lower()
        if not (inicio.startswith("oi") or inicio.startswith("olá") or inicio.startswith("ola")):
            reply = f"Oi, {nome}! {reply}"

    return reply


# API 
@app.on_event("startup")
def on_startup() -> None:
    Base.metadata.create_all(bind=engine)
    docs = rag_text.carregar_docs()
    rag_text.build_or_load_index(docs)
    print("API pronta.")

@app.get("/ping")
def ping() -> dict:
    return {"status": "ok"}

def _get_conversation_or_404(conversation_id: int, db: Session) -> Conversation:
    conversation = db.get(Conversation, conversation_id)
    if not conversation:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Conversa não encontrada.")
    return conversation

@app.post("/conversations", status_code=status.HTTP_201_CREATED)
def create_conversation(payload: ConversationCreate, db: Session = Depends(get_db)) -> dict:
    conversation = Conversation(title=payload.title)
    db.add(conversation)
    db.commit()
    db.refresh(conversation)
    welcome = Message(conversation_id=conversation.id, role="assistant", text=WELCOME_TEXT)
    db.add(welcome)
    db.commit()
    return {"id": conversation.id, "title": conversation.title}

@app.get("/conversations")
def list_conversations(db: Session = Depends(get_db)) -> List[dict]:
    stmt = select(Conversation).order_by(Conversation.id.desc())
    conversations = list(db.scalars(stmt))
    return [
        {"id": conv.id, "title": conv.title, "created_at": _format_datetime(conv.created_at)}
        for conv in conversations
    ]

@app.get("/conversations/{conversation_id}/messages")
def list_messages(conversation_id: int, db: Session = Depends(get_db)) -> List[dict]:
    conversation = _get_conversation_or_404(conversation_id, db)
    messages = (
        select(Message)
        .where(Message.conversation_id == conversation.id)
        .order_by(Message.id.asc())
    )
    rows = list(db.scalars(messages))
    return [
        {"role": msg.role, "content": msg.text, "created_at": _format_datetime(msg.created_at)}
        for msg in rows
    ]

@app.patch("/conversations/{conversation_id}")
def update_conversation(conversation_id: int, payload: ConversationUpdate, db: Session = Depends(get_db)) -> dict:
    conversation = _get_conversation_or_404(conversation_id, db)
    conversation.title = payload.title
    db.add(conversation)
    db.commit()
    return {"id": conversation.id, "title": conversation.title}

@app.delete("/conversations/{conversation_id}")
def delete_conversation(conversation_id: int, db: Session = Depends(get_db)) -> dict:
    conversation = _get_conversation_or_404(conversation_id, db)
    db.delete(conversation)
    db.commit()
    memory_cache.pop(conversation_id, None)
    return {"message": "Conversa apagada"}

@app.post("/chat/send")
def chat_send(payload: ChatPayload, db: Session = Depends(get_db)) -> dict:
    conversation = _get_conversation_or_404(payload.conversation_id, db)
    texto = payload.text or ""

    user_message = Message(conversation_id=conversation.id, role="user", text=texto)
    db.add(user_message)
    db.commit()
    db.refresh(user_message)

    memoria = _remember(conversation.id, "user", texto)
    if _is_name_question(texto):
        nome_conhecido = _find_known_name(conversation.id)
        reply_text = f"Seu nome é {nome_conhecido}." if nome_conhecido else "Não tenho seu nome registrado ainda."
        assistant_message = Message(conversation_id=conversation.id, role="assistant", text=reply_text)
        db.add(assistant_message)
        db.commit()
        db.refresh(assistant_message)
        _remember(conversation.id, "assistant", reply_text)
        return {"reply": reply_text}

    intent = _detect_intent(texto)
    money_hint = _guess_money_hint(texto)

    if intent == "todo":
        reply_text = _handle_todo_chat(texto, db)
    else:
        contexto = rag_text.contexto_curto(texto, k=5) if intent == "doc" else ""
        reply_text = _run_llm(conversation.id, texto, memoria, db, contexto)

    reply_text = _clean_assistant_text(reply_text)
    reply_text = _ensure_brl_text(reply_text, context_hint=money_hint)

    assistant_message = Message(conversation_id=conversation.id, role="assistant", text=reply_text)
    db.add(assistant_message)
    db.commit()
    db.refresh(assistant_message)
    _remember(conversation.id, "assistant", reply_text)

    return {"reply": reply_text}

@app.post("/todo", status_code=status.HTTP_201_CREATED)
def todo_create(payload: TodoCreatePayload, db: Session = Depends(get_db)) -> dict:
    try:
        return todo_tool.create_todo(
            db,
            title=payload.title,
            description=payload.description or "",
            due_date=payload.due_date,
            status=payload.status or "aberta",
        )
    except todo_tool.TodoError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail)

@app.get("/todo")
def todo_list(
    status_filter: Optional[str] = Query(default=None, alias="status"),
    date_filter: Optional[str] = Query(default=None, alias="date"),
    db: Session = Depends(get_db),
) -> dict:
    try:
        target_date = datetime.strptime(date_filter, "%Y-%m-%d").date() if date_filter else None
    except ValueError:
        raise HTTPException(status_code=422, detail="data inválida (use YYYY-MM-DD)")
    try:
        tasks = todo_tool.list_todos(db, status=status_filter, target_date=target_date)
        return {"items": tasks}
    except todo_tool.TodoError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail)

@app.patch("/todo/{todo_id}")
def todo_update(todo_id: int, payload: TodoUpdatePayload, db: Session = Depends(get_db)) -> dict:
    try:
        data = payload.model_dump(exclude_unset=True)
        due_date_value = data["due_date"] if "due_date" in data else todo_tool._MISSING 
        return todo_tool.update_todo(
            db,
            todo_id,
            title=data.get("title"),
            description=data.get("description"),
            due_date=due_date_value,
            status=data.get("status"),
        )
    except todo_tool.TodoError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail)

@app.delete("/todo/{todo_id}")
def todo_delete(todo_id: int, db: Session = Depends(get_db)) -> dict:
    try:
        return todo_tool.delete_todo(db, todo_id)
    except todo_tool.TodoError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail)

@app.get("/todo/stats")
def todo_stats(db: Session = Depends(get_db)) -> dict:
    return todo_tool.stats_por_status(db)



