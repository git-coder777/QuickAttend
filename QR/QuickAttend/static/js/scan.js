// Student scan page: opens the camera, reads the QR, asks the server if it is valid.

const scanCard = document.getElementById("scan-card");
const detailsCard = document.getElementById("details-card");
const errorBox = document.getElementById("error-box");
const successBox = document.getElementById("success-box");
const camMsg = document.getElementById("cam-msg");
const retryBtn = document.getElementById("retry-btn");

let scanner = null;
let busy = false;

function showError(message) {
  errorBox.textContent = message;
  errorBox.classList.remove("hidden");
}

function startScanner() {
  errorBox.classList.add("hidden");
  retryBtn.classList.add("hidden");
  busy = false;

  scanner = new Html5Qrcode("reader");
  scanner.start(
    { facingMode: "environment" },
    { fps: 10, qrbox: { width: 220, height: 220 } },
    onScanSuccess,
    () => {}                       // ignore "no QR found yet" messages
  ).catch(() => {
    camMsg.textContent = "Camera could not be opened. Allow camera permission, or type the code below.";
  });
}

function stopScanner() {
  if (scanner) {
    scanner.stop().catch(() => {});
  }
}

function onScanSuccess(text) {
  if (busy) return;
  busy = true;
  stopScanner();
  sendCode(text);
}

async function sendCode(code) {
  const response = await fetch("/student/scan", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ code: code })
  });
  const data = await response.json();

  if (data.ok) {
    document.getElementById("d-subject").textContent = data.subject;
    document.getElementById("d-class").textContent = data.class_name;
    document.getElementById("d-teacher").textContent = data.teacher;
    document.getElementById("d-time").textContent = data.time;
    document.getElementById("d-date").textContent = data.date;
    scanCard.classList.add("hidden");
    detailsCard.classList.remove("hidden");
  } else {
    showError(data.message);
    retryBtn.classList.remove("hidden");
  }
}

document.getElementById("present-btn").onclick = async function () {
  this.disabled = true;
  const response = await fetch("/student/mark", { method: "POST" });
  const data = await response.json();

  if (data.ok) {
    detailsCard.classList.add("hidden");
    successBox.classList.remove("hidden");
  } else {
    showError(data.message);
    this.disabled = false;
  }
};

document.getElementById("manual-btn").onclick = function () {
  const code = document.getElementById("manual-code").value.trim();
  if (code.length === 6) {
    stopScanner();
    sendCode(code);
  } else {
    showError("Please enter the 6 digit code.");
  }
};

retryBtn.onclick = startScanner;

startScanner();
