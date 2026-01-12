// WebSocket connection
let ws = null;
let reconnectInterval = null;
const WS_URL = `ws://${window.location.host}/ws`;

// Charts
let pnlChart = null;
let positionChart = null;

// Data history
const pnlHistory = [];
const positionHistory = [];
const maxHistoryLength = 50;

// Initialize
document.addEventListener("DOMContentLoaded", () => {
  initCharts();
  connectWebSocket();
  fetchInitialData();
});

// WebSocket Connection
function connectWebSocket() {
  try {
    ws = new WebSocket(WS_URL);

    ws.onopen = () => {
      console.log("WebSocket connected");
      updateConnectionStatus(true);
      clearInterval(reconnectInterval);
    };

    ws.onmessage = (event) => {
      const message = JSON.parse(event.data);
      handleWebSocketMessage(message);
    };

    ws.onerror = (error) => {
      console.error("WebSocket error:", error);
      updateConnectionStatus(false);
    };

    ws.onclose = () => {
      console.log("WebSocket disconnected");
      updateConnectionStatus(false);

      // Reconnect after 3 seconds
      reconnectInterval = setInterval(() => {
        console.log("Attempting to reconnect...");
        connectWebSocket();
      }, 3000);
    };
  } catch (error) {
    console.error("Failed to connect WebSocket:", error);
    updateConnectionStatus(false);
  }
}

function handleWebSocketMessage(message) {
  if (message.type === "update" || message.type === "init") {
    updateDashboard(message.data);
  } else if (message.type === "ping") {
    // Send pong
    if (ws && ws.readyState === WebSocket.OPEN) {
      ws.send(JSON.stringify({ type: "pong" }));
    }
  }
}

// Fetch initial data via HTTP
async function fetchInitialData() {
  try {
    const response = await fetch("/api/metrics");
    const data = await response.json();
    if (!data.error) {
      updateDashboard(data);
    }
  } catch (error) {
    console.error("Failed to fetch initial data:", error);
  }
}

// Update connection status
function updateConnectionStatus(connected) {
  const statusDot = document.getElementById("connectionStatus");
  const statusText = document.getElementById("connectionText");

  if (connected) {
    statusDot.classList.add("connected");
    statusText.textContent = "已連接";
  } else {
    statusDot.classList.remove("connected");
    statusText.textContent = "未連接";
  }
}

// Update dashboard with new data
function updateDashboard(data) {
  // Summary cards
  updateSummaryCards(data);

  // Performance metrics
  updatePerformanceMetrics(data);

  // Order statistics
  updateOrderStatistics(data);

  // Uptime program
  updateUptimeProgram(data);

  // Charts
  updateCharts(data);

  // Last update time
  document.getElementById("lastUpdate").textContent =
    new Date().toLocaleTimeString("zh-TW");
}

function updateSummaryCards(data) {
  // Total PnL
  const totalPnl = data.total_pnl || 0;
  const totalPnlEl = document.getElementById("totalPnl");
  totalPnlEl.textContent = formatCurrency(totalPnl);
  totalPnlEl.className = "card-value " + getPnlClass(totalPnl);

  const realized = data.realized_pnl || 0;
  const unrealized = data.unrealized_pnl || 0;
  document.getElementById("pnlChange").textContent = `已實現: ${formatCurrency(
    realized
  )} | 未實現: ${formatCurrency(unrealized)}`;

  // Runtime
  const runtime = data.runtime_hours || 0;
  document.getElementById("runtime").textContent = `${runtime.toFixed(1)}h`;
  const hourlyPnl = runtime > 0 ? totalPnl / runtime : 0;
  document.getElementById("runtimeDetail").textContent = `${formatCurrency(
    hourlyPnl
  )}/hr`;

  // Position
  const position = data.current_position || 0;
  const posEl = document.getElementById("position");
  posEl.textContent = `${position >= 0 ? "+" : ""}${position.toFixed(4)} BTC`;
  posEl.className =
    "card-value " +
    (position > 0 ? "positive" : position < 0 ? "negative" : "neutral");
  document.getElementById("positionValue").textContent = `周轉率: ${(
    data.inventory_turnover || 0
  ).toFixed(2)} 次/hr`;

  // Fill rate
  const fillRate = (data.fill_rate || 0) * 100;
  const fillRateEl = document.getElementById("fillRate");
  fillRateEl.textContent = `${fillRate.toFixed(1)}%`;
  fillRateEl.className = "card-value " + getFillRateClass(fillRate);
  document.getElementById("fillRateDetail").textContent = `${
    data.filled_orders || 0
  }/${data.total_orders || 0} 成交`;

  // Uptime
  const uptime = data.uptime_percentage || 0;
  const uptimeEl = document.getElementById("uptime");
  uptimeEl.textContent = `${uptime.toFixed(1)}%`;
  uptimeEl.className = "card-value " + getUptimeClass(uptime);
  document.getElementById("uptimeTier").textContent = getUptimeTier(uptime);
}

function updatePerformanceMetrics(data) {
  document.getElementById("realizedPnl").textContent = formatCurrency(
    data.realized_pnl || 0
  );
  document.getElementById("unrealizedPnl").textContent = formatCurrency(
    data.unrealized_pnl || 0
  );
  document.getElementById("totalVolume").textContent = `${(
    data.total_volume || 0
  ).toFixed(4)} BTC`;

  const hourlyPnl =
    (data.runtime_hours || 0) > 0
      ? (data.total_pnl || 0) / data.runtime_hours
      : 0;
  document.getElementById("hourlyPnl").textContent = `${formatCurrency(
    hourlyPnl
  )}/hr`;
}

function updateOrderStatistics(data) {
  document.getElementById("totalOrders").textContent = (
    data.total_orders || 0
  ).toLocaleString();
  document.getElementById("filledOrders").textContent = (
    data.filled_orders || 0
  ).toLocaleString();
  document.getElementById("cancelledOrders").textContent = (
    data.cancelled_orders || 0
  ).toLocaleString();
  document.getElementById("avgSpread").textContent = `${(
    data.average_spread_bps || 0
  ).toFixed(2)} bps`;
  document.getElementById("turnover").textContent = `${(
    data.inventory_turnover || 0
  ).toFixed(2)} 次/hr`;
}

function updateUptimeProgram(data) {
  const uptime = data.uptime_percentage || 0;

  // Progress bar
  document.getElementById("uptimeProgress").style.width = `${uptime}%`;
  document.getElementById("uptimePercentage").textContent = `${uptime.toFixed(
    1
  )}%`;

  // Reward tier
  const tier = getUptimeTier(uptime);
  document.getElementById("rewardTier").textContent = tier;

  // Qualified checks (simulated if not provided)
  const qualified = data.qualified_checks || 0;
  const total = data.total_checks || 0;
  document.getElementById(
    "qualifiedChecks"
  ).textContent = `${qualified}/${total}`;

  // Maker hours estimation
  const multiplier = uptime >= 70 ? 1.0 : uptime >= 50 ? 0.5 : 0;
  const makerHours = multiplier * 1.0; // Assuming 2 BTC orders
  document.getElementById("makerHours").textContent = `${makerHours.toFixed(
    2
  )}/hr`;

  const monthlyHours = makerHours * 24 * 30;
  document.getElementById("monthlyHours").textContent = `${monthlyHours.toFixed(
    0
  )} hrs`;

  // Fee tier
  const runtime = data.runtime_hours || 0;
  let feeTier = "";
  if (runtime >= 504) {
    feeTier = "💎 MM2 (2.0 bps taker + 0.5 bps maker)";
  } else if (runtime >= 360) {
    feeTier = "⭐ MM1 (2.25 bps taker + 0.25 bps maker)";
  } else {
    const progress1 = ((runtime / 360) * 100).toFixed(1);
    const progress2 = ((runtime / 504) * 100).toFixed(1);
    feeTier = `⚡ MM1: ${progress1}% | MM2: ${progress2}%`;
  }
  document.getElementById("feeTier").textContent = feeTier;
}

function updateCharts(data) {
  const timestamp = new Date().toLocaleTimeString("zh-TW", {
    hour: "2-digit",
    minute: "2-digit",
  });

  // PnL history
  pnlHistory.push({
    time: timestamp,
    realized: data.realized_pnl || 0,
    unrealized: data.unrealized_pnl || 0,
    total: data.total_pnl || 0,
  });

  if (pnlHistory.length > maxHistoryLength) {
    pnlHistory.shift();
  }

  // Position history
  positionHistory.push({
    time: timestamp,
    position: data.current_position || 0,
  });

  if (positionHistory.length > maxHistoryLength) {
    positionHistory.shift();
  }

  // Update charts
  updatePnlChart();
  updatePositionChart();
}

function initCharts() {
  // PnL Chart
  const pnlCtx = document.getElementById("pnlChart").getContext("2d");
  pnlChart = new Chart(pnlCtx, {
    type: "line",
    data: {
      labels: [],
      datasets: [
        {
          label: "總 PnL",
          data: [],
          borderColor: "#00d4aa",
          backgroundColor: "rgba(0, 212, 170, 0.1)",
          tension: 0.4,
          fill: true,
        },
        {
          label: "已實現 PnL",
          data: [],
          borderColor: "#3742fa",
          backgroundColor: "rgba(55, 66, 250, 0.1)",
          tension: 0.4,
          fill: true,
        },
      ],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: {
        legend: {
          labels: { color: "#e6e8f0" },
        },
      },
      scales: {
        x: {
          ticks: { color: "#a0a8c0" },
          grid: { color: "#2d3561" },
        },
        y: {
          ticks: { color: "#a0a8c0" },
          grid: { color: "#2d3561" },
        },
      },
    },
  });

  // Position Chart
  const posCtx = document.getElementById("positionChart").getContext("2d");
  positionChart = new Chart(posCtx, {
    type: "line",
    data: {
      labels: [],
      datasets: [
        {
          label: "倉位 (BTC)",
          data: [],
          borderColor: "#ffa502",
          backgroundColor: "rgba(255, 165, 2, 0.1)",
          tension: 0.4,
          fill: true,
        },
      ],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: {
        legend: {
          labels: { color: "#e6e8f0" },
        },
      },
      scales: {
        x: {
          ticks: { color: "#a0a8c0" },
          grid: { color: "#2d3561" },
        },
        y: {
          ticks: { color: "#a0a8c0" },
          grid: { color: "#2d3561" },
        },
      },
    },
  });
}

function updatePnlChart() {
  pnlChart.data.labels = pnlHistory.map((d) => d.time);
  pnlChart.data.datasets[0].data = pnlHistory.map((d) => d.total);
  pnlChart.data.datasets[1].data = pnlHistory.map((d) => d.realized);
  pnlChart.update("none");
}

function updatePositionChart() {
  positionChart.data.labels = positionHistory.map((d) => d.time);
  positionChart.data.datasets[0].data = positionHistory.map((d) => d.position);
  positionChart.update("none");
}

// Helper functions
function formatCurrency(value) {
  return `$${value >= 0 ? "+" : ""}${value.toFixed(2)}`;
}

function getPnlClass(value) {
  return value > 0 ? "positive" : value < 0 ? "negative" : "neutral";
}

function getFillRateClass(rate) {
  return rate > 70 ? "positive" : rate > 40 ? "neutral" : "negative";
}

function getUptimeClass(uptime) {
  return uptime >= 70 ? "positive" : uptime >= 50 ? "neutral" : "negative";
}

function getUptimeTier(uptime) {
  if (uptime >= 70) return "🟢 Boosted (1.0x)";
  if (uptime >= 50) return "🟡 Standard (0.5x)";
  return "⚪ Inactive (0x)";
}
