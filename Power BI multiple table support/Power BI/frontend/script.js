// Global variables
let currentCharts = [];
let dbConfig = null;

// DOM Elements
const dbConfigForm = document.getElementById('dbConfigForm');
const queryInput = document.getElementById('queryInput');
const submitQueryBtn = document.getElementById('submitQuery');
const loadingIndicator = document.getElementById('loadingIndicator');
const errorMessage = document.getElementById('errorMessage');
const resultsSection = document.getElementById('resultsSection');
const metricsContainer = document.getElementById('metricsContainer');
const chartsContainer = document.getElementById('chartsContainer');
const insightsContainer = document.getElementById('insightsContainer');
const dataTable = document.getElementById('dataTable');
const historyContainer = document.getElementById('historyContainer');
const suggestionContainer = document.getElementById('suggestionContainer'); // New for Gemini suggestions

// Load saved configuration
function loadSavedConfig() {
    const savedConfig = localStorage.getItem('dbConfig');
    if (savedConfig) {
        dbConfig = JSON.parse(savedConfig);
        document.getElementById('dbType').value = dbConfig.driver;
        document.getElementById('server').value = dbConfig.server;
        document.getElementById('port').value = dbConfig.port;
        document.getElementById('database').value = dbConfig.database;
        document.getElementById('username').value = dbConfig.username;
        document.getElementById('password').value = dbConfig.password;
    }
}

// Save configuration
dbConfigForm.addEventListener('submit', async function(e) {
    e.preventDefault();

    dbConfig = {
        driver: document.getElementById('dbType').value,
        server: document.getElementById('server').value,
        port: parseInt(document.getElementById('port').value),
        database: document.getElementById('database').value,
        username: document.getElementById('username').value,
        password: document.getElementById('password').value
    };

    localStorage.setItem('dbConfig', JSON.stringify(dbConfig));
    showSuccess('Configuration saved successfully!');
    await testDbConnection(dbConfig);
});

// Test DB connection
async function testDbConnection(config) {
    try {
        const res = await fetch('http://localhost:8000/api/test-connection', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(config)
        });
        const data = await res.json();
        if (!res.ok) throw new Error(data.detail || 'Connection failed');
        showSuccess('Connection successful!');
    } catch (e) {
        showError('DB Connection failed: ' + e.message);
    }
}

// Handle query submission
submitQueryBtn.addEventListener('click', async function() {
    if (!dbConfig) {
        showError('Please save database configuration first');
        return;
    }

    const query = queryInput.value.trim();
    if (!query) {
        showError('Please enter a query');
        return;
    }

    try {
        showLoading();
        clearResults();

        const response = await fetch('http://localhost:8000/api/query', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ config: dbConfig, query: query })
        });

        const data = await response.json();
        if (!response.ok) throw new Error(data.detail || `Server responded with ${response.status}`);

        displayResults(data);
        saveToHistory(query, data);
    } catch (error) {
        console.error('Error details:', error);
        showError(error.message || 'An error occurred while processing your query');
    } finally {
        hideLoading();
    }
});

// Display results
function displayResults(data) {
    resultsSection.style.display = 'block';

    if (data.metrics && data.metrics.length > 0) {
        metricsContainer.innerHTML = data.metrics.map(metric => `
            <div class="col-md-4">
                <div class="card metric-card">
                    <div class="card-body">
                        <h6 class="card-title">${metric.title}</h6>
                        <p class="card-text">${formatMetricValue(metric.value)}</p>
                    </div>
                </div>
            </div>
        `).join('');
    }

    let showCharts = true;

    if (data.metadata && data.metadata.raw_data) {
        const rawData = data.metadata.raw_data;
        const labels = rawData.map(r => Object.values(r)[0]);

        if (labels.length > 50) {
            showCharts = false;
        }
    }

    if (showCharts && data.visualizations && data.visualizations.length > 0) {
        chartsContainer.innerHTML = data.visualizations.map((viz, index) => {
            const isPie = viz.type === 'pie';
            const maxItems = isPie ? 10 : undefined;
            if (isPie && viz.data.labels.length > 10) {
                viz.data.labels = viz.data.labels.slice(0, 10);
                viz.data.values = viz.data.values.slice(0, 10);
            }
            return `
                <div class="col-md-6">
                    <div class="card chart-card">
                        <div class="card-header d-flex justify-content-between align-items-center">
                            <h6>${viz.title}</h6>
                            <select onchange="changeChartType(${index}, this.value)">
                                <option value="bar">Bar</option>
                                <option value="line">Line</option>
                                <option value="pie">Pie</option>
                            </select>
                        </div>
                        <div class="card-body">
                            <canvas id="chart${index}"></canvas>
                        </div>
                    </div>
                </div>
            `;
        }).join('');
        data.visualizations.forEach((viz, index) => {
            createChart(`chart${index}`, viz);
        });
    }

    if (data.insights && data.insights.length > 0) {
        insightsContainer.innerHTML = data.insights.map(insight => `
            <div class="insight-item">
                <i class="fas fa-lightbulb"></i>
                <span>${insight}</span>
            </div>
        `).join('');
    }

    if (data.metadata && data.metadata.raw_data) {
        const rawData = data.metadata.raw_data;
        if (rawData.length > 0) {
            const headers = Object.keys(rawData[0]);
            dataTable.innerHTML = `
                <thead>
                    <tr>${headers.map(h => `<th>${h}</th>`).join('')}</tr>
                </thead>
                <tbody>
                    ${rawData.map(row => `
                        <tr>${headers.map(h => `<td>${formatTableCell(row[h])}</td>`).join('')}</tr>
                    `).join('')}
                </tbody>
            `;
        }
    }

    if (data.suggestions && data.suggestions.length > 0) {
        suggestionContainer.innerHTML = `
            <h5>Chart Suggestions from Gemini</h5>
            <ul class="list-group">
                ${data.suggestions.map(s => `<li class="list-group-item"><i class="fas fa-magic"></i> ${s}</li>`).join('')}
            </ul>
        `;
    } else {
        suggestionContainer.innerHTML = '';
    }
}

function changeChartType(index, newType) {
    const canvasId = `chart${index}`;
    const oldChart = currentCharts[index];
    if (oldChart) oldChart.destroy();

    const viz = {
        type: newType,
        title: oldChart.options.plugins.title.text,
        data: {
            labels: oldChart.data.labels,
            values: oldChart.data.datasets[0].data
        }
    };

    createChart(canvasId, viz);
}

function createChart(canvasId, visualization) {
    const ctx = document.getElementById(canvasId).getContext('2d');
    const chart = new Chart(ctx, {
        type: visualization.type,
        data: {
            labels: visualization.data.labels,
            datasets: [{
                data: visualization.data.values,
                backgroundColor: getChartColors(visualization.type),
                borderColor: getChartColors(visualization.type),
                borderWidth: 1
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                legend: { position: 'top' },
                title: { display: true, text: visualization.title }
            }
        }
    });
    currentCharts.push(chart);
}

function formatMetricValue(value) {
    if (typeof value === 'number') return value.toLocaleString();
    return value;
}

function formatTableCell(value) {
    if (value === null || value === undefined) return '';
    if (typeof value === 'number') return value.toLocaleString();
    if (typeof value === 'boolean') return value ? 'Yes' : 'No';
    return value;
}

function getChartColors(type) {
    const colors = {
        bar: ['#4e73df', '#1cc88a', '#36b9cc', '#f6c23e', '#e74a3b'],
        line: ['#4e73df'],
        pie: ['#4e73df', '#1cc88a', '#36b9cc', '#f6c23e', '#e74a3b']
    };
    return colors[type] || colors.bar;
}

function showLoading() {
    loadingIndicator.style.display = 'flex';
    submitQueryBtn.disabled = true;
}

function hideLoading() {
    loadingIndicator.style.display = 'none';
    submitQueryBtn.disabled = false;
}

function showError(message) {
    errorMessage.textContent = message;
    errorMessage.style.display = 'block';
    console.error('Error:', message);
    setTimeout(() => errorMessage.style.display = 'none', 5000);
}

function showSuccess(message) {
    const successAlert = document.createElement('div');
    successAlert.className = 'alert alert-success alert-dismissible fade show';
    successAlert.innerHTML = `
        ${message}
        <button type="button" class="btn-close" data-bs-dismiss="alert" aria-label="Close"></button>
    `;
    document.querySelector('.container-fluid').insertBefore(successAlert, document.querySelector('.container-fluid').firstChild);
    setTimeout(() => successAlert.remove(), 3000);
}

function clearResults() {
    currentCharts.forEach(chart => chart.destroy());
    currentCharts = [];
    metricsContainer.innerHTML = '';
    chartsContainer.innerHTML = '';
    insightsContainer.innerHTML = '';
    dataTable.innerHTML = '';
    suggestionContainer.innerHTML = '';
    resultsSection.style.display = 'none';
}

function saveToHistory(query, data) {
    const history = JSON.parse(localStorage.getItem('queryHistory') || '[]');
    history.unshift({ query, timestamp: new Date().toISOString(), resultCount: data.metadata?.data_points || 0 });
    localStorage.setItem('queryHistory', JSON.stringify(history.slice(0, 10)));
    updateHistoryDisplay();
}

function updateHistoryDisplay() {
    const history = JSON.parse(localStorage.getItem('queryHistory') || '[]');
    historyContainer.innerHTML = history.map(item => `
        <div class="history-item">
            <div class="query-text">${item.query}</div>
            <div class="query-meta">
                <span class="timestamp">${new Date(item.timestamp).toLocaleString()}</span>
                <span class="result-count">${item.resultCount} results</span>
            </div>
        </div>
    `).join('');
}

// Navigation
document.querySelectorAll('[data-section]').forEach(link => {
    link.addEventListener('click', function(e) {
        e.preventDefault();
        const targetSection = this.getAttribute('data-section');

        document.querySelectorAll('.content-section').forEach(section => section.classList.remove('active'));
        document.querySelectorAll('#sidebar li').forEach(item => item.classList.remove('active'));

        document.getElementById(targetSection).classList.add('active');
        this.parentElement.classList.add('active');
    });
});

// Initialize
loadSavedConfig();
updateHistoryDisplay();