import {useEffect, useRef, useState, type FormEvent, type PointerEvent, type ReactNode} from 'react';
import {Bot, Send, X} from 'lucide-react';
import './assistant.css';

type SavedCase = {id: string; case_ref: string; seed: string};
type Health = {ai?: {enabled: boolean; model: string}};
type Message = {role: 'user' | 'model'; content: string};
type AssistantStatus = 'checking' | 'enabled' | 'missing' | 'outdated' | 'unavailable';
type AssistantSize = {width: number; height: number};
type ResizeStart = AssistantSize & {x: number; y: number};

function renderAssistantContent(content: string) {
  const lines = content.split('\n');
  const elements: ReactNode[] = [];
  let index = 0;
  let key = 0;

  function renderInline(text: string): ReactNode[] {
    const parts = text.split(/(\*\*[^*]+\*\*|`[^`]+`|\*[^*]+\*)/g);
    return parts.map((part, partIndex) => {
      if (part.startsWith('**') && part.endsWith('**')) {
        return <strong key={partIndex}>{part.slice(2, -2)}</strong>;
      }
      if (part.startsWith('`') && part.endsWith('`')) {
        return <code key={partIndex}>{part.slice(1, -1)}</code>;
      }
      if (part.startsWith('*') && part.endsWith('*')) {
        return <em key={partIndex}>{part.slice(1, -1)}</em>;
      }
      return part;
    });
  }

  while (index < lines.length) {
    const line = lines[index].trim();
    if (!line) {
      index += 1;
      continue;
    }

    const heading = line.match(/^#{1,3}\s+(.+)$/);
    if (heading) {
      elements.push(<h3 key={key++}>{renderInline(heading[1])}</h3>);
      index += 1;
      continue;
    }

    if (line.startsWith('|')) {
      const rows: string[][] = [];
      while (index < lines.length && lines[index].trim().startsWith('|')) {
        const cells = lines[index].trim().replace(/^\||\|$/g, '').split('|').map(cell => cell.trim());
        if (!cells.every(cell => /^:?-{3,}:?$/.test(cell))) rows.push(cells);
        index += 1;
      }
      if (rows.length) {
        const [header, ...body] = rows;
        elements.push(<table key={key++}>
          <thead><tr>{header.map((cell, cellIndex) => <th key={cellIndex}>{renderInline(cell)}</th>)}</tr></thead>
          <tbody>{body.map((row, rowIndex) => <tr key={rowIndex}>
            {header.map((_, cellIndex) => <td key={cellIndex}>{renderInline(row[cellIndex] || '')}</td>)}
          </tr>)}</tbody>
        </table>);
      }
      continue;
    }

    if (/^[-*]\s+/.test(line)) {
      const items: ReactNode[] = [];
      while (index < lines.length && /^[-*]\s+/.test(lines[index].trim())) {
        items.push(<li key={items.length}>{renderInline(lines[index].trim().replace(/^[-*]\s+/, ''))}</li>);
        index += 1;
      }
      elements.push(<ul key={key++}>{items}</ul>);
      continue;
    }

    if (/^\d+[.)]\s+/.test(line)) {
      const items: ReactNode[] = [];
      while (index < lines.length && /^\d+[.)]\s+/.test(lines[index].trim())) {
        items.push(<li key={items.length}>{renderInline(lines[index].trim().replace(/^\d+[.)]\s+/, ''))}</li>);
        index += 1;
      }
      elements.push(<ol key={key++}>{items}</ol>);
      continue;
    }

    elements.push(<p key={key++}>{renderInline(line)}</p>);
    index += 1;
  }

  return elements;
}

const API_BASE_URL = (import.meta.env.VITE_API_BASE_URL || '').replace(/\/+$/, '');

async function api<T>(url: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE_URL}${url}`, init);

  if (!response.ok) {
    let message = 'The request could not be completed.';

    try {
      const body = await response.json();
      message = body.detail || message;
    } catch {
      // Response may not contain JSON.
    }

    throw new Error(message);
  }

  return response.json();
}

export function InvestigationAssistant() {
  const [open, setOpen] = useState(false);
  const [panelSize, setPanelSize] = useState<AssistantSize | null>(null);
  const resizeStart = useRef<ResizeStart | null>(null);
  const [cases, setCases] = useState<SavedCase[]>([]);
  const [caseId, setCaseId] = useState('');
  const [model, setModel] = useState('');
  const [assistantStatus, setAssistantStatus] = useState<AssistantStatus>('checking');
  const [messages, setMessages] = useState<Message[]>([]);
  const [question, setQuestion] = useState('');
  const [loading, setLoading] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');

  useEffect(() => {
    if (!open) return;
    let active = true;
    setLoading(true);
    setError('');
    const refreshStatus = async () => {
      try {
        const health = await api<Health>('/api/health');
        if (!active) return;
        if (!health.ai || typeof health.ai.enabled !== 'boolean') {
          setAssistantStatus('outdated');
          return;
        }
        setAssistantStatus(health.ai.enabled ? 'enabled' : 'missing');
        setModel(health.ai.model);
      } catch {
        if (active) setAssistantStatus('unavailable');
      }
    };
    const initialize = async () => {
      try {
        const saved = await api<SavedCase[]>('/api/cases?limit=200');
        if (!active) return;
        setCases(saved);
        setCaseId(current => current || saved[0]?.id || '');
      } catch (reason) {
        if (active) setError(reason instanceof Error ? reason.message : 'Could not load saved investigations.');
      } finally {
        if (active) setLoading(false);
      }
      await refreshStatus();
    };
    void initialize();
    const interval = window.setInterval(() => { void refreshStatus(); }, 5000);
    window.addEventListener('focus', refreshStatus);
    return () => {
      active = false;
      window.clearInterval(interval);
      window.removeEventListener('focus', refreshStatus);
    };
  }, [open]);

  function selectCase(value: string) {
    setCaseId(value);
    setMessages([]);
    setError('');
  }

  async function submit(event: FormEvent) {
    event.preventDefault();
    const text = question.trim();
    if (!caseId || assistantStatus !== 'enabled' || !text || busy) return;

    const nextMessages: Message[] = [...messages, {role: 'user', content: text}];
    setBusy(true);
    setError('');
    try {
      const response = await api<{answer: string}>(
        `/api/cases/${encodeURIComponent(caseId)}/assistant`,
        {
          method: 'POST',
          headers: {'Content-Type': 'application/json'},
          body: JSON.stringify({messages: nextMessages}),
        },
      );
      setMessages([...nextMessages, {role: 'model', content: response.answer}]);
      setQuestion('');
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'The assistant request failed.');
    } finally {
      setBusy(false);
    }
  }

  function startResize(event: PointerEvent<HTMLButtonElement>) {
    const panel = event.currentTarget.parentElement;
    if (!panel) return;
    const bounds = panel.getBoundingClientRect();
    resizeStart.current = {width: bounds.width, height: bounds.height, x: event.clientX, y: event.clientY};
    event.currentTarget.setPointerCapture(event.pointerId);
    event.preventDefault();
  }

  function resizePanel(event: PointerEvent<HTMLButtonElement>) {
    if (!resizeStart.current) return;
    const minimumWidth = Math.min(320, window.innerWidth - 32);
    const minimumHeight = Math.min(360, window.innerHeight - 100);
    const maximumWidth = window.innerWidth - 32;
    const maximumHeight = window.innerHeight - 100;
    const width = Math.min(maximumWidth, Math.max(minimumWidth, resizeStart.current.width - (event.clientX - resizeStart.current.x)));
    const height = Math.min(maximumHeight, Math.max(minimumHeight, resizeStart.current.height - (event.clientY - resizeStart.current.y)));
    setPanelSize({width, height});
  }

  function stopResize(event: PointerEvent<HTMLButtonElement>) {
    resizeStart.current = null;
    if (event.currentTarget.hasPointerCapture(event.pointerId)) event.currentTarget.releasePointerCapture(event.pointerId);
  }

  return <div className="assistant-widget">
    {open && <section className="assistant-panel" style={panelSize || undefined} role="dialog" aria-modal="false" aria-labelledby="assistant-title">
      <button className="assistant-resize-handle" type="button" aria-label="Resize assistant panel" title="Resize assistant panel"
        onPointerDown={startResize} onPointerMove={resizePanel} onPointerUp={stopResize} onPointerCancel={stopResize}/>
      <header className="assistant-header">
        <div><Bot size={19}/><div><h2 id="assistant-title">AI Investigation Assistant</h2><small>{model || 'Google Gemini API'}</small></div></div>
        <button type="button" aria-label="Close assistant" onClick={() => setOpen(false)}><X size={18}/></button>
      </header>
      <div className="assistant-privacy">
        Sending a message shares the selected case's transaction summary with Google Gemini API. Do not send sensitive personal data.
      </div>
      <label className="assistant-case">Investigation
        <select value={caseId} onChange={event => selectCase(event.target.value)} disabled={loading || cases.length === 0}>
          {cases.length === 0 && <option value="">No saved cases</option>}
          {cases.map(item => <option value={item.id} key={item.id}>{item.case_ref} · {item.seed.slice(0, 12)}…</option>)}
        </select>
      </label>
      <div className="assistant-messages" aria-live="polite">
        {messages.length === 0 && <p className="assistant-empty">Ask about observed flows, candidate attribution, evidence gaps, or verification steps.</p>}
        {messages.map((message, index) => <div className={'assistant-message '+message.role} key={index}>
          <strong>{message.role === 'user' ? 'You' : 'Assistant'}</strong>
          {message.role === 'model'
            ? <div className="assistant-content">{renderAssistantContent(message.content)}</div>
            : <p>{message.content}</p>}
        </div>)}
        {busy && <p className="assistant-working">Reviewing the selected case…</p>}
      </div>
      {error && <p className="assistant-error" role="alert">{error}</p>}
      {assistantStatus === 'checking' && !loading && <p className="assistant-config">Checking AI assistant configuration…</p>}
      {assistantStatus === 'outdated' && <p className="assistant-config">The backend is outdated. Stop the Python server and restart it so it loads the AI assistant API.</p>}
      {assistantStatus === 'missing' && <p className="assistant-config">Set GEMINI_API_KEY in backend/.env or the project-root .env, then restart the backend to enable AI.</p>}
      {assistantStatus === 'unavailable' && <p className="assistant-config">Could not check AI status. Confirm the backend is running; checking again automatically.</p>}
      <form className="assistant-form" onSubmit={submit}>
        <textarea value={question} onChange={event => setQuestion(event.target.value)} maxLength={2000} rows={2}
          placeholder={assistantStatus === 'enabled' ? 'Ask about this investigation…' : 'Assistant is not ready'}
          aria-label="Message the investigation assistant" disabled={assistantStatus !== 'enabled' || !caseId || busy}/>
        <button type="submit" aria-label="Send message" disabled={assistantStatus !== 'enabled' || !caseId || !question.trim() || busy}><Send size={17}/></button>
      </form>
    </section>}
    <button className="assistant-launcher" type="button" onClick={() => setOpen(value => !value)} aria-expanded={open}>
      {open ? <X size={18}/> : <Bot size={19}/>}
      <span>{open ? 'Close assistant' : 'AI Assistant'}</span>
    </button>
  </div>;
}
