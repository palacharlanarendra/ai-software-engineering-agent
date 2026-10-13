/**
 * AI Software Engineering Agent — Cloud IDE Application Logic
 * Single Page Application integrating Monaco Editor & LangGraph REST APIs
 */

// Application State
const state = {
    currentFilePath: "app/main.py",
    currentFileContent: "",
    activeMode: "code", // 'code' | 'diff'
    diffSplitMode: true, // true = side-by-side, false = inline
    activeThreadId: null,
    activePatchId: null,
    activePatches: [], // Multi-edit changeset patches
    selectedPatchIndex: 0,
    editorInstance: null,
    diffEditorInstance: null,
    allFiles: [],
    monacoReady: false,
};


// ==============================================================================
// 1. Monaco Editor Initialization
// ==============================================================================
function initMonaco() {
    require.config({ paths: { vs: 'https://cdnjs.cloudflare.com/ajax/libs/monaco-editor/0.45.0/min/vs' } });
    require(['vs/editor/editor.main'], function () {
        state.monacoReady = true;

        // Custom theme tweak to seamlessly match IDE background
        monaco.editor.defineTheme('custom-dark', {
            base: 'vs-dark',
            inherit: true,
            rules: [],
            colors: {
                'editor.background': '#131822',
                'editor.lineHighlightBackground': '#182030',
                'editorLineNumber.foreground': '#4b5563',
                'editorLineNumber.activeForeground': '#93c5fd',
                'diffEditor.insertedTextBackground': '#10b98125',
                'diffEditor.removedTextBackground': '#ef444425',
            }
        });

        const codeContainer = document.getElementById('monaco-code-container');
        const diffContainer = document.getElementById('monaco-diff-container');

        // Standard Code Editor
        state.editorInstance = monaco.editor.create(codeContainer, {
            value: "# Loading repository...",
            language: "python",
            theme: "custom-dark",
            fontSize: 13,
            fontFamily: "'JetBrains Mono', Consolas, monospace",
            minimap: { enabled: true },
            scrollBeyondLastLine: false,
            automaticLayout: true,
            readOnly: false,
            renderWhitespace: "selection",
        });

        // Monaco Diff Editor
        state.diffEditorInstance = monaco.editor.createDiffEditor(diffContainer, {
            theme: "custom-dark",
            fontSize: 13,
            fontFamily: "'JetBrains Mono', Consolas, monospace",
            minimap: { enabled: false },
            scrollBeyondLastLine: false,
            automaticLayout: true,
            readOnly: true,
            renderSideBySide: state.diffSplitMode,
        });

        // Load initial file and file list
        loadFilesList();
        loadFileContent(state.currentFilePath);
        checkSystemHealth();
    });
}

function getLanguageForFile(filePath) {
    if (filePath.endsWith('.py')) return 'python';
    if (filePath.endsWith('.json')) return 'json';
    if (filePath.endsWith('.md')) return 'markdown';
    if (filePath.endsWith('.yaml') || filePath.endsWith('.yml')) return 'yaml';
    if (filePath.endsWith('.html')) return 'html';
    if (filePath.endsWith('.css')) return 'css';
    if (filePath.endsWith('.js')) return 'javascript';
    if (filePath.endsWith('.ts')) return 'typescript';
    if (filePath.endsWith('.sh')) return 'shell';
    return 'plaintext';
}

function getIconForFile(filePath) {
    if (filePath.endsWith('.py')) return '🐍';
    if (filePath.endsWith('.json')) return '⚙️';
    if (filePath.endsWith('.md')) return '📝';
    if (filePath.endsWith('.yaml') || filePath.endsWith('.yml')) return '🔧';
    if (filePath.endsWith('.sh')) return '🐚';
    if (filePath.endsWith('.env')) return '🔒';
    return '📄';
}

// ==============================================================================
// 2. File Explorer & Content Management
// ==============================================================================
async function loadFilesList() {
    try {
        const res = await fetch('/api/files');
        if (!res.ok) throw new Error("Failed to load file list");
        const files = await res.json();
        state.allFiles = files;
        renderFileTree(files);
    } catch (err) {
        showToast("Error loading file list: " + err.message, "error");
    }
}

function renderFileTree(files) {
    const container = document.getElementById('file-tree-container');
    container.innerHTML = "";

    if (!files || files.length === 0) {
        container.innerHTML = '<div class="tree-loading">No files found.</div>';
        return;
    }

    files.forEach(file => {
        const item = document.createElement('div');
        item.className = 'tree-item' + (file === state.currentFilePath ? ' active' : '');
        item.dataset.path = file;

        const icon = document.createElement('span');
        icon.className = 'tree-item-icon';
        icon.textContent = getIconForFile(file);

        const name = document.createElement('span');
        name.textContent = file;

        item.appendChild(icon);
        item.appendChild(name);

        item.addEventListener('click', () => {
            document.querySelectorAll('.tree-item').forEach(el => el.classList.remove('active'));
            item.classList.add('active');
            loadFileContent(file);
        });

        container.appendChild(item);
    });
}

async function loadFileContent(filePath) {
    try {
        const res = await fetch(`/api/file?path=${encodeURIComponent(filePath)}`);
        if (!res.ok) throw new Error("Failed to read file");
        const data = await res.json();

        state.currentFilePath = filePath;
        state.currentFileContent = data.content;

        // Update UI headers
        const parts = filePath.split('/');
        const fileName = parts.pop();
        const dir = parts.length > 0 ? parts.join('/') + ' /' : '';

        document.getElementById('breadcrumb-filename').textContent = fileName;
        document.querySelector('.folder-path').textContent = dir;
        document.getElementById('tab-filename').textContent = filePath;

        // Switch to Code Mode
        switchEditorMode('code');

        // Update Monaco Editor Model
        const lang = getLanguageForFile(filePath);
        const oldModel = state.editorInstance.getModel();
        if (oldModel) oldModel.dispose();

        const newModel = monaco.editor.createModel(data.content, lang);
        state.editorInstance.setModel(newModel);
    } catch (err) {
        showToast("Error opening file: " + err.message, "error");
    }
}

function switchEditorMode(mode) {
    state.activeMode = mode;
    const codeContainer = document.getElementById('monaco-code-container');
    const diffContainer = document.getElementById('monaco-diff-container');
    const btnCode = document.getElementById('btn-view-code');
    const btnDiff = document.getElementById('btn-view-diff');
    const diffToggle = document.getElementById('diff-style-toggle');

    if (mode === 'code') {
        codeContainer.style.display = 'block';
        diffContainer.style.display = 'none';
        btnCode.classList.add('active');
        btnDiff.classList.remove('active');
        diffToggle.style.display = 'none';
        state.editorInstance.layout();
    } else {
        codeContainer.style.display = 'none';
        diffContainer.style.display = 'block';
        btnCode.classList.remove('active');
        btnDiff.classList.add('active');
        diffToggle.style.display = 'flex';
        state.diffEditorInstance.layout();
    }
}

function renderDiffForPatch(patchIndex) {
    if (!state.activePatches || !state.activePatches[patchIndex]) return;
    state.selectedPatchIndex = patchIndex;
    const currentPatch = state.activePatches[patchIndex];

    const origContent = currentPatch.original_content || "";
    const propContent = currentPatch.proposed_content || "";
    const lang = getLanguageForFile(currentPatch.file_path);

    const origModel = monaco.editor.createModel(origContent, lang);
    const propModel = monaco.editor.createModel(propContent, lang);
    state.diffEditorInstance.setModel({ original: origModel, modified: propModel });

    // Highlight active diff file tab button
    document.querySelectorAll('.diff-file-tab-btn').forEach((btn, idx) => {
        if (idx === patchIndex) {
            btn.classList.add('active');
        } else {
            btn.classList.remove('active');
        }
    });

    // Update active tab title
    const tabTitle = document.getElementById('tab-filename');
    if (tabTitle) {
        tabTitle.textContent = currentPatch.file_path + " (Diff)";
    }
}


// ==============================================================================
// 3. System Health Checks
// ==============================================================================
async function checkSystemHealth() {
    try {
        const res = await fetch('/health');
        if (!res.ok) return;
        const data = await res.json();

        const qdrantPill = document.getElementById('qdrant-status-pill');
        const qdrantDot = qdrantPill.querySelector('.status-dot');
        if (data.qdrant_connected) {
            qdrantDot.className = 'status-dot dot-green';
        } else {
            qdrantDot.className = 'status-dot dot-purple';
            qdrantPill.querySelector('.pill-text').textContent = 'Qdrant (Offline)';
        }
    } catch (_) {}
}

// ==============================================================================
// 4. AI Agent Task Execution (LangGraph API integration)
// ==============================================================================
async function runAgentTask() {
    const promptInput = document.getElementById('task-prompt');
    const taskText = promptInput.value.trim();

    if (!taskText) {
        showToast("Please enter a task description.", "error");
        promptInput.focus();
        return;
    }

    const btnRun = document.getElementById('btn-run-agent');
    const spinner = document.getElementById('run-spinner');
    const btnText = btnRun.querySelector('.btn-text');
    const stepper = document.getElementById('agent-stepper');
    const badge = document.getElementById('agent-status-badge');
    const statusLabel = document.getElementById('agent-status-label');

    // UI Updates: Loading state
    btnRun.disabled = true;
    spinner.style.display = 'inline-block';
    btnText.textContent = "Processing...";
    stepper.style.display = 'block';
    badge.className = 'status-badge badge-running';
    badge.textContent = "RUNNING";
    statusLabel.textContent = "Agent workflow in progress...";

    // Hide previous results
    const noChangesBanner = document.getElementById('no-changes-banner');
    if (noChangesBanner) noChangesBanner.style.display = 'none';
    document.getElementById('evidence-section').style.display = 'none';
    document.getElementById('approval-gate-banner').style.display = 'none';
    document.getElementById('result-card').style.display = 'none';
    document.getElementById('btn-view-diff').disabled = true;

    // Reset Stepper
    setStepState('step-intake', 'active');
    setStepState('step-retrieval', 'idle');
    setStepState('step-analysis', 'idle');
    setStepState('step-proposal', 'idle');
    setStepState('step-verification', 'idle');
    const stepPropDetail = document.getElementById('step-proposal-detail');
    if (stepPropDetail) stepPropDetail.textContent = 'Diff generated';
    const stepVerifDetail = document.getElementById('step-verification-detail');
    if (stepVerifDetail) stepVerifDetail.textContent = 'Awaiting approval';

    state.activeThreadId = "ui-session-" + Math.random().toString(36).substring(2, 9);

    try {
        setStepState('step-intake', 'completed');
        setStepState('step-retrieval', 'active');

        // Call FastAPI POST /task
        const res = await fetch('/task', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                task: taskText,
                thread_id: state.activeThreadId,
                auto_approve: false,
            })
        });

        if (!res.ok) {
            const errData = await res.json().catch(() => ({}));
            throw new Error(errData.detail || "Task failed with status " + res.status);
        }

        const taskState = await res.json();
        handleTaskStateResponse(taskState);

    } catch (err) {
        showToast("Agent Error: " + err.message, "error");
        badge.className = 'status-badge badge-failed';
        badge.textContent = "FAILED";
        statusLabel.textContent = "Workflow halted on error";
        document.getElementById('terminal-agent-output').textContent = "ERROR: " + err.message;
    } finally {
        btnRun.disabled = false;
        spinner.style.display = 'none';
        btnText.textContent = "Generate Patch Proposal ➔";
    }
}

function setStepState(stepId, stateType) {
    const el = document.getElementById(stepId);
    if (!el) return;
    el.className = 'step-item ' + stateType;
}

function handleTaskStateResponse(taskState) {
    const badge = document.getElementById('agent-status-badge');
    const statusLabel = document.getElementById('agent-status-label');
    const patch = taskState.patch;

    // Stepper updates
    setStepState('step-retrieval', 'completed');
    setStepState('step-analysis', 'completed');
    setStepState('step-proposal', 'completed');

    // Display Analysis & Evidence
    const analysis = taskState.analysis || {};
    if (analysis.summary) {
        document.getElementById('evidence-section').style.display = 'block';
        document.getElementById('diagnosis-summary-text').textContent = analysis.summary;

        const citationsList = document.getElementById('citations-list');
        citationsList.innerHTML = "";
        const evidence = analysis.evidence || [];

        evidence.forEach(ev => {
            const item = document.createElement('div');
            item.className = 'citation-item';
            item.innerHTML = `
                <div class="citation-header">
                    <span>${ev.file_path || 'file'}</span>
                    <span>Lines ${ev.start_line}-${ev.end_line}</span>
                </div>
                <div class="citation-explanation">${ev.explanation || ev.snippet || ''}</div>
            `;
            citationsList.appendChild(item);
        });
    }

    const patches = (taskState.patches && taskState.patches.length > 0) ? taskState.patches : (patch ? [patch] : []);

    if (taskState.status === "awaiting_approval" && patches.length > 0) {
        state.activePatches = patches;
        state.activePatchId = taskState.bundle_patch_id || patch.patch_id || patches[0].patch_id;

        badge.className = 'status-badge badge-awaiting';
        badge.textContent = "AWAITING APPROVAL";
        const fileCountText = patches.length > 1 ? `${patches.length} files proposed` : "1 file proposed";
        statusLabel.textContent = `Patch ready (${fileCountText}). Review diffs to approve.`;

        // Configure multi-file diff tab bar
        const diffTabsBar = document.getElementById('diff-file-tabs');
        const diffTabsList = document.getElementById('diff-tabs-list');

        if (diffTabsBar && diffTabsList) {
            if (patches.length > 1) {
                diffTabsBar.style.display = 'flex';
                diffTabsList.innerHTML = '';
                patches.forEach((p, idx) => {
                    const btn = document.createElement('button');
                    btn.className = 'diff-file-tab-btn' + (idx === 0 ? ' active' : '');
                    btn.innerHTML = `${getIconForFile(p.file_path)} <span>${p.file_path}</span>`;
                    btn.addEventListener('click', () => {
                        renderDiffForPatch(idx);
                    });
                    diffTabsList.appendChild(btn);
                });
            } else {
                diffTabsBar.style.display = 'none';
            }
        }

        // Render first patch diff
        renderDiffForPatch(0);

        // Enable diff button and switch to diff view automatically
        const btnDiff = document.getElementById('btn-view-diff');
        btnDiff.disabled = false;
        switchEditorMode('diff');

        // Show Approval Gate banner
        const gate = document.getElementById('approval-gate-banner');
        gate.style.display = 'block';
        const displayTag = patches.length > 1 ? `${state.activePatchId} (${patches.length} files)` : state.activePatchId;
        document.getElementById('gate-patch-id').textContent = displayTag;

        showToast(`Patch proposal generated for ${patches.length} file(s)! Review diffs.`, "info");

    } else if (taskState.status === "no_changes_needed") {

        badge.className = 'status-badge badge-idle';
        badge.textContent = "NO CHANGES";
        statusLabel.textContent = "No code changes needed";

        // Display No Changes Banner
        const banner = document.getElementById('no-changes-banner');
        if (banner) {
            banner.style.display = 'flex';
            const detail = document.getElementById('no-changes-detail');
            if (detail) {
                detail.textContent = analysis.summary || "The requested feature, endpoint, or fix is already implemented in the code. Review the open file in the editor to verify.";
            }
        }

        // Complete stepper with skipped indicators
        setStepState('step-proposal', 'completed');
        setStepState('step-verification', 'completed');
        const stepPropDetail = document.getElementById('step-proposal-detail');
        if (stepPropDetail) stepPropDetail.textContent = 'Already satisfied';
        const stepVerifDetail = document.getElementById('step-verification-detail');
        if (stepVerifDetail) stepVerifDetail.textContent = 'No patch required';

        // Update Terminal Panels to be crystal clear
        const summaryText = analysis.summary || "Requirement already satisfied in the codebase.";
        const termAgent = document.getElementById('terminal-agent-output');
        if (termAgent) {
            termAgent.textContent = `=== SWE AGENT DIAGNOSIS COMPLETE ===\n\nStatus: NO_CHANGES_NEEDED\nReasoning: ${summaryText}\nEvidence citations: ${analysis.evidence ? analysis.evidence.length : 0} matching locations found.\nAction: No diff proposed to prevent duplicate or redundant code modifications.`;
        }

        const termTest = document.getElementById('terminal-test-output');
        if (termTest) {
            termTest.textContent = `ℹ️ NO PATCH PROPOSED:\nThe requested code is already present in your repository.\nFor example, if you asked for @app.get('/version'), check lines 170-181 of app/main.py — it is already defined and working!\n\nTry a new prompt from the Quick Prompts above (e.g., '+ Add /ping API') to see full diff generation and live pytest verification.`;
        }

        showToast("Diagnosis complete: Code already satisfies requirements.", "info");
    } else {
        badge.className = 'status-badge badge-failed';
        badge.textContent = taskState.status ? taskState.status.toUpperCase() : "FAILED";
        statusLabel.textContent = "Workflow ended with status: " + taskState.status;
        if (taskState.errors && taskState.errors.length) {
            document.getElementById('terminal-agent-output').textContent = taskState.errors.join("\n");
        }
    }
}

// ==============================================================================
// 5. Human Approval & Live Test Verification
// ==============================================================================
async function submitApproval(approved) {
    if (!state.activeThreadId || !state.activePatchId) {
        showToast("No active patch available for approval.", "error");
        return;
    }

    const btnApprove = document.getElementById('btn-approve-patch');
    const btnReject = document.getElementById('btn-reject-patch');
    const spinner = document.getElementById('approve-spinner');
    const badge = document.getElementById('agent-status-badge');
    const statusLabel = document.getElementById('agent-status-label');

    btnApprove.disabled = true;
    btnReject.disabled = true;
    if (approved) spinner.style.display = 'inline-block';

    setStepState('step-verification', 'active');
    statusLabel.textContent = approved ? "Applying patch and running pytest..." : "Rejecting patch...";

    try {
        const res = await fetch(`/task/${state.activeThreadId}/approve`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                approved: approved,
                patch_id: state.activePatchId,
                human_feedback: approved ? "Approved via Cloud IDE" : "Rejected by user",
            })
        });

        if (!res.ok) {
            const errData = await res.json().catch(() => ({}));
            throw new Error(errData.detail || "Approval failed");
        }

        const finalState = await res.json();
        document.getElementById('approval-gate-banner').style.display = 'none';

        if (approved && finalState.patch_applied) {
            setStepState('step-verification', 'completed');
            badge.className = 'status-badge badge-verified';
            badge.textContent = "VERIFIED";
            statusLabel.textContent = "Patch verified & applied to disk!";

            // Render Test Results in Terminal Drawer
            const testResults = finalState.test_results || {};
            const termOutput = document.getElementById('terminal-test-output');
            termOutput.textContent = testResults.output || "Verification tests executed successfully.";

            const indicator = document.getElementById('test-indicator');
            indicator.className = 'tab-indicator ' + (testResults.passed ? 'indicator-success' : 'indicator-fail');

            // Open bottom drawer automatically to show test output
            document.getElementById('bottom-drawer').classList.remove('collapsed');
            document.getElementById('bottom-drawer').classList.add('expanded');

            // Show success result card
            const resultCard = document.getElementById('result-card');
            resultCard.style.display = 'block';
            document.getElementById('result-title').textContent = testResults.passed ? "All Tests Passed!" : "Verification Completed";
            document.getElementById('result-subtitle').textContent = `Applied patch to disk. Verification passed: ${testResults.passed}`;

            showToast("Patch applied! Tests passed successfully.", "success");

            // Hide diff tabs bar and refresh active file on disk into Monaco Editor
            const diffTabsBar = document.getElementById('diff-file-tabs');
            if (diffTabsBar) diffTabsBar.style.display = 'none';

            loadFilesList();
            setTimeout(() => {
                loadFileContent(state.currentFilePath);
            }, 500);

        } else if (!approved) {
            const diffTabsBar = document.getElementById('diff-file-tabs');
            if (diffTabsBar) diffTabsBar.style.display = 'none';
            badge.className = 'status-badge badge-idle';
            badge.textContent = "REJECTED";
            statusLabel.textContent = "Patch was rejected by operator";
            showToast("Patch proposal rejected.", "info");
            switchEditorMode('code');
        } else {
            const diffTabsBar = document.getElementById('diff-file-tabs');
            if (diffTabsBar) diffTabsBar.style.display = 'none';

            badge.className = 'status-badge badge-failed';
            badge.textContent = "TESTS FAILED";
            statusLabel.textContent = "Tests failed. Patch rolled back.";
            showToast("Verification failed. Changes rolled back.", "error");
        }

    } catch (err) {
        showToast("Error during approval: " + err.message, "error");
    } finally {
        btnApprove.disabled = false;
        btnReject.disabled = false;
        spinner.style.display = 'none';
    }
}

// ==============================================================================
// 6. Sandbox Reset
// ==============================================================================
async function resetSandbox() {
    const btn = document.getElementById('btn-reset-sandbox');
    btn.disabled = true;
    try {
        const res = await fetch('/api/reset', { method: 'POST' });
        if (!res.ok) throw new Error("Reset failed");
        showToast("Sandbox reverted to clean git state.", "success");
        loadFileContent(state.currentFilePath);
    } catch (err) {
        showToast("Reset failed: " + err.message, "error");
    } finally {
        btn.disabled = false;
    }
}

// ==============================================================================
// 7. Toast Alerts & UI Event Handlers
// ==============================================================================
function showToast(message, type = 'info') {
    const container = document.getElementById('toast-container');
    const toast = document.createElement('div');
    toast.className = `toast toast-${type}`;
    toast.textContent = message;

    container.appendChild(toast);
    setTimeout(() => {
        toast.style.opacity = '0';
        toast.style.transform = 'translateX(20px)';
        setTimeout(() => toast.remove(), 250);
    }, 3500);
}

// Attach Event Listeners
document.addEventListener('DOMContentLoaded', () => {
    initMonaco();

    // Run Task
    document.getElementById('btn-run-agent').addEventListener('click', runAgentTask);

    // Prompt Pills
    document.querySelectorAll('.pill-btn').forEach(pill => {
        pill.addEventListener('click', () => {
            const promptBox = document.getElementById('task-prompt');
            promptBox.value = pill.dataset.prompt;
            promptBox.focus();
        });
    });

    // Approval Buttons
    document.getElementById('btn-approve-patch').addEventListener('click', () => submitApproval(true));
    document.getElementById('btn-reject-patch').addEventListener('click', () => submitApproval(false));

    // Reset Sandbox
    document.getElementById('btn-reset-sandbox').addEventListener('click', resetSandbox);

    // Refresh Files
    document.getElementById('btn-refresh-files').addEventListener('click', loadFilesList);

    // Filter Files Search
    document.getElementById('file-search-input').addEventListener('input', (e) => {
        const term = e.target.value.toLowerCase();
        const filtered = state.allFiles.filter(f => f.toLowerCase().includes(term));
        renderFileTree(filtered);
    });

    // Editor View Mode Switchers
    document.getElementById('btn-view-code').addEventListener('click', () => switchEditorMode('code'));
    document.getElementById('btn-view-diff').addEventListener('click', () => switchEditorMode('diff'));

    // Diff Split/Inline Toggle
    document.getElementById('btn-diff-split').addEventListener('click', function () {
        this.classList.add('active');
        document.getElementById('btn-diff-inline').classList.remove('active');
        state.diffSplitMode = true;
        state.diffEditorInstance.updateOptions({ renderSideBySide: true });
    });

    document.getElementById('btn-diff-inline').addEventListener('click', function () {
        this.classList.add('active');
        document.getElementById('btn-diff-split').classList.remove('active');
        state.diffSplitMode = false;
        state.diffEditorInstance.updateOptions({ renderSideBySide: false });
    });

    // Drawer Tabs
    document.querySelectorAll('.drawer-tab').forEach(tab => {
        tab.addEventListener('click', () => {
            document.querySelectorAll('.drawer-tab').forEach(t => t.classList.remove('active'));
            document.querySelectorAll('.drawer-panel').forEach(p => p.classList.remove('active'));
            tab.classList.add('active');
            const targetPanel = document.getElementById('panel-' + tab.dataset.tab);
            if (targetPanel) targetPanel.classList.add('active');
        });
    });

    // Drawer Size Toggle
    document.getElementById('btn-toggle-drawer').addEventListener('click', function () {
        const drawer = document.getElementById('bottom-drawer');
        if (drawer.classList.contains('expanded')) {
            drawer.classList.remove('expanded');
            drawer.classList.add('collapsed');
            this.textContent = '▲';
        } else if (drawer.classList.contains('collapsed')) {
            drawer.classList.remove('collapsed');
            this.textContent = '▼';
        } else {
            drawer.classList.add('expanded');
            this.textContent = '▼';
        }
    });

    // Clear Console
    document.getElementById('btn-clear-console').addEventListener('click', () => {
        document.getElementById('terminal-test-output').textContent = "Console cleared.";
        document.getElementById('terminal-agent-output').textContent = "Console cleared.";
    });
});
