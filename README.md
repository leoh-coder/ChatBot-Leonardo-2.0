# ChatBot-Leonardo 2.0  
Chatbot pessoal, agora com **RAG**, **To-Do inteligente**, **múltiplas conversas**, **gráficos no frontend** e **backend completo em FastAPI + PostgreSQL + FAISS**.

Este é o **Projeto 2** da minha jornada em IA Generativa, após o ChatBot-Leonardo original.  
Aqui evoluí o sistema para algo mais próximo de um assistente real, com memória, tarefas, PDFs e interface própria.

---

## 🚀 Funcionalidades

### 🧠 1. Chat geral (Gemini + LangChain)  
Conversa natural, contextual e inteligente usando `gemini-2.5-flash`.

### 📚 2. RAG — Respostas baseadas em PDF  
- Lê PDFs da pasta `Backend/data/docs`  
- Gera embeddings com GEMINI `text-embedding-004`  
- Indexa com **FAISS**  
- Permite perguntar sobre o conteúdo do PDF

### ✅ 3. To-Do inteligente (via linguagem natural)  
- Criar tarefa  
- Listar  
- Concluir  
- Excluir  
- Bloqueia alterações em tarefas concluídas  
- Reconhece datas naturais (“hoje”, “amanhã”, “terça”, etc.)

### 📊 4. Gráficos automáticos no frontend  
Quando o usuário escreve:  
> "mostrar gráfico"  
o sistema consulta `/todo/stats` e renderiza um gráfico de barras via Canvas no chat.

### 💬 5. Múltiplas conversas  
Similar ao ChatGPT:  
- Criar conversas  
- Renomear  
- Excluir  
- Alternar entre elas  
- Histórico salvo no banco

---

## 🛠️ Tecnologias utilizadas

### Backend  
- **FastAPI**
- **SQLAlchemy**
- **PostgreSQL 16**
- **LangChain**
- **Gemini API**
- **FAISS**
- **PyMuPDF** (para ler PDFs)

### Frontend  
- HTML + CSS  
- JavaScript puro  
- Canvas API (gráficos)

### Infra  
- Docker  

---

# 📂 Estrutura do Projeto
```
ChatBot-Leonardo/
├── docker-compose.yml
├── README.md
├── Backend/
│ ├── app.py
│ ├── db.py
│ ├── models.py
│ ├── requirements.txt
│ ├── Dockerfile
│ ├── .env.example
│ ├── data/
│ │ ├── docs/
│ │ │ └── ebook-gestao-do-tempo-e-produtividade.pdf
│ │ └── .faiss_text/
│ └── tools/
│ ├── rag_text.py
│ ├── todo.py
│ └── init.py
└── Frontend/
  ├── index.html
  ├── styles.css
  └── app.js

```


# 🧩 Como rodar (via Docker)

1️⃣ Clone o repositório:

```
git clone https://github.com/leoh-coder/ChatBot-Leonardo-2.0.git
cd ChatBot-Leonardo-2.0
```
2️⃣ Configure o arquivo .env:
```
cd Backend
cp .env.example .env
```
Edite e coloque sua chave:
```
GEMINI_API_KEY=SUA_CHAVE_AQUI
GEMINI_MODEL=gemini-2.5-flash
DATABASE_URL=postgresql+psycopg2://leonardo:secret123@db:5432/ChatBot_Leonardo
RAG_DOCS_DIR=./data/docs
RAG_INDEX_DIR=./data/.faiss_text
```
3️⃣ Suba com Docker:
```
cd ..
docker-compose up --build
```
4️⃣ Abra no navegador:
```
Frontend → http://127.0.0.1:5500

API → http://127.0.0.1:8010/ping
```
# 🧩 Como rodar sem Docker


1️⃣ Suba um Postgres local:
```
docker run --name chatbot-postgres -e POSTGRES_USER=leonardo \
  -e POSTGRES_PASSWORD=secret123 -e POSTGRES_DB=ChatBot_Leonardo \
  -p 5432:5432 -d postgres:16
```
2️⃣ Configure o .env:
```
DATABASE_URL=postgresql+psycopg2://leonardo:secret123@localhost:5432/ChatBot_Leonardo
```
3️⃣ Ative o ambiente Python:
```
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```
4️⃣ Rode o backend:
```
uvicorn app:app --reload --port 8010
```
5️⃣ Abra o frontend:
```
Frontend/index.html
```
Ou:

```
cd Frontend
python -m http.server 5500
```


## 🧾 Licença

## Este projeto é de uso educacional como parte da minha formação em IA Generativa.

### Se quiser usar ou estudar, fique à vontade! 😊

---
## Autor: Leonardo Henrique Ramos Ferreira
## GitHub: https://github.com/leoh-coder
