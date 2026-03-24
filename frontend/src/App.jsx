import { useState, useEffect, useRef, useCallback } from "react";

const API = (import.meta.env.VITE_API_URL || "http://localhost:5001/api").replace(/\/+$/, "");
const GOOGLE_CLIENT_ID = import.meta.env.VITE_GOOGLE_CLIENT_ID || "";
const IDLE_TIMEOUT_MS = 20 * 60 * 1000;

const STATUS_COLOR = { queued:"#f59e0b", running:"#3b82f6", done:"#10b981", error:"#ef4444" };
const STATUS_LABEL = { queued:"Queued", running:"Processing…", done:"Complete", error:"Failed" };

// ─── Google Sign-In Button ─────────────────────────────────────────────────────
function GoogleSignInButton({ onLogin, onError }) {
  const containerRef = useRef(null);
  const onLoginRef   = useRef(onLogin);
  useEffect(() => { onLoginRef.current = onLogin; }, [onLogin]);

  useEffect(() => {
    if (!GOOGLE_CLIENT_ID) { onError?.("VITE_GOOGLE_CLIENT_ID is not set in frontend/.env"); return; }
    function mount() {
      if (!containerRef.current || !window.google?.accounts?.id) return;
      window.google.accounts.id.initialize({
        client_id: GOOGLE_CLIENT_ID,
        auto_select: false,
        callback: async ({ credential }) => {
          try {
            const res  = await fetch(API + "/auth/google", { method:"POST", headers:{"Content-Type":"application/json"}, body: JSON.stringify({ token: credential }) });
            const user = await res.json();
            if (res.ok) onLoginRef.current(user);
            else onError?.(user.error || "Google sign-in failed.");
          } catch { onError?.("Cannot reach backend on port 5001. Is the server running?"); }
        },
      });
      window.google.accounts.id.renderButton(containerRef.current, { theme:"filled_black", size:"large", shape:"rectangular", text:"signin_with", width:260 });
    }
    if (window.google?.accounts?.id) { mount(); }
    else if (!document.getElementById("gsi-script")) {
      const s = document.createElement("script");
      s.id = "gsi-script"; s.src = "https://accounts.google.com/gsi/client"; s.async = true;
      s.onload = mount; s.onerror = () => onError?.("Failed to load Google Sign-In script.");
      document.head.appendChild(s);
    } else {
      var existing = document.getElementById("gsi-script");
      if (window.google?.accounts?.id) mount();
      else existing.addEventListener("load", mount, { once: true });
    }
  }, []);

  if (!GOOGLE_CLIENT_ID) return (
    <p style={{ fontSize:10, color:"#f87171", lineHeight:1.6 }}>
      Add VITE_GOOGLE_CLIENT_ID to frontend/.env
    </p>
  );
  return <div ref={containerRef} />;
}

// ─── Mermaid Panel ─────────────────────────────────────────────────────────────
function MermaidPanel({ code, title }) {
  const [svg,    setSvg]    = useState("");
  const [err,    setErr]    = useState("");
  const [copied, setCopied] = useState(false);

  useEffect(function() {
    if (!code) return;
    setSvg("");
    setErr("");

    function doRender() {
      try {
        // Initialize without any error rendering options
        window.mermaid.initialize({
          startOnLoad: false,
          theme: "dark",
          securityLevel: "loose",
        });
      } catch(e) {}

      var id = "mmd" + Math.random().toString(36).slice(2);

      // Mermaid appends error divs to body — watch for them and remove
      var observer = new MutationObserver(function(mutations) {
        mutations.forEach(function(m) {
          m.addedNodes.forEach(function(node) {
            if (node.id && node.id.indexOf(id) !== -1) node.remove();
            if (node.className && String(node.className).indexOf("mermaid") !== -1) node.remove();
          });
        });
      });
      observer.observe(document.body, { childList: true });

      window.mermaid.render(id, code)
        .then(function(result) {
          observer.disconnect();
          // Reject if the SVG itself contains a Mermaid error marker
          if (result.svg && result.svg.indexOf("syntax error") !== -1) {
            setErr("The LLM produced invalid Mermaid syntax for this diagram.");
          } else {
            setSvg(result.svg);
          }
        })
        .catch(function(e) {
          observer.disconnect();
          // Remove any bomb/error element mermaid injected
          var el = document.getElementById(id);
          if (el) el.remove();
          setErr(e.message || "Mermaid render failed.");
        });
    }

    if (window.mermaid) {
      doRender();
    } else {
      var s = document.createElement("script");
      s.src = "https://cdn.jsdelivr.net/npm/mermaid@10/dist/mermaid.min.js";
      s.onload = doRender;
      document.head.appendChild(s);
    }
  }, [code]);

  function openFullscreen() {
    var w = window.open("", "_blank");
    if (w) {
      var html = "<!DOCTYPE html><html><body style='background:#0f172a;padding:20px'>" + svg + "</body></html>";
      w.document.write(html);
      w.document.close();
    }
  }

  function copyCode() {
    navigator.clipboard.writeText(code || "");
    setCopied(true);
    setTimeout(function() { setCopied(false); }, 1500);
  }

  return (
    <div style={{ flex:1, overflowY:"auto", padding:"24px", display:"flex", flexDirection:"column", gap:16 }}>
      <div style={{ display:"flex", alignItems:"center", justifyContent:"space-between" }}>
        <span style={{ fontSize:13, fontWeight:700, color:"#e2e8f0" }}>{title}</span>
        <div style={{ display:"flex", gap:8 }}>
          <button style={btnStyle} onClick={copyCode}>{copied ? "✓ Copied" : "Copy code"}</button>
          {svg && <button style={btnStyle} onClick={openFullscreen}>⛶ Full screen</button>}
        </div>
      </div>

      {err && (
        <div style={{ background:"#1c0a0a", border:"1px solid #7f1d1d", borderRadius:8, padding:16, display:"flex", flexDirection:"column", gap:10 }}>
          <p style={{ fontSize:12, color:"#f87171", fontWeight:700 }}>⚠ Diagram could not be rendered</p>
          <p style={{ fontSize:11, color:"#94a3b8", lineHeight:1.6 }}>
            The LLM generated diagram syntax that Mermaid could not parse. You can paste the raw code into{" "}
            <a href="https://mermaid.live" target="_blank" rel="noreferrer" style={{ color:"#38bdf8" }}>mermaid.live</a>{" "}
            to inspect it.
          </p>
          <pre style={{ fontSize:11, color:"#fca5a5", background:"#0b1120", padding:12, borderRadius:6, overflowX:"auto", lineHeight:1.6, margin:0 }}>{code}</pre>
        </div>
      )}

      {svg && (
        <div
          dangerouslySetInnerHTML={{ __html: svg }}
          style={{ background:"#0b1120", borderRadius:8, padding:16, border:"1px solid #1e293b", overflowX:"auto" }}
        />
      )}

      {!err && svg && (
        <details>
          <summary style={{ fontSize:11, color:"#475569", cursor:"pointer" }}>View raw Mermaid code</summary>
          <pre style={{ fontSize:11, color:"#64748b", background:"#0b1120", padding:12, borderRadius:6, marginTop:8, overflowX:"auto", lineHeight:1.6 }}>{code}</pre>
        </details>
      )}
    </div>
  );
}


var btnStyle = { background:"#1e293b", border:"1px solid #334155", borderRadius:5, padding:"4px 10px", fontSize:11, color:"#94a3b8", cursor:"pointer", fontFamily:"inherit" };

// ─── Markdown Panel ────────────────────────────────────────────────────────────
function MarkdownPanel({ content }) {
  if (!content) return null;

  function fmt(text) {
    // inline code
    text = text.replace(/`([^`]+)`/g, function(_, c) {
      return '<code style="background:#1e293b;padding:1px 5px;border-radius:3px;font-size:11px;color:#7dd3fc">' + c + '</code>';
    });
    // bold
    text = text.replace(/\*\*([^*]+)\*\*/g, '<strong style="color:#e2e8f0">$1</strong>');
    // italic
    text = text.replace(/\*([^*]+)\*/g, '<em style="color:#94a3b8">$1</em>');
    return text;
  }

  function renderMarkdown(raw) {
    var lines   = raw.split("\n");
    var out     = [];
    var i       = 0;
    while (i < lines.length) {
      var line = lines[i];
      // Fenced code block
      if (line.trimStart().startsWith("```")) {
        var codeLines = [];
        i++;
        while (i < lines.length && !lines[i].trimStart().startsWith("```")) {
          codeLines.push(lines[i].replace(/</g, "&lt;").replace(/>/g, "&gt;"));
          i++;
        }
        out.push('<pre style="background:#0b1120;padding:12px;border-radius:6px;overflow-x:auto;font-size:11px;border:1px solid #1e293b;margin:10px 0"><code>' + codeLines.join("\n") + "</code></pre>");
        i++; // skip closing ```
        continue;
      }
      // Headers
      if (line.startsWith("#### ")) { out.push('<h4 style="color:#94a3b8;font-size:11px;text-transform:uppercase;letter-spacing:.06em;margin:16px 0 6px">' + fmt(line.slice(5)) + "</h4>"); i++; continue; }
      if (line.startsWith("### "))  { out.push('<h3 style="color:#cbd5e1;font-size:13px;font-weight:700;margin:20px 0 8px">'  + fmt(line.slice(4)) + "</h3>"); i++; continue; }
      if (line.startsWith("## "))   { out.push('<h2 style="color:#e2e8f0;font-size:15px;font-weight:700;margin:24px 0 10px;padding-bottom:6px;border-bottom:1px solid #1e293b">' + fmt(line.slice(3)) + "</h2>"); i++; continue; }
      if (line.startsWith("# "))    { out.push('<h1 style="color:#f1f5f9;font-size:18px;font-weight:700;margin:0 0 16px">' + fmt(line.slice(2)) + "</h1>"); i++; continue; }
      // List items — collect consecutive
      if (/^\s*[-*] /.test(line)) {
        var items = [];
        while (i < lines.length && /^\s*[-*] /.test(lines[i])) {
          items.push('<li style="color:#94a3b8;font-size:12px;margin:3px 0;line-height:1.7">' + fmt(lines[i].replace(/^\s*[-*] /, "")) + "</li>");
          i++;
        }
        out.push('<ul style="padding-left:20px;margin:8px 0">' + items.join("") + "</ul>");
        continue;
      }
      // Blank line
      if (line.trim() === "") { out.push("<br/>"); i++; continue; }
      // Paragraph
      out.push('<p style="color:#94a3b8;font-size:12px;line-height:1.8;margin:4px 0">' + fmt(line) + "</p>");
      i++;
    }
    return out.join("\n");
  }

  return (
    <div
      style={{ flex:1, overflowY:"auto", padding:"24px" }}
      dangerouslySetInnerHTML={{ __html: renderMarkdown(content) }}
    />
  );
}

// ─── Main App ──────────────────────────────────────────────────────────────────
export default function App() {
  const [user, setUser] = useState(function() {
    try { return JSON.parse(localStorage.getItem("devdocs_user") || "null"); } catch { return null; }
  });

  const [repoUrl,      setRepoUrl]      = useState("");
  const [provider,     setProvider]     = useState("gpt");
  const [apiKey,       setApiKey]       = useState("");
  const [showKey,      setShowKey]      = useState(false);
  const [apiKeySaved,  setApiKeySaved]  = useState(false);
  const [savingKey,    setSavingKey]    = useState(false);
  const [gptModel,     setGptModel]     = useState("gpt-3.5-turbo");
  const [ollamaModel,  setOllamaModel]  = useState("codellama");

  const [jobId,     setJobId]     = useState(null);
  const [job,       setJob]       = useState(null);
  const [loading,   setLoading]   = useState(false);
  const [error,     setError]     = useState("");
  const [notice,    setNotice]    = useState("");
  const [activeTab, setActiveTab] = useState("logs");

  const [localHistory,  setLocalHistory]  = useState([]);
  const [remoteHistory, setRemoteHistory] = useState([]);
  const [deletingId,    setDeletingId]    = useState(null);
  const [confirmDelete, setConfirmDelete] = useState(null);
  const [tooltip,       setTooltip]       = useState(null);
  const [tabData,       setTabData]       = useState(null);
  const [tabLoading,    setTabLoading]    = useState(false);

  const [chatMessages,  setChatMessages]  = useState([]);
  const [chatInput,     setChatInput]     = useState("");
  const [chatLoading,   setChatLoading]   = useState(false);

  const logsRef = useRef(null);
  const chatEndRef = useRef(null);

  // ── History ─────────────────────────────────────────────────────────────────
  const fetchLocalHistory = useCallback(async function() {
    try {
      var res  = await fetch(API + "/jobs");
      var data = await res.json();
      setLocalHistory(data);
    } catch {}
  }, []);

  const fetchRemoteHistory = useCallback(async function(uid) {
    if (!uid) return;
    try {
      var res  = await fetch(API + "/user/jobs/" + uid);
      var data = await res.json();
      setRemoteHistory(Array.isArray(data) ? data : []);
    } catch {}
  }, []);

  const fetchSavedApiKey = useCallback(async function(uid) {
    if (!uid) return;
    try {
      var res  = await fetch(API + "/user/" + uid + "/apikey");
      var data = await res.json();
      if (!res.ok) {
        setError(data.error || "Could not fetch saved API key.");
        return;
      }
      if (data.api_key) {
        setApiKey(data.api_key);
        setApiKeySaved(true);
      } else {
        setApiKey("");
        setApiKeySaved(false);
      }
    } catch {
      setError("Could not fetch saved API key.");
    }
  }, []);

  // ── Auth ────────────────────────────────────────────────────────────────────
  const handleLogin = useCallback(async function(u) {
    setError("");
    setNotice("");
    setUser(u);
    localStorage.setItem("devdocs_user", JSON.stringify(u));
    await Promise.all([fetchRemoteHistory(u.user_id), fetchSavedApiKey(u.user_id)]);
  }, [fetchRemoteHistory, fetchSavedApiKey]);

  async function saveApiKey() {
    if (!user || !apiKey.trim()) return;
    setSavingKey(true);
    setError("");
    try {
      var res = await fetch(API + "/user/" + user.user_id + "/apikey", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ api_key: apiKey.trim() }),
      });
      var data = await res.json();
      if (!res.ok || !data.ok) {
        setError(data.error || "Could not save API key.");
        setApiKeySaved(false);
        return;
      }
      setApiKeySaved(true);
      setNotice("API key saved to your account.");
    } catch {
      setError("Could not save API key.");
    }
    setSavingKey(false);
  }

  const signOut = useCallback(function(reason) {
    window.google?.accounts.id.disableAutoSelect();
    setUser(null); setRemoteHistory([]); setLocalHistory([]);
    setJob(null); setJobId(null); setTabData(null);
    setApiKey(""); setApiKeySaved(false);
    localStorage.removeItem("devdocs_user");
    if (reason) setNotice(reason);
  }, []);

  const fetchTabData = useCallback(async function(id) {
    setTabLoading(true);
    setTabData(null);
    try {
      var res  = await fetch(API + "/tabs/" + id);
      var data = await res.json();
      setTabData(data);
    } catch {}
    setTabLoading(false);
  }, []);

  useEffect(function() { fetchLocalHistory(); }, [fetchLocalHistory]);
  useEffect(function() {
    if (!user) return;
    fetchRemoteHistory(user.user_id);
    fetchSavedApiKey(user.user_id);
  }, [user, fetchRemoteHistory, fetchSavedApiKey]);

  useEffect(function() {
    window.google?.accounts?.id?.disableAutoSelect();
  }, []);

  useEffect(function() {
    if (!user) return;
    var timer = null;
    var resetTimer = function() {
      if (timer) clearTimeout(timer);
      timer = setTimeout(function() {
        signOut("Signed out after inactivity.");
      }, IDLE_TIMEOUT_MS);
    };
    var events = ["mousemove", "keydown", "mousedown", "touchstart", "scroll"];
    events.forEach(function(name) { window.addEventListener(name, resetTimer, { passive: true }); });
    resetTimer();
    return function() {
      if (timer) clearTimeout(timer);
      events.forEach(function(name) { window.removeEventListener(name, resetTimer); });
    };
  }, [user, signOut]);

  // ── Delete ──────────────────────────────────────────────────────────────────
  function deleteJob(e, jobIdToDelete) {
    e.stopPropagation();
    if (!user) return;
    setConfirmDelete(jobIdToDelete);
  }

  async function confirmDeleteJob() {
    var id = confirmDelete;
    setConfirmDelete(null);
    setDeletingId(id);
    try {
      await fetch(API + "/job/" + id + "?user_id=" + user.user_id, { method: "DELETE" });
      setRemoteHistory(function(h) { return h.filter(function(j) { return j.job_id !== id; }); });
      if (jobId === id) { setJob(null); setJobId(null); setTabData(null); }
    } catch {}
    setDeletingId(null);
  }

  // ── Polling ─────────────────────────────────────────────────────────────────
  useEffect(function() {
    if (!jobId) return;
    var poll = setInterval(async function() {
      try {
        var res  = await fetch(API + "/status/" + jobId);
        var data = await res.json();
        setJob(data);
        if (data.status === "done" || data.status === "error") {
          clearInterval(poll);
          if (data.status === "done") { setActiveTab("pdf"); fetchTabData(jobId); }
          fetchLocalHistory();
          if (user) fetchRemoteHistory(user.user_id);
        }
      } catch {}
    }, 1500);
    return function() { clearInterval(poll); };
  }, [jobId, user]);

  useEffect(function() {
    if (activeTab === "logs" && logsRef.current)
      logsRef.current.scrollTop = logsRef.current.scrollHeight;
  }, [job, activeTab]);

  // ── Submit ───────────────────────────────────────────────────────────────────
  async function submit() {
    if (!repoUrl.trim())                      { setError("Enter a GitHub URL."); return; }
    if (provider === "gpt" && !apiKey.trim()) { setError("Enter your OpenAI API key."); return; }
    setError(""); setLoading(true); setJob(null); setTabData(null); setActiveTab("logs");
    try {
      var res  = await fetch(API + "/generate", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          repo_url: repoUrl.trim(), provider,
          api_key:  apiKey.trim(),
          model:    provider === "gpt" ? gptModel : ollamaModel,
          user_id:  user ? user.user_id : "",
        }),
      });
      var data = await res.json();
      if (!res.ok) { setError(data.error || "Failed to start job."); return; }
      setJobId(data.job_id);
    } catch { setError("Cannot reach backend on port 5001."); }
    finally  { setLoading(false); }
  }

  async function loadJob(id) {
    setJobId(id); setActiveTab("logs"); setTabData(null); setChatMessages([]);
    var res  = await fetch(API + "/status/" + id);
    var data = await res.json();
    setJob(data);
    if (data.status === "done") { setActiveTab("pdf"); fetchTabData(id); }
  }

  async function sendChatMessage() {
    var q = chatInput.trim();
    if (!q || !jobId || chatLoading) return;
    var userMsg = { role:"user", content:q };
    setChatMessages(function(prev) { return prev.concat([userMsg]); });
    setChatInput("");
    setChatLoading(true);
    try {
      var res = await fetch(API + "/chat/" + jobId, {
        method:"POST", headers:{"Content-Type":"application/json"},
        body: JSON.stringify({
          query: q,
          provider: provider,
          api_key: apiKey.trim(),
          model: provider === "gpt" ? gptModel : ollamaModel,
          user_id: user ? user.user_id : "",
          history: chatMessages.concat([userMsg]).slice(-10),
        }),
      });
      var data = await res.json();
      if (!res.ok) {
        setChatMessages(function(prev) { return prev.concat([{ role:"assistant", content:"Error: " + (data.error || "Chat failed.") }]); });
      } else {
        var sources = (data.sources || []).map(function(s) { return s.file + " (" + s.lines + ")"; }).join(", ");
        var reply = data.answer + (sources ? "\n\n📎 Sources: " + sources : "");
        setChatMessages(function(prev) { return prev.concat([{ role:"assistant", content: reply }]); });
      }
    } catch {
      setChatMessages(function(prev) { return prev.concat([{ role:"assistant", content:"Error: Cannot reach backend." }]); });
    }
    setChatLoading(false);
  }

  useEffect(function() {
    if (chatEndRef.current) chatEndRef.current.scrollIntoView({ behavior:"smooth" });
  }, [chatMessages]);

  var pdfUrl         = jobId ? (API + "/report/" + jobId) : null;
  var displayHistory = user ? remoteHistory : localHistory;

  var TAB_LIST = [
    { id:"logs",         label:"📋 Logs" },
    { id:"pdf",          label:"📄 PDF Report" },
    { id:"api_docs",     label:"🔌 API Docs" },
    { id:"sequence",     label:"🔄 Sequence" },
    { id:"setup",        label:"⚙️ Setup" },
    { id:"tests",        label:"🧪 Tests" },
    { id:"chat",         label:"💬 Chat" },
  ];
  var DIAGRAM_TABS = ["api_docs","sequence","setup","tests"];

  return (
    <div style={S.root}>

      {/* ── Sidebar ── */}
      <aside style={S.sidebar}>
        <div style={S.topBar}>
          <div style={S.logo}>
            <span style={S.logoMark}>◈</span>
            <span style={S.logoText}>DevDocs.ai</span>
          </div>
          {user ? (
            <div style={S.userRow}>
              <img src={user.picture} alt="" style={S.avatar} referrerPolicy="no-referrer" />
              <div style={S.userInfo}>
                <span style={S.userName}>{user.name}</span>
                <span style={S.userEmail}>{user.email}</span>
              </div>
              <button style={S.signOutBtn} onClick={signOut} title="Sign out">✕</button>
            </div>
          ) : (
            <GoogleSignInButton onLogin={handleLogin} onError={function(msg) { setError(msg); }} />
          )}
        </div>

        <p style={S.tagline}>AI-powered documentation for any GitHub repo.</p>
        <div style={S.divider} />

        {/* Provider */}
        <div style={S.section}>
          <label style={S.label}>LLM Provider</label>
          <div style={S.providerRow}>
            {["gpt","ollama"].map(function(p) {
              return (
                <button key={p} style={Object.assign({}, S.providerBtn, provider===p ? S.providerActive : {})} onClick={function() { setProvider(p); }}>
                  {p === "gpt" ? "🤖 GPT (Paid)" : "🦙 Ollama (Free)"}
                </button>
              );
            })}
          </div>
          {provider === "ollama" && <p style={S.hint}>Requires <code style={S.code}>ollama serve</code> running locally.</p>}
        </div>

        {/* Form */}
        <div style={S.section}>
          <label style={S.label}>GitHub Repository URL</label>
          <input style={S.input} placeholder="https://github.com/user/repo"
            value={repoUrl} onChange={function(e) { setRepoUrl(e.target.value); }}
            onKeyDown={function(e) { if (e.key === "Enter") submit(); }} />

          {provider === "gpt" ? (
            <div>
              <label style={S.label}>
                OpenAI API Key
                {apiKeySaved && <span style={S.savedBadge}>✓ saved</span>}
              </label>
              <div style={S.keyRow}>
                <input
                  style={Object.assign({}, S.input, { flex:1, marginBottom:0 })}
                  type={showKey ? "text" : "password"}
                  placeholder={apiKeySaved ? "Using saved key — paste to update" : "sk-..."}
                  value={apiKey}
                  onChange={function(e) { setApiKey(e.target.value); setApiKeySaved(false); }}
                />
                <button style={S.eyeBtn} onClick={function() { setShowKey(function(v) { return !v; }); }}>
                  {showKey ? "🙈" : "👁"}
                </button>
              </div>
              {user && apiKey.trim() && !apiKeySaved && (
                <button style={S.saveKeyBtn} onClick={saveApiKey} disabled={savingKey}>
                  {savingKey ? "Saving…" : "💾 Save key to account"}
                </button>
              )}
              <label style={S.label}>Model</label>
              <select style={S.select} value={gptModel} onChange={function(e) { setGptModel(e.target.value); }}>
                <option value="gpt-3.5-turbo">GPT-3.5 Turbo — fast &amp; cheap</option>
                <option value="gpt-4o-mini">GPT-4o Mini — smarter</option>
                <option value="gpt-4o">GPT-4o — best quality</option>
              </select>
            </div>
          ) : (
            <div>
              <label style={S.label}>Ollama Model</label>
              <select style={S.select} value={ollamaModel} onChange={function(e) { setOllamaModel(e.target.value); }}>
                <option value="codellama">codellama</option>
                <option value="llama3">llama3</option>
                <option value="mistral">mistral</option>
                <option value="deepseek-coder">deepseek-coder</option>
                <option value="phi3">phi3</option>
                <option value="gemma">gemma</option>
              </select>
              <p style={S.hint}>Make sure you have run ollama pull {ollamaModel}</p>
            </div>
          )}

          {error && <p style={S.errorMsg}>⚠ {error}</p>}
          {notice && <p style={S.noticeMsg}>✓ {notice}</p>}

          <button style={Object.assign({}, S.btn, { opacity: loading ? 0.6 : 1 })} onClick={submit} disabled={loading}>
            {loading ? "Starting…" : "Generate Report →"}
          </button>
        </div>

        {/* History */}
        <div style={S.section}>
          <div style={S.historyHeader}>
            <span style={S.label}>{user ? "Account History" : "Session History"}</span>
          </div>
          {displayHistory.length === 0 ? (
            <p style={S.emptyHint}>{!user ? "Sign in to save & retrieve your history." : "No runs yet."}</p>
          ) : (
            <div style={S.histList}>
              {displayHistory.map(function(h) {
                return (
                  <div key={h.job_id} style={{ position:"relative" }}
                    onMouseEnter={function(e) {
                      var rect = e.currentTarget.getBoundingClientRect();
                      setTooltip({ id: h.job_id, text: h.repo_url.replace("https://github.com/",""), x: rect.left + 8, y: rect.top - 8 });
                    }}
                    onMouseLeave={function() { setTooltip(null); }}
                  >
                    <div
                      style={Object.assign({}, S.histItem, { background: h.job_id === jobId ? "#1e293b" : "transparent" })}
                      onClick={function() { loadJob(h.job_id); }}
                    >
                      <span style={Object.assign({}, S.dot, { background: STATUS_COLOR[h.status] || "#64748b" })} />
                      <div style={S.histMeta}>
                        <span style={S.histRepo}>{h.repo_url.replace("https://github.com/","")}</span>
                        <span style={S.histDate}>
                          {h.provider === "ollama" ? "🦙" : "🤖"} {new Date(h.created_at).toLocaleDateString()}
                        </span>
                      </div>
                      {user && (
                        <button style={S.deleteBtn}
                          onClick={function(e) { deleteJob(e, h.job_id); }}
                          disabled={deletingId === h.job_id}
                        >
                          {deletingId === h.job_id ? "…" : "🗑"}
                        </button>
                      )}
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </div>
      </aside>

      {/* ── Main ── */}
      <main style={S.main}>
        {!job && !jobId ? (
          <div style={S.homeHero}>
            <div style={S.homeCard}>
              <div style={S.emptyIcon}>◈</div>
              <p style={S.emptyTitle}>Generate repo docs in one click</p>
              <p style={S.emptyText}>Paste a GitHub repository URL in the left panel, choose a model, then run generation.</p>
              <div style={S.homeSteps}>
                <span style={S.stepPill}>1. Sign in (optional)</span>
                <span style={S.stepPill}>2. Paste repo URL</span>
                <span style={S.stepPill}>3. Generate report</span>
              </div>
            </div>
          </div>
        ) : (
          <div style={{ display:"flex", flexDirection:"column", height:"100%", overflow:"hidden" }}>

            {/* Status bar */}
            <div style={S.statusBar}>
              <div style={S.statusLeft}>
                <span style={Object.assign({}, S.statusDot, {
                  background: STATUS_COLOR[job?.status] || "#64748b",
                  animation: job?.status === "running" ? "pulse 1.2s infinite" : "none",
                })} />
                <span style={S.statusLabel}>{STATUS_LABEL[job?.status] ?? "…"}</span>
                <span style={S.statusRepo}>{job?.repo_url?.replace("https://github.com/","")}</span>
                <span style={Object.assign({}, S.providerPill, { background: job?.provider === "ollama" ? "#78350f" : "#0c4a6e" })}>
                  {job?.provider === "ollama" ? "🦙 Ollama" : "🤖 GPT"}
                </span>
              </div>
              {job?.has_pdf && (
                <a href={pdfUrl + "?dl=1"} download style={S.dlBtn}>↓ Download PDF</a>
              )}
            </div>

            {/* Tabs */}
            <div style={S.tabsBar}>
              {TAB_LIST.map(function(t) {
                var isPdf     = t.id === "pdf";
                var isDiagram = DIAGRAM_TABS.includes(t.id);
                var isChat    = t.id === "chat";
                var disabled  = (isPdf && !job?.has_pdf) || (isDiagram && !tabData && !tabLoading) || (isChat && job?.status !== "done");
                return (
                  <button key={t.id}
                    style={Object.assign({}, S.tab,
                      activeTab === t.id ? S.tabActive : {},
                      disabled ? { opacity:0.35, cursor:"not-allowed" } : {}
                    )}
                    onClick={function() { if (!disabled) setActiveTab(t.id); }}
                  >
                    {t.label}
                  </button>
                );
              })}
            </div>

            {/* Tab content */}
            <div style={{ flex:1, overflow:"hidden", display:"flex", flexDirection:"column" }}>

              {activeTab === "logs" && (
                <div style={S.logsBox} ref={logsRef}>
                  {(job?.logs || []).map(function(line, i) {
                    var color = line.includes("[ERROR]") ? "#f87171"
                              : line.includes("[WARN]")  ? "#fbbf24"
                              : (line.includes("complete") || line.includes("saved") || line.includes("Done")) ? "#34d399"
                              : "#94a3b8";
                    return <div key={i} style={Object.assign({}, S.logLine, { color: color })}>{line}</div>;
                  })}
                  {job?.status === "running" && <div style={Object.assign({}, S.logLine, { color:"#60a5fa" })}>⟳ Running…</div>}
                  {job?.status === "done"    && <div style={Object.assign({}, S.logLine, { color:"#34d399", fontWeight:600 })}>✅ Complete — switch to Report PDF tab.</div>}
                </div>
              )}

              {activeTab === "pdf" && job?.has_pdf && (
                <div style={S.pdfOuter}><iframe key={jobId} title="Report" src={pdfUrl} style={S.pdfFrame} /></div>
              )}
              {activeTab === "pdf" && !job?.has_pdf && (
                <div style={S.empty}><p style={S.emptyText}>PDF will appear here once the job completes.</p></div>
              )}

              {tabLoading && DIAGRAM_TABS.includes(activeTab) && (
                <div style={S.tabLoading}>⟳ Loading content…</div>
              )}

              {!tabLoading && tabData && activeTab === "api_docs"     && <MarkdownPanel content={tabData.api_docs} />}
              {!tabLoading && tabData && activeTab === "sequence"     && <MermaidPanel  code={tabData.sequence_mermaid} title="Sequence Diagram" />}
              {!tabLoading && tabData && activeTab === "setup"        && <MarkdownPanel content={tabData.setup} />}
              {!tabLoading && tabData && activeTab === "tests"        && <MarkdownPanel content={tabData.test_summary} />}

              {activeTab === "chat" && (
                <div style={S.chatContainer}>
                  <div style={S.chatMessages}>
                    {chatMessages.length === 0 && (
                      <div style={S.chatWelcome}>
                        <span style={{ fontSize:28 }}>💬</span>
                        <p style={{ fontSize:14, fontWeight:700, color:"#e2e8f0", marginTop:10 }}>Chat with this repo</p>
                        <p style={{ fontSize:12, color:"#64748b", maxWidth:360, textAlign:"center", lineHeight:1.7, marginTop:6 }}>
                          Ask anything about the codebase — architecture, how a function works, where something is defined, or how to extend it.
                        </p>
                      </div>
                    )}
                    {chatMessages.map(function(msg, i) {
                      var isUser = msg.role === "user";
                      return (
                        <div key={i} style={Object.assign({}, S.chatBubbleRow, { justifyContent: isUser ? "flex-end" : "flex-start" })}>
                          <div style={Object.assign({}, S.chatBubble, isUser ? S.chatBubbleUser : S.chatBubbleBot)}>
                            {msg.content.split("\n").map(function(line, j) {
                              return <p key={j} style={{ margin: line ? "3px 0" : "8px 0", minHeight: line ? undefined : 1 }}>{line}</p>;
                            })}
                          </div>
                        </div>
                      );
                    })}
                    {chatLoading && (
                      <div style={Object.assign({}, S.chatBubbleRow, { justifyContent:"flex-start" })}>
                        <div style={Object.assign({}, S.chatBubble, S.chatBubbleBot, { opacity:0.6 })}>⟳ Thinking…</div>
                      </div>
                    )}
                    <div ref={chatEndRef} />
                  </div>
                  <div style={S.chatInputBar}>
                    <input
                      style={S.chatInput}
                      placeholder="Ask about this repo…"
                      value={chatInput}
                      onChange={function(e) { setChatInput(e.target.value); }}
                      onKeyDown={function(e) { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); sendChatMessage(); } }}
                      disabled={chatLoading}
                    />
                    <button style={Object.assign({}, S.chatSendBtn, { opacity: chatLoading || !chatInput.trim() ? 0.4 : 1 })}
                      onClick={sendChatMessage} disabled={chatLoading || !chatInput.trim()}>
                      Send
                    </button>
                  </div>
                </div>
              )}

            </div>
          </div>
        )}
      </main>

      {/* ── Tooltip ── */}
      {tooltip && (
        <div style={Object.assign({}, S.tooltip, { left: tooltip.x, top: tooltip.y, transform:"translateY(-100%)" })}>
          {tooltip.text}
        </div>
      )}

      {/* ── Delete confirmation modal ── */}
      {confirmDelete && (
        <div style={S.modalOverlay} onClick={function() { setConfirmDelete(null); }}>
          <div style={S.modalBox} onClick={function(e) { e.stopPropagation(); }}>
            <p style={S.modalTitle}>Delete this run?</p>
            <p style={S.modalBody}>This will permanently delete the report and its PDF from storage. This cannot be undone.</p>
            <div style={S.modalBtns}>
              <button style={S.modalCancel} onClick={function() { setConfirmDelete(null); }}>Cancel</button>
              <button style={S.modalConfirm} onClick={confirmDeleteJob}>Delete</button>
            </div>
          </div>
        </div>
      )}

      <style>{`
        *{box-sizing:border-box;margin:0;padding:0}
        html,body,#root{height:100%}
        body{background:#0f172a;color:#e2e8f0;font-family:Inter,system-ui,-apple-system,Segoe UI,Roboto,Arial,sans-serif}
        @keyframes pulse{0%,100%{opacity:1}50%{opacity:.25}}
        input::placeholder{color:#475569}
        select option{background:#1e293b}
        ::-webkit-scrollbar{width:5px}
        ::-webkit-scrollbar-track{background:transparent}
        ::-webkit-scrollbar-thumb{background:#334155;border-radius:3px}
        code{font-family:inherit}
      `}</style>
    </div>
  );
}

const S = {
  root:        { display:"flex", height:"100vh", overflow:"hidden", background:"#0f172a" },
  sidebar:     { width:300, minWidth:300, background:"#0b1120", borderRight:"1px solid #1e293b", display:"flex", flexDirection:"column", gap:0, overflowY:"auto" },
  topBar:      { padding:"20px 20px 0", display:"flex", flexDirection:"column", gap:12 },
  logo:        { display:"flex", alignItems:"center", gap:9 },
  logoMark:    { fontSize:20, color:"#38bdf8" },
  logoText:    { fontSize:17, fontWeight:700, color:"#f1f5f9", letterSpacing:"-0.02em" },
  userRow:     { display:"flex", alignItems:"center", gap:10, background:"#1e293b", borderRadius:8, padding:"8px 10px" },
  avatar:      { width:32, height:32, borderRadius:"50%", flexShrink:0 },
  userInfo:    { flex:1, overflow:"hidden", display:"flex", flexDirection:"column", gap:1 },
  userName:    { fontSize:12, fontWeight:700, color:"#f1f5f9", whiteSpace:"nowrap", overflow:"hidden", textOverflow:"ellipsis" },
  userEmail:   { fontSize:10, color:"#64748b", whiteSpace:"nowrap", overflow:"hidden", textOverflow:"ellipsis" },
  signOutBtn:  { background:"transparent", border:"none", color:"#475569", cursor:"pointer", fontSize:12, padding:"2px 4px" },
  tagline:     { padding:"12px 20px 0", fontSize:11, color:"#475569", lineHeight:1.6 },
  divider:     { height:1, background:"#1e293b", margin:"14px 0 0" },
  section:     { padding:"14px 20px", display:"flex", flexDirection:"column", gap:8, borderBottom:"1px solid #1e293b" },
  label:       { fontSize:10, color:"#64748b", textTransform:"uppercase", letterSpacing:"0.08em", display:"flex", alignItems:"center", gap:6 },
  savedBadge:  { fontSize:9, color:"#34d399", background:"#0d2e1f", padding:"1px 6px", borderRadius:10, fontWeight:600, textTransform:"none" },
  input:       { background:"#1e293b", border:"1px solid #334155", borderRadius:6, padding:"9px 11px", color:"#e2e8f0", fontSize:12, fontFamily:"inherit", outline:"none", width:"100%" },
  keyRow:      { display:"flex", gap:6, alignItems:"center" },
  eyeBtn:      { background:"#1e293b", border:"1px solid #334155", borderRadius:6, padding:"9px 10px", cursor:"pointer", fontSize:13, flexShrink:0 },
  saveKeyBtn:  { background:"#0f2d1a", border:"1px solid #166534", borderRadius:6, padding:"7px 10px", color:"#34d399", fontSize:11, cursor:"pointer", fontFamily:"inherit", textAlign:"center" },
  select:      { background:"#1e293b", border:"1px solid #334155", borderRadius:6, padding:"9px 11px", color:"#e2e8f0", fontSize:12, fontFamily:"inherit", outline:"none", width:"100%", cursor:"pointer" },
  btn:         { background:"#38bdf8", color:"#0f172a", border:"none", borderRadius:6, padding:"11px 0", fontSize:12, fontWeight:700, cursor:"pointer", width:"100%", marginTop:2, fontFamily:"inherit", letterSpacing:"0.03em" },
  errorMsg:    { fontSize:11, color:"#f87171", lineHeight:1.5 },
  noticeMsg:   { fontSize:11, color:"#34d399", lineHeight:1.5 },
  hint:        { fontSize:10, color:"#475569", lineHeight:1.6 },
  code:        { background:"#1e293b", padding:"1px 5px", borderRadius:3, color:"#7dd3fc" },
  providerRow:    { display:"flex", gap:6 },
  providerBtn:    { flex:1, background:"#1e293b", border:"1px solid #334155", borderRadius:6, padding:"8px 6px", fontSize:11, color:"#94a3b8", cursor:"pointer", fontFamily:"inherit", textAlign:"center" },
  providerActive: { background:"#0c4a6e", border:"1px solid #38bdf8", color:"#38bdf8", fontWeight:700 },
  historyHeader:  { display:"flex", justifyContent:"space-between", alignItems:"center" },
  emptyHint:      { fontSize:10, color:"#334155", fontStyle:"italic" },
  histList:       { display:"flex", flexDirection:"column", gap:2 },
  histItem:       { display:"flex", alignItems:"center", gap:8, padding:"6px 8px", borderRadius:5, cursor:"pointer" },
  histMeta:       { flex:1, overflow:"hidden", display:"flex", flexDirection:"column", gap:1 },
  histRepo:       { fontSize:11, color:"#94a3b8", overflow:"hidden", textOverflow:"ellipsis", whiteSpace:"nowrap" },
  histDate:       { fontSize:9, color:"#475569" },
  dot:            { width:7, height:7, borderRadius:"50%", flexShrink:0 },
  deleteBtn:      { background:"transparent", border:"none", color:"#475569", cursor:"pointer", fontSize:13, padding:"2px 4px", flexShrink:0, opacity:0.6 },
  main:           { flex:1, display:"flex", flexDirection:"column", overflow:"hidden" },
  empty:          { flex:1, display:"flex", flexDirection:"column", alignItems:"center", justifyContent:"center", gap:10, opacity:.4 },
  homeHero:       { flex:1, display:"flex", alignItems:"center", justifyContent:"center", padding:24 },
  homeCard:       { width:"100%", maxWidth:560, border:"1px solid #1e293b", background:"#0b1120", borderRadius:12, padding:"28px 24px", display:"flex", flexDirection:"column", alignItems:"center", gap:12 },
  homeSteps:      { marginTop:6, display:"flex", gap:8, flexWrap:"wrap", justifyContent:"center" },
  stepPill:       { border:"1px solid #334155", background:"#1e293b", color:"#94a3b8", borderRadius:16, fontSize:11, padding:"4px 10px" },
  emptyIcon:      { fontSize:44, color:"#38bdf8" },
  emptyTitle:     { fontSize:15, color:"#e2e8f0", fontWeight:600 },
  emptyText:      { fontSize:12, color:"#64748b", textAlign:"center", maxWidth:300 },
  statusBar:      { display:"flex", alignItems:"center", justifyContent:"space-between", padding:"12px 24px", borderBottom:"1px solid #1e293b", background:"#0b1120", flexShrink:0 },
  statusLeft:     { display:"flex", alignItems:"center", gap:10, flexWrap:"wrap" },
  statusDot:      { width:8, height:8, borderRadius:"50%", flexShrink:0 },
  statusLabel:    { fontSize:11, fontWeight:700, color:"#e2e8f0", textTransform:"uppercase", letterSpacing:"0.06em" },
  statusRepo:     { fontSize:11, color:"#475569" },
  providerPill:   { fontSize:10, padding:"2px 8px", borderRadius:20, color:"#fff", fontWeight:600 },
  dlBtn:          { background:"#38bdf8", border:"none", borderRadius:5, padding:"7px 14px", fontSize:11, color:"#0f172a", fontWeight:700, cursor:"pointer", fontFamily:"inherit", textDecoration:"none", display:"inline-flex", alignItems:"center" },
  tabsBar:        { display:"flex", borderBottom:"1px solid #1e293b", background:"#0b1120", flexShrink:0, overflowX:"auto" },
  tab:            { background:"transparent", border:"none", borderBottom:"2px solid transparent", padding:"10px 16px", fontSize:11, color:"#64748b", cursor:"pointer", fontFamily:"inherit", transition:"all .15s", whiteSpace:"nowrap" },
  tabActive:      { color:"#38bdf8", borderBottomColor:"#38bdf8" },
  logsBox:        { flex:1, overflowY:"auto", padding:"18px 24px", display:"flex", flexDirection:"column", gap:3 },
  logLine:        { fontSize:12, lineHeight:1.7, color:"#94a3b8", fontFamily:"inherit" },
  pdfOuter:       { flex:1, display:"flex", flexDirection:"column", minHeight:0 },
  pdfFrame:       { flex:1, width:"100%", border:"none", background:"#fff", minHeight:0, height:"100%" },
  tabLoading:     { flex:1, display:"flex", alignItems:"center", justifyContent:"center", fontSize:13, color:"#475569" },
  chatContainer:  { flex:1, display:"flex", flexDirection:"column", overflow:"hidden" },
  chatMessages:   { flex:1, overflowY:"auto", padding:"20px 24px", display:"flex", flexDirection:"column", gap:12 },
  chatWelcome:    { flex:1, display:"flex", flexDirection:"column", alignItems:"center", justifyContent:"center", opacity:0.5 },
  chatBubbleRow:  { display:"flex", width:"100%" },
  chatBubble:     { maxWidth:"75%", padding:"10px 14px", borderRadius:12, fontSize:12, lineHeight:1.7, wordBreak:"break-word", fontFamily:"inherit" },
  chatBubbleUser: { background:"#0c4a6e", color:"#e0f2fe", borderBottomRightRadius:4 },
  chatBubbleBot:  { background:"#1e293b", color:"#e2e8f0", borderBottomLeftRadius:4, border:"1px solid #334155" },
  chatInputBar:   { display:"flex", gap:8, padding:"12px 24px", borderTop:"1px solid #1e293b", background:"#0b1120", flexShrink:0 },
  chatInput:      { flex:1, background:"#1e293b", border:"1px solid #334155", borderRadius:8, padding:"10px 14px", color:"#e2e8f0", fontSize:12, fontFamily:"inherit", outline:"none" },
  chatSendBtn:    { background:"#38bdf8", border:"none", borderRadius:8, padding:"10px 20px", color:"#0f172a", fontSize:12, fontWeight:700, cursor:"pointer", fontFamily:"inherit", flexShrink:0 },
  tooltip:        { position:"fixed", background:"#431407", border:"1px solid #ea580c", borderRadius:6, padding:"6px 10px", fontSize:11, color:"#fed7aa", whiteSpace:"normal", wordBreak:"break-all", zIndex:9999, pointerEvents:"none", maxWidth:220, lineHeight:1.5, boxShadow:"0 4px 12px rgba(0,0,0,0.4)" },
  modalOverlay:   { position:"fixed", inset:0, background:"rgba(0,0,0,0.6)", display:"flex", alignItems:"center", justifyContent:"center", zIndex:200 },
  modalBox:       { background:"#1e293b", border:"1px solid #334155", borderRadius:10, padding:"24px 28px", maxWidth:360, width:"90%", display:"flex", flexDirection:"column", gap:12 },
  modalTitle:     { fontSize:14, fontWeight:700, color:"#f1f5f9" },
  modalBody:      { fontSize:12, color:"#64748b", lineHeight:1.7 },
  modalBtns:      { display:"flex", gap:8, justifyContent:"flex-end", marginTop:4 },
  modalCancel:    { background:"transparent", border:"1px solid #334155", borderRadius:6, padding:"7px 16px", color:"#94a3b8", fontSize:12, cursor:"pointer", fontFamily:"inherit" },
  modalConfirm:   { background:"#ef4444", border:"none", borderRadius:6, padding:"7px 16px", color:"#fff", fontSize:12, fontWeight:700, cursor:"pointer", fontFamily:"inherit" },
};