"use client";

import { useEffect, useRef, useState } from "react";
import { consumeEvents } from "./stream.mjs";

type SocialProfile = {
  platform: string;
  handle: string;
  profile_url: string;
  confidence: "knowledge_graph" | "lens_result" | "search_result";
};

type Candidate = {
  rank: number;
  title: string;
  source: string;
  source_url: string;
  image_url: string;
  thumbnail_url?: string;
  exact_match: boolean;
};

type Blockchain = {
  backend: string;
  chain_id: number;
  transaction_hash: string;
  block_number: number;
  explorer_url: string | null;
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
  blockchain: Blockchain;
  evidence_path: string;
};

type FeedData = {
  preview?: string;
  detected_faces?: number;
  selected_face?: { x: number; y: number; width: number; height: number };
  image_width?: number;
  image_height?: number;
  bytes?: number;
  candidates?: Candidate[];
  candidate?: Candidate;
  cosine_similarity?: number;
  accepted?: boolean;
  identity?: { name: string; kgmid: string; source: string } | null;
  profiles?: SocialProfile[];
  match?: Candidate & { cosine_similarity: number; detected_faces: number; preview: string };
  chain_record?: Record<string, string>;
  receipt?: Blockchain;
  checks?: Record<string, boolean>;
  result?: PipelineResult;
};

type Feed = {
  id: number | string;
  run_id?: string;
  stage: string;
  state: "running" | "completed" | "finished" | "failed";
  message: string;
  elapsed_ms?: number;
  duration_ms?: number;
  data: FeedData;
};

const API_URL = process.env.NEXT_PUBLIC_FACECHAIN_API_URL ?? "http://localhost:8000";
const ACCEPTED_TYPES = ["image/jpeg", "image/png", "image/webp"];
const STEPS = [
  ["input", "Encode", "YuNet + SFace", "Detect the largest input face, align it, and create an in-memory SFace feature vector."],
  ["crop", "Prepare", "Face → search crop", "Crop the detected face with context and compress the actual search upload below 500 KB."],
  ["search", "Discover", "SerpApi → Lens", "Upload the crop to SerpApi and retrieve live Google Lens results from supported social platforms."],
  ["profiles", "Resolve", "Entity → profiles", "Use Lens identity evidence and a Knowledge Graph ID when available to associate profile URLs."],
  ["confirm", "Compare", "Candidate → SFace", "Download each ranked candidate and compare all detected faces against the input vector."],
  ["evidence", "Fingerprint", "Match → SHA-256", "Hash the selected image bytes and deterministic discovery metadata independently."],
  ["anchor", "Publish", "Record → Ethereum", "Write the compact evidence record into local Ethereum or Sepolia transaction calldata."],
  ["verify", "Read back", "Ethereum → proof", "Read the transaction back and require exact record equality before reporting verification."],
] as const;

function duration(milliseconds?: number) {
  if (milliseconds === undefined) return "";
  if (milliseconds < 0.01) return "<0.01 ms";
  return milliseconds < 1000
    ? `${milliseconds.toFixed(2)} ms`
    : `${(milliseconds / 1000).toFixed(2)} s`;
}

function confidence(value: SocialProfile["confidence"]) {
  if (value === "knowledge_graph") return "KNOWLEDGE GRAPH";
  if (value === "lens_result") return "DIRECT LENS RESULT";
  return "ENTITY SEARCH RESULT";
}

export default function Home() {
  const inputRef = useRef<HTMLInputElement>(null);
  const abortRef = useRef<AbortController | null>(null);
  const [file, setFile] = useState<File | null>(null);
  const [original, setOriginal] = useState("");
  const [events, setEvents] = useState<Feed[]>([]);
  const [selected, setSelected] = useState("input");
  const [follow, setFollow] = useState(true);
  const [running, setRunning] = useState(false);
  const [error, setError] = useState("");
  const [chain, setChain] = useState<"local" | "sepolia">("local");
  const [consent, setConsent] = useState(false);
  const [dragging, setDragging] = useState(false);
  const [online, setOnline] = useState<boolean | null>(null);
  const [result, setResult] = useState<PipelineResult | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    const timer = window.setTimeout(() => controller.abort(), 3000);
    fetch(`${API_URL}/api/health`, { signal: controller.signal })
      .then((response) => setOnline(response.ok))
      .catch(() => setOnline(false))
      .finally(() => window.clearTimeout(timer));
    return () => {
      controller.abort();
      window.clearTimeout(timer);
      abortRef.current?.abort();
    };
  }, []);

  useEffect(() => () => {
    if (original) URL.revokeObjectURL(original);
  }, [original]);

  function chooseFile(next?: File) {
    if (!next || running) return;
    if (!ACCEPTED_TYPES.includes(next.type) || !next.size || next.size > 15_000_000) {
      setError("Choose a non-empty JPG, PNG, or WebP under 15 MB.");
      return;
    }
    if (original) URL.revokeObjectURL(original);
    setFile(next);
    setOriginal(URL.createObjectURL(next));
    setEvents([]);
    setResult(null);
    setError("");
    setSelected("input");
    setFollow(true);
  }

  async function runPipeline() {
    if (!file || !consent || running) return;
    setRunning(true);
    setEvents([]);
    setResult(null);
    setError("");
    setFollow(true);
    const controller = new AbortController();
    abortRef.current = controller;
    const form = new FormData();
    form.append("image", file);
    form.append("chain", chain);
    let finished = false;

    try {
      const response = await fetch(`${API_URL}/api/runs`, {
        method: "POST",
        headers: { Accept: "text/event-stream" },
        body: form,
        signal: controller.signal,
      });
      if (!response.ok) {
        const payload = await response.json();
        throw new Error(payload.detail ?? "The discovery run failed.");
      }
      if (!response.body) throw new Error("Streaming is unavailable in this browser.");
      setOnline(true);
      await consumeEvents<Feed>(response.body, (event) => {
        setEvents((previous) => [...previous, event]);
        if (event.state === "failed") throw new Error(event.message);
        if (event.state === "finished" && event.data.result) {
          finished = true;
          setResult(event.data.result);
        }
      });
      if (!finished) throw new Error("The connection ended before verification completed.");
    } catch (reason) {
      const message = reason instanceof Error ? reason.message : "The discovery run failed.";
      setError(
        message === "Failed to fetch"
          ? "Cannot reach FaceChain. Start the Python API and check its allowed browser origin."
          : message,
      );
    } finally {
      abortRef.current = null;
      setRunning(false);
    }
  }

  const latest = events.at(-1);
  const activeStage = follow && latest && STEPS.some(([id]) => id === latest.stage)
    ? latest.stage
    : selected;
  const stageDefinition = STEPS.find(([id]) => id === activeStage) ?? STEPS[0];
  const current = events.filter((event) => event.stage === activeStage).at(-1);
  const completed = (id: string) => events.findLast(
    (event) => event.stage === id && event.state === "completed",
  );
  const inputEvent = completed("input")?.data;
  const cropEvent = completed("crop")?.data;
  const searchEvent = completed("search")?.data;
  const profileEvent = completed("profiles")?.data;
  const confirmationEvents = events.filter(
    (event) => event.stage === "confirm" && event.data.candidate,
  );
  const confirmationEvent = confirmationEvents.at(-1)?.data;
  const confirmedMatch = completed("confirm")?.data.match;
  const evidenceEvent = completed("evidence")?.data;
  const receipt = completed("anchor")?.data.receipt ?? result?.blockchain;
  const checks = completed("verify")?.data.checks;
  const done = STEPS.filter(([id]) => completed(id)).length;

  const shownProfiles = result?.social_profiles ?? profileEvent?.profiles ?? [];
  const shownIdentity = result?.identity ?? profileEvent?.identity;

  return (
    <main className="lab">
      <header className="nav shell">
        <a className="wordmark" href="#top"><span className="mark">FC</span> FACECHAIN LIVE</a>
        <div className="nav-meta">
          <span>HH GOA · TASK 03</span>
          <span className={`engine-pill ${online === false ? "offline" : ""}`}>
            <i />{online === null ? "CONNECTING" : online ? "ENGINE ONLINE" : "ENGINE UNREACHABLE"}
          </span>
        </div>
      </header>

      <section className="lab-intro shell" id="top">
        <div><p className="eyebrow">FACE DISCOVERY / LIVE ARCHITECTURE</p><h1>SEE THE SEARCH.<br /><em>PROVE THE MATCH.</em></h1></div>
        <p>Follow the actual image through YuNet, SFace, Google Lens, profile resolution, candidate confirmation, and Ethereum verification. Every update comes from the backend.</p>
      </section>

      <section className="workbench shell">
        <aside className="intake">
          <span className="kicker">01 / SEARCH INPUT</span><h2>DROP THE<br />FACE.</h2>
          <input ref={inputRef} type="file" accept={ACCEPTED_TYPES.join(",")} hidden disabled={running} onChange={(event) => chooseFile(event.target.files?.[0])} />
          <button className={`source-drop ${dragging ? "dragging" : ""}`} disabled={running} onClick={() => inputRef.current?.click()} onDragOver={(event) => { event.preventDefault(); setDragging(true); }} onDragLeave={() => setDragging(false)} onDrop={(event) => { event.preventDefault(); setDragging(false); chooseFile(event.dataTransfer.files[0]); }}>
            {original ? <Picture src={original} alt="Selected search image" /> : <span><b>＋</b>DROP AN IMAGE<br /><small>or browse your files</small></span>}
          </button>
          <p className="file-caption">{file ? `${file.name} · ${(file.size / 1_000_000).toFixed(2)} MB` : "JPG / PNG / WEBP · UP TO 15 MB"}</p>
          <label className="chain-label">EVIDENCE CHAIN<select value={chain} disabled={running} onChange={(event) => setChain(event.target.value as "local" | "sepolia")}><option value="local">Local Ethereum · temporary</option><option value="sepolia">Sepolia · public testnet</option></select></label>
          <label className="consent-row lab-consent"><input type="checkbox" checked={consent} onChange={(event) => setConsent(event.target.checked)} /><span>I confirm I have consent to search this face and understand that discovered public URLs may be placed on-chain.</span></label>
          <button className="run-button" disabled={!file || !consent || running} onClick={runPipeline}>{running ? "SEARCHING LIVE…" : "RUN FACECHAIN"}<span>↗</span></button>
          <p className="fine">Face embeddings stay in memory. Images and embeddings are never written on-chain.</p>
        </aside>

        <div className="observatory">
          <div className="live-heading"><span className={running ? "live-dot" : ""}>{running ? "● LIVE FROM THE PIPELINE" : result ? "✓ END-TO-END VERIFIED" : "PIPELINE OBSERVATORY"}</span><span>{done} / {STEPS.length} COMPLETE</span>{latest?.elapsed_ms !== undefined && <span>TOTAL SERVER TIME: {duration(latest.elapsed_ms)}</span>}</div>
          <ol className="architecture pipeline-architecture" aria-label="Live FaceChain architecture">{STEPS.map(([id, title, subtitle], index) => {
            const item = events.findLast((event) => event.stage === id);
            const state = item?.state === "finished"
              ? "completed"
              : error && item?.state === "running" ? "failed" : item?.state ?? "pending";
            const complete = completed(id);
            return <li key={id} className={state}><button onClick={() => { setSelected(id); setFollow(false); }} aria-pressed={activeStage === id}><span className="node-index">{complete ? "✓" : String(index + 1).padStart(2, "0")}</span><b>{title}</b><small>{subtitle}</small><span className="node-state">{complete ? "completed" : state}{complete && <small>{duration(complete.duration_ms)}</small>}</span></button></li>;
          })}</ol>
          <div className="inspector-head"><div><span className="kicker">INSIDE THE OPERATION</span><h2>{stageDefinition[1]}</h2></div><button className="follow-button" aria-pressed={follow} onClick={() => setFollow(!follow)}>{follow ? "FOLLOWING LIVE" : "FOLLOW LIVE ↗"}</button></div>
          <p className="operation-description">{stageDefinition[3]}</p>
          <div className={`pixel-stage pipeline-stage ${running && current?.state === "running" ? "working" : ""}`}>
            {activeStage === "crop" && cropEvent?.preview ? <><Picture src={cropEvent.preview} alt="Actual face crop sent to SerpApi" /><span className="image-caption">SERPAPI UPLOAD · {cropEvent.bytes?.toLocaleString()} BYTES</span></>
              : activeStage === "search" && searchEvent?.candidates?.length ? <CandidateGallery candidates={searchEvent.candidates} />
              : activeStage === "profiles" ? <ProfileStage identity={shownIdentity} profiles={shownProfiles} />
              : activeStage === "confirm" && (confirmationEvent?.preview || confirmedMatch?.preview) ? <MatchStage data={confirmedMatch ?? confirmationEvent} />
              : ["evidence", "anchor", "verify"].includes(activeStage) && evidenceEvent?.chain_record ? <ProofStage record={evidenceEvent.chain_record} receipt={receipt} checks={checks} />
              : original ? <div className="face-preview"><Picture src={activeStage === "input" && inputEvent?.preview ? inputEvent.preview : original} alt={activeStage === "input" && inputEvent?.preview ? "Backend face detection preview" : "Uploaded input face"} /><span className="image-caption">{inputEvent ? `${inputEvent.detected_faces} FACE${inputEvent.detected_faces === 1 ? "" : "S"} · ${inputEvent.image_width} × ${inputEvent.image_height}` : "AWAITING YUNET DETECTION"}</span></div>
              : <div className="empty-stage"><span className="empty-cross">＋</span><h3>THE PIPELINE OPENS HERE.</h3><p>Upload a consented image to begin.</p></div>}
            {running && current?.state === "running" && <div className="processing-beam" />}
          </div>
          <div className="operation-state" role="status"><span className="operation-message">{current?.message ?? "Waiting for this operation."}</span>{current && <span>{current.state === "running" ? "IN PROGRESS" : `THIS STEP: ${duration(current.duration_ms)}`}</span>}</div>
          {error && <p className="error-box" role="alert">{error}</p>}
        </div>
      </section>

      <section className="telemetry shell">
        <div className="feed-panel"><div className="live-heading"><span>02 / REAL EVENT FEED</span><span>BACKEND TIMINGS</span></div><div className="event-log" role="log" aria-live="polite" aria-relevant="additions">{events.length ? events.map((event, index) => <div className={`event ${event.state}`} key={`${event.id}-${index}`}><time>{event.elapsed_ms === undefined ? "—" : `+${(event.elapsed_ms / 1000).toFixed(3)}s`}</time><b>{event.stage}</b><span>{event.message}</span><small>{event.state}</small></div>) : <p className="feed-empty">Real pipeline events appear here as the backend produces them.</p>}</div></div>
        <aside className="receipt-panel social-receipt"><span className="kicker">03 / DISCOVERY OUTPUT</span><h2>{result ? "MATCH\nVERIFIED." : "PROFILES\nPENDING."}</h2>
          {shownIdentity && <div className="identity-summary"><span>RESOLVED IDENTITY</span><b>{shownIdentity.name}</b><small>{shownIdentity.kgmid || "VISUAL CONSENSUS · NO KGMID"}</small></div>}
          <div className="social-list">{shownProfiles.length ? shownProfiles.map((profile) => <a key={`${profile.platform}-${profile.handle}`} href={profile.profile_url} target="_blank" rel="noreferrer"><span>{profile.platform.slice(0, 2).toUpperCase()}</span><div><b>{profile.handle}</b><small>{confidence(profile.confidence)}</small></div><i>↗</i></a>) : <p>No evidence-backed social handles have been returned yet.</p>}</div>
          {result && <div className="final-match"><span>{result.source_platform}</span><b>{(result.cosine_similarity * 100).toFixed(1)}% FACE MATCH</b><a href={result.source_url} target="_blank" rel="noreferrer">OPEN MATCHED SOURCE ↗</a></div>}
          {receipt && <div className="receipt-summary"><span>{receipt.backend.toUpperCase()} · BLOCK #{receipt.block_number}</span><code>{receipt.transaction_hash}</code>{receipt.explorer_url && <a href={receipt.explorer_url} target="_blank" rel="noreferrer">VIEW ON ETHERSCAN ↗</a>}</div>}
          <p className="fine">Profile labels show their evidence source. A face similarity score and third-party metadata are supporting evidence, not proof of account control.</p>
        </aside>
      </section>
      <footer><div className="shell footer-inner"><b>FC / FACECHAIN LIVE</b><span>HH GOA · WATCH THE ARCHITECTURE WORK.</span><span>FACE → SEARCH → MATCH → PROOF</span></div></footer>
    </main>
  );
}

function CandidateGallery({ candidates }: { candidates: Candidate[] }) {
  return <div className="candidate-gallery">{candidates.slice(0, 8).map((candidate) => <a key={candidate.source_url} href={candidate.source_url} target="_blank" rel="noreferrer"><Picture src={candidate.thumbnail_url || candidate.image_url} alt={candidate.title} /><span>{candidate.exact_match ? "EXACT" : `#${candidate.rank}`} · {candidate.source}</span></a>)}</div>;
}

function ProfileStage({ identity, profiles }: { identity?: { name: string; kgmid: string; source: string } | null; profiles: SocialProfile[] }) {
  return <div className="profile-stage"><p>RESOLVED ENTITY</p><h3>{identity?.name ?? "NO CANONICAL ENTITY"}</h3><span>{identity?.kgmid || "NO KNOWLEDGE GRAPH ID"}</span><div>{profiles.map((profile) => <a key={profile.profile_url} href={profile.profile_url} target="_blank" rel="noreferrer"><b>{profile.platform}</b><span>{profile.handle}</span><small>{confidence(profile.confidence)}</small></a>)}</div></div>;
}

function MatchStage({ data }: { data: FeedData["match"] | FeedData }) {
  const score = data?.cosine_similarity;
  const candidate = "candidate" in data! ? data.candidate : data as Candidate;
  return <div className="match-stage">{data?.preview && <Picture src={data.preview} alt="Candidate image downloaded and processed by the backend" />}<div className="match-readout"><span>{candidate?.source ?? "CANDIDATE"}</span><b>{score === undefined ? "DOWNLOADING" : `${(score * 100).toFixed(1)}%`}</b><small>SFACE COSINE SIMILARITY</small></div>{score !== undefined && <div className="score-track"><i style={{ width: `${Math.max(0, Math.min(score, 1)) * 100}%` }} /></div>}</div>;
}

function ProofStage({ record, receipt, checks }: { record: Record<string, string>; receipt?: Blockchain; checks?: Record<string, boolean> }) {
  return <div className="proof-stage"><p>CONTENT SHA-256</p><code>{record.content_sha256}</code><p>METADATA SHA-256</p><code>{record.metadata_sha256}</code>{receipt && <><p>TRANSACTION / BLOCK {receipt.block_number}</p><code>{receipt.transaction_hash}</code></>}{checks && <div className="check-row">{Object.entries(checks).map(([key, value]) => <span key={key}>{value ? "✓" : "×"} {key.replaceAll("_", " ")}</span>)}</div>}</div>;
}

function Picture({ src, alt }: { src: string; alt: string }) {
  // Search result and data URLs must bypass the deployment image proxy.
  // eslint-disable-next-line @next/next/no-img-element
  return <img src={src} alt={alt} />;
}
