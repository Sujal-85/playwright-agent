import React, { useState, useRef, useEffect, useCallback } from 'react';
import {
  Terminal, Play, Square, Globe, ShieldAlert,
  AlertTriangle, CheckCircle2, Info, ExternalLink, X,
  Download, Loader2, RefreshCw
} from 'lucide-react';
import './App.css';

const BACKEND_URL = process.env.REACT_APP_BACKEND_URL;
const API = `${BACKEND_URL}/api`;
const WS_BASE = BACKEND_URL.replace('https://', 'wss://').replace('http://', 'ws://');

const getPathname = (url) => {
  try { return new URL(url).pathname || '/'; } catch { return url; }
};

const formatElapsed = (s) => {
  const m = Math.floor(s / 60).toString().padStart(2, '0');
  const sec = (s % 60).toString().padStart(2, '0');
  return `${m}:${sec}`;
};

const StatusBadge = ({ status }) => {
  if (!status && status !== 0) return <span className="badge badge-neutral">---</span>;
  const cls = status >= 400 ? 'badge-error' : status >= 300 ? 'badge-warn' : status === 0 ? 'badge-neutral' : 'badge-ok';
  return <span className={`badge ${cls}`}>{status || 'ERR'}</span>;
};

const LogIcon = ({ type }) => {
  const size = 11;
  const sw = 1.5;
  switch (type) {
    case 'success': return <CheckCircle2 size={size} strokeWidth={sw} className="text-[#3fb950] shrink-0 mt-0.5" />;
    case 'error': return <ShieldAlert size={size} strokeWidth={sw} className="text-[#f85149] shrink-0 mt-0.5" />;
    case 'warning': return <AlertTriangle size={size} strokeWidth={sw} className="text-[#d29922] shrink-0 mt-0.5" />;
    default: return <Info size={size} strokeWidth={sw} className="text-[#58a6ff] shrink-0 mt-0.5" />;
  }
};

export default function App() {
  const [url, setUrl] = useState('https://example.com');
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [maxPages, setMaxPages] = useState(20);
  const [maxDepth, setMaxDepth] = useState(2);

  const [sessionId, setSessionId] = useState(null);
  const [isRunning, setIsRunning] = useState(false);
  const [crawlStatus, setCrawlStatus] = useState(null);
  const [logEntries, setLogEntries] = useState([]);
  const [pages, setPages] = useState([]);
  const [selectedPage, setSelectedPage] = useState(null);
  const [elapsed, setElapsed] = useState(0);
  const [wsConnected, setWsConnected] = useState(false);

  const wsRef = useRef(null);
  const logEndRef = useRef(null);
  const timerRef = useRef(null);
  const startRef = useRef(null);

  const stats = {
    total: pages.length,
    errors: pages.filter(p => !p.status || p.status >= 400).length,
    authRequired: pages.filter(p => p.requires_auth).length,
  };

  useEffect(() => {
    logEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [logEntries]);

  useEffect(() => {
    if (isRunning) {
      startRef.current = Date.now() - elapsed * 1000;
      timerRef.current = setInterval(() => {
        setElapsed(Math.floor((Date.now() - startRef.current) / 1000));
      }, 1000);
    } else {
      clearInterval(timerRef.current);
    }
    return () => clearInterval(timerRef.current);
    // eslint-disable-next-line
  }, [isRunning]);

  const addLog = useCallback((message, type = 'info') => {
    const ts = new Date().toLocaleTimeString('en-US', { hour12: false });
    setLogEntries(prev => [...prev.slice(-500), { id: `${Date.now()}-${Math.random()}`, message, type, ts }]);
  }, []);

  const handleWsMessage = useCallback((raw) => {
    try {
      const { event: evtType, data } = JSON.parse(raw.data);
      switch (evtType) {
        case 'crawl_started':
          addLog(`Crawl started → ${data.url} (max ${data.max_pages} pages, depth ${data.max_depth})`, 'info');
          break;
        case 'page_visited':
          setPages(prev => [...prev, data]);
          addLog(`[${data.status}] ${data.url}`, data.status >= 400 ? 'error' : 'success');
          break;
        case 'page_error':
          setPages(prev => [...prev, { ...data, status: 0, page_type: 'error' }]);
          addLog(`ERR ${data.url}: ${(data.error || '').substring(0, 80)}`, 'error');
          break;
        case 'login_detected':
          addLog(`Login form detected at ${data.url}${data.reason ? ` — ${data.reason}` : ''}`, 'warning');
          break;
        case 'login_success':
          addLog(`Logged in successfully at ${data.url}`, 'success');
          break;
        case 'login_failed':
          addLog(`Login failed at ${data.url}: ${data.reason || ''}`, 'error');
          break;
        case 'crawl_complete':
          setIsRunning(false);
          setCrawlStatus('completed');
          addLog(`Crawl complete — ${data.total_pages} pages in ${data.elapsed_seconds}s`, 'success');
          break;
        case 'crawl_error':
          setIsRunning(false);
          setCrawlStatus('error');
          addLog(`Crawl error: ${data.error}`, 'error');
          break;
        case 'crawl_stopped':
          setIsRunning(false);
          setCrawlStatus('stopped');
          addLog('Crawl stopped by user', 'warning');
          break;
        default:
          if (data && data.message) addLog(data.message, 'info');
      }
    } catch (e) {
      // ignore parse errors
    }
  }, [addLog]);

  const connectWs = useCallback((sid) => {
    if (wsRef.current) { try { wsRef.current.close(); } catch (e) {} }
    const ws = new WebSocket(`${WS_BASE}/api/ws/${sid}`);
    wsRef.current = ws;
    ws.onopen = () => { setWsConnected(true); addLog('WebSocket connected', 'success'); };
    ws.onmessage = handleWsMessage;
    ws.onerror = () => addLog('WebSocket error — updates may be delayed', 'warning');
    ws.onclose = () => {
      setWsConnected(false);
      addLog('WebSocket closed', 'info');
      setIsRunning(prev => {
        if (prev) setCrawlStatus('stopped');
        return false;
      });
    };
  }, [handleWsMessage, addLog]);

  const startCrawl = async () => {
    if (!url.trim()) return;
    setLogEntries([]);
    setPages([]);
    setElapsed(0);
    setCrawlStatus('running');
    setIsRunning(true);
    addLog(`Initiating crawl of ${url}…`, 'info');

    try {
      const res = await fetch(`${API}/crawl/start`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          url: url.trim(),
          username: username || null,
          password: password || null,
          max_pages: maxPages,
          max_depth: maxDepth,
        }),
      });
      const data = await res.json();
      if (!data.session_id) throw new Error(data.detail || 'No session_id returned');
      setSessionId(data.session_id);
      addLog(`Session: ${data.session_id}`, 'info');
      connectWs(data.session_id);
    } catch (e) {
      addLog(`Failed to start crawl: ${e.message}`, 'error');
      setIsRunning(false);
      setCrawlStatus('error');
    }
  };

  const stopCrawl = async () => {
    if (!sessionId) return;
    try {
      await fetch(`${API}/crawl/${sessionId}/stop`, { method: 'POST' });
    } catch (e) {
      addLog(`Stop request failed: ${e.message}`, 'error');
    }
    if (wsRef.current) { try { wsRef.current.close(); } catch (e) {} }
    setIsRunning(false);
    setCrawlStatus('stopped');
  };

  const downloadReport = async () => {
    if (!sessionId) return;
    try {
      const res = await fetch(`${API}/crawl/${sessionId}/report`);
      const report = await res.json();
      const blob = new Blob([JSON.stringify(report, null, 2)], { type: 'application/json' });
      const a = document.createElement('a');
      a.href = URL.createObjectURL(blob);
      a.download = `crawl-${sessionId.substring(0, 8)}.json`;
      a.click();
    } catch (e) {
      addLog(`Download failed: ${e.message}`, 'error');
    }
  };

  const logTextColor = (type) => {
    switch (type) {
      case 'success': return 'text-[#3fb950]';
      case 'error': return 'text-[#f85149]';
      case 'warning': return 'text-[#d29922]';
      default: return 'text-[#58a6ff]';
    }
  };

  return (
    <div className="app-shell" data-testid="app-root">
      {/* Header */}
      <header className="app-header" data-testid="app-header">
        <div className="flex items-center gap-3">
          <Terminal size={20} strokeWidth={1.5} className="text-[#58a6ff]" />
          <h1 className="text-xl font-semibold tracking-tight text-[#e6edf3]">Playwright Web Agent</h1>
          <span className="text-[10px] font-mono px-2 py-0.5 rounded bg-[#161b22] border border-[#30363d] text-[#8b949e] uppercase tracking-wider">v1.0</span>
        </div>
        <div className="flex items-center gap-2">
          {wsConnected && isRunning && (
            <span className="flex items-center gap-1.5 text-xs font-mono text-[#3fb950]">
              <span className="w-1.5 h-1.5 rounded-full bg-[#3fb950] animate-pulse inline-block" />
              LIVE
            </span>
          )}
          {sessionId && (crawlStatus === 'completed' || crawlStatus === 'stopped') && (
            <button onClick={downloadReport} className="btn-secondary flex items-center gap-1.5 text-xs" data-testid="download-report-btn">
              <Download size={13} strokeWidth={1.5} /> Report
            </button>
          )}
        </div>
      </header>

      {/* Control Bar */}
      <div className="control-bar" data-testid="control-bar">
        <input
          type="url"
          placeholder="https://example.com"
          value={url}
          onChange={e => setUrl(e.target.value)}
          disabled={isRunning}
          className="input-base flex-1 min-w-[180px]"
          data-testid="url-input"
          onKeyDown={e => e.key === 'Enter' && !isRunning && startCrawl()}
        />
        <input type="text" placeholder="Username" value={username} onChange={e => setUsername(e.target.value)} disabled={isRunning} className="input-base w-32" data-testid="username-input" />
        <input type="password" placeholder="Password" value={password} onChange={e => setPassword(e.target.value)} disabled={isRunning} className="input-base w-32" data-testid="password-input" />
        <div className="flex items-center gap-1.5 shrink-0">
          <label className="text-[11px] text-[#8b949e] whitespace-nowrap">Pages:</label>
          <input type="number" value={maxPages} onChange={e => setMaxPages(Math.min(200, Math.max(1, +e.target.value || 1)))} disabled={isRunning} className="input-base w-14 text-center" data-testid="max-pages-input" />
        </div>
        <div className="flex items-center gap-1.5 shrink-0">
          <label className="text-[11px] text-[#8b949e]">Depth:</label>
          <input type="number" value={maxDepth} onChange={e => setMaxDepth(Math.min(5, Math.max(1, +e.target.value || 1)))} disabled={isRunning} className="input-base w-12 text-center" data-testid="depth-input" />
        </div>
        {!isRunning ? (
          <button onClick={startCrawl} disabled={!url.trim()} className="btn-primary flex items-center gap-2 shrink-0" data-testid="start-crawl-btn">
            <Play size={14} strokeWidth={1.5} /> Start Crawl
          </button>
        ) : (
          <button onClick={stopCrawl} className="btn-danger flex items-center gap-2 shrink-0" data-testid="stop-crawl-btn">
            <Square size={13} strokeWidth={1.5} fill="currentColor" /> Stop
          </button>
        )}
      </div>

      {/* Main Content */}
      <div className="main-grid">
        {/* Log Panel */}
        <div className="log-panel" data-testid="log-panel-container">
          <div className="panel-header">
            <Terminal size={13} strokeWidth={1.5} className="text-[#58a6ff]" />
            <span className="panel-label">Live Log</span>
            {isRunning && <Loader2 size={12} strokeWidth={1.5} className="ml-1 animate-spin text-[#58a6ff]" />}
            <span className="ml-auto text-[10px] font-mono text-[#8b949e]">{logEntries.length} entries</span>
          </div>
          <div className="log-body" data-testid="log-panel" aria-live="polite">
            {logEntries.length === 0 ? (
              <div className="empty-state">
                <Terminal size={40} strokeWidth={0.8} className="text-[#30363d] mb-3" />
                <p className="text-[#8b949e] text-xs text-center leading-5">Logs will appear here<br />when crawl starts</p>
              </div>
            ) : (
              logEntries.map(entry => (
                <div key={entry.id} className="log-line" data-testid={`log-entry-${entry.type}`}>
                  <LogIcon type={entry.type} />
                  <span className="text-[#8b949e] shrink-0">[{entry.ts}]</span>
                  <span className={logTextColor(entry.type)}>{entry.message}</span>
                </div>
              ))
            )}
            <div ref={logEndRef} />
          </div>
        </div>

        {/* Pages Panel */}
        <div className="pages-panel">
          <div className="panel-header">
            <Globe size={13} strokeWidth={1.5} className="text-[#58a6ff]" />
            <span className="panel-label">Crawled Pages</span>
            <span className="ml-auto text-[10px] font-mono text-[#8b949e]">{pages.length} pages</span>
          </div>
          <div className="pages-body" data-testid="pages-grid">
            {pages.length === 0 ? (
              <div className="empty-state">
                <Globe size={48} strokeWidth={0.8} className="text-[#30363d] mb-3" />
                <p className="text-[#8b949e] text-xs text-center leading-5">No pages crawled yet.<br />Enter a URL and click Start Crawl.</p>
              </div>
            ) : (
              <div className="pages-grid-inner">
                {pages.map((page, i) => (
                  <div key={`${page.url}-${i}`} onClick={() => setSelectedPage(page)} className="page-card" data-testid={`page-card-${i}`}>
                    <div className="card-screenshot">
                      {page.screenshot ? (
                        <img src={`data:image/png;base64,${page.screenshot}`} alt={page.title || 'Page'} className="w-full h-full object-cover" />
                      ) : (
                        <Globe size={28} strokeWidth={0.8} className="text-[#30363d]" />
                      )}
                      <div className="card-overlay"><ExternalLink size={18} strokeWidth={1.5} className="text-white" /></div>
                    </div>
                    <div className="card-footer">
                      <div className="flex items-center gap-1.5 mb-1">
                        <StatusBadge status={page.status} />
                        <span className="text-[10px] font-mono text-[#8b949e] truncate">{page.page_type || 'page'}</span>
                        {page.requires_auth && <ShieldAlert size={10} strokeWidth={1.5} className="text-[#d29922] shrink-0" />}
                      </div>
                      <p className="text-[11px] text-[#e6edf3] truncate font-mono" title={page.url}>{getPathname(page.url)}</p>
                      <p className="text-[10px] text-[#8b949e] truncate" title={page.title}>{page.title || 'Untitled'}</p>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>
      </div>

      {/* Stats Bar */}
      <footer className="stats-bar" data-testid="stats-bar">
        <div className="flex items-center gap-4">
          <span className="stat-item text-[#58a6ff]"><Globe size={11} strokeWidth={1.5} /> {stats.total} pages</span>
          <span className="stat-item text-[#f85149]"><ShieldAlert size={11} strokeWidth={1.5} /> {stats.errors} errors</span>
          <span className="stat-item text-[#d29922]"><AlertTriangle size={11} strokeWidth={1.5} /> {stats.authRequired} auth</span>
        </div>
        <div className="flex items-center gap-3">
          <span className="stat-item">
            <RefreshCw size={11} strokeWidth={1.5} className={isRunning ? 'animate-spin' : ''} />
            {crawlStatus === 'completed' && <span className="text-[#3fb950]">Complete</span>}
            {crawlStatus === 'error' && <span className="text-[#f85149]">Error</span>}
            {crawlStatus === 'stopped' && <span className="text-[#d29922]">Stopped</span>}
            {crawlStatus === 'running' && <span className="text-[#58a6ff]">Running</span>}
            {!crawlStatus && <span>Idle</span>}
          </span>
          <span className="font-mono text-[#e6edf3]">{formatElapsed(elapsed)}</span>
        </div>
      </footer>

      {/* Page Detail Modal */}
      {selectedPage && (
        <div className="modal-backdrop" onClick={() => setSelectedPage(null)} data-testid="page-modal">
          <div className="modal-box" onClick={e => e.stopPropagation()}>
            <div className="modal-header">
              <div className="flex items-center gap-2 min-w-0">
                <StatusBadge status={selectedPage.status} />
                <span className="text-sm font-mono text-[#e6edf3] truncate" title={selectedPage.url}>{selectedPage.url}</span>
              </div>
              <button onClick={() => setSelectedPage(null)} className="text-[#8b949e] hover:text-[#e6edf3] transition-colors shrink-0 ml-2" data-testid="close-modal-btn">
                <X size={17} strokeWidth={1.5} />
              </button>
            </div>
            <div className="modal-body">
              {selectedPage.screenshot && (
                <img src={`data:image/png;base64,${selectedPage.screenshot}`} alt={selectedPage.title} className="w-full rounded border border-[#30363d] mb-4" />
              )}
              <div className="grid grid-cols-2 gap-3 text-sm">
                {[
                  ['Title', selectedPage.title || '—'],
                  ['Page Type', selectedPage.page_type || '—'],
                  ['Links Found', selectedPage.links_found ?? '—'],
                  ['Depth', selectedPage.depth ?? '—'],
                  ['Risk Level', selectedPage.risk_level || '—'],
                  ['Auth Required', selectedPage.requires_auth ? 'Yes' : 'No'],
                ].map(([label, val]) => (
                  <div key={label} className="info-tile">
                    <div className="info-label">{label}</div>
                    <div className="info-val">{val}</div>
                  </div>
                ))}
              </div>
              {selectedPage.notes && (
                <div className="info-tile mt-3">
                  <div className="info-label">AI Notes</div>
                  <div className="info-val">{selectedPage.notes}</div>
                </div>
              )}
              {selectedPage.interesting_elements?.length > 0 && (
                <div className="info-tile mt-3">
                  <div className="info-label mb-2">Interesting Elements</div>
                  {selectedPage.interesting_elements.map((el, i) => (
                    <div key={i} className="text-xs font-mono text-[#e6edf3] mb-1">{el}</div>
                  ))}
                </div>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
