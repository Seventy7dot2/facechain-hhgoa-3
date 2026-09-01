"use client";

import { ChangeEvent, DragEvent, FormEvent, useEffect, useRef, useState } from "react";

type SocialProfile = {
  platform: string;
  handle: string;
  profile_url: string;
  confidence: "knowledge_graph" | "lens_result" | "search_result";
};

type PipelineResult = {
  status: "verified";
  run_id: string;
  source_url: string;
  source_title: string;
  source_platform: string;
  cosine_similarity: number;
  content_sha256: string;
  identity: { name: string; kgmid: string; source: string } | null;
  social_profiles: SocialProfile[];
  blockchain: {
    backend: string;
    chain_id: number;
    transaction_hash: string;
    block_number: number;
    sender: string;
    explorer_url: string | null;
  };
  evidence_path: string;
};

const API_URL = process.env.NEXT_PUBLIC_FACECHAIN_API_URL ?? "http://localhost:8000";
const MAX_BYTES = 15_000_000;
const ACCEPTED_TYPES = ["image/jpeg", "image/png", "image/webp"];
const STAGES = [
  ["01", "FACE ENCODE", "YuNet detection + 128D SFace vector"],
  ["02", "SEARCH WEB", "Genuine Google Lens reverse search"],
  ["03", "MATCH FACE", "Candidate-by-candidate similarity check"],
  ["04", "MAP SOCIALS", "Entity-safe profile resolution"],
  ["05", "ANCHOR PROOF", "Ethereum write + independent read-back"],
] as const;

function compactHash(value: string, start = 12, end = 10) {
  if (value.length <= start + end + 3) return value;
  return `${value.slice(0, start)}…${value.slice(-end)}`;
}

function confidenceLabel(value: SocialProfile["confidence"]) {
  if (value === "knowledge_graph") return "KNOWLEDGE GRAPH";
  if (value === "lens_result") return "LENS CONFIRMED";
  return "SEARCH RESULT";
}

export default function Home() {
  const inputRef = useRef<HTMLInputElement>(null);
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const [file, setFile] = useState<File | null>(null);
  const [preview, setPreview] = useState<string | null>(null);
  const [dragging, setDragging] = useState(false);
  const [consent, setConsent] = useState(false);
  const [chain, setChain] = useState<"local" | "sepolia">("local");
  const [running, setRunning] = useState(false);
  const [stage, setStage] = useState(-1);
  const [result, setResult] = useState<PipelineResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [apiReady, setApiReady] = useState<boolean | null>(null);
  const [copied, setCopied] = useState<string | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 2500);
    fetch(`${API_URL}/api/health`, { signal: controller.signal })
      .then((response) => setApiReady(response.ok))
      .catch(() => setApiReady(false))
      .finally(() => clearTimeout(timeout));
    return () => controller.abort();
  }, []);

  useEffect(() => {
    return () => {
      if (preview) URL.revokeObjectURL(preview);
      if (timerRef.current) clearInterval(timerRef.current);
    };
  }, [preview]);

  function chooseFile(next: File | null) {
    setError(null);
    setResult(null);
    if (!next) return;
    if (!ACCEPTED_TYPES.includes(next.type)) {
      setError("Use a JPG, PNG, or WebP image.");
      return;
    }
    if (next.size > MAX_BYTES) {
      setError("Keep the image under 15 MB.");
      return;
    }
    if (preview) URL.revokeObjectURL(preview);
    setFile(next);
    setPreview(URL.createObjectURL(next));
  }

  function handleInput(event: ChangeEvent<HTMLInputElement>) {
    chooseFile(event.target.files?.[0] ?? null);
  }

  function handleDrop(event: DragEvent<HTMLDivElement>) {
    event.preventDefault();
    setDragging(false);
    chooseFile(event.dataTransfer.files?.[0] ?? null);
  }

  async function runPipeline(event: FormEvent) {
    event.preventDefault();
    if (!file || !consent || running) return;
    setRunning(true);
    setResult(null);
    setError(null);
    setStage(0);
    let currentStage = 0;
    timerRef.current = setInterval(() => {
      currentStage = Math.min(currentStage + 1, STAGES.length - 1);
      setStage(currentStage);
    }, 2400);

    const body = new FormData();
    body.append("image", file);
    body.append("chain", chain);
    try {
      const response = await fetch(`${API_URL}/api/runs`, { method: "POST", body });
      const payload = await response.json();
      if (!response.ok) throw new Error(payload.detail ?? "The verification run failed.");
      setStage(STAGES.length);
      setResult(payload as PipelineResult);
      setApiReady(true);
      window.setTimeout(() => {
        document.getElementById("proof")?.scrollIntoView({ behavior: "smooth", block: "start" });
      }, 100);
    } catch (requestError) {
      const message = requestError instanceof Error ? requestError.message : "The verification run failed.";
      setError(
        message === "Failed to fetch"
          ? "Local engine is offline. Start it with `uv run facechain serve`, then retry."
          : message,
      );
      setStage(-1);
    } finally {
      if (timerRef.current) clearInterval(timerRef.current);
      timerRef.current = null;
      setRunning(false);
    }
  }

  async function copyValue(key: string, value: string) {
    await navigator.clipboard.writeText(value);
    setCopied(key);
    window.setTimeout(() => setCopied(null), 1400);
  }

  function reset() {
    if (preview) URL.revokeObjectURL(preview);
    setFile(null);
    setPreview(null);
    setConsent(false);
    setResult(null);
    setError(null);
    setStage(-1);
    if (inputRef.current) inputRef.current.value = "";
    window.scrollTo({ top: 0, behavior: "smooth" });
  }

  return (
    <main>
      <section className="hero" aria-labelledby="hero-title">
        <div className="sun" aria-hidden="true"><span /></div>
        <div className="topographic-lines" aria-hidden="true" />
        <header className="nav shell">
          <a className="wordmark" href="#top" aria-label="FaceChain home">
            <span className="mark">FC</span>
            <span>FACECHAIN</span>
          </a>
          <div className="nav-meta">
            <span>HH GOA · TASK 03</span>
            <span className={`engine-pill ${apiReady === false ? "offline" : ""}`}>
              <i /> {apiReady === null ? "CHECKING ENGINE" : apiReady ? "ENGINE READY" : "ENGINE OFFLINE"}
            </span>
          </div>
        </header>

        <div id="top" className="hero-grid shell">
          <div className="hero-copy">
            <p className="eyebrow">FACE ID × SOCIAL SEARCH × ETHEREUM</p>
            <h1 id="hero-title">
              FIND THE FACE.<br />
              <em>PROVE THE FIND.</em>
            </h1>
            <p className="lede">
              One image in. A real matching post out. Every byte fingerprinted and anchored to an
              Ethereum block before you call it verified.
            </p>
            <div className="proof-strip" aria-label="Pipeline capabilities">
              <span><b>01</b> LOCAL FACE ENCODING</span>
              <span><b>02</b> GENUINE WEB SEARCH</span>
              <span><b>03</b> TAMPER-EVIDENT PROOF</span>
            </div>
          </div>

          <form className="scan-card" onSubmit={runPipeline}>
            <div className="card-rivet one" /><div className="card-rivet two" />
            <div className="card-head">
              <div>
                <span className="kicker">START A TRACE</span>
                <h2>DROP THE SCAN</h2>
              </div>
              <span className="task-chip">#03</span>
            </div>

            <div
              className={`dropzone ${dragging ? "dragging" : ""} ${preview ? "has-image" : ""}`}
              onDragOver={(event) => { event.preventDefault(); setDragging(true); }}
              onDragLeave={() => setDragging(false)}
              onDrop={handleDrop}
              onClick={() => inputRef.current?.click()}
              role="button"
              tabIndex={0}
              onKeyDown={(event) => {
                if (event.key === "Enter" || event.key === " ") inputRef.current?.click();
              }}
              aria-label="Choose a face image"
            >
              <input
                ref={inputRef}
                type="file"
                accept="image/jpeg,image/png,image/webp"
                onChange={handleInput}
                hidden
              />
              {preview ? (
                <>
                  {/* eslint-disable-next-line @next/next/no-img-element */}
                  <img src={preview} alt="Selected face scan preview" />
                  <div className="image-scanline" aria-hidden="true" />
                  <span className="replace-label">CLICK TO REPLACE</span>
                </>
              ) : (
                <div className="drop-copy">
                  <span className="face-brackets" aria-hidden="true"><i /><i /><i /><i /></span>
                  <strong>DRAG IMAGE HERE</strong>
                  <small>OR CLICK TO BROWSE</small>
                  <span>JPG · PNG · WEBP / MAX 15 MB</span>
                </div>
              )}
            </div>

            {file && (
              <div className="file-row">
                <span>{file.name}</span>
                <span>{(file.size / 1_000_000).toFixed(2)} MB</span>
              </div>
            )}

            <fieldset className="chain-picker">
              <legend>CHAIN TARGET</legend>
              <button type="button" className={chain === "local" ? "selected" : ""} onClick={() => setChain("local")}>
                <span>LOCAL ETHEREUM</span><small>FAST · NO GAS</small>
              </button>
              <button type="button" className={chain === "sepolia" ? "selected" : ""} onClick={() => setChain("sepolia")}>
                <span>SEPOLIA</span><small>PUBLIC · TESTNET</small>
              </button>
            </fieldset>

            <label className="consent-row">
              <input type="checkbox" checked={consent} onChange={(event) => setConsent(event.target.checked)} />
              <span>I confirm I have consent to search this face and understand public URLs may be anchored on-chain.</span>
            </label>

            <button className="run-button" disabled={!file || !consent || running} type="submit">
              <span>{running ? "TRACE IN PROGRESS" : "RUN FACECHAIN"}</span>
              <b>{running ? "•••" : "↗"}</b>
            </button>
            {chain === "sepolia" && <p className="chain-note">Requires a funded test wallet in the local environment.</p>}
            {error && <div className="error-box" role="alert">{error}</div>}
          </form>
        </div>
      </section>

      <section className="process-section" aria-label="Verification pipeline">
        <div className="ticker" aria-hidden="true">
          <div>NO HARDCODED RESULTS ✦ NO FACE EMBEDDINGS ON-CHAIN ✦ VERIFY EVERY BYTE ✦&nbsp;</div>
          <div>NO HARDCODED RESULTS ✦ NO FACE EMBEDDINGS ON-CHAIN ✦ VERIFY EVERY BYTE ✦&nbsp;</div>
        </div>
        <div className="shell process-inner">
          <div className="section-heading">
            <p>INSIDE THE RUN</p>
            <h2>FIVE MOVES.<br />ONE PROOF.</h2>
          </div>
          <ol className="stage-list">
            {STAGES.map(([number, title, detail], index) => {
              const complete = stage > index;
              const active = stage === index;
              return (
                <li key={number} className={`${complete ? "complete" : ""} ${active ? "active" : ""}`}>
                  <span className="stage-number">{complete ? "✓" : number}</span>
                  <div><strong>{title}</strong><small>{detail}</small></div>
                  <i aria-hidden="true" />
                </li>
              );
            })}
          </ol>
        </div>
      </section>

      {result && (
        <section id="proof" className="result-section" aria-labelledby="proof-title">
          <div className="shell">
            <div className="verified-banner">
              <span className="verified-seal">✓</span>
              <div><p>END-TO-END CHECK COMPLETE</p><h2 id="proof-title">PROOF, NOT PROMISES.</h2></div>
              <span className="run-id">RUN / {result.run_id}</span>
            </div>

            <div className="result-grid">
              <article className="result-card match-card">
                <div className="result-label"><span>01</span> MATCHED CONTENT</div>
                <div className="platform-line">
                  <span>{result.source_platform}</span>
                  <b>{(result.cosine_similarity * 100).toFixed(1)}% FACE MATCH</b>
                </div>
                <h3>{result.source_title}</h3>
                <a href={result.source_url} target="_blank" rel="noreferrer">OPEN ORIGINAL POST ↗</a>
                <div className="hash-box"><span>CONTENT SHA-256</span><code>{compactHash(result.content_sha256)}</code>
                  <button onClick={() => copyValue("content", result.content_sha256)}>{copied === "content" ? "COPIED" : "COPY"}</button>
                </div>
              </article>

              <article className="result-card identity-card">
                <div className="result-label"><span>02</span> RESOLVED IDENTITY</div>
                <h3>{result.identity?.name ?? "NO CANONICAL ENTITY"}</h3>
                <p className="identity-source">
                  {result.identity?.kgmid ? `GOOGLE ENTITY ${result.identity.kgmid}` : "VISUAL CONSENSUS · NO KGMID"}
                </p>
                <div className="profile-list">
                  {result.social_profiles.length ? result.social_profiles.map((profile) => (
                    <a key={`${profile.platform}-${profile.handle}`} href={profile.profile_url} target="_blank" rel="noreferrer">
                      <span className="platform-icon">{profile.platform.slice(0, 2).toUpperCase()}</span>
                      <div><b>{profile.handle}</b><small>{confidenceLabel(profile.confidence)}</small></div>
                      <i>↗</i>
                    </a>
                  )) : <p className="empty-profiles">No profile passed the safe association rules.</p>}
                </div>
              </article>

              <article className="result-card chain-card">
                <div className="result-label"><span>03</span> BLOCKCHAIN RECEIPT</div>
                <div className="chain-status"><i /> VERIFIED ON {result.blockchain.backend.toUpperCase()}</div>
                <dl>
                  <div><dt>BLOCK</dt><dd>#{result.blockchain.block_number}</dd></div>
                  <div><dt>CHAIN ID</dt><dd>{result.blockchain.chain_id}</dd></div>
                  <div><dt>TRANSACTION</dt><dd><code>{compactHash(result.blockchain.transaction_hash, 14, 12)}</code>
                    <button onClick={() => copyValue("tx", result.blockchain.transaction_hash)}>{copied === "tx" ? "COPIED" : "COPY"}</button></dd></div>
                </dl>
                {result.blockchain.explorer_url && <a className="explorer-link" href={result.blockchain.explorer_url} target="_blank" rel="noreferrer">VIEW ON ETHERSCAN ↗</a>}
              </article>

              <article className="result-card evidence-card">
                <div className="result-label"><span>04</span> EVIDENCE BUNDLE</div>
                <p>Search response, selected image bytes, canonical metadata, receipt, and read-back verification are preserved locally.</p>
                <code>{result.evidence_path}</code>
                <div className="privacy-row"><span>IMAGE ON-CHAIN</span><b>NO</b><span>EMBEDDING STORED</span><b>NO</b></div>
              </article>
            </div>
            <button className="again-button" onClick={reset}>RUN ANOTHER TRACE <span>↗</span></button>
          </div>
        </section>
      )}

      <footer>
        <div className="shell footer-inner">
          <div><span className="mark">FC</span><b>FACECHAIN</b></div>
          <p>BUILT FOR HH GOA 2026 · TASK 03</p>
          <p>CONSENT FIRST. VERIFY ALWAYS.</p>
        </div>
      </footer>
    </main>
  );
}
