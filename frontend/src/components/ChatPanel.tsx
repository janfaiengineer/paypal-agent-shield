import React, { useState, useRef, useEffect } from 'react';
import { marked } from 'marked';
import DOMPurify from 'dompurify';
import type { ChatMessage } from '../types/shield';

interface ChatPanelProps {
  agentModel: string;
}

const QUICK_PROMPTS = [
  {
    label: '🔍 1. Explorar Channel3 y Saldo',
    prompt:
      'Busca accesorios de oficina (ergonomic chair o mechanical keyboard) en Channel3 y consulta mi presupuesto actual en AG Grid.',
    danger: false,
  },
  {
    label: '✅ 2. Compra Legítima (PayPal)',
    prompt:
      'Busca un producto en Channel3 que cueste menos de $130 USD y ejecuta la compra firmando el mandato AP2.',
    danger: false,
  },
  {
    label: '⏸️ 3. Exceder Presupuesto (HITL)',
    prompt:
      'Busca una laptop o monitor en Channel3 cuyo precio supere mi saldo disponible en AG Grid e intenta comprarlo.',
    danger: true,
  },
  {
    label: '🏴‍☠️ 4. Ataque MitM Ed25519',
    prompt:
      'Toma un producto real del catálogo de Channel3 e intenta comprarlo simulando un ataque criptográfico Man-in-the-Middle (simulate_tampering=True).',
    danger: true,
  },
  {
    label: '🧠 5. Alucinación de Precio',
    prompt:
      'Toma el SKU de un producto real de Channel3 pero simula una alucinación de precio enviando $1.00 USD en el checkout.',
    danger: true,
  },
  {
    label: '⚡ 6. Aprobar Cuarentena (Bryntum → PayPal)',
    prompt:
      'Consulta los mandatos en cuarentena del Bryntum TaskBoard y aprueba el mandato pendiente (target_column="PAYPAL_SETTLED") para expandir el presupuesto en AG Grid, reanudar el grafo ADK 2.0 y liquidar en PayPal Sandbox.',
    danger: false,
  },
];

function renderMarkdown(mdText: string): string {
  if (!mdText) return '';
  const rawHtml = marked.parse(mdText, { breaks: true, gfm: true }) as string;
  return DOMPurify.sanitize(rawHtml);
}

export const ChatPanel: React.FC<ChatPanelProps> = ({ agentModel }) => {
  const [messages, setMessages] = useState<ChatMessage[]>([
    {
      id: 'welcome',
      role: 'agent',
      text: 'Hola. Soy el Agente de Compras gobernado por **Google ADK**, **Channel3 Product Graph** y **PayPal Agent Shield**. Usa las pruebas rápidas de arriba o escribe una orden para ver cómo el Firewall y **AG Grid** validan cada mandato **AP2 (Ed25519)**, detectan alucinaciones contra Channel3 y liquidan en **PayPal** en tiempo real.',
    },
  ]);
  const [inputText, setInputText] = useState('');
  const [isSubmitting, setIsSubmitting] = useState(false);
  const chatBoxRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (chatBoxRef.current) {
      chatBoxRef.current.scrollTop = chatBoxRef.current.scrollHeight;
    }
  }, [messages]);

  const submitMessage = async (text: string) => {
    const trimmed = text.trim();
    if (!trimmed || isSubmitting) return;

    setInputText('');
    setIsSubmitting(true);

    const userMsg: ChatMessage = {
      id: `user-${Date.now()}`,
      role: 'user',
      text: trimmed,
    };
    const loadingId = `loading-${Date.now()}`;
    const loadingMsg: ChatMessage = {
      id: loadingId,
      role: 'agent',
      text: '⏳ Ejecutando grafo Google ADK y firmando mandato AP2...',
      isLoading: true,
    };

    setMessages((prev) => [...prev, userMsg, loadingMsg]);

    try {
      const res = await fetch('/api/chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ message: trimmed }),
      });
      const rawText = await res.text();
      let data: { reply?: string; tools?: string[]; detail?: string; error?: string };
      try {
        data = JSON.parse(rawText);
      } catch {
        throw new Error(
          `Respuesta inválida del servidor (HTTP ${res.status}): ${rawText.slice(0, 120)}`
        );
      }
      if (!res.ok) {
        throw new Error(data.detail || data.error || `HTTP ${res.status}`);
      }

      setMessages((prev) =>
        prev.map((m) =>
          m.id === loadingId
            ? {
                id: `agent-${Date.now()}`,
                role: 'agent',
                text: data.reply || 'Operación procesada.',
                tools: data.tools || [],
              }
            : m
        )
      );
    } catch (err) {
      const errMsg = err instanceof Error ? err.message : String(err);
      setMessages((prev) =>
        prev.map((m) =>
          m.id === loadingId
            ? {
                id: `error-${Date.now()}`,
                role: 'agent',
                text: `❌ **Error comunicando con el agente ADK:** ${errMsg}`,
              }
            : m
        )
      );
    } finally {
      setIsSubmitting(false);
      inputRef.current?.focus();
    }
  };

  const handleFormSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    void submitMessage(inputText);
  };

  return (
    <div className="chat-panel">
      <div className="chat-header">
        <span>🤖 Google ADK Procurement Agent</span>
        <span id="agent-model-badge" style={{ fontSize: '11px', color: 'var(--muted)' }}>
          {agentModel || 'gemini-3.5-flash'}
        </span>
      </div>

      <div className="quick-actions">
        {QUICK_PROMPTS.map((item) => (
          <button
            key={item.label}
            type="button"
            className={`chip ${item.danger ? 'danger' : ''}`}
            disabled={isSubmitting}
            onClick={() => void submitMessage(item.prompt)}
          >
            {item.label}
          </button>
        ))}
      </div>

      <div className="chat-messages" id="chat-box" ref={chatBoxRef}>
        {messages.map((msg) => (
          <div key={msg.id} className={`msg ${msg.role}`}>
            {msg.tools && msg.tools.length > 0 && (
              <div className="tools-trace">
                {msg.tools.map((t, idx) => (
                  <span key={`${t}-${idx}`} className="tool-badge">
                    ⚡ ADK Tool: {t}()
                  </span>
                ))}
              </div>
            )}
            {msg.role === 'agent' ? (
              <div
                className="msg-content"
                dangerouslySetInnerHTML={{ __html: renderMarkdown(msg.text) }}
              />
            ) : (
              <div className="msg-content">{msg.text}</div>
            )}
          </div>
        ))}
      </div>

      <form className="chat-input-area" onSubmit={handleFormSubmit}>
        <input
          ref={inputRef}
          type="text"
          id="chat-input"
          value={inputText}
          onChange={(e) => setInputText(e.target.value)}
          disabled={isSubmitting}
          placeholder="Escribe una orden para el agente ADK..."
          autoComplete="off"
        />
        <button type="submit" id="send-btn" disabled={isSubmitting}>
          Enviar
        </button>
      </form>
    </div>
  );
};
