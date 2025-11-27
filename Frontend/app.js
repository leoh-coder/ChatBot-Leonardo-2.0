const API = "http://127.0.0.1:8010";
let current = null;

const list = document.getElementById("list");
const convTitle = document.getElementById("convTitle");
const msgs = document.getElementById("msgs");
const input = document.getElementById("input");
const sendBtn = document.getElementById("sendBtn");
const renameBtn = document.getElementById("renameBtn");
const deleteBtn = document.getElementById("deleteBtn");
const loadingEl = document.getElementById("loading");

function setLoading(on) {
  if (!loadingEl) return;
  if (on) loadingEl.classList.remove("hidden");
  else loadingEl.classList.add("hidden");
}

function setComposerEnabled(on) {
  input.disabled = !on;
  sendBtn.disabled = !on;
}

function setActionButtonsEnabled(on) {
  renameBtn.disabled = !on;
  deleteBtn.disabled = !on;
}

function toast(msg) {
  console.log("[UI]", msg);
}

window.onerror = (m, f, l, c, e) =>
  console.error("JS erro:", m, f, l, c, e);

/* grafico*/
function shouldShowChart(triggerText) {
  if (!triggerText) return false;
  const data = triggerText
    .toLowerCase()
    .normalize("NFD")
    .replace(/[\u0300-\u036f]/g, "");

  const gatilhos = [
    "grafico",
    "grafico das tarefas",
    "grafico de tarefas",
    "grafico das minhas tarefas",
    "mostrar grafico",
    "mostrar o grafico",
    "mostre o grafico",
  ];
  if (gatilhos.some((g) => data.includes(g))) {
    return true;
  }
  if (data.includes("vou te mostrar um grafico")) {
    return true;
  }

  return false;
}
async function maybeShowChart(triggerText) {
  if (!shouldShowChart(triggerText)) return;
  try {
    const stats = await api("/todo/stats");
    appendChartBubble(stats);
  } catch (e) {
    console.warn("Falha ao carregar gráfico:", e.message);
    const a = document.createElement("div");
    a.className = "bubble assistant";
    a.textContent =
      "Não consegui gerar o gráfico das tarefas agora. Tente novamente mais tarde.";
    msgs.appendChild(a);
    msgs.scrollTop = msgs.scrollHeight;
  }
}
function appendChartBubble(stats = {}) {
  const bubble = document.createElement("div");
  bubble.className = "bubble assistant chart";

  const title = document.createElement("div");
  title.className = "chart-title";
  title.textContent = "Status das suas tarefas";
  bubble.appendChild(title);

  const canvas = document.createElement("canvas");
  canvas.width = 240;
  canvas.height = 160;
  bubble.appendChild(canvas);

  msgs.appendChild(bubble);
  msgs.scrollTop = msgs.scrollHeight;

  renderChart(canvas, stats);
}
function renderChart(canvas, stats = {}) {
  if (!canvas) return;
  const ctx = canvas.getContext("2d");
  if (!ctx) return;

const keys   = ["aberta", "concluida"];
const labels = ["abertas", "concluídas"];
const colors = ["#22c55e", "#f87171"];
const values = keys.map((k) => Number(stats[k] || 0));

  const width = canvas.clientWidth || 320;
  const height = canvas.clientHeight || 200;
  canvas.width = width;
  canvas.height = height;

  ctx.clearRect(0, 0, width, height);

  const max = Math.max(...values, 1);
  const usableHeight = height - 40;
  const barWidth = Math.min(40, width / (keys.length * 2));
  const gap = barWidth * 0.8;
  const totalWidth = keys.length * barWidth + (keys.length - 1) * gap;
  const startX = (width - totalWidth) / 2;

  ctx.font = "12px system-ui";
  ctx.textAlign = "center";

  values.forEach((val, idx) => {
    const barHeight = (val / max) * usableHeight;
    const x = startX + idx * (barWidth + gap);
    const y = height - barHeight - 20;

    ctx.fillStyle = colors[idx % colors.length];
    ctx.fillRect(x, y, barWidth, barHeight);

    ctx.fillStyle = "#e5e7eb";
    ctx.fillText(String(val), x + barWidth / 2, y - 4);
    ctx.fillText(labels[idx], x + barWidth / 2, height - 5);
  });
}

/* */

async function api(path, opts = {}) {
  const r = await fetch(API + path, opts).catch((e) => {
    throw new Error("Falha de rede/CORS: " + e.message);
  });
  if (!r.ok) {
    const t = await r.text().catch(() => "");
    throw new Error(`HTTP ${r.status} ${r.statusText} | ${t}`);
  }
  return r.json();
}
(async () => {
  try {
    await api("/ping");
  } catch (e) {
    toast("Backend inacessível: " + e.message);
  }
})();

/* conversa */

async function loadConversations(selectId = null) {
  try {
    const data = await api("/conversations");
    list.innerHTML = "";
    data.forEach((c) => {
      const div = document.createElement("div");
      div.className =
        "conv" + (current && current.id === c.id ? " active" : "");
      div.textContent = c.title;
      div.dataset.id = c.id;
      div.onclick = () => selectConversation(c);
      list.appendChild(div);
    });

    if (selectId) {
      const found = data.find((x) => x.id === selectId);
      if (found) await selectConversation(found);
    } else if (current) {
      const keep = data.find((x) => x.id === current.id);
      if (keep) await selectConversation(keep);
    } else if (data.length) {
      await selectConversation(data[0]);
    } else {
      current = null;
      convTitle.textContent = "Selecione uma conversa";
      msgs.innerHTML = '<div class="empty">Sem conversa selecionada.</div>';
      setComposerEnabled(false);
      setActionButtonsEnabled(false);
    }
  } catch (e) {
    setComposerEnabled(false);
    setActionButtonsEnabled(false);
    toast("Erro ao listar conversas: " + e.message);
  }
}

async function selectConversation(c) {
  current = c;
  convTitle.textContent = c.title;

  [...document.querySelectorAll(".conv")].forEach((el) => {
    el.classList.toggle("active", Number(el.dataset.id) === c.id);
  });

  setComposerEnabled(true);
  setActionButtonsEnabled(true);
  await loadMessages();
}

async function loadMessages() {
  if (!current) return;
  try {
    const data = await api(`/conversations/${current.id}/messages`);
    msgs.innerHTML = "";
    if (!data.length) {
      msgs.innerHTML = '<div class="empty">Sem mensagens ainda.</div>';
      return;
    }
    data.forEach((m) => {
      const div = document.createElement("div");
      div.className = "bubble " + (m.role === "user" ? "user" : "assistant");
      div.textContent = m.content;
      msgs.appendChild(div);
    });
    msgs.scrollTop = msgs.scrollHeight;
  } catch (e) {
    toast("Erro ao carregar mensagens: " + e.message);
  }
}

/* .*/

document
  .getElementById("newConv")
  .addEventListener("submit", async (e) => {
    e.preventDefault();
    const titleEl = document.getElementById("title");
    const title = titleEl.value.trim() || "Nova conversa";
    try {
      const res = await api("/conversations", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ title }),
      });
      titleEl.value = "";
      await loadConversations(res.id);
    } catch (e) {
      toast("Erro ao criar conversa: " + e.message);
    }
  });

renameBtn.addEventListener("click", async () => {
  if (!current) return;
  const newTitle = prompt("Novo título:", current.title);
  if (!newTitle || newTitle.trim() === current.title) return;
  try {
    await api(`/conversations/${current.id}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ title: newTitle.trim() }),
    });
    await loadConversations(current.id);
  } catch (e) {
    toast("Erro ao renomear: " + e.message);
  }
});

deleteBtn.addEventListener("click", async () => {
  if (!current) return;
  if (!confirm(`Apagar "${current.title}"?`)) return;
  try {
    await api(`/conversations/${current.id}`, { method: "DELETE" });
    current = null;
    await loadConversations();
  } catch (e) {
    toast("Erro ao apagar: " + e.message);
  }
});

/* mensagem */

document
  .getElementById("composer")
  .addEventListener("submit", async (e) => {
    e.preventDefault();
    if (!current)
      return toast("Selecione ou crie uma conversa primeiro.");
    const text = input.value.trim();
    if (!text) return;

    const u = document.createElement("div");
    u.className = "bubble user";
    u.textContent = text;
    msgs.appendChild(u);
    msgs.scrollTop = msgs.scrollHeight;
    maybeShowChart(text);

    input.value = "";
    setComposerEnabled(false);
    setActionButtonsEnabled(false);
    setLoading(true);
    sendBtn.disabled = true;
    input.disabled = true;

    try {
      const res = await api("/chat/send", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          conversation_id: current.id,
          message: text,
        }),
      });

      const a = document.createElement("div");
      a.className = "bubble assistant";
      a.textContent = res.reply || "(sem resposta)";
      msgs.appendChild(a);
      msgs.scrollTop = msgs.scrollHeight;
      maybeShowChart(res.reply || "");
    } catch (err) {
      const a = document.createElement("div");
      a.className = "bubble assistant";
      a.textContent = "Erro ao enviar: " + err.message;
      msgs.appendChild(a);
    } finally {
      setComposerEnabled(true);
      setActionButtonsEnabled(true);
      setLoading(false);
      sendBtn.disabled = false;
      input.disabled = false;
      input.focus();
    }
  });

loadConversations();
window.addEventListener("focus", () => current && loadMessages());
