// NoteGen Frontend Application
const API_BASE = '';
let currentView = 'courses';
let currentCourse = null;
let currentSession = null;
let ws = null;
let transcriptChunks = [];
let liveNotes = '';

// API Helper
async function api(endpoint, options = {}) {
    const url = `${API_BASE}/api${endpoint}`;
    const config = {
        headers: { 'Content-Type': 'application/json' },
        ...options,
    };

    if (options.body && typeof options.body === 'object' && !(options.body instanceof FormData)) {
        config.body = JSON.stringify(options.body);
    }

    if (options.body instanceof FormData) {
        delete config.headers['Content-Type'];
    }

    const response = await fetch(url, config);
    if (!response.ok) {
        const error = await response.json().catch(() => ({ detail: 'Request failed' }));
        throw new Error(error.detail || 'Request failed');
    }
    return response.json();
}

// Render Functions
function render(html) {
    document.getElementById('main-content').innerHTML = html;
}

function updateBreadcrumb(items) {
    const breadcrumb = document.getElementById('breadcrumb');
    breadcrumb.innerHTML = items.map((item, i) => {
        if (i === items.length - 1) {
            return `<span class="current">${item.label}</span>`;
        }
        return `<a href="#" data-view="${item.view}" data-id="${item.id || ''}">${item.label}</a><span class="separator">/</span>`;
    }).join('');

    breadcrumb.querySelectorAll('a').forEach(a => {
        a.addEventListener('click', (e) => {
            e.preventDefault();
            const view = a.dataset.view;
            const id = a.dataset.id;
            if (view === 'courses') {
                navigateToCourses();
            } else if (view === 'course' && id) {
                navigateToCourse(id);
            }
        });
    });
}

// Views
async function renderCoursesView() {
    currentView = 'courses';
    currentCourse = null;
    currentSession = null;
    disconnectWebSocket();

    updateBreadcrumb([{ label: 'Courses' }]);

    render('<div class="loading"><div class="spinner"></div>Loading courses...</div>');

    try {
        const courses = await api('/courses');

        if (courses.length === 0) {
            render(`
                <div class="view-header">
                    <h2>Your Courses</h2>
                    <button class="btn btn-primary" onclick="showCreateCourseModal()">+ New Course</button>
                </div>
                <div class="empty-state">
                    <p>No courses yet. Create your first course to get started.</p>
                    <button class="btn btn-primary" onclick="showCreateCourseModal()">Create Course</button>
                </div>
            `);
        } else {
            render(`
                <div class="view-header">
                    <h2>Your Courses</h2>
                    <button class="btn btn-primary" onclick="showCreateCourseModal()">+ New Course</button>
                </div>
                <div class="card-grid">
                    ${courses.map(course => `
                        <div class="card" onclick="navigateToCourse(${course.id})">
                            <h3>${escapeHtml(course.name)}</h3>
                            <div class="meta">Created ${formatDate(course.created_at)}</div>
                        </div>
                    `).join('')}
                </div>
            `);
        }
    } catch (err) {
        render(`<div class="empty-state"><p>Error loading courses: ${escapeHtml(err.message)}</p></div>`);
    }
}

async function renderCourseView(courseId) {
    currentView = 'course';
    currentSession = null;
    disconnectWebSocket();

    render('<div class="loading"><div class="spinner"></div>Loading sessions...</div>');

    try {
        const [courses, sessions] = await Promise.all([
            api('/courses'),
            api(`/sessions?course_id=${courseId}`)
        ]);

        currentCourse = courses.find(c => c.id === parseInt(courseId));
        if (!currentCourse) throw new Error('Course not found');

        updateBreadcrumb([
            { label: 'Courses', view: 'courses' },
            { label: currentCourse.name }
        ]);

        if (sessions.length === 0) {
            render(`
                <div class="view-header">
                    <h2>${escapeHtml(currentCourse.name)}</h2>
                    <button class="btn btn-primary" onclick="createSession(${courseId})">+ New Session</button>
                </div>
                <div class="empty-state">
                    <p>No sessions yet. Create your first session to start recording.</p>
                    <button class="btn btn-primary" onclick="createSession(${courseId})">Create Session</button>
                </div>
            `);
        } else {
            render(`
                <div class="view-header">
                    <h2>${escapeHtml(currentCourse.name)}</h2>
                    <button class="btn btn-primary" onclick="createSession(${courseId})">+ New Session</button>
                </div>
                <div class="card-grid">
                    ${sessions.map(session => `
                        <div class="card" onclick="navigateToSession(${session.id})">
                            <h3>Session ${session.session_number}</h3>
                            <div class="meta">Created ${formatDate(session.created_at)}</div>
                            <span class="status status-${session.status}">${session.status}</span>
                        </div>
                    `).join('')}
                </div>
            `);
        }
    } catch (err) {
        render(`<div class="empty-state"><p>Error loading sessions: ${escapeHtml(err.message)}</p></div>`);
    }
}

async function renderSessionView(sessionId) {
    currentView = 'session';
    transcriptChunks = [];
    liveNotes = '';

    render('<div class="loading"><div class="spinner"></div>Loading session...</div>');

    try {
        const session = await api(`/sessions/${sessionId}`);
        currentSession = session;

        // Load course info if not already loaded
        if (!currentCourse || currentCourse.id !== session.course_id) {
            const courses = await api('/courses');
            currentCourse = courses.find(c => c.id === session.course_id);
        }

        updateBreadcrumb([
            { label: 'Courses', view: 'courses' },
            { label: currentCourse.name, view: 'course', id: currentCourse.id },
            { label: `Session ${session.session_number}` }
        ]);

        // Load existing data
        const [notesData, slidesData] = await Promise.all([
            api(`/sessions/${sessionId}/notes`).catch(() => ({})),
            api(`/sessions/${sessionId}/slides/outline`).catch(() => null)
        ]);

        liveNotes = notesData.live_draft || notesData.merged || notesData.polished || '';

        renderSessionContent(session, slidesData);
        connectWebSocket(sessionId);

    } catch (err) {
        render(`<div class="empty-state"><p>Error loading session: ${escapeHtml(err.message)}</p></div>`);
    }
}

function renderSessionContent(session, slidesData) {
    const isRecording = session.status === 'recording';
    const hasSlides = slidesData && slidesData.sections && slidesData.sections.length > 0;

    render(`
        <div class="recording-controls">
            <button class="btn ${isRecording ? 'btn-danger' : 'btn-success'}" id="recordBtn" onclick="toggleRecording()">
                ${isRecording ? '⏹ Stop Recording' : '🎙 Start Recording'}
            </button>
            <div class="recording-status">
                <div class="recording-indicator ${isRecording ? 'active' : ''}"></div>
                <span id="recordingStatusText">${isRecording ? 'Recording...' : 'Ready'}</span>
            </div>
        </div>

        <div class="session-layout">
            <div class="panel">
                <div class="panel-header">
                    <h3>Slides</h3>
                </div>
                <div class="panel-content" id="slidesPanel">
                    ${hasSlides ? renderSlidesOutline(slidesData) : renderSlideUpload()}
                </div>
            </div>

            <div class="panel">
                <div class="panel-header">
                    <h3>Notes & Transcript</h3>
                    <div class="action-bar">
                        ${session.status === 'stopped' ? `
                            <button class="btn btn-sm btn-secondary" onclick="mergeNotes()">Merge with Slides</button>
                            <button class="btn btn-sm btn-secondary" onclick="polishNotes()">Polish Notes</button>
                        ` : ''}
                    </div>
                </div>
                <div class="panel-content">
                    <div class="tabs">
                        <button class="tab active" data-tab="notes" onclick="switchTab('notes')">Notes</button>
                        <button class="tab" data-tab="transcript" onclick="switchTab('transcript')">Transcript</button>
                    </div>
                    <div id="tabContent">
                        <div id="notesTab" class="notes-content">${liveNotes || '<span style="color: var(--text-secondary)">Notes will appear here as you record...</span>'}</div>
                        <div id="transcriptTab" style="display: none;">
                            <div id="transcriptChunks">
                                ${transcriptChunks.length === 0
                                    ? '<span style="color: var(--text-secondary)">Transcript will appear here...</span>'
                                    : transcriptChunks.map(renderTranscriptChunk).join('')
                                }
                            </div>
                        </div>
                    </div>
                </div>
            </div>
        </div>
    `);

    setupSlideUploadHandlers();
}

function renderSlideUpload() {
    return `
        <div class="upload-zone" id="uploadZone">
            <div class="upload-icon">📄</div>
            <strong>Upload Slides</strong>
            <p>Drag & drop PDF or PPTX file, or click to browse</p>
            <input type="file" id="fileInput" accept=".pdf,.pptx" style="display: none;">
        </div>
    `;
}

function renderSlidesOutline(slidesData) {
    if (!slidesData.sections || slidesData.sections.length === 0) {
        return '<p style="color: var(--text-secondary)">No outline extracted from slides.</p>';
    }

    return `
        <div class="slide-outline">
            ${slidesData.sections.map(section => `
                <div class="slide-section">
                    <h4>${escapeHtml(section.title || 'Untitled Section')}</h4>
                    ${section.bullets && section.bullets.length > 0 ? `
                        <ul>
                            ${section.bullets.map(b => `<li>${escapeHtml(b)}</li>`).join('')}
                        </ul>
                    ` : ''}
                </div>
            `).join('')}
        </div>
        <button class="btn btn-sm btn-secondary" style="margin-top: 16px;" onclick="reuploadSlides()">Replace Slides</button>
    `;
}

function renderTranscriptChunk(chunk) {
    return `
        <div class="transcript-chunk">
            <div class="time">${formatTime(chunk.start_time)} - ${formatTime(chunk.end_time)}</div>
            <div class="text">${escapeHtml(chunk.text)}</div>
        </div>
    `;
}

function setupSlideUploadHandlers() {
    const uploadZone = document.getElementById('uploadZone');
    const fileInput = document.getElementById('fileInput');

    if (!uploadZone || !fileInput) return;

    uploadZone.addEventListener('click', () => fileInput.click());

    uploadZone.addEventListener('dragover', (e) => {
        e.preventDefault();
        uploadZone.classList.add('dragover');
    });

    uploadZone.addEventListener('dragleave', () => {
        uploadZone.classList.remove('dragover');
    });

    uploadZone.addEventListener('drop', (e) => {
        e.preventDefault();
        uploadZone.classList.remove('dragover');
        const files = e.dataTransfer.files;
        if (files.length > 0) {
            uploadSlides(files[0]);
        }
    });

    fileInput.addEventListener('change', (e) => {
        if (e.target.files.length > 0) {
            uploadSlides(e.target.files[0]);
        }
    });
}

// Actions
async function showCreateCourseModal() {
    const overlay = document.createElement('div');
    overlay.className = 'modal-overlay';
    overlay.innerHTML = `
        <div class="modal">
            <h3>Create New Course</h3>
            <form id="createCourseForm">
                <div class="form-group">
                    <label for="courseName">Course Name</label>
                    <input type="text" id="courseName" placeholder="e.g., CS101 - Intro to Programming" required>
                </div>
                <div class="modal-actions">
                    <button type="button" class="btn btn-secondary" onclick="closeModal()">Cancel</button>
                    <button type="submit" class="btn btn-primary">Create</button>
                </div>
            </form>
        </div>
    `;
    document.body.appendChild(overlay);

    document.getElementById('courseName').focus();

    document.getElementById('createCourseForm').addEventListener('submit', async (e) => {
        e.preventDefault();
        const name = document.getElementById('courseName').value.trim();
        if (!name) return;

        try {
            await api('/courses', {
                method: 'POST',
                body: { name }
            });
            closeModal();
            renderCoursesView();
        } catch (err) {
            alert('Error creating course: ' + err.message);
        }
    });

    overlay.addEventListener('click', (e) => {
        if (e.target === overlay) closeModal();
    });
}

function closeModal() {
    const modal = document.querySelector('.modal-overlay');
    if (modal) modal.remove();
}

async function createSession(courseId) {
    try {
        const sessionNumber = prompt('Enter session number (e.g. 4):');
        if (!sessionNumber) return;

        const session = await api('/sessions', {
            method: 'POST',
            body: { course_id: courseId, session_number: sessionNumber }
        });
        navigateToSession(session.id);
    } catch (err) {
        alert('Error creating session: ' + err.message);
    }
}

async function toggleRecording() {
    if (!currentSession) return;

    const btn = document.getElementById('recordBtn');
    btn.disabled = true;

    try {
        if (currentSession.status === 'recording') {
            await api(`/sessions/${currentSession.id}/recording/stop`, { method: 'POST' });
            currentSession.status = 'stopped';
        } else {
            await api(`/sessions/${currentSession.id}/recording/start`, { method: 'POST' });
            currentSession.status = 'recording';
        }

        updateRecordingUI();
    } catch (err) {
        alert('Error toggling recording: ' + err.message);
    } finally {
        btn.disabled = false;
    }
}

function updateRecordingUI() {
    const btn = document.getElementById('recordBtn');
    const indicator = document.querySelector('.recording-indicator');
    const statusText = document.getElementById('recordingStatusText');

    const isRecording = currentSession.status === 'recording';

    if (btn) {
        btn.className = `btn ${isRecording ? 'btn-danger' : 'btn-success'}`;
        btn.innerHTML = isRecording ? '⏹ Stop Recording' : '🎙 Start Recording';
    }

    if (indicator) {
        indicator.classList.toggle('active', isRecording);
    }

    if (statusText) {
        statusText.textContent = isRecording ? 'Recording...' : (currentSession.status === 'stopped' ? 'Stopped' : 'Ready');
    }
}

async function uploadSlides(file) {
    if (!currentSession) return;

    const slidesPanel = document.getElementById('slidesPanel');
    slidesPanel.innerHTML = '<div class="loading"><div class="spinner"></div>Processing slides...</div>';

    const formData = new FormData();
    formData.append('file', file);

    try {
        const result = await fetch(`/api/sessions/${currentSession.id}/slides`, {
            method: 'POST',
            body: formData
        }).then(r => r.json());

        slidesPanel.innerHTML = renderSlidesOutline({ sections: result.outline || [] });

        // Re-setup handlers for the replace button
        const replaceBtn = slidesPanel.querySelector('button');
        if (replaceBtn) {
            replaceBtn.addEventListener('click', reuploadSlides);
        }
    } catch (err) {
        slidesPanel.innerHTML = `
            ${renderSlideUpload()}
            <p style="color: var(--danger); margin-top: 12px;">Error: ${escapeHtml(err.message)}</p>
        `;
        setupSlideUploadHandlers();
    }
}

function reuploadSlides() {
    const slidesPanel = document.getElementById('slidesPanel');
    slidesPanel.innerHTML = renderSlideUpload();
    setupSlideUploadHandlers();
}

async function mergeNotes() {
    if (!currentSession) return;

    try {
        await api(`/sessions/${currentSession.id}/notes/merge`, { method: 'POST' });
        const notesData = await api(`/sessions/${currentSession.id}/notes`);
        liveNotes = notesData.merged || notesData.live_draft || '';
        document.getElementById('notesTab').innerHTML = liveNotes || '<span style="color: var(--text-secondary)">No notes yet.</span>';
    } catch (err) {
        alert('Error merging notes: ' + err.message);
    }
}

async function polishNotes() {
    if (!currentSession) return;

    try {
        await api(`/sessions/${currentSession.id}/notes/polish`, { method: 'POST' });
        const notesData = await api(`/sessions/${currentSession.id}/notes`);
        liveNotes = notesData.polished || notesData.merged || '';
        document.getElementById('notesTab').innerHTML = liveNotes || '<span style="color: var(--text-secondary)">No notes yet.</span>';
    } catch (err) {
        alert('Error polishing notes: ' + err.message);
    }
}

function switchTab(tab) {
    document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
    document.querySelector(`[data-tab="${tab}"]`).classList.add('active');

    document.getElementById('notesTab').style.display = tab === 'notes' ? 'block' : 'none';
    document.getElementById('transcriptTab').style.display = tab === 'transcript' ? 'block' : 'none';
}

// WebSocket
function connectWebSocket(sessionId) {
    disconnectWebSocket();

    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    ws = new WebSocket(`${protocol}//${window.location.host}/ws/session/${sessionId}`);

    ws.onmessage = (event) => {
        const data = JSON.parse(event.data);
        handleWebSocketMessage(data);
    };

    ws.onerror = (error) => {
        console.error('WebSocket error:', error);
    };

    ws.onclose = () => {
        console.log('WebSocket closed');
    };
}

function disconnectWebSocket() {
    if (ws) {
        ws.close();
        ws = null;
    }
}

function handleWebSocketMessage(data) {
    switch (data.type) {
        case 'recording_status':
            if (currentSession) {
                currentSession.status = data.status === 'recording' ? 'recording' : 'idle';
                updateRecordingUI();
            }
            break;

        case 'chunk_transcribed':
            transcriptChunks.push({
                chunk_index: data.chunk_index,
                start_time: data.start_time,
                end_time: data.end_time,
                text: data.text
            });

            const transcriptContainer = document.getElementById('transcriptChunks');
            if (transcriptContainer) {
                if (transcriptChunks.length === 1) {
                    transcriptContainer.innerHTML = '';
                }
                transcriptContainer.innerHTML += renderTranscriptChunk(data);
                transcriptContainer.scrollTop = transcriptContainer.scrollHeight;
            }
            break;

        case 'live_notes_updated':
            liveNotes = data.notes;
            const notesTab = document.getElementById('notesTab');
            if (notesTab) {
                notesTab.innerHTML = liveNotes;
            }
            break;
    }
}

// Navigation
function navigateToCourses() {
    renderCoursesView();
}

function navigateToCourse(courseId) {
    renderCourseView(courseId);
}

function navigateToSession(sessionId) {
    renderSessionView(sessionId);
}

// Utilities
function escapeHtml(text) {
    if (!text) return '';
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

function formatDate(dateStr) {
    if (!dateStr) return '';
    const date = new Date(dateStr);
    return date.toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' });
}

function formatTime(seconds) {
    if (seconds == null) return '00:00';
    const mins = Math.floor(seconds / 60);
    const secs = Math.floor(seconds % 60);
    return `${mins.toString().padStart(2, '0')}:${secs.toString().padStart(2, '0')}`;
}

// Initialize
document.addEventListener('DOMContentLoaded', () => {
    renderCoursesView();
});
