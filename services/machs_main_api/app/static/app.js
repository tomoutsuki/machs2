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
    const mode = document.getElementById("mode").value;
    const policy = document.getElementById("policy").value;
    const resource = JSON.parse(document.getElementById("resource-json").value);
    const payload = { mode, resource };
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
    const mode = document.getElementById("mode").value;
    const q = new URLSearchParams({ mode });
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

let lastDecryptPackage = null;

document.getElementById("decrypt-btn").addEventListener("click", async () => {
  try {
    const mode = document.getElementById("mode").value;
    const entryId = document.getElementById("entry-id").value.trim();
    const out = await api(`/entries/${entryId}/decrypt-package?mode=${mode}`, { method: "POST" });
    lastDecryptPackage = out;
    decryptOutEl.textContent = JSON.stringify(out, null, 2);
  } catch (err) {
    decryptOutEl.textContent = String(err.message || err);
  }
});

function b64ToBytes(b64) {
  const bin = atob(b64);
  const arr = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i += 1) {
    arr[i] = bin.charCodeAt(i);
  }
  return arr;
}

document.getElementById("run-client-decrypt").addEventListener("click", async () => {
  try {
    if (!lastDecryptPackage || !lastDecryptPackage.result || !lastDecryptPackage.result.client_decrypt_required) {
      throw new Error("No AES decrypt package available");
    }

    const r = lastDecryptPackage.result;
    const keyBytes = b64ToBytes(r.data_key_b64);
    const iv = b64ToBytes(r.iv_b64);
    const ct = b64ToBytes(r.ciphertext_b64);
    const tag = b64ToBytes(r.tag_b64);
    const aad = b64ToBytes(r.aad);

    const full = new Uint8Array(ct.length + tag.length);
    full.set(ct, 0);
    full.set(tag, ct.length);

    const cryptoKey = await crypto.subtle.importKey("raw", keyBytes, { name: "AES-GCM" }, false, ["decrypt"]);
    const plainBuf = await crypto.subtle.decrypt({ name: "AES-GCM", iv, additionalData: aad }, cryptoKey, full);
    const plain = new TextDecoder().decode(plainBuf);
    decryptOutEl.textContent = JSON.stringify({ client_plaintext_json: JSON.parse(plain) }, null, 2);
  } catch (err) {
    decryptOutEl.textContent = String(err.message || err);
  }
});
