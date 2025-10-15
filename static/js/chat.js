let sessionId = null;

const chatBox = document.getElementById("chat-box");
const userInput = document.getElementById("user-input");
const sendBtn = document.getElementById("send-btn");
const summaryBtn = document.getElementById("summary-btn");
const escalateBtn = document.getElementById("escalate-btn");

function addMessage(sender, text) {
  const p = document.createElement("p");
  // allow some HTML for bold labels in summary responses
  p.innerHTML = `<strong>${sender}:</strong> ${text}`;
  chatBox.appendChild(p);
  chatBox.scrollTop = chatBox.scrollHeight;
}

async function sendMessage() {
  const message = userInput.value.trim();
  if (!message) return;
  addMessage("You", message);
  userInput.value = "";
  sendBtn.disabled = true;

  try {
    const res = await fetch("/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message, session_id: sessionId }),
    });

    const data = await res.json();
    if (data.error) {
      addMessage("Clara", "Error: " + data.error);
    } else {
      sessionId = data.session_id;
      addMessage("Clara", data.reply);
    }
  } catch (err) {
    addMessage("Clara", "Network error. Please retry.");
  } finally {
    sendBtn.disabled = false;
  }
}

async function requestSummary() {
  if (!sessionId) {
    addMessage("Clara", "Start a conversation first to summarize.");
    return;
  }
  addMessage("You", "[Requesting summary]");
  summaryBtn.disabled = true;
  try {
    const res = await fetch("/summarize", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ session_id: sessionId }),
    });
    const data = await res.json();
    if (data.error) {
      addMessage("Clara", "Error: " + data.error);
    } else {
      addMessage("Clara", `<strong>Summary:</strong> ${data.summary}`);
      if (data.next_actions && data.next_actions.length) {
        addMessage(
          "Clara",
          `<strong>Next actions:</strong> ${data.next_actions.join("; ")}`
        );
      }
    }
  } catch (err) {
    addMessage("Clara", "Unable to get summary.");
  } finally {
    summaryBtn.disabled = false;
  }
}

async function requestEscalation() {
  if (!sessionId) {
    addMessage("Clara", "Start a conversation first to escalate.");
    return;
  }
  addMessage("You", "[Requesting escalation]");
  escalateBtn.disabled = true;
  try {
    const res = await fetch("/escalate", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ session_id: sessionId }),
    });
    const data = await res.json();
    if (data.error) {
      addMessage("Clara", "Error: " + data.error);
    } else if (data.ticket_id) {
      addMessage(
        "Clara",
        `Escalation created. Ticket #${data.ticket_id} — status: ${data.status}`
      );
    } else {
      addMessage("Clara", "Escalation failed.");
    }
  } catch (err) {
    addMessage("Clara", "Unable to escalate right now.");
  } finally {
    escalateBtn.disabled = false;
  }
}

sendBtn.addEventListener("click", sendMessage);
userInput.addEventListener("keydown", (e) => {
  if (e.key === "Enter") sendMessage();
});
summaryBtn.addEventListener("click", requestSummary);
escalateBtn.addEventListener("click", requestEscalation);
