// Local State
let selectedVillagers = [];
let activeCampaignType = 'survey';
let charts = {};
let callsCache = [];

// API Base Helpers
async function apiCall(endpoint, options = {}) {
    const headers = { 'Content-Type': 'application/json', ...options.headers };
    try {
        const response = await fetch(endpoint, { ...options, headers });
        if (!response.ok) {
            const data = await response.json().catch(() => ({}));
            throw new Error(data.detail || `HTTP error! Status: ${response.status}`);
        }
        return await response.json();
    } catch (error) {
        console.error(`API Call failed (${endpoint}):`, error);
        alert(`Error: ${error.message}`);
        throw error;
    }
}

// Initialise Dashboard
document.addEventListener('DOMContentLoaded', () => {
    showDashboard();

    // Set Live Time
    updateTime();
    setInterval(updateTime, 1000);

    setupEventListeners();
});

// Update DateTime in header
function updateTime() {
    const dateElem = document.getElementById('current-date-time');
    if (dateElem) {
        const options = { weekday: 'long', year: 'numeric', month: 'long', day: 'numeric', hour: '2-digit', minute: '2-digit', second: '2-digit' };
        dateElem.textContent = new Date().toLocaleDateString('en-US', options);
    }
}

// Nav Navigation & Tab Toggles
function setupEventListeners() {
    // Navigation items
    document.querySelectorAll('.nav-item').forEach(item => {
        item.addEventListener('click', (e) => {
            e.preventDefault();
            document.querySelectorAll('.nav-item').forEach(n => n.classList.remove('active'));
            item.classList.add('active');
            
            const tabId = item.getAttribute('data-tab');
            document.querySelectorAll('.tab-panel').forEach(panel => panel.classList.remove('active'));
            document.getElementById(`tab-${tabId}`).classList.add('active');

            if (tabId === 'overview') loadOverviewData();
            if (tabId === 'outbound') loadCampaignData();
            if (tabId === 'villagers') loadDirectoryData();
            if (tabId === 'logs') loadLogsData();
            if (tabId === 'prompts') loadPromptsData();
        });
    });

    // Sub-campaign parameters tab toggles
    document.querySelectorAll('.tab-sub').forEach(tab => {
        tab.addEventListener('click', () => {
            document.querySelectorAll('.tab-sub').forEach(t => t.classList.remove('active'));
            tab.classList.add('active');
            activeCampaignType = tab.getAttribute('data-type');

            document.querySelectorAll('.campaign-form-step').forEach(form => form.classList.remove('active'));
            document.getElementById(`form-${activeCampaignType}`).classList.add('active');
        });
    });

    // Villager CRUD actions
    document.getElementById('btn-open-add-villager').addEventListener('click', () => openVillagerModal());
    document.getElementById('btn-close-modal').addEventListener('click', closeVillagerModal);
    document.getElementById('btn-cancel-modal').addEventListener('click', closeVillagerModal);
    document.getElementById('villager-form').addEventListener('submit', handleVillagerSubmit);

    // Filters for campaign grid
    document.getElementById('campaign-search').addEventListener('input', filterCampaignTable);
    document.getElementById('campaign-ward-filter').addEventListener('change', filterCampaignTable);
    document.getElementById('check-all-campaign').addEventListener('change', toggleSelectAllCampaign);

    // Filters for directory
    document.getElementById('directory-search').addEventListener('input', filterDirectoryTable);
    document.getElementById('directory-ward-filter').addEventListener('change', filterDirectoryTable);

    // Launch campaign button
    document.getElementById('btn-launch-campaign').addEventListener('click', launchCampaign);

    // Export Logs CSV
    document.getElementById('btn-export-logs').addEventListener('click', () => {
        window.open('/api/calls/export', '_blank');
    });

    // Call details close modal
    document.getElementById('btn-close-detail-modal').addEventListener('click', closeDetailModal);

    // Campaign voice preview button listeners
    document.querySelectorAll('.btn-preview-tts').forEach(btn => {
        btn.addEventListener('click', () => handleCampaignPreview(btn));
    });
}

function showDashboard() {
    // Auto-detect public URL
    document.getElementById('system-webhook-url').textContent = window.location.origin;

    // Load initial Tab
    loadOverviewData();
    loadConfigData();
}

async function loadConfigData() {
    try {
        const config = await apiCall('/api/config');
        const modeBadge = document.getElementById('telephony-mode-badge');
        if (modeBadge) {
            if (config.mode === 'live') {
                modeBadge.textContent = 'Live (Vobiz)';
                modeBadge.className = 'badge badge-success';
            } else {
                modeBadge.textContent = 'Simulated';
                modeBadge.className = 'badge badge-warning';
            }
        }
    } catch (e) {
        console.error('Failed to load system config:', e);
    }
}

// --- Overview/Stats & Graph charts ---

async function loadOverviewData() {
    try {
        const stats = await apiCall('/api/calls/stats');
        const villagers = await apiCall('/api/villagers');

        // Update Overview badges
        document.getElementById('stat-total-villagers').textContent = villagers.length;
        document.getElementById('stat-success-rate').textContent = `${stats.success_rate}%`;
        document.getElementById('stat-total-surveys').textContent = stats.surveys.total;
        document.getElementById('stat-pending-summons').textContent = stats.summoning.pending;

        // Render Graphs
        renderOverviewCharts(stats);
    } catch (e) {
        console.error('Failed to load overview statistics:', e);
    }
}

function renderOverviewCharts(stats) {
    // Rating chart
    const ratingCtx = document.getElementById('chart-survey-ratings').getContext('2d');
    if (charts.ratings) charts.ratings.destroy();

    charts.ratings = new Chart(ratingCtx, {
        type: 'bar',
        data: {
            labels: ['Good Experience', 'Neutral Experience', 'Poor Experience', 'Recommend Yes', 'Recommend No'],
            datasets: [{
                label: 'Feedback Counts',
                data: [
                    stats.surveys.satisfaction_good,
                    stats.surveys.satisfaction_neutral,
                    stats.surveys.satisfaction_poor,
                    stats.surveys.rec_yes,
                    stats.surveys.rec_no
                ],
                backgroundColor: [
                    'rgba(16, 185, 129, 0.45)', // Green
                    'rgba(245, 158, 11, 0.45)', // Orange
                    'rgba(239, 68, 68, 0.45)',  // Red
                    'rgba(13, 148, 136, 0.45)',  // Teal
                    'rgba(99, 102, 241, 0.45)'  // Indigo
                ],
                borderColor: [
                    '#10b981', '#f59e0b', '#ef4444', '#0d9488', '#6366f1'
                ],
                borderWidth: 1.5
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            scales: {
                y: { beginAtZero: true, grid: { color: 'rgba(255, 255, 255, 0.05)' }, ticks: { color: '#94a3b8' } },
                x: { ticks: { color: '#94a3b8' } }
            },
            plugins: {
                legend: { display: false }
            }
        }
    });

    // Summons outcome chart
    const summonCtx = document.getElementById('chart-summon-responses').getContext('2d');
    if (charts.summons) charts.summons.destroy();

    charts.summons = new Chart(summonCtx, {
        type: 'doughnut',
        data: {
            labels: ['Confirmed Visits', 'Reschedule Requested', 'Cancelled', 'Pending Outcome'],
            datasets: [{
                data: [
                    stats.summoning.confirmed,
                    stats.summoning.reschedule,
                    stats.summoning.cancelled,
                    stats.summoning.pending
                ],
                backgroundColor: [
                    'rgba(16, 185, 129, 0.4)',
                    'rgba(245, 158, 11, 0.4)',
                    'rgba(239, 68, 68, 0.4)',
                    'rgba(255, 255, 255, 0.05)'
                ],
                borderColor: [
                    '#10b981', '#f59e0b', '#ef4444', 'rgba(255, 255, 255, 0.15)'
                ],
                borderWidth: 1.5
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                legend: {
                    position: 'bottom',
                    labels: { color: '#94a3b8', font: { family: 'Plus Jakarta Sans', size: 11 } }
                }
            }
        }
    });
}

// --- Campaign Handling Grid ---

async function loadCampaignData() {
    selectedVillagers = [];
    document.getElementById('selected-count').textContent = '0 selected';
    document.getElementById('check-all-campaign').checked = false;
    
    try {
        const list = await apiCall('/api/villagers');
        const body = document.getElementById('campaign-villagers-body');
        body.innerHTML = '';

        // populate village/ward filter dynamically
        const wards = [...new Set(list.map(v => v.village_ward))].filter(Boolean);
        const wardFilter = document.getElementById('campaign-ward-filter');
        wardFilter.innerHTML = '<option value="">All Villages / Wards</option>';
        wards.forEach(w => {
            wardFilter.innerHTML += `<option value="${w}">${w}</option>`;
        });

        list.forEach(v => {
            if (v.status !== 'Active') return;
            const tr = document.createElement('tr');
            tr.innerHTML = `
                <td><input type="checkbox" class="check-campaign" value="${v.id}"></td>
                <td><strong>${v.name}</strong></td>
                <td>${v.phone}</td>
                <td><span class="badge badge-primary">${v.village_ward || '-'}</span></td>
            `;
            body.appendChild(tr);

            // Row checkbox change listener
            const chk = tr.querySelector('.check-campaign');
            chk.addEventListener('change', () => {
                if (chk.checked) {
                    selectedVillagers.push(v.id);
                } else {
                    selectedVillagers = selectedVillagers.filter(id => id !== v.id);
                }
                document.getElementById('selected-count').textContent = `${selectedVillagers.length} selected`;
            });
        });
    } catch (e) {
        console.error('Failed to load campaign villagers:', e);
    }
}

function filterCampaignTable() {
    const search = document.getElementById('campaign-search').value.toLowerCase();
    const ward = document.getElementById('campaign-ward-filter').value;
    
    const rows = document.querySelectorAll('#campaign-villagers-body tr');
    rows.forEach(row => {
        const name = row.children[1].textContent.toLowerCase();
        const phone = row.children[2].textContent.toLowerCase();
        const rowWard = row.children[3].textContent.trim();
        
        const matchesSearch = name.includes(search) || phone.includes(search);
        const matchesWard = !ward || rowWard === ward;
        
        row.style.display = (matchesSearch && matchesWard) ? '' : 'none';
    });
}

function toggleSelectAllCampaign() {
    const isChecked = document.getElementById('check-all-campaign').checked;
    selectedVillagers = [];
    
    document.querySelectorAll('#campaign-villagers-body tr').forEach(row => {
        if (row.style.display === 'none') return;
        const chk = row.querySelector('.check-campaign');
        chk.checked = isChecked;
        if (isChecked) {
            selectedVillagers.push(chk.value);
        }
    });
    
    document.getElementById('selected-count').textContent = `${selectedVillagers.length} selected`;
}

async function launchCampaign() {
    if (selectedVillagers.length === 0) {
        alert('Please select at least one villager to initiate the voice campaign.');
        return;
    }

    const payload = {
        villager_ids: selectedVillagers,
        type: activeCampaignType,
        details: {}
    };

    if (activeCampaignType === 'survey') {
        payload.details = {
            q1: document.getElementById('survey-q1').value.trim(),
            q2: document.getElementById('survey-q2').value.trim(),
            q3: document.getElementById('survey-q3').value.trim()
        };
    } else if (activeCampaignType === 'summoning') {
        const date = document.getElementById('summon-date').value.trim();
        const time = document.getElementById('summon-time').value.trim();
        const purposeInput = document.getElementById('summon-purpose');
        let purpose = purposeInput.value.trim();

        // Translate purpose if English before launching
        if (/[a-zA-Z]{2,}/.test(purpose)) {
            try {
                const transData = await apiCall('/api/campaigns/preview', {
                    method: 'POST',
                    body: JSON.stringify({ text: purpose })
                });
                if (transData.translated_text) {
                    purpose = transData.translated_text;
                    purposeInput.value = purpose; // Update textarea!
                }
            } catch (e) {
                console.error("Failed to translate summoning purpose on launch:", e);
            }
        }

        payload.details = {
            date: date,
            time: time,
            purpose: purpose
        };
    } else if (activeCampaignType === 'announcement') {
        payload.details = {
            announcement: document.getElementById('announce-message').value.trim()
        };
    }

    const btn = document.getElementById('btn-launch-campaign');
    btn.disabled = true;
    btn.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> Triggering Campaign...';

    try {
        const res = await apiCall('/api/campaigns/trigger', {
            method: 'POST',
            body: JSON.stringify(payload)
        });

        alert(`Successfully launched campaign on Vobiz! Triggered Count: ${res.triggered_count}`);
        
        // Switch to history tab or trigger updates
        document.querySelector('.nav-item[data-tab="logs"]').click();
    } catch (e) {
        // Handled in apiCall
    } finally {
        btn.disabled = false;
        btn.innerHTML = '<i class="fa-solid fa-rocket"></i> Launch Outbound Campaign';
    }
}

// --- Villagers Directory (CRUD UI) ---

async function loadDirectoryData() {
    try {
        const list = await apiCall('/api/villagers');
        const body = document.getElementById('directory-table-body');
        body.innerHTML = '';

        // Wards dropdown populations
        const wards = [...new Set(list.map(v => v.village_ward))].filter(Boolean);
        const dirWard = document.getElementById('directory-ward-filter');
        dirWard.innerHTML = '<option value="">All Villages / Wards</option>';
        wards.forEach(w => {
            dirWard.innerHTML += `<option value="${w}">${w}</option>`;
        });

        list.forEach(v => {
            const tr = document.createElement('tr');
            tr.innerHTML = `
                <td><strong>${v.name}</strong></td>
                <td>${v.phone}</td>
                <td><span class="badge badge-primary">${v.village_ward || '-'}</span></td>
                <td><span class="badge ${v.status === 'Active' ? 'badge-success' : 'badge-danger'}">${v.status}</span></td>
                <td>
                    <button class="btn btn-secondary btn-edit-villager" style="padding: 5px 10px; font-size: 11px;"><i class="fa-solid fa-pen-to-square"></i></button>
                    <button class="btn btn-danger btn-delete-villager" style="padding: 5px 10px; font-size: 11px; background: var(--red); color: white;"><i class="fa-solid fa-trash"></i></button>
                </td>
            `;
            body.appendChild(tr);

            tr.querySelector('.btn-edit-villager').addEventListener('click', () => openVillagerModal(v));
            tr.querySelector('.btn-delete-villager').addEventListener('click', () => deleteVillager(v.id));
        });
    } catch (e) {
        console.error('Failed to load directory:', e);
    }
}

function filterDirectoryTable() {
    const search = document.getElementById('directory-search').value.toLowerCase();
    const ward = document.getElementById('directory-ward-filter').value;
    
    const rows = document.querySelectorAll('#directory-table-body tr');
    rows.forEach(row => {
        const name = row.children[0].textContent.toLowerCase();
        const phone = row.children[1].textContent.toLowerCase();
        const rowWard = row.children[2].textContent.trim();
        
        const matchesSearch = name.includes(search) || phone.includes(search) || rowWard.toLowerCase().includes(search);
        const matchesWard = !ward || rowWard === ward;
        
        row.style.display = (matchesSearch && matchesWard) ? '' : 'none';
    });
}

function openVillagerModal(villager = null) {
    const modal = document.getElementById('villager-modal');
    modal.style.display = 'flex';
    
    if (villager) {
        document.getElementById('modal-title').textContent = 'Edit Villager Details';
        document.getElementById('form-v-id').value = villager.id;
        document.getElementById('form-v-name').value = villager.name;
        document.getElementById('form-v-phone').value = villager.phone;
        document.getElementById('form-v-ward').value = villager.village_ward || '';
        document.getElementById('form-v-status').value = villager.status;
    } else {
        document.getElementById('modal-title').textContent = 'Add New Villager';
        document.getElementById('form-v-id').value = '';
        document.getElementById('villager-form').reset();
        document.getElementById('form-v-phone').value = '+91';
    }
}

function closeVillagerModal() {
    document.getElementById('villager-modal').style.display = 'none';
}

async function handleVillagerSubmit(e) {
    e.preventDefault();
    
    const id = document.getElementById('form-v-id').value;
    const payload = {
        name: document.getElementById('form-v-name').value.trim(),
        phone: document.getElementById('form-v-phone').value.trim(),
        village_ward: document.getElementById('form-v-ward').value.trim(),
        status: document.getElementById('form-v-status').value
    };

    try {
        if (id) {
            await apiCall(`/api/villagers/${id}`, {
                method: 'PUT',
                body: JSON.stringify(payload)
            });
        } else {
            await apiCall('/api/villagers', {
                method: 'POST',
                body: JSON.stringify(payload)
            });
        }
        closeVillagerModal();
        loadDirectoryData();
    } catch (e) {
        // error alerts handled
    }
}

async function deleteVillager(vId) {
    if (!confirm('Are you sure you want to delete this villager?')) return;
    try {
        await apiCall(`/api/villagers/${vId}`, { method: 'DELETE' });
        loadDirectoryData();
    } catch (e) {
        // error alerts handled
    }
}

// --- History & Logs Table ---

async function loadLogsData() {
    try {
        const logs = await apiCall('/api/calls');
        callsCache = logs; // store in memory for modal detail access
        
        const body = document.getElementById('logs-table-body');
        body.innerHTML = '';

        logs.slice().reverse().forEach(c => {
            const tr = document.createElement('tr');
            tr.style.cursor = 'pointer'; // show interactive row cursor
            
            // Format Outcome details
            let outcome = '-';
            if (c.type === 'survey' && c.survey_results) {
                const r = c.survey_results;
                outcome = `Rating: ${r.q1_rating || '-'}; Rec: ${r.q2_recommend || '-'}; Exp: ${r.q3_experience || '-'}`;
            } else if (c.type === 'summoning') {
                const s = c.summoning_status;
                outcome = `Outcomes: ${s ? s.toUpperCase() : 'PENDING'}`;
            } else if (c.type === 'announcement') {
                outcome = c.announcement_played ? 'Broadcast Played' : 'Broadcast Failed';
            }

            // status badge
            let badgeClass = 'badge-warning';
            if (c.status === 'completed' || c.status === 'answered') badgeClass = 'badge-success';
            if (c.status === 'failed') badgeClass = 'badge-danger';
            if (c.status === 'no_answer') badgeClass = 'badge-warning';

            const localTime = new Date(c.timestamp).toLocaleString();
            const duration = c.duration_seconds ? `${c.duration_seconds}s` : '0s';
            const cost = c.total_cost ? `₹${c.total_cost.toFixed(2)}` : '₹0.00';

            tr.innerHTML = `
                <td><code>${c.id}</code></td>
                <td><strong>${c.villager_name}</strong></td>
                <td>${c.phone}</td>
                <td><span class="badge badge-primary">${c.type.toUpperCase()}</span></td>
                <td><span class="badge ${badgeClass}">${c.status.toUpperCase()}</span></td>
                <td>${duration}</td>
                <td>${cost}</td>
                <td>${localTime}</td>
                <td>${outcome}</td>
            `;
            body.appendChild(tr);

            // Bind timeline detail click
            tr.addEventListener('click', () => openDetailModal(c.id));
        });
    } catch (e) {
        console.error('Failed to load call logs:', e);
    }
}

function openDetailModal(callId) {
    const call = callsCache.find(c => c.id === callId);
    if (!call) return;

    document.getElementById('detail-call-id').textContent = call.id;
    document.getElementById('detail-recipient').textContent = call.villager_name;
    document.getElementById('detail-phone').textContent = call.phone;
    document.getElementById('detail-type').textContent = call.type.toUpperCase();
    
    const statusLabel = document.getElementById('detail-status');
    statusLabel.textContent = call.status.toUpperCase();
    statusLabel.className = 'badge';
    if (call.status === 'completed') statusLabel.classList.add('badge-success');
    else if (call.status === 'failed') statusLabel.classList.add('badge-danger');
    else statusLabel.classList.add('badge-warning');

    document.getElementById('detail-digits').textContent = (call.digits_pressed && call.digits_pressed.length > 0) 
        ? call.digits_pressed.join(' , ') 
        : '(None)';

    // duration & itemized billing details
    document.getElementById('detail-duration').textContent = call.duration_seconds ? `${call.duration_seconds} seconds` : '0 seconds';
    
    const telephonyCostVal = call.telephony_cost ? call.telephony_cost.toFixed(2) : '0.00';
    const ttsCostVal = call.tts_cost ? call.tts_cost.toFixed(2) : '0.00';
    const totalCostVal = call.total_cost ? call.total_cost.toFixed(2) : '0.00';
    document.getElementById('detail-cost').innerHTML = `₹${totalCostVal} <span style="font-size: 11px; font-weight: normal; color: var(--text-dim);"> (Call: ₹${telephonyCostVal} + TTS: ₹${ttsCostVal})</span>`;

    // timeline population
    const list = document.getElementById('detail-timeline-list');
    list.innerHTML = '';
    
    if (call.history && call.history.length > 0) {
        call.history.forEach(item => {
            const timeStr = new Date(item.time).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' });
            const li = document.createElement('li');
            li.className = 'timeline-item';
            li.innerHTML = `
                <span class="timeline-time">${timeStr}</span>
                <span class="timeline-event">${item.event}</span>
            `;
            list.appendChild(li);
        });
    } else {
        list.innerHTML = '<li style="color: var(--text-dim); font-size: 13px;">No events recorded for this session.</li>';
    }

    document.getElementById('call-detail-modal').style.display = 'flex';
}

function closeDetailModal() {
    document.getElementById('call-detail-modal').style.display = 'none';
}

// --- Voice Prompts Library Tab Manager ---

async function loadPromptsData() {
    try {
        const list = await apiCall('/api/prompts');
        const container = document.getElementById('prompts-list-container');
        container.innerHTML = '';

        list.forEach(p => {
            const card = document.createElement('div');
            card.className = 'prompt-card glass-panel border-glow';
            
            // predict cached file url
            const audioUrl = `/audio/${p.id}.wav?cb=${Date.now()}`;
            
            // Calculate Cost details HTML
            let costHtml = '';
            if (p.cost_info) {
                costHtml = `
                    <div class="prompt-cost-info" style="font-size: 11px; color: var(--teal); margin-top: 8px; display: flex; flex-direction: column; gap: 2px; line-height: 1.3;">
                        <span><strong>Last Operation Cost:</strong> ₹${p.cost_info.total_cost.toFixed(4)}</span>
                        <span style="font-size: 9.5px; color: var(--text-dim);">
                            (Trans: ${p.cost_info.translation_chars} chars [₹${p.cost_info.translation_cost.toFixed(4)}] + TTS: ${p.cost_info.synthesis_chars} chars [₹${p.cost_info.synthesis_cost.toFixed(4)}])
                        </span>
                    </div>
                `;
            } else {
                costHtml = `
                    <div class="prompt-cost-info" style="font-size: 11px; color: var(--text-dim); margin-top: 8px;">
                        <span><strong>Last Operation Cost:</strong> No cost recorded (using fallback TTS)</span>
                    </div>
                `;
            }

            card.innerHTML = `
                <h4>${p.name}</h4>
                <p style="font-size: 11px; color: var(--text-dim); margin-top: -6px;">System ID: <code>${p.id}</code></p>
                <textarea rows="3" id="prompt-txt-${p.id}">${p.text}</textarea>
                <div class="audio-player-wrapper">
                    <p style="font-size: 11.5px; color: var(--text-muted); margin-bottom: 4px;">Listen Generated Voice:</p>
                    <audio controls id="prompt-audio-${p.id}" src="${audioUrl}"></audio>
                    ${costHtml}
                </div>
                <div class="prompt-card-actions" style="margin-top: 10px;">
                    <button class="btn btn-primary btn-save-prompt" data-id="${p.id}" style="font-size: 12px; padding: 8px 14px;">
                        <i class="fa-solid fa-wand-magic-sparkles"></i> Synthesize & Save
                    </button>
                </div>
            `;
            container.appendChild(card);

            const btn = card.querySelector('.btn-save-prompt');
            btn.addEventListener('click', () => saveAndSynthesizePrompt(p.id, btn));
        });
    } catch (e) {
        console.error('Failed to load prompts:', e);
    }
}

async function saveAndSynthesizePrompt(promptId, buttonElement) {
    const text = document.getElementById(`prompt-txt-${promptId}`).value.trim();
    if (!text) {
        alert('Prompt text cannot be empty.');
        return;
    }

    buttonElement.disabled = true;
    buttonElement.innerHTML = '<i class="fa-solid fa-circle-notch fa-spin"></i> Generating Audio...';

    try {
        await apiCall(`/api/prompts/${promptId}`, {
            method: 'PUT',
            body: JSON.stringify({ text })
        });

        // reload prompts grid so text changes (translations) and cost badge updates
        await loadPromptsData();

        // reload audio element with cache buster and autoplay
        const audio = document.getElementById(`prompt-audio-${promptId}`);
        if (audio) {
            audio.src = `/audio/${promptId}.wav?cb=${Date.now()}`;
            audio.load();
            audio.play().catch(e => console.log('Audio autoplay prevented:', e));
        }
        alert('Voice prompt successfully saved and synthesized via Sarvam AI!');
    } catch (e) {
        // Handled in apiCall
    } finally {
        buttonElement.disabled = false;
        buttonElement.innerHTML = '<i class="fa-solid fa-wand-magic-sparkles"></i> Synthesize & Save';
    }
}

// Campaign inputs voice previews
async function handleCampaignPreview(btn) {
    const inputId = btn.getAttribute('data-input-id');
    const previewType = btn.getAttribute('data-preview-type');
    
    let text = '';
    let badgeId = '';

    if (inputId) {
        text = document.getElementById(inputId).value.trim();
        badgeId = `preview-cost-${inputId}`;
    } else if (previewType === 'summoning') {
        const date = document.getElementById('summon-date').value.trim();
        const time = document.getElementById('summon-time').value.trim();
        const purposeInput = document.getElementById('summon-purpose');
        let purpose = purposeInput.value.trim();

        // If purpose is in English, let's first translate it!
        if (/[a-zA-Z]{2,}/.test(purpose)) {
            try {
                const transData = await apiCall('/api/campaigns/preview', {
                    method: 'POST',
                    body: JSON.stringify({ text: purpose })
                });
                if (transData.translated_text) {
                    purpose = transData.translated_text;
                    purposeInput.value = purpose; // Update textarea!
                }
            } catch (e) {
                console.error("Failed to translate summoning purpose preview:", e);
            }
        }

        text = `Hello. This is a summoning reminder from your Gram Panchayat. You are requested to attend a meeting at the Panchayat office on ${date} at ${time} for ${purpose}. Please press 1 to confirm your visit, press 2 to request a reschedule, press 3 to cancel this visit, or press 9 to repeat these details.`;
        badgeId = 'preview-cost-summoning';
    }

    if (!text) {
        alert('Script content cannot be empty.');
        return;
    }

    // Set loading state
    const originalHtml = btn.innerHTML;
    btn.disabled = true;
    btn.innerHTML = '<i class="fa-solid fa-circle-notch fa-spin"></i> Previewing...';
    
    const costBadge = document.getElementById(badgeId);
    if (costBadge) costBadge.textContent = '';

    try {
        const data = await apiCall('/api/campaigns/preview', {
            method: 'POST',
            body: JSON.stringify({ text })
        });

        // If translated from English to Marathi, update the input box for surveys/announcements
        if (inputId && data.translated_text !== text) {
            document.getElementById(inputId).value = data.translated_text;
        }

        // Play voice preview audio
        if (data.audio_url) {
            const player = new Audio(data.audio_url);
            player.play().catch(e => console.log('Audio autoplay prevented:', e));
        }

        // Update cost badge
        if (costBadge && data.cost_info) {
            costBadge.textContent = `Cost: ₹${data.cost_info.total_cost.toFixed(4)}`;
        }

    } catch (e) {
        // Handled in apiCall
    } finally {
        btn.disabled = false;
        btn.innerHTML = originalHtml;
    }
}
