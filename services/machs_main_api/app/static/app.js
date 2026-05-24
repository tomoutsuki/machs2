const meEl = document.getElementById("me");
const createOutEl = document.getElementById("create-out");
const searchOutEl = document.getElementById("search-out");
const decryptOutEl = document.getElementById("decrypt-out");

const samplePatient = {
  resourceType: "Patient",
  id: "ui-generated-patient",
  name: [{ family: "Silva", given: ["Joao", "Pedro"] }],
  identifier: [{ system: "https://saude.gov.br/fhir/sid/cpf", value: "12345678901" }],
  birthDate: "1990-01-01",
  gender: "male"
};

document.getElementById("resource-json").value = JSON.stringify(samplePatient, null, 2);

async function api(path, options = {}) {
  const res = await fetch(path, {
    ...options,
    headers: {
      "Content-Type": "application/json",
      ...(options.headers || {})
    },
    credentials: "include"
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    throw new Error(data.detail || data.error || JSON.stringify(data));
  }
  return data;
}

document.getElementById("login-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  try {
    const payload = {
      username: document.getElementById("username").value,
      password: document.getElementById("password").value
    };
    await api("/auth/login", { method: "POST", body: JSON.stringify(payload) });
    const me = await api("/auth/me");
    meEl.textContent = JSON.stringify(me, null, 2);
  } catch (err) {
    meEl.textContent = String(err.message || err);
  }
});

document.getElementById("create-entry").addEventListener("click", async () => {
  try {
    const policy = document.getElementById("policy").value;
    const resource = JSON.parse(document.getElementById("resource-json").value);
    const payload = { resource };
    if (policy.trim()) {
      payload.policy_expression = policy;
    }
    const out = await api("/entries", { method: "POST", body: JSON.stringify(payload) });
    createOutEl.textContent = JSON.stringify(out, null, 2);
    document.getElementById("entry-id").value = out.entry_id;
  } catch (err) {
    createOutEl.textContent = String(err.message || err);
  }
});

document.getElementById("search-btn").addEventListener("click", async () => {
  try {
    const q = new URLSearchParams();
    const name = document.getElementById("search-name").value.trim();
    const cpf = document.getElementById("search-cpf").value.trim();
    const birthdate = document.getElementById("search-birthdate").value.trim();
    if (name) q.set("name", name);
    if (cpf) q.set("cpf", cpf);
    if (birthdate) q.set("birthdate", birthdate);
    const out = await api(`/entries/search?${q.toString()}`);
    searchOutEl.textContent = JSON.stringify(out, null, 2);
  } catch (err) {
    searchOutEl.textContent = String(err.message || err);
  }
});

document.getElementById("decrypt-btn").addEventListener("click", async () => {
  try {
    const entryId = document.getElementById("entry-id").value.trim();
    const out = await api(`/entries/${entryId}/decrypt-package`, { method: "POST" });
    decryptOutEl.textContent = JSON.stringify(out, null, 2);
  } catch (err) {
    decryptOutEl.textContent = String(err.message || err);
  }
});
