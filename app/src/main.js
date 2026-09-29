const RETRY_INTERVAL_SECONDS = 3;

let secondsRemaining = RETRY_INTERVAL_SECONDS;
let checking = false;

const statusText = document.querySelector("#status-text");
const retrySeconds = document.querySelector("#retry-seconds");
const retryButton = document.querySelector("#retry-button");
const hotkeyLabel = document.querySelector("#hotkey-label");

async function retryBackend() {
  if (checking) {
    return;
  }

  checking = true;
  retryButton.disabled = true;
  statusText.textContent = "backend に接続しています…";

  try {
    const online = await window.__TAURI__.core.invoke("retry_backend");
    if (!online) {
      statusText.textContent = "まだ応答がありません — 再試行を続けます";
    }
  } catch (error) {
    console.error("backend retry failed", error);
    statusText.textContent = "接続確認に失敗しました — 再試行を続けます";
  } finally {
    checking = false;
    retryButton.disabled = false;
    secondsRemaining = RETRY_INTERVAL_SECONDS;
    retrySeconds.textContent = secondsRemaining;
  }
}

retryButton.addEventListener("click", retryBackend);

window.__TAURI__.core
  .invoke("active_hotkey")
  .then((hotkey) => {
    hotkeyLabel.textContent =
      hotkey === "unavailable" ? "hotkey unavailable" : hotkey;
  })
  .catch((error) => {
    console.error("failed to read active hotkey", error);
    hotkeyLabel.textContent = "hotkey unavailable";
  });

window.setInterval(() => {
  if (checking) {
    return;
  }

  secondsRemaining -= 1;
  retrySeconds.textContent = Math.max(secondsRemaining, 0);

  if (secondsRemaining <= 0) {
    retryBackend();
  }
}, 1000);
