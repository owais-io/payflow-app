"use strict";

// Relative, same-origin paths (1.5.2). In Kubernetes the Ingress routes /api/accounts to
// accounts-api and /api/payments to payments-api and strips the /api prefix; locally,
// frontend/dev/nginx.local.conf does the same. No hostnames here, so no CORS.
const API = {
  accounts: "/api/accounts",
  payments: "/api/payments",
};

const STORAGE_KEY = "payflow.accounts";
const HISTORY_LIMIT = 50;
const MONEY_PATTERN = /^\d{1,10}(\.\d{1,2})?$/; // NUMERIC(12,2): up to 10 digits, 2 decimals
const UUID_PATTERN = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

const $ = (id) => document.getElementById(id);

// --- API calls ---------------------------------------------------------------

class ApiError extends Error {
  constructor(status, message) {
    super(message);
    this.status = status;
  }
}

// FastAPI errors are {"detail": "..."}, or {"detail": [{"msg": ...}, ...]} for 422.
function errorMessage(status, body) {
  const detail = body && body.detail;
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail) && detail.length > 0 && detail[0].msg) return detail[0].msg;
  if (status === 502 || status === 504) return "The service is not reachable right now.";
  return `Request failed (HTTP ${status}).`;
}

async function api(path, options = {}) {
  let response;
  try {
    response = await fetch(path, {
      ...options,
      headers: { Accept: "application/json", ...(options.body ? { "Content-Type": "application/json" } : {}) },
    });
  } catch {
    throw new ApiError(0, "Can't reach the server. Is it running?");
  }
  let body = null;
  try {
    body = await response.json();
  } catch {
    // non-JSON body, e.g. an nginx error page
  }
  if (!response.ok) throw new ApiError(response.status, errorMessage(response.status, body));
  return body;
}

const createAccount = (ownerName, initialBalance) =>
  api(API.accounts, {
    method: "POST",
    body: JSON.stringify({ owner_name: ownerName, initial_balance: initialBalance }),
  });
const getAccount = (id) => api(`${API.accounts}/${encodeURIComponent(id)}`);
const getBalance = (id) => api(`${API.accounts}/${encodeURIComponent(id)}/balance`);
const createPayment = (fromId, toId, amount) =>
  api(API.payments, {
    method: "POST",
    body: JSON.stringify({ from_account_id: fromId, to_account_id: toId, amount }),
  });
const listPayments = (accountId) =>
  api(`${API.payments}?${new URLSearchParams({ account_id: accountId, limit: HISTORY_LIMIT })}`);

// --- State: which accounts this browser knows ----------------------------------

// [{ id, owner_name }]. Only IDs and names are stored; balances are always fetched.
let accounts = loadAccounts();
const balances = new Map(); // id -> "1000.00" | null (not found) | undefined (not loaded)

function loadAccounts() {
  try {
    const saved = JSON.parse(localStorage.getItem(STORAGE_KEY) || "[]");
    return Array.isArray(saved) ? saved.filter((a) => a && UUID_PATTERN.test(a.id)) : [];
  } catch {
    return [];
  }
}

function saveAccounts() {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(accounts));
  } catch {
    // private mode or storage full: the page still works for this visit
  }
}

function rememberAccount(account) {
  if (!accounts.some((a) => a.id === account.id)) {
    accounts.push({ id: account.id, owner_name: account.owner_name });
    saveAccounts();
  }
  balances.set(account.id, account.balance);
}

function forgetAccount(id) {
  accounts = accounts.filter((a) => a.id !== id);
  balances.delete(id);
  saveAccounts();
}

const ownerOf = (id) => accounts.find((a) => a.id === id)?.owner_name;

// --- Formatting ------------------------------------------------------------------

const shortId = (id) => id.slice(0, 8);

// Money stays a string end to end, so 0.1 + 0.2 problems never appear.
function formatMoney(amount) {
  const [whole, fraction = "00"] = String(amount).split(".");
  return `PKR ${whole.replace(/\B(?=(\d{3})+(?!\d))/g, ",")}.${fraction.padEnd(2, "0")}`;
}

const formatDate = (iso) =>
  new Date(iso).toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" });

function setStatus(id, message, kind = "info") {
  const el = $(id);
  el.textContent = message;
  el.dataset.kind = kind;
}

// Every value from the API goes in through textContent, never innerHTML.
function cell(text, className) {
  const td = document.createElement("td");
  td.textContent = text;
  if (className) td.className = className;
  return td;
}

function button(label, onClick, className = "link") {
  const b = document.createElement("button");
  b.type = "button";
  b.className = className;
  b.textContent = label;
  b.addEventListener("click", onClick);
  return b;
}

// Disables the form while a request is in flight, so a double click can't send twice.
async function busy(form, work) {
  const controls = form.querySelectorAll("button, input, select");
  controls.forEach((c) => (c.disabled = true));
  try {
    await work();
  } finally {
    controls.forEach((c) => (c.disabled = false));
  }
}

// --- Rendering -----------------------------------------------------------------

function renderAccounts() {
  const body = $("accounts-body");
  body.replaceChildren();
  $("no-accounts").hidden = accounts.length > 0;
  $("accounts-table").hidden = accounts.length === 0;

  for (const account of accounts) {
    const row = document.createElement("tr");
    const balance = balances.get(account.id);

    const idCell = document.createElement("td");
    const code = document.createElement("code");
    code.textContent = shortId(account.id);
    code.title = account.id;
    idCell.append(code, " ", button("Copy", () => copyId(account.id)));

    const balanceText =
      balance === undefined ? "…" : balance === null ? "not found" : formatMoney(balance);

    const actions = document.createElement("td");
    actions.className = "actions";
    actions.append(
      button("History", () => showHistory(account.id)),
      button("Remove", () => {
        forgetAccount(account.id);
        renderAll();
      }),
    );

    row.append(cell(account.owner_name), idCell, cell(balanceText, "num"), actions);
    body.append(row);
  }
}

function fillSelect(select, placeholder) {
  const previous = select.value;
  select.replaceChildren(new Option(placeholder, ""));
  for (const account of accounts) {
    select.append(new Option(`${account.owner_name} (${shortId(account.id)})`, account.id));
  }
  if (accounts.some((a) => a.id === previous)) select.value = previous;
}

function renderAll() {
  renderAccounts();
  fillSelect($("from-account"), "Choose an account");
  fillSelect($("to-account"), "Choose an account");
  fillSelect($("history-account"), "Choose an account");
}

async function refreshBalances() {
  setStatus("accounts-status", "");
  const results = await Promise.allSettled(accounts.map((a) => getBalance(a.id)));
  results.forEach((result, i) => {
    const id = accounts[i].id;
    if (result.status === "fulfilled") {
      balances.set(id, result.value.balance);
    } else if (result.reason.status === 404) {
      balances.set(id, null);
    } else {
      setStatus("accounts-status", result.reason.message, "error");
    }
  });
  renderAccounts();
}

async function copyId(id) {
  try {
    await navigator.clipboard.writeText(id);
    setStatus("accounts-status", `Copied ${id}`, "success");
  } catch {
    setStatus("accounts-status", id, "info"); // no clipboard access (plain http): show it instead
  }
}

async function showHistory(accountId) {
  $("history-account").value = accountId;
  const body = $("history-body");
  setStatus("history-status", "");
  if (!accountId) {
    body.replaceChildren();
    $("history-table").hidden = true;
    $("no-history").hidden = false;
    $("no-history").textContent = "Pick an account to see its payments.";
    return;
  }

  let payments;
  try {
    payments = await listPayments(accountId);
  } catch (err) {
    setStatus("history-status", err.message, "error");
    return;
  }

  body.replaceChildren();
  $("history-table").hidden = payments.length === 0;
  $("no-history").hidden = payments.length > 0;
  $("no-history").textContent = "No payments for this account yet.";

  for (const p of payments) {
    const sent = p.from_account_id === accountId;
    const other = sent ? p.to_account_id : p.from_account_id;
    const row = document.createElement("tr");
    row.append(
      cell(formatDate(p.created_at)),
      cell(sent ? "Sent" : "Received"),
      cell(ownerOf(other) ?? shortId(other)),
      cell(`${sent ? "−" : "+"} ${formatMoney(p.amount)}`, `num ${sent ? "out" : "in"}`),
    );
    body.append(row);
  }
  if (payments.length === HISTORY_LIMIT) {
    setStatus("history-status", `Showing the latest ${HISTORY_LIMIT} payments.`);
  }
}

// --- Forms -----------------------------------------------------------------------

$("create-form").addEventListener("submit", (event) => {
  event.preventDefault();
  const form = event.currentTarget;
  const ownerName = form.owner_name.value.trim();
  const initialBalance = form.initial_balance.value.trim() || "0.00";

  if (!ownerName) return setStatus("create-status", "Enter the owner's name.", "error");
  if (!MONEY_PATTERN.test(initialBalance)) {
    return setStatus("create-status", "Balance must be a number like 1000 or 1000.50.", "error");
  }

  busy(form, async () => {
    try {
      const account = await createAccount(ownerName, initialBalance);
      rememberAccount(account);
      renderAll();
      form.reset();
      setStatus(
        "create-status",
        `Created ${account.owner_name}'s account with ${formatMoney(account.balance)}.`,
        "success",
      );
    } catch (err) {
      setStatus("create-status", err.message, "error");
    }
  });
});

$("add-form").addEventListener("submit", (event) => {
  event.preventDefault();
  const form = event.currentTarget;
  const id = form.account_id.value.trim();
  if (!UUID_PATTERN.test(id)) return setStatus("add-status", "That is not a valid account ID.", "error");

  busy(form, async () => {
    try {
      const account = await getAccount(id);
      rememberAccount(account);
      renderAll();
      form.reset();
      setStatus("add-status", `Added ${account.owner_name}'s account.`, "success");
    } catch (err) {
      setStatus("add-status", err.status === 404 ? "No account with that ID." : err.message, "error");
    }
  });
});

$("transfer-form").addEventListener("submit", (event) => {
  event.preventDefault();
  const form = event.currentTarget;
  const fromId = form.from_account_id.value;
  const toId = form.to_account_id.value;
  const amount = form.amount.value.trim();

  if (!fromId || !toId) return setStatus("transfer-status", "Choose both accounts.", "error");
  if (fromId === toId) return setStatus("transfer-status", "Choose two different accounts.", "error");
  if (!MONEY_PATTERN.test(amount) || Number(amount) <= 0) {
    return setStatus("transfer-status", "Amount must be more than 0, like 250 or 250.50.", "error");
  }

  busy(form, async () => {
    try {
      const payment = await createPayment(fromId, toId, amount);
      form.amount.value = "";
      setStatus(
        "transfer-status",
        `Sent ${formatMoney(payment.amount)} to ${ownerOf(toId)}. Payment ${shortId(payment.id)}.`,
        "success",
      );
    } catch (err) {
      // 409 insufficient funds, 404 unknown account, 503 accounts-api down: the API's own words.
      setStatus("transfer-status", err.message, "error");
      return;
    }
    await refreshBalances();
    const shown = $("history-account").value;
    if (shown === fromId || shown === toId) await showHistory(shown);
  });
});

$("history-account").addEventListener("change", (event) => showHistory(event.target.value));
$("refresh-balances").addEventListener("click", refreshBalances);

// --- Start -----------------------------------------------------------------------

renderAll();
refreshBalances();
