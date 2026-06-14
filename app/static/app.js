// --- State ---
let imageBase64 = null;
let imageMimeType = null;

// --- Elements ---
const form        = document.getElementById("verify-form");
const uploadZone  = document.getElementById("upload-zone");
const uploadPrompt = document.getElementById("upload-prompt");
const fileInput   = document.getElementById("file-input");
const preview     = document.getElementById("preview");
const clearBtn    = document.getElementById("clear-btn");
const submitBtn   = document.getElementById("submit-btn");
const errorMsg    = document.getElementById("error-msg");
const results     = document.getElementById("results");

// --- Upload zone interactions ---

uploadZone.addEventListener("click", () => fileInput.click());

uploadZone.addEventListener("keydown", (e) => {
  if (e.key === "Enter" || e.key === " ") fileInput.click();
});

uploadZone.addEventListener("dragover", (e) => {
  e.preventDefault();
  uploadZone.classList.add("drag-over");
});

uploadZone.addEventListener("dragleave", () => {
  uploadZone.classList.remove("drag-over");
});

uploadZone.addEventListener("drop", (e) => {
  e.preventDefault();
  uploadZone.classList.remove("drag-over");
  processFile(e.dataTransfer.files[0]);
});

fileInput.addEventListener("change", (e) => {
  processFile(e.target.files[0]);
});

clearBtn.addEventListener("click", (e) => {
  e.stopPropagation();
  clearImage();
});

// Shrink large photos in the browser before upload: smaller payload, and the
// server's (free-tier) CPU doesn't do the heavy resize. 1280 matches
// MAX_IMAGE_SIDE in the extractor, so the server's own resize becomes a no-op.
const MAX_UPLOAD_SIDE = 1280;

async function downscaleToJpeg(file, maxSide) {
  // createImageBitmap applies the photo's EXIF rotation, so sideways phone
  // shots come out upright (and we re-encode, which strips the EXIF tag).
  const bitmap = await createImageBitmap(file, { imageOrientation: "from-image" });
  const scale = Math.min(1, maxSide / Math.max(bitmap.width, bitmap.height)); // never upscale
  const width = Math.round(bitmap.width * scale);
  const height = Math.round(bitmap.height * scale);

  const canvas = document.createElement("canvas");
  canvas.width = width;
  canvas.height = height;
  canvas.getContext("2d").drawImage(bitmap, 0, 0, width, height);
  bitmap.close?.();

  return canvas.toDataURL("image/jpeg", 0.85);
}

function setImage(dataUrl, mimeType) {
  imageBase64 = dataUrl.split(",")[1];
  imageMimeType = mimeType;

  preview.src = dataUrl;
  preview.classList.remove("hidden");
  uploadPrompt.classList.add("hidden");
  clearBtn.classList.remove("hidden");
  submitBtn.disabled = false;
  hideError();
}

async function processFile(file) {
  if (!file) return;

  const allowed = ["image/jpeg", "image/png", "image/webp"];
  if (!allowed.includes(file.type)) {
    showError("Please upload a JPEG, PNG, or WebP image.");
    return;
  }
  if (file.size > 15 * 1024 * 1024) {
    showError("Image must be under 15 MB.");
    return;
  }

  try {
    setImage(await downscaleToJpeg(file, MAX_UPLOAD_SIDE), "image/jpeg");
  } catch (err) {
    // Older browser or resize failed — fall back to sending the original file.
    const reader = new FileReader();
    reader.onload = (e) => setImage(e.target.result, file.type);
    reader.readAsDataURL(file);
  }
}

function clearImage() {
  imageBase64 = null;
  imageMimeType = null;
  preview.src = "";
  preview.classList.add("hidden");
  uploadPrompt.classList.remove("hidden");
  clearBtn.classList.add("hidden");
  fileInput.value = "";
  submitBtn.disabled = true;
}

// --- Form submission ---

form.addEventListener("submit", async (e) => {
  e.preventDefault();
  hideError();
  results.innerHTML = "";
  results.classList.add("hidden");

  submitBtn.disabled = true;
  submitBtn.textContent = "Verifying label...";

  const application = {
    brand_name:        document.getElementById("brand_name").value.trim(),
    class_type:        document.getElementById("class_type").value.trim(),
    alcohol_content:   document.getElementById("alcohol_content").value.trim(),
    net_contents:      document.getElementById("net_contents").value.trim(),
    bottler_info:      document.getElementById("bottler_info").value.trim(),
    country_of_origin: document.getElementById("country_of_origin").value.trim(),
  };

  try {
    const res = await fetch("/api/verify", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        image_base64: imageBase64,
        mime_type: imageMimeType,
        application,
      }),
    });

    if (!res.ok) {
      const data = await res.json().catch(() => ({}));
      throw new Error(data.detail || "Verification failed.");
    }

    renderResults(await res.json());
  } catch (err) {
    showError(err.message || "Something went wrong. Please try again.");
  } finally {
    // Only re-enable if an image is still loaded (user may have cleared it mid-request)
    submitBtn.disabled = !imageBase64;
    submitBtn.textContent = "Verify Label";
  }
});

// --- Render results ---

function renderResults(data) {
  const passed = data.overall_status === "pass";
  const secs   = (data.processing_time_ms / 1000).toFixed(1);

  const verdict = `
    <div class="verdict ${passed ? "pass" : "fail"}">
      <div class="verdict-icon">${passed ? "✓" : "✗"}</div>
      <div>
        <div class="verdict-title">${passed ? "Label Approved" : "Label Rejected"}</div>
        <div class="verdict-sub">Processed in ${secs}s</div>
      </div>
    </div>`;

  // Append government warning as a regular row for uniform display
  const warningRow = {
    field:    "government_warning",
    label:    "Government Warning Statement",
    status:   data.government_warning.status,
    expected: null,
    found:    data.government_warning.found,
    note:     data.government_warning.note,
  };

  const rows = [...data.fields, warningRow].map(renderRow).join("");
  const table = `<div class="field-table">${rows}</div>`;

  results.innerHTML = verdict + table;
  results.classList.remove("hidden");
  results.scrollIntoView({ behavior: "smooth", block: "nearest" });
}

function renderRow(field) {
  const pass = field.status === "pass";

  let detail = "";
  if (!pass) {
    const expected = field.expected
      ? `<div><strong>Expected:</strong> ${esc(field.expected)}</div>`
      : "";
    const found = `<div><strong>Found:</strong> ${field.found ? esc(field.found) : "<em>not found</em>"}</div>`;
    const note  = field.note ? `<div class="mismatch">${esc(field.note)}</div>` : "";
    detail = `<div class="field-detail">${expected}${found}${note}</div>`;
  } else if (field.note) {
    detail = `<div class="field-detail"><span class="ok">${esc(field.note)}</span></div>`;
  }

  return `
    <div class="field-row">
      <span class="badge ${pass ? "pass" : "fail"}">${pass ? "PASS" : "FAIL"}</span>
      <div>
        <div class="field-name">${esc(field.label)}</div>
        ${detail}
      </div>
    </div>`;
}

// --- Helpers ---

function showError(msg) {
  errorMsg.textContent = msg;
  errorMsg.classList.remove("hidden");
}

function hideError() {
  errorMsg.classList.add("hidden");
}

function esc(str) {
  return String(str)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}
