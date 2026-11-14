const result = document.querySelector("#result");
const form = document.querySelector("#check-form");
const fileInput = document.querySelector("#file");
const preview = document.querySelector("#preview");
const claimInput = document.querySelector("#claim");
const urlInput = document.querySelector("#image-url");
const submit = document.querySelector("#submit");
const formError = document.querySelector("#form-error");
const drop = document.querySelector("#drop");
const demoList = document.querySelector("#demo-list");
const keys = document.querySelector("#keys");

let objectUrl = "";
let lastPayload = null;

const stageOrder = [
  ["vision", "Read the image"],
  ["credentials", "Content credentials"],
  ["youcom_search", "You.com search"],
  ["youcom_contents", "Read sources"],
  ["youcom_answer", "Cited synthesis"],
  ["reverse_image", "Reverse image"],
  ["detector", "AI-image prior"],
];

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

function klassFor(verdict) {
  if (verdict === "Likely Real") return "v-real";
  if (verdict === "Likely AI or Fake") return "v-fake";
  if (verdict === "Out of Context") return "v-ooc";
  return "v-unverified";
}

async function loadHealth() {
  const response = await fetch("/api/health");
  const data = await response.json();
  const items = [
    ["You.com", data.keys.youcom],
    ["Vision", data.keys.openai || data.keys.gemini],
    ["Treg", data.keys.treg],
    ["XDC paywall", data.keys.xdc_ai],
  ];
  keys.innerHTML = items
    .map(([name, on]) => `<span class="chip ${on ? "on" : ""}">${escapeHtml(name)} ${on ? "ready" : "add key"}</span>`)
    .join("");
}

async function loadDemos() {
  const response = await fetch("/api/demos");
  const data = await response.json();
  demoList.innerHTML = data.demos
    .map(
      (demo) => `<button type="button" class="demo" data-id="${escapeHtml(demo.id)}">
        <img src="${escapeHtml(demo.image)}" alt="">
        <span><strong>${escapeHtml(demo.title)}</strong><span>${escapeHtml(demo.blurb)}</span></span>
      </button>`
    )
    .join("");
  demoList.querySelectorAll(".demo").forEach((button) => {
    button.addEventListener("click", () => {
      const demo = data.demos.find((item) => item.id === button.dataset.id);
      claimInput.value = demo.claim;
      fileInput.value = "";
      if (objectUrl) URL.revokeObjectURL(objectUrl);
      preview.hidden = true;
      runCheck({ demo_id: demo.id, claim: demo.claim }, demo.image);
    });
  });
}

function showError(message) {
  formError.hidden = false;
  formError.textContent = message;
}

function showLoading() {
  formError.hidden = true;
  result.innerHTML = `<div class="loading">
    <p class="eyebrow">Checking</p>
    <h2>Reading the file and the story around it.</h2>
    <p>A live You.com lookup can take about half a minute. Sample checks without keys finish immediately.</p>
    <ol class="steps" id="steps">
      ${stageOrder.map(([id, label], index) => `<li class="${index < 2 ? "go" : ""}" data-step="${id}">${escapeHtml(label)}</li>`).join("")}
    </ol>
  </div>`;
  let step = 2;
  const timer = setInterval(() => {
    const rows = result.querySelectorAll(".steps li");
    if (!rows.length || step >= rows.length) {
      clearInterval(timer);
      return;
    }
    rows[step].classList.add("go");
    step += 1;
  }, 700);
  result.dataset.timer = String(timer);
}

function stopLoading() {
  const timer = Number(result.dataset.timer || 0);
  if (timer) clearInterval(timer);
}

function link(url, label) {
  if (!url) return escapeHtml(label);
  return `<a href="${escapeHtml(url)}" target="_blank" rel="noopener noreferrer">${escapeHtml(label)}</a>`;
}

function render(data, previewUrl) {
  stopLoading();
  const facts = ["who", "what", "where", "when"]
    .filter((name) => data.claim && data.claim[name])
    .map((name) => `<span>${escapeHtml(name)}: ${escapeHtml(data.claim[name])}</span>`)
    .join("");
  const clues = (data.clues || [])
    .map(
      (clue) => `<li class="clue">
        <span class="weight">${escapeHtml(clue.weight)}</span>
        <div><strong>${link(clue.url, clue.title)}</strong><p class="detail">${escapeHtml(clue.detail)}</p></div>
      </li>`
    )
    .join("");
  const timeline = (data.timeline || [])
    .map(
      (event) => `<li><strong>${escapeHtml(event.at || "undated")}</strong><div>${link(event.url, event.label)}</div></li>`
    )
    .join("");
  const sources = (data.sources || [])
    .map(
      (source) => `<li class="source">
        <strong>${link(source.url, source.title)}</strong>
        <div class="detail">${escapeHtml(source.outlet)}${source.page_age ? " · " + escapeHtml(source.page_age) : ""}</div>
        <p class="excerpt">${escapeHtml(source.excerpt || "")}</p>
      </li>`
    )
    .join("");
  const stages = stageOrder
    .map(([id, label]) => {
      const stage = (data.stages || {})[id] || {};
      return `<li><strong>${escapeHtml(label)}</strong> · ${escapeHtml(stage.status || "n/a")}<p class="detail">${escapeHtml(stage.detail || "")}</p></li>`;
    })
    .join("");
  const scores = data.scores || {};
  const shot = previewUrl ? `<img class="shot" src="${escapeHtml(previewUrl)}" alt="Image under check">` : "";
  result.innerHTML = `<article class="${klassFor(data.verdict)}">
    <div class="verdict-head">
      <div>
        <p class="kicker">Receipt · ${escapeHtml(data.receipt_id || "")}${data.cache && data.cache.hit ? " · cached" : ""}</p>
        <h2 class="verdict-word">${escapeHtml(data.verdict)}</h2>
      </div>
      <button type="button" class="ghost" id="copy">Copy JSON</button>
    </div>
    <div class="meter"><span><i style="width:${Number(data.confidence) || 0}%"></i></span><small>Confidence ${escapeHtml(data.confidence)}</small></div>
    <p class="summary">${escapeHtml(data.summary || "")}</p>
    ${shot}
    <div class="claim-box">
      <h3>Claim</h3>
      <p>${escapeHtml((data.claim && data.claim.text) || "No claim text.")}</p>
      <div class="facts">${facts}</div>
    </div>
    <div class="panel">
      <h3>Clues</h3>
      <ul class="clues">${clues}</ul>
    </div>
    <div class="panel">
      <h3>First seen / timeline</h3>
      <ul class="timeline">${timeline}</ul>
    </div>
    <div class="panel">
      <h3>Sources</h3>
      ${sources ? `<ul class="sources">${sources}</ul>` : `<p class="detail">No live sources on this receipt. Add YDC_API_KEY and run the check again.</p>`}
    </div>
    <div class="panel">
      <h3>How this was checked</h3>
      <p class="scores">signals · real ${escapeHtml(scores.real)} · fake ${escapeHtml(scores.fake)} · context ${escapeHtml(scores.out_of_context)} · detector ${escapeHtml(data.detector && data.detector.score)}</p>
      <ul class="stage-list">${stages}</ul>
    </div>
  </article>`;
  document.querySelector("#copy").addEventListener("click", async () => {
    const button = document.querySelector("#copy");
    const text = JSON.stringify(data, null, 2);
    try {
      await navigator.clipboard.writeText(text);
      button.textContent = "Copied";
    } catch (error) {
      button.textContent = "Select the JSON in the API docs";
    }
  });
}

async function runCheck(body, previewUrl) {
  lastPayload = body;
  submit.disabled = true;
  showLoading();
  try {
    const response = await fetch("/api/check", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    const data = await response.json();
    if (!response.ok) {
      stopLoading();
      result.innerHTML = `<div class="empty"><h2>Check did not run.</h2><p>${escapeHtml(data.detail || "Request failed.")}</p></div>`;
      return;
    }
    render(data, previewUrl || data.preview_url || "");
  } catch (error) {
    stopLoading();
    result.innerHTML = `<div class="empty"><h2>Check did not run.</h2><p>${escapeHtml(error.message || "Network error.")}</p></div>`;
  } finally {
    submit.disabled = false;
  }
}

function fileToBase64(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result).split(",")[1]);
    reader.onerror = () => reject(reader.error);
    reader.readAsDataURL(file);
  });
}

fileInput.addEventListener("change", () => {
  const file = fileInput.files && fileInput.files[0];
  if (!file) return;
  if (objectUrl) URL.revokeObjectURL(objectUrl);
  objectUrl = URL.createObjectURL(file);
  preview.src = objectUrl;
  preview.alt = file.name;
  preview.hidden = false;
});

["dragover", "dragenter"].forEach((name) => {
  drop.addEventListener(name, (event) => {
    event.preventDefault();
    drop.classList.add("hot");
  });
});
["dragleave", "drop"].forEach((name) => {
  drop.addEventListener(name, (event) => {
    event.preventDefault();
    drop.classList.remove("hot");
  });
});
drop.addEventListener("drop", (event) => {
  const file = event.dataTransfer.files && event.dataTransfer.files[0];
  if (!file) return;
  const transfer = new DataTransfer();
  transfer.items.add(file);
  fileInput.files = transfer.files;
  fileInput.dispatchEvent(new Event("change"));
});

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  const file = fileInput.files && fileInput.files[0];
  if (!file) {
    showError("Choose an image, or open one of the demo samples.");
    return;
  }
  formError.hidden = true;
  const image_base64 = await fileToBase64(file);
  const localPreview = objectUrl;
  await runCheck(
    {
      image_base64,
      media_type: file.type || "image/jpeg",
      filename: file.name,
      claim: claimInput.value,
      image_url: urlInput.value,
    },
    localPreview
  );
});

loadHealth();
loadDemos();
