import React, { useState } from 'react';
import type { CredentialsPayload } from '../types/shield';

interface ConfigModalProps {
  isOpen: boolean;
  onClose: () => void;
  onSave: (payload: CredentialsPayload) => Promise<void>;
}

interface SecretFieldProps {
  id: string;
  label: string;
  placeholder: string;
  value: string;
  onChange: (val: string) => void;
  children?: React.ReactNode;
}

const EyeIcon = () => (
  <svg
    width="16"
    height="16"
    viewBox="0 0 24 24"
    fill="none"
    stroke="currentColor"
    strokeWidth="2"
    strokeLinecap="round"
    strokeLinejoin="round"
  >
    <path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z" />
    <circle cx="12" cy="12" r="3" />
  </svg>
);

const EyeOffIcon = () => (
  <svg
    width="16"
    height="16"
    viewBox="0 0 24 24"
    fill="none"
    stroke="currentColor"
    strokeWidth="2"
    strokeLinecap="round"
    strokeLinejoin="round"
  >
    <path d="M17.94 17.94A10.07 10.07 0 0 1 12 20c-7 0-11-8-11-8a18.45 18.45 0 0 1 5.06-5.94M9.9 4.24A9.12 9.12 0 0 1 12 4c7 0 11 8 11 8a18.5 18.5 0 0 1-2.16 3.19m-6.72-1.07a3 3 0 1 1-4.24-4.24" />
    <line x1="1" y1="1" x2="23" y2="23" />
  </svg>
);

const SecretField: React.FC<SecretFieldProps> = ({
  id,
  label,
  placeholder,
  value,
  onChange,
  children,
}) => {
  const [visible, setVisible] = useState(false);

  return (
    <div style={{ marginBottom: '14px' }}>
      <label style={{ fontSize: '11px', color: '#cbd5e1', fontWeight: 600 }}>{label}</label>
      <div style={{ position: 'relative', marginTop: '6px' }}>
        <input
          id={id}
          type={visible ? 'text' : 'password'}
          placeholder={placeholder}
          value={value}
          onChange={(e) => onChange(e.target.value)}
          style={{
            width: '100%',
            padding: '9px 36px 9px 9px',
            background: '#070b14',
            border: '1px solid #334155',
            color: 'white',
            borderRadius: '6px',
            fontSize: '12px',
          }}
        />
        <button
          type="button"
          onClick={() => setVisible((v) => !v)}
          title={visible ? 'Ocultar credencial' : 'Mostrar credencial'}
          style={{
            position: 'absolute',
            right: '6px',
            top: '50%',
            transform: 'translateY(-50%)',
            background: 'transparent',
            border: 'none',
            color: '#94a3b8',
            cursor: 'pointer',
            padding: '4px',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
          }}
        >
          {visible ? <EyeOffIcon /> : <EyeIcon />}
        </button>
      </div>
      {children}
    </div>
  );
};

export const ConfigModal: React.FC<ConfigModalProps> = ({ isOpen, onClose, onSave }) => {
  const [googleApiKey, setGoogleApiKey] = useState('');
  const [paypalClientId, setPaypalClientId] = useState('');
  const [paypalClientSecret, setPaypalClientSecret] = useState('');
  const [channel3ApiKey, setChannel3ApiKey] = useState('');
  const [renderApiKey, setRenderApiKey] = useState('');
  const [saving, setSaving] = useState(false);

  if (!isOpen) return null;

  const handleSave = async () => {
    setSaving(true);
    try {
      await onSave({
        google_api_key: googleApiKey,
        paypal_client_id: paypalClientId,
        paypal_client_secret: paypalClientSecret,
        channel3_api_key: channel3ApiKey,
        render_api_key: renderApiKey,
      });
      setGoogleApiKey('');
      setPaypalClientSecret('');
      setChannel3ApiKey('');
      setRenderApiKey('');
      onClose();
    } finally {
      setSaving(false);
    }
  };

  return (
    <div
      id="config-modal"
      style={{
        display: 'flex',
        position: 'fixed',
        inset: 0,
        background: 'rgba(0,0,0,0.75)',
        zIndex: 999,
        alignItems: 'center',
        justifyContent: 'center',
      }}
    >
      <div
        style={{
          background: '#0f172a',
          border: '1px solid #334155',
          borderRadius: '12px',
          width: '460px',
          padding: '24px',
          boxShadow: '0 20px 50px rgba(0,0,0,0.6)',
        }}
      >
        <h3 style={{ margin: '0 0 6px 0', fontSize: '16px' }}>
          🔐 Configurar Credenciales en Caliente (BYOK)
        </h3>
        <p style={{ margin: '0 0 16px 0', fontSize: '12px', color: '#94a3b8', lineHeight: 1.4 }}>
          Las llaves se inyectan exclusivamente en la memoria del <b>Shield Control Plane</b>. El
          LLM nunca tiene acceso de lectura a tus secretos de PayPal.
        </p>

        <SecretField
          id="cfg-gemini"
          label="GOOGLE_API_KEY (Gemini / ADK)"
          placeholder="AIzaSy... (Dejar vacío para conservar actual)"
          value={googleApiKey}
          onChange={setGoogleApiKey}
        >
          <a
            href="https://aistudio.google.com/app/apikey"
            target="_blank"
            rel="noopener noreferrer"
            style={{
              display: 'inline-block',
              marginTop: '4px',
              fontSize: '11px',
              color: '#38bdf8',
              textDecoration: 'none',
            }}
          >
            🔗 Obtener API Key en Google AI Studio (aistudio.google.com) ↗
          </a>
        </SecretField>

        <SecretField
          id="cfg-pp-id"
          label="PAYPAL_CLIENT_ID (Sandbox)"
          placeholder="Client ID de developer.paypal.com"
          value={paypalClientId}
          onChange={setPaypalClientId}
        >
          <a
            href="https://developer.paypal.com/dashboard/applications/sandbox"
            target="_blank"
            rel="noopener noreferrer"
            style={{
              display: 'inline-block',
              marginTop: '4px',
              fontSize: '11px',
              color: '#38bdf8',
              textDecoration: 'none',
            }}
          >
            🔗 Obtener Client ID en PayPal Developer Dashboard ↗
          </a>
        </SecretField>

        <SecretField
          id="cfg-pp-secret"
          label="PAYPAL_CLIENT_SECRET (Sandbox)"
          placeholder="Client Secret de PayPal Sandbox"
          value={paypalClientSecret}
          onChange={setPaypalClientSecret}
        >
          <div
            style={{
              display: 'flex',
              justifyContent: 'space-between',
              alignItems: 'center',
              marginTop: '4px',
            }}
          >
            <a
              href="https://developer.paypal.com/dashboard/applications/sandbox"
              target="_blank"
              rel="noopener noreferrer"
              style={{ fontSize: '11px', color: '#38bdf8', textDecoration: 'none' }}
            >
              🔗 Obtener Client Secret ↗
            </a>
            <a
              href="https://developer.paypal.com/dashboard/api-calls/sandbox"
              target="_blank"
              rel="noopener noreferrer"
              style={{ fontSize: '11px', color: '#34d399', textDecoration: 'none' }}
            >
              📡 Ver Logs de API Calls (Sandbox) ↗
            </a>
          </div>
        </SecretField>

        <SecretField
          id="cfg-c3-key"
          label="CHANNEL3_API_KEY (Product Graph)"
          placeholder="c3_live_... (Dejar vacío para conservar actual)"
          value={channel3ApiKey}
          onChange={setChannel3ApiKey}
        >
          <a
            href="https://trychannel3.com/dashboard/api"
            target="_blank"
            rel="noopener noreferrer"
            style={{
              display: 'inline-block',
              marginTop: '4px',
              fontSize: '11px',
              color: '#38bdf8',
              textDecoration: 'none',
            }}
          >
            🔗 Obtener API Key en Channel3 (trychannel3.com/dashboard/api) ↗
          </a>
        </SecretField>

        <SecretField
          id="cfg-render-key"
          label="RENDER_API_KEY (Render Workflows Orchestration)"
          placeholder="rnd_... (Opcional - Activa Render Workflows remoto)"
          value={renderApiKey}
          onChange={setRenderApiKey}
        >
          <a
            href="https://dashboard.render.com/u/settings#api-keys"
            target="_blank"
            rel="noopener noreferrer"
            style={{
              display: 'inline-block',
              marginTop: '4px',
              fontSize: '11px',
              color: '#38bdf8',
              textDecoration: 'none',
            }}
          >
            🔗 Obtener API Key en Render Dashboard ↗
          </a>
        </SecretField>

        <div style={{ display: 'flex', justifyContent: 'flex-end', gap: '8px', marginTop: '18px' }}>
          <button
            type="button"
            onClick={onClose}
            style={{
              background: 'transparent',
              color: '#94a3b8',
              border: '1px solid #334155',
              padding: '8px 14px',
              borderRadius: '6px',
              cursor: 'pointer',
              fontSize: '12px',
            }}
          >
            Cancelar
          </button>
          <button
            type="button"
            disabled={saving}
            onClick={() => void handleSave()}
            style={{
              background: '#38bdf8',
              color: '#090d16',
              border: 'none',
              padding: '8px 16px',
              borderRadius: '6px',
              fontWeight: 700,
              cursor: 'pointer',
              fontSize: '12px',
            }}
          >
            {saving ? 'Guardando...' : 'Guardar y Activar'}
          </button>
        </div>
      </div>
    </div>
  );
};
