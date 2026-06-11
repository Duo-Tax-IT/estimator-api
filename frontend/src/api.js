// Every backend call in one place. `secret` (the optional secret-sauce header)
// is only sent when a page supplies one; the API contract is unchanged from the
// old vanilla pages.

const json = async (resp) => {
  const data = await resp.json().catch(() => ({}));
  if (!resp.ok) throw new Error(data.detail || `${resp.status} ${resp.statusText}`);
  return data;
};

const headers = (secret, hasBody) => ({
  ...(hasBody && { "Content-Type": "application/json" }),
  ...(secret && { "secret-sauce": secret }),
});

const get = (path, secret) => fetch(path, { headers: headers(secret, false) }).then(json);
const post = (path, body, secret) =>
  fetch(path, { method: "POST", headers: headers(secret, true), body: JSON.stringify(body) }).then(json);

export const searchAddress = (q) =>
  get(`/search?q=${encodeURIComponent(q)}`).then((d) => d.suggestions || []);

export const getPhotos = (rpId, secret) =>
  get(`/photos?rpId=${encodeURIComponent(rpId)}`, secret).then((d) => d.photos || []);

export const photosDownloadUrl = (rpId) => `/photos/download?rpId=${encodeURIComponent(rpId)}`;

export const getRuns = (rpId, secret) =>
  get(rpId ? `/runs?rpId=${encodeURIComponent(rpId)}` : "/runs", secret).then((d) => d.runs || []);

export const getRun = (id, secret) =>
  get(`/runs/${encodeURIComponent(id)}`, secret).then((d) => d.run);

const ESTIMATE_PATHS = { v2: "/estimate/v2", v3: "/estimate/v3" };
export const estimate = (version, body, secret) =>
  post(ESTIMATE_PATHS[version] || "/estimate", body, secret);

// One playground step for a given pipeline version (v2 or v3).
export const pipelineStep = (version, name, body, secret) =>
  post(`/estimate/${version}/step/${name}`, body, secret);

export const learnAnalyze = (body, secret) =>
  post("/learn/analyze", body, secret).then((d) => d.analysis);

// Diagnostic chat about a saved run (explain-only). chat() persists + returns the
// reply; getChat() restores the thread.
export const chat = (runId, message, includePhotos, secret) =>
  post("/chat", { runId, message, includePhotos }, secret);
export const getChat = (runId, secret) =>
  get(`/chat?runId=${encodeURIComponent(runId)}`, secret).then((d) => d.messages || []);

export const getSessions = (runId, secret) =>
  get(runId ? `/learn/sessions?runId=${encodeURIComponent(runId)}` : "/learn/sessions", secret)
    .then((d) => d.sessions || []);

// Applied-flag for tuning recommendations. Keys are "sessionId:recIndex".
export const getApplied = (secret) => get("/learn/applied", secret).then((d) => d.applied || []);
export const markApplied = (sessionId, recIndex, applied, secret) =>
  post("/learn/applied", { sessionId, recIndex, applied }, secret);

// Prompt preview returns plain text (not JSON) and has its own error shape.
export async function previewPrompt(version, body, secret) {
  const resp = await fetch(version === "v2" ? "/debug/prompt/v2" : "/debug/prompt", {
    method: "POST", headers: headers(secret, true), body: JSON.stringify(body),
  });
  const text = await resp.text();
  if (!resp.ok) throw new Error(`Error (${resp.status}): ${text}`);
  return text;
}
