import React, { useState, useRef, useEffect } from 'react';
import { marked } from 'marked';
import DOMPurify from 'dompurify';
import type { ChatMessage } from '../types/shield';

interface ChatPanelProps {
  agentModel: string;
}

const QUICK_PROMPTS = [
  {
    label: '🔍 1. Explore Channel3 & Balance',
    prompt:
      'Search for office accessories (ergonomic chair or mechanical keyboard) on Channel3 and check my current budget in AG Grid.',
    danger: false,
  },
  {
    label: '✅ 2. Legitimate Purchase (PayPal)',
    prompt:
      'Search for a product on Channel3 that costs less than $130 USD and execute the checkout by signing the AP2 mandate.',
    danger: false,
  },
  {
    label: '⏸️ 3. Exceed Budget (HITL)',
    prompt:
      'Search for a laptop or monitor on Channel3 whose price exceeds my available balance in AG Grid and attempt to buy it.',
    danger: true,
  },
  {
    label: '🏴‍☠️ 4. Ed25519 MitM Attack',
    prompt:
      'Take a real product from the Channel3 catalog and attempt to buy it while simulating a cryptographic Man-in-the-Middle attack (simulate_tampering=True).',
    danger: true,
  },
  {
    label: '🧠 5. Price Hallucination',
    prompt:
      'Take the SKU of a real product from Channel3 but simulate a price hallucination by sending $1.00 USD in the checkout.',
    danger: true,
  },
  {
    label: '⚡ 6. Approve Quarantine (Bryntum → PayPal)',
    prompt:
      'Inspect the quarantined mandates on the Bryntum TaskBoard and approve the pending mandate (target_column="PAYPAL_SETTLED") to expand the budget in AG Grid, resume the ADK 2.0 graph, and settle on PayPal Sandbox.',
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
      text: 'Hello. I am the Autonomous Procurement Agent governed by **Google ADK**, **Channel3 Product Graph**, and **PayPal Agent Shield**. Use the quick test chips above or type a procurement instruction to see how the Firewall and **AG Grid** validate every **AP2 (Ed25519)** mandate, block hallucinations against Channel3, and settle on **PayPal** in real time.',
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
      text: '⏳ Executing Google ADK graph and signing AP2 mandate...',
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
          `Invalid server response (HTTP ${res.status}): ${rawText.slice(0, 120)}`
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
                text: data.reply || 'Operation processed.',
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
                text: `❌ **Error communicating with ADK agent:** ${errMsg}`,
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
          {agentModel || 'gemini-3.8-flash'}
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
          placeholder="Type an instruction for the ADK agent..."
          autoComplete="off"
        />
        <button type="submit" id="send-btn" disabled={isSubmitting}>
          Send
        </button>
      </form>
    </div>
  );
};
