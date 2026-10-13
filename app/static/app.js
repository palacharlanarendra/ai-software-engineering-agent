/**
 * Antigravity SWE Agent — Cloud IDE Application Logic
 * Single Page Application integrating Monaco Editor, Hierarchical Tree,
 * Live Git Diff Viewer, Antigravity Changes Review Bar, and LangGraph REST APIs
 */

// Application State
const state = {
    currentFilePath: "app/main.py",
    currentFileContent: "",
    activeMode: "code", // 'code' | 'diff'
    diffSplitMode: true, // true = side-by-side, false = inline
    diffSource: "agent", // 'agent' | 'git'
    activeThreadId: null,
    activePatchId: null,
    activePatches: [], // Proposed patches from agent
    selectedPatchIndex: 0,
    activeGitDiffPath: null,
    editorInstance: null,
    diffEditorInstance: null,
    allFiles: [],
    openTabs: ["app/main.py"],
    activeSidebarView: "explorer", // 'explorer' | 'changes'
    gitChanges: {}, // map: path -> { path, status, additions, deletions }
    gitStats: { total_additions: 0, total_deletions: 0, total_files: 0 },
    expandedFolders: new Set(["app", "app/agent", "app/tools", "app/rag", "app/static", "app/tests", "scripts"]),
    searchQuery: "",
    monacoReady: false,
};

// ==============================================================================
// 1. Monaco Editor Initialization
// ==============================================================================
function initMonaco() {
    require.config({ paths: { vs: 'https://cdnjs.cloudflare.com/ajax/libs/monaco-editor/0.45.0/min/vs' } });
    require(['vs/editor/editor.main'], function () {
        state.monacoReady = true;

        // Custom Antigravity dark theme matching IDE background
        monaco.editor.defineTheme('antigravity-dark', {
            base: 'vs-dark',
            inherit: true,
            rules: [
                { token: 'comment', foreground: '6272a4', fontStyle: 'italic' },
                { token: 'keyword', foreground: 'ff79c6', fontStyle: 'bold' },
                { token: 'string', foreground: 'f1fa8c' },
                { token: 'number', foreground: 'bd93f9' },
                { token: 'type', foreground: '8be9fd' },
            ],
            colors: {
                'editor.background': '#131822',
                'editor.foreground': '#f8fafc',
                'editor.lineHighlightBackground': '#182030',
                'editorLineNumber.foreground': '#4b5563',
                'editorLineNumber.activeForeground': '#93c5fd',
                'editorIndentGuide.background': '#1c2436',
                'editorIndentGuide.activeBackground': '#3b82f6',
                'diffEditor.insertedTextBackground': '#10b98125',
                'diffEditor.removedTextBackground': '#ef444425',
                'diffEditor.insertedLineBackground': '#10b98115',
                'diffEditor.removedLineBackground': '#ef444415',
            }
        });

        const codeContainer = document.getElementById('monaco-code-container');
        const diffContainer = document.getElementById('monaco-diff-container');

        // Standard Code Editor with rich UX settings
        state.editorInstance = monaco.editor.create(codeContainer, {
            value: "# Loading repository...",
            language: "python",
            theme: "antigravity-dark",
            fontSize: 13,
            fontFamily: "'JetBrains Mono', Consolas, monospace",
            minimap: { enabled: true, renderCharacters: false },
            scrollBeyondLastLine: false,
            automaticLayout: true,
            readOnly: false,
            renderWhitespace: "selection",
            bracketPairColorization: { enabled: true },
            cursorBlinking: "smooth",
            smoothScrolling: true,
        });

        // Monaco Diff Editor
        state.diffEditorInstance = monaco.editor.createDiffEditor(diffContainer, {
            theme: "antigravity-dark",
            fontSize: 13,
            fontFamily: "'JetBrains Mono', Consolas, monospace",
            minimap: { enabled: false },
            scrollBeyondLastLine: false,
            automaticLayout: true,
            readOnly: true,
            renderSideBySide: state.diffSplitMode,
            bracketPairColorization: { enabled: true },
        });

        // Initial Data Loads
        loadFilesList();
        loadGitChanges();
        loadFileContent(state.currentFilePath);
        checkSystemHealth();
    });
}

function getLanguageForFile(filePath) {
    if (!filePath) return 'plaintext';
    if (filePath.endsWith('.py')) return 'python';
    if (filePath.endsWith('.json')) return 'json';
    if (filePath.endsWith('.md')) return 'markdown';
    if (filePath.endsWith('.yaml') || filePath.endsWith('.yml')) return 'yaml';
    if (filePath.endsWith('.html')) return 'html';
    if (filePath.endsWith('.css')) return 'css';
    if (filePath.endsWith('.js')) return 'javascript';
    if (filePath.endsWith('.ts')) return 'typescript';
    if (filePath.endsWith('.sh')) return 'shell';
    if (filePath.endsWith('.ini')) return 'ini';
    return 'plaintext';
}

function getIconForFile(filePath) {
    if (!filePath) return '📄';
    if (filePath.endsWith('.py')) return '🐍';
    if (filePath.endsWith('.json')) return '⚙️';
    if (filePath.endsWith('.md')) return '📝';
    if (filePath.endsWith('.yaml') || filePath.endsWith('.yml')) return '🔧';
    if (filePath.endsWith('.html')) return '🌐';
    if (filePath.endsWith('.css')) return '🎨';
    if (filePath.endsWith('.js')) return '⚡';
    if (filePath.endsWith('.ts')) return '🔷';
    if (filePath.endsWith('.sh')) return '🐚';
    if (filePath.endsWith('.env')) return '🔒';
    if (filePath.endsWith('.ini')) return '⚙️';
    if (filePath.endsWith('.txt')) return '📄';
    return '📄';
}

// ==============================================================================
// 2. Hierarchical File Tree & Folder Expand / Compress
// ==============================================================================

/**
 * Builds nested tree object from flat path array
 */
function buildTreeFromFileList(fileList) {
    const root = {
        name: "ai-software-engineering-agent",
        type: "directory",
        path: "",
        children: {},
    };

    fileList.forEach(filePath => {
        const parts = filePath.split('/');
        let current = root;
        let currentPath = "";

        for (let i = 0; i < parts.length; i++) {
            const part = parts[i];
            currentPath = currentPath ? `${currentPath}/${part}` : part;
            const isFile = (i === parts.length - 1);

            if (isFile) {
                current.children[part] = {
                    name: part,
                    type: "file",
                    path: filePath,
                };
            } else {
                if (!current.children[part]) {
                    current.children[part] = {
                        name: part,
                        type: "directory",
                        path: currentPath,
                        children: {},
                    };
                }
                current = current.children[part];
            }
        }
    });

    return root;
}

/**
 * Checks if directory node has any modified descendants in git or active patches
 */
function hasModifiedDescendant(node) {
    if (node.type === "file") {
        return Boolean(state.gitChanges[node.path] || state.activePatches.some(p => p.file_path === node.path));
    }
    if (node.children) {
        return Object.values(node.children).some(child => hasModifiedDescendant(child));
    }
    return false;
}

/**
 * Recursively renders tree nodes into container
 */
function renderTreeNode(node, container, depth, matchingPaths, activeExpandedSet) {
    // Sort keys: directories first (alphabetical), then files (alphabetical)
    const childKeys = Object.keys(node.children || {}).sort((a, b) => {
        const itemA = node.children[a];
        const itemB = node.children[b];
        if (itemA.type !== itemB.type) {
            return itemA.type === "directory" ? -1 : 1;
        }
        return a.localeCompare(b);
    });

    childKeys.forEach(key => {
        const item = node.children[key];

        // Filter by search query if search is active
        if (matchingPaths) {
            const isMatch = item.type === "file" ? matchingPaths.has(item.path) : Array.from(matchingPaths).some(p => p.startsWith(item.path + '/'));
            if (!isMatch) return;
        }

        const indentPx = 8 + depth * 14;

        if (item.type === "directory") {
            const isExpanded = activeExpandedSet.has(item.path);
            const hasMod = hasModifiedDescendant(item);

            // Folder row
            const folderRow = document.createElement('div');
            folderRow.className = 'tree-node folder-node';
            folderRow.dataset.path = item.path;
            folderRow.style.paddingLeft = `${indentPx}px`;

            const chevron = document.createElement('span');
            chevron.className = `tree-chevron ${isExpanded ? 'open' : ''}`;
            chevron.textContent = '▸';

            const icon = document.createElement('span');
            icon.className = 'tree-folder-icon';
            icon.textContent = isExpanded ? '📂' : '📁';

            const label = document.createElement('span');
            label.className = 'tree-label';
            label.textContent = item.name;

            folderRow.appendChild(chevron);
            folderRow.appendChild(icon);
            folderRow.appendChild(label);

            if (hasMod) {
                const dot = document.createElement('span');
                dot.className = 'folder-modified-dot';
                dot.title = 'Contains modified files';
                folderRow.appendChild(dot);
            }

            // Children container
            const childrenContainer = document.createElement('div');
            childrenContainer.className = `folder-children ${isExpanded ? '' : 'collapsed'}`;
            childrenContainer.dataset.parentPath = item.path;

            // Click listener for Expand/Compress
            folderRow.addEventListener('click', (e) => {
                e.stopPropagation();
                const nowExpanded = !state.expandedFolders.has(item.path);
                if (nowExpanded) {
                    state.expandedFolders.add(item.path);
                    chevron.classList.add('open');
                    icon.textContent = '📂';
                    childrenContainer.classList.remove('collapsed');
                } else {
                    state.expandedFolders.delete(item.path);
                    chevron.classList.remove('open');
                    icon.textContent = '📁';
                    childrenContainer.classList.add('collapsed');
                }
            });

            container.appendChild(folderRow);
            container.appendChild(childrenContainer);

            // Recursively render children
            renderTreeNode(item, childrenContainer, depth + 1, matchingPaths, activeExpandedSet);

        } else {
            // File row
            const fileRow = document.createElement('div');
            const isActive = (item.path === state.currentFilePath);
            fileRow.className = `tree-node file-node ${isActive ? 'active' : ''}`;
            fileRow.dataset.path = item.path;
            fileRow.style.paddingLeft = `${indentPx}px`;

            const spacer = document.createElement('span');
            spacer.className = 'tree-indent-spacer';

            const icon = document.createElement('span');
            icon.className = 'tree-file-icon';
            icon.textContent = getIconForFile(item.name);

            const label = document.createElement('span');
            label.className = 'tree-label';
            label.textContent = item.name;

            fileRow.appendChild(spacer);
            fileRow.appendChild(icon);
            fileRow.appendChild(label);

            // Check git changes or patch proposals for 'M', 'A', 'D' badges
            const gitMod = state.gitChanges[item.path];
            const patchMod = state.activePatches.find(p => p.file_path === item.path);

            if (gitMod || patchMod) {
                const badge = document.createElement('span');
                const statusCode = (patchMod ? 'M' : (gitMod ? gitMod.status : 'M'));
                badge.className = `tree-git-badge status-${statusCode.toLowerCase()}`;
                badge.textContent = statusCode;
                badge.title = gitMod ? `Git modified (+${gitMod.additions} -${gitMod.deletions})` : 'Proposed Patch';
                fileRow.appendChild(badge);
            }

            fileRow.addEventListener('click', () => {
                document.querySelectorAll('.file-node').forEach(el => el.classList.remove('active'));
                fileRow.classList.add('active');
                openFile(item.path);
            });

            container.appendChild(fileRow);
        }
    });
}

/**
 * Main Tree Renderer
 */
function renderFileTree() {
    const container = document.getElementById('file-tree-container');
    container.innerHTML = "";

    if (!state.allFiles || state.allFiles.length === 0) {
        container.innerHTML = '<div class="tree-loading">No files found.</div>';
        return;
    }

    const treeRoot = buildTreeFromFileList(state.allFiles);
    let matchingPaths = null;
    let activeExpandedSet = new Set(state.expandedFolders);

    // Apply Search Filter if any
    const searchVal = state.searchQuery.trim().toLowerCase();
    const matchInfo = document.getElementById('search-match-info');
    const clearBtn = document.getElementById('btn-clear-search');

    if (searchVal) {
        clearBtn.style.display = 'block';
        const matches = state.allFiles.filter(f => f.toLowerCase().includes(searchVal));
        matchingPaths = new Set(matches);
        matchInfo.style.display = 'block';
        matchInfo.textContent = `${matches.length} matching file${matches.length === 1 ? '' : 's'}`;

        // Auto-expand all ancestor directories of matched files
        matches.forEach(p => {
            const parts = p.split('/');
            let accumulated = "";
            for (let i = 0; i < parts.length - 1; i++) {
                accumulated = accumulated ? `${accumulated}/${parts[i]}` : parts[i];
                activeExpandedSet.add(accumulated);
            }
        });
    } else {
        clearBtn.style.display = 'none';
        matchInfo.style.display = 'none';
    }

    renderTreeNode(treeRoot, container, 0, matchingPaths, activeExpandedSet);
}

/**
 * Expand all folders
 */
function expandAllFolders() {
    state.allFiles.forEach(f => {
        const parts = f.split('/');
        let cur = "";
        for (let i = 0; i < parts.length - 1; i++) {
            cur = cur ? `${cur}/${parts[i]}` : parts[i];
            state.expandedFolders.add(cur);
        }
    });
    renderFileTree();
}

/**
 * Collapse all folders
 */
function collapseAllFolders() {
    state.expandedFolders.clear();
    renderFileTree();
}

/**
 * Load Files list from API
 */
async function loadFilesList() {
    try {
        const res = await fetch('/api/files');
        if (!res.ok) throw new Error("Failed to load file list");
        const files = await res.json();
        state.allFiles = files;
        renderFileTree();
    } catch (err) {
        showToast("Error loading file list: " + err.message, "error");
    }
}

// ==============================================================================
// 3. Git Changes & Working Tree Diffs
// ==============================================================================

async function loadGitChanges() {
    try {
        const res = await fetch('/api/git/changes');
        if (!res.ok) return;
        const data = await res.json();

        state.gitStats = {
            total_additions: data.total_additions || 0,
            total_deletions: data.total_deletions || 0,
            total_files: data.total_files || 0,
        };

        const changeMap = {};
        (data.changes || []).forEach(c => {
            changeMap[c.path] = c;
        });
        state.gitChanges = changeMap;

        // Update UI Pills and Badges
        updateGitStatusUI(data);
        renderSourceControlPane(data);
        renderDrawerGitChanges(data);

        // Re-render tree so 'M' badges and folder dots update
        renderFileTree();

    } catch (err) {
        console.warn("Could not load git changes:", err);
    }
}

function updateGitStatusUI(data) {
    const pill = document.getElementById('git-status-pill');
    const dot = document.getElementById('git-status-dot');
    const text = document.getElementById('git-status-text');
    const countBadge = document.getElementById('changes-count-badge');
    const rootBadge = document.getElementById('root-changes-badge');
    const quickbar = document.getElementById('git-changes-quickbar');
    const quickbarStat = document.getElementById('quickbar-stat');

    const total = data.total_files || 0;
    if (total > 0) {
        dot.className = 'status-dot dot-amber';
        text.innerHTML = `${total} changes <span class="diff-add">+${data.total_additions}</span> <span class="diff-del">-${data.total_deletions}</span>`;
        countBadge.style.display = 'block';
        countBadge.textContent = total;
        rootBadge.style.display = 'inline-block';
        rootBadge.textContent = `${total} M`;

        if (quickbar && quickbarStat) {
            quickbar.style.display = 'flex';
            quickbarStat.innerHTML = `<span class="diff-add">+${data.total_additions}</span> <span class="diff-del">-${data.total_deletions}</span>`;
        }
    } else {
        dot.className = 'status-dot dot-green';
        text.textContent = 'Git Clean';
        countBadge.style.display = 'none';
        rootBadge.style.display = 'none';
        if (quickbar) quickbar.style.display = 'none';
    }
}

function renderSourceControlPane(data) {
    const container = document.getElementById('changes-files-container');
    const countText = document.getElementById('changes-pane-count');
    const statAdd = document.getElementById('pane-stat-add');
    const statDel = document.getElementById('pane-stat-del');

    if (!container) return;

    countText.textContent = `${data.total_files || 0} files changed`;
    statAdd.textContent = `+${data.total_additions || 0}`;
    statDel.textContent = `-${data.total_deletions || 0}`;

    container.innerHTML = "";
    const changes = data.changes || [];
    if (changes.length === 0) {
        container.innerHTML = '<div class="tree-loading">No working tree changes.</div>';
        return;
    }

    changes.forEach(c => {
        const row = document.createElement('div');
        row.className = 'changes-file-row';
        row.innerHTML = `
            <div style="display: flex; align-items: center; gap: 6px; overflow: hidden;">
                <span>${getIconForFile(c.path)}</span>
                <span style="overflow: hidden; text-overflow: ellipsis; white-space: nowrap;">${c.path}</span>
            </div>
            <div style="display: flex; align-items: center; gap: 8px; flex-shrink: 0;">
                <span class="diff-stat-pill"><span class="pill-add">+${c.additions}</span><span class="pill-del">-${c.deletions}</span></span>
                <span class="tree-git-badge status-${c.status.toLowerCase()}">${c.status}</span>
            </div>
        `;

        row.addEventListener('click', () => {
            document.querySelectorAll('.changes-file-row').forEach(el => el.classList.remove('active'));
            row.classList.add('active');
            openGitDiff(c.path);
        });

        container.appendChild(row);
    });
}

function renderDrawerGitChanges(data) {
    const list = document.getElementById('drawer-git-changes-list');
    if (!list) return;

    list.innerHTML = "";
    const changes = data.changes || [];
    if (changes.length === 0) {
        list.innerHTML = '<div class="drawer-git-loading">Working tree is clean. No uncommitted modifications.</div>';
        return;
    }

    changes.forEach(c => {
        const card = document.createElement('div');
        card.className = 'drawer-git-file-card';
        card.innerHTML = `
            <div style="display: flex; align-items: center; gap: 8px;">
                <span>${getIconForFile(c.path)}</span>
                <strong>${c.path}</strong>
                <span class="tree-git-badge status-${c.status.toLowerCase()}">${c.status}</span>
            </div>
            <div style="display: flex; align-items: center; gap: 12px;">
                <span class="diff-stat-pill"><span class="pill-add">+${c.additions}</span><span class="pill-del">-${c.deletions}</span></span>
                <button class="btn btn-secondary btn-sm" data-diff-path="${c.path}">⚡ Inspect Diff</button>
            </div>
        `;

        const btn = card.querySelector('button');
        btn.addEventListener('click', () => openGitDiff(c.path));

        list.appendChild(card);
    });
}

/**
 * Loads and renders Git Diff against HEAD in Monaco Diff Editor
 */
async function openGitDiff(filePath) {
    try {
        const res = await fetch(`/api/git/diff?path=${encodeURIComponent(filePath)}`);
        if (!res.ok) throw new Error("Failed to load git diff");
        const data = await res.json();

        state.diffSource = 'git';
        state.activeGitDiffPath = filePath;

        const lang = getLanguageForFile(filePath);
        const origModel = monaco.editor.createModel(data.original_content || "", lang);
        const propModel = monaco.editor.createModel(data.modified_content || "", lang);
        state.diffEditorInstance.setModel({ original: origModel, modified: propModel });

        // Update active tab title
        const tabTitle = document.getElementById('tab-filename');
        if (tabTitle) tabTitle.textContent = `${filePath} (Git Diff)`;

        // Enable and switch to diff mode
        const btnDiff = document.getElementById('btn-view-diff');
        btnDiff.disabled = false;
        switchEditorMode('diff');

        // Configure Antigravity Review Bar for Git Changes
        setupGitReviewBar(filePath, data);

        showToast(`Inspecting git diff for ${filePath}`, "info");

    } catch (err) {
        showToast("Error loading git diff: " + err.message, "error");
    }
}

function setupGitReviewBar(activePath, diffData) {
    const reviewBar = document.getElementById('antigravity-review-bar');
    const statText = document.getElementById('review-stat-text');
    const filesList = document.getElementById('review-files-list');
    const countLabel = document.getElementById('review-count-label');
    const btnAccept = document.getElementById('btn-review-accept-all');
    const btnReject = document.getElementById('btn-review-reject-all');

    if (!reviewBar) return;

    reviewBar.style.display = 'flex';
    const changes = Object.values(state.gitChanges);
    statText.innerHTML = `${changes.length} files changed <span class="diff-add">+${state.gitStats.total_additions}</span> <span class="diff-del">-${state.gitStats.total_deletions}</span>`;
    countLabel.textContent = `${changes.length} Working Changes`;

    btnAccept.textContent = 'Keep Changes';
    btnReject.textContent = 'Reset Sandbox';
    btnReject.onclick = resetSandbox;
    btnAccept.onclick = () => {
        reviewBar.style.display = 'none';
        showToast("Changes kept in sandbox.", "info");
    };

    filesList.innerHTML = '';
    changes.forEach(c => {
        const row = document.createElement('div');
        row.className = `review-file-row ${c.path === activePath ? 'active' : ''}`;
        const parts = c.path.split('/');
        const basename = parts.pop();
        const dirname = parts.join('/');

        row.innerHTML = `
            <span class="diff-stat-pill"><span class="pill-add">+${c.additions}</span><span class="pill-del">-${c.deletions}</span></span>
            <span class="file-basename">${basename}</span>
            <span class="file-dirname">${dirname || '.'}</span>
        `;

        row.addEventListener('click', () => {
            openGitDiff(c.path);
        });

        filesList.appendChild(row);
    });
}

// ==============================================================================
// 4. File Content Loading & Multi-Tab Management
// ==============================================================================

async function openFile(filePath) {
    if (!state.openTabs.includes(filePath)) {
        state.openTabs.push(filePath);
    }
    renderTabs();
    await loadFileContent(filePath);
}

function renderTabs() {
    const container = document.getElementById('tabs-container');
    if (!container) return;
    container.innerHTML = '';

    state.openTabs.forEach(file => {
        const isActive = (file === state.currentFilePath && state.activeMode === 'code');
        const isModified = Boolean(state.gitChanges[file] || state.activePatches.some(p => p.file_path === file));

        const tab = document.createElement('div');
        tab.className = `tab-item ${isActive ? 'active' : ''}`;
        tab.dataset.path = file;

        const icon = document.createElement('span');
        icon.className = 'tab-icon';
        icon.textContent = getIconForFile(file);

        const title = document.createElement('span');
        title.className = 'tab-title';
        title.textContent = file;

        tab.appendChild(icon);
        tab.appendChild(title);

        if (isModified) {
            const dot = document.createElement('span');
            dot.className = 'tab-status-dot';
            dot.title = 'Modified';
            tab.appendChild(dot);
        }

        // Close tab button
        const closeBtn = document.createElement('button');
        closeBtn.className = 'tab-close-btn';
        closeBtn.textContent = '×';
        closeBtn.title = 'Close tab';
        closeBtn.addEventListener('click', (e) => {
            e.stopPropagation();
            closeTab(file);
        });
        tab.appendChild(closeBtn);

        tab.addEventListener('click', () => {
            openFile(file);
        });

        container.appendChild(tab);
    });
}

function closeTab(filePath) {
    state.openTabs = state.openTabs.filter(f => f !== filePath);
    if (state.openTabs.length === 0) {
        state.openTabs = ["README.md"];
    }
    if (state.currentFilePath === filePath) {
        const nextFile = state.openTabs[state.openTabs.length - 1];
        openFile(nextFile);
    } else {
        renderTabs();
    }
}

async function loadFileContent(filePath) {
    try {
        const res = await fetch(`/api/file?path=${encodeURIComponent(filePath)}`);
        if (!res.ok) throw new Error("Failed to read file");
        const data = await res.json();

        state.currentFilePath = filePath;
        state.currentFileContent = data.content;

        // Update Breadcrumbs
        updateBreadcrumbs(filePath);

        // Switch to Code Mode
        switchEditorMode('code');

        // Update Monaco Editor Model
        const lang = getLanguageForFile(filePath);
        const oldModel = state.editorInstance.getModel();
        if (oldModel) oldModel.dispose();

        const newModel = monaco.editor.createModel(data.content, lang);
        state.editorInstance.setModel(newModel);

        renderTabs();

    } catch (err) {
        showToast("Error opening file: " + err.message, "error");
    }
}

function updateBreadcrumbs(filePath) {
    const parts = filePath.split('/');
    const fileName = parts.pop();
    const dir = parts.join(' › ');

    const breadcrumbRoot = document.querySelector('.breadcrumb-root');
    const folderPath = document.querySelector('.folder-path');
    const breadcrumbFilename = document.getElementById('breadcrumb-filename');

    if (breadcrumbRoot) breadcrumbRoot.textContent = "ai-software-engineering-agent";
    if (folderPath) folderPath.textContent = dir || "root";
    if (breadcrumbFilename) breadcrumbFilename.textContent = fileName;
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
    renderTabs();
}

// ==============================================================================
// 5. AI Agent Task Execution & Patch Proposal
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

    state.activeThreadId = "ui-session-" + Math.random().toString(36).substring(2, 9);

    try {
        setStepState('step-intake', 'completed');
        setStepState('step-retrieval', 'active');

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
        state.diffSource = 'agent';
        state.activePatchId = taskState.bundle_patch_id || patch.patch_id || patches[0].patch_id;

        badge.className = 'status-badge badge-awaiting';
        badge.textContent = "AWAITING APPROVAL";
        const fileCountText = patches.length > 1 ? `${patches.length} files proposed` : "1 file proposed";
        statusLabel.textContent = `Patch ready (${fileCountText}). Review diffs to approve.`;

        // Render first patch diff
        renderDiffForPatch(0);

        // Configure multi-file diff tab bar on top of editor
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
                    btn.addEventListener('click', () => renderDiffForPatch(idx));
                    diffTabsList.appendChild(btn);
                });
            } else {
                diffTabsBar.style.display = 'none';
            }
        }

        // Configure Antigravity Floating Review Bar
        setupAgentReviewBar(patches);

        // Enable diff button and switch to diff view automatically
        const btnDiff = document.getElementById('btn-view-diff');
        btnDiff.disabled = false;
        switchEditorMode('diff');

        // Show Approval Gate banner
        const gate = document.getElementById('approval-gate-banner');
        gate.style.display = 'block';
        const displayTag = patches.length > 1 ? `${state.activePatchId} (${patches.length} files)` : state.activePatchId;
        document.getElementById('gate-patch-id').textContent = displayTag;

        // Re-render file tree so badges appear
        renderFileTree();

        showToast(`Patch proposal ready for ${patches.length} file(s)! Review diffs.`, "info");

    } else if (taskState.status === "no_changes_needed") {
        badge.className = 'status-badge badge-idle';
        badge.textContent = "NO CHANGES";
        statusLabel.textContent = "No code changes needed";

        const banner = document.getElementById('no-changes-banner');
        if (banner) {
            banner.style.display = 'flex';
            const detail = document.getElementById('no-changes-detail');
            if (detail) {
                detail.textContent = analysis.summary || "Requirement is already implemented in the code.";
            }
        }

        setStepState('step-proposal', 'completed');
        setStepState('step-verification', 'completed');
        showToast("Diagnosis complete: Code already satisfies requirements.", "info");

    } else {
        badge.className = 'status-badge badge-failed';
        badge.textContent = taskState.status ? taskState.status.toUpperCase() : "FAILED";
        statusLabel.textContent = "Workflow ended with status: " + taskState.status;
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

    document.querySelectorAll('.diff-file-tab-btn').forEach((btn, idx) => {
        btn.classList.toggle('active', idx === patchIndex);
    });

    document.querySelectorAll('.review-file-row').forEach((row, idx) => {
        row.classList.toggle('active', idx === patchIndex);
    });

    const tabTitle = document.getElementById('tab-filename');
    if (tabTitle) {
        tabTitle.textContent = currentPatch.file_path + " (Diff)";
    }
}

function setupAgentReviewBar(patches) {
    const reviewBar = document.getElementById('antigravity-review-bar');
    const statText = document.getElementById('review-stat-text');
    const filesList = document.getElementById('review-files-list');
    const countLabel = document.getElementById('review-count-label');
    const btnAccept = document.getElementById('btn-review-accept-all');
    const btnReject = document.getElementById('btn-review-reject-all');

    if (!reviewBar) return;

    reviewBar.style.display = 'flex';

    // Calculate rough additions/deletions from diffs
    let totalAdds = 0;
    let totalDels = 0;
    patches.forEach(p => {
        const lines = (p.diff || "").split('\n');
        lines.forEach(l => {
            if (l.startsWith('+') && !l.startsWith('+++')) totalAdds++;
            if (l.startsWith('-') && !l.startsWith('---')) totalDels++;
        });
    });

    statText.innerHTML = `${patches.length} files changed <span class="diff-add">+${totalAdds}</span> <span class="diff-del">-${totalDels}</span>`;
    countLabel.textContent = `${patches.length} Proposed Files`;

    btnAccept.textContent = 'Accept all';
    btnReject.textContent = 'Reject all';
    btnAccept.onclick = () => submitApproval(true);
    btnReject.onclick = () => submitApproval(false);

    filesList.innerHTML = '';
    patches.forEach((p, idx) => {
        const row = document.createElement('div');
        row.className = `review-file-row ${idx === state.selectedPatchIndex ? 'active' : ''}`;
        const parts = p.file_path.split('/');
        const basename = parts.pop();
        const dirname = parts.join('/');

        let pAdds = 0;
        let pDels = 0;
        (p.diff || "").split('\n').forEach(l => {
            if (l.startsWith('+') && !l.startsWith('+++')) pAdds++;
            if (l.startsWith('-') && !l.startsWith('---')) pDels++;
        });

        row.innerHTML = `
            <span class="diff-stat-pill"><span class="pill-add">+${pAdds}</span><span class="pill-del">-${pDels}</span></span>
            <span class="file-basename">${basename}</span>
            <span class="file-dirname">${dirname || '.'}</span>
        `;

        row.addEventListener('click', () => {
            renderDiffForPatch(idx);
        });

        filesList.appendChild(row);
    });
}

// ==============================================================================
// 6. Human Approval & Live Test Verification
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
                human_feedback: approved ? "Approved via Antigravity IDE" : "Rejected by user",
            })
        });

        if (!res.ok) {
            const errData = await res.json().catch(() => ({}));
            throw new Error(errData.detail || "Approval failed");
        }

        const finalState = await res.json();
        document.getElementById('approval-gate-banner').style.display = 'none';

        // Hide Review Bar
        const reviewBar = document.getElementById('antigravity-review-bar');
        if (reviewBar) reviewBar.style.display = 'none';

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

            // Open bottom drawer automatically
            document.getElementById('bottom-drawer').classList.remove('collapsed');
            document.getElementById('bottom-drawer').classList.add('expanded');

            // Show success result card
            const resultCard = document.getElementById('result-card');
            resultCard.style.display = 'block';
            document.getElementById('result-title').textContent = testResults.passed ? "All Tests Passed!" : "Verification Completed";
            document.getElementById('result-subtitle').textContent = `Applied patch to disk. Verification passed: ${testResults.passed}`;

            showToast("Patch applied! Tests passed successfully.", "success");

            // Refresh git changes and files
            state.activePatches = [];
            loadFilesList();
            loadGitChanges();
            setTimeout(() => {
                loadFileContent(state.currentFilePath);
            }, 500);

        } else if (!approved) {
            state.activePatches = [];
            badge.className = 'status-badge badge-idle';
            badge.textContent = "REJECTED";
            statusLabel.textContent = "Patch was rejected by operator";
            showToast("Patch proposal rejected.", "info");
            switchEditorMode('code');
            renderFileTree();
        } else {
            state.activePatches = [];
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
// 7. On-Demand Pytest Execution
// ==============================================================================

async function runOnDemandTests() {
    const termOutput = document.getElementById('terminal-test-output');
    const indicator = document.getElementById('test-indicator');
    const drawer = document.getElementById('bottom-drawer');

    // Switch to test results tab & expand drawer
    drawer.classList.remove('collapsed');
    drawer.classList.add('expanded');
    switchDrawerTab('test-results');

    indicator.className = 'tab-indicator';
    termOutput.textContent = "Executing automated pytest test suite...\n$ pytest -v app/tests/";

    try {
        const res = await fetch('/api/run-tests', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
        });

        if (!res.ok) throw new Error("Test execution failed");
        const data = await res.json();

        termOutput.textContent = data.output || "Tests completed.";
        indicator.className = 'tab-indicator ' + (data.passed ? 'indicator-success' : 'indicator-fail');

        if (data.passed) {
            showToast("Pytest complete: All tests passed!", "success");
        } else {
            showToast("Pytest complete: Test failures detected.", "error");
        }

    } catch (err) {
        termOutput.textContent = "Failed to run tests: " + err.message;
        indicator.className = 'tab-indicator indicator-fail';
        showToast("Test runner error: " + err.message, "error");
    }
}

// ==============================================================================
// 8. Sandbox Reset
// ==============================================================================

async function resetSandbox() {
    const btn = document.getElementById('btn-reset-sandbox');
    if (btn) btn.disabled = true;
    try {
        const res = await fetch('/api/reset', { method: 'POST' });
        if (!res.ok) throw new Error("Reset failed");
        showToast("Sandbox reverted to clean git state.", "success");
        loadGitChanges();
        loadFileContent(state.currentFilePath);
    } catch (err) {
        showToast("Reset failed: " + err.message, "error");
    } finally {
        if (btn) btn.disabled = false;
    }
}

// ==============================================================================
// 9. Toast Alerts & System Health
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

function switchDrawerTab(tabId) {
    document.querySelectorAll('.drawer-tab').forEach(t => t.classList.toggle('active', t.dataset.tab === tabId));
    document.querySelectorAll('.drawer-panel').forEach(p => p.classList.toggle('active', p.id === 'panel-' + tabId));
}

// ==============================================================================
// 10. Event Listeners & UI Binding
// ==============================================================================

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
    const resetSideBtn = document.getElementById('act-btn-reset-side');
    if (resetSideBtn) resetSideBtn.addEventListener('click', resetSandbox);

    // Tree Action Buttons: Collapse All / Expand All / Refresh
    document.getElementById('btn-collapse-all').addEventListener('click', collapseAllFolders);
    document.getElementById('btn-expand-all').addEventListener('click', expandAllFolders);
    document.getElementById('btn-refresh-files').addEventListener('click', () => {
        loadFilesList();
        loadGitChanges();
    });
    const btnRefreshGit = document.getElementById('btn-refresh-git');
    if (btnRefreshGit) btnRefreshGit.addEventListener('click', loadGitChanges);

    // Root section header click toggle
    const rootHeader = document.getElementById('workspace-root-header');
    if (rootHeader) {
        rootHeader.addEventListener('click', () => {
            const chevron = document.getElementById('root-chevron');
            const treeContainer = document.getElementById('file-tree-container');
            if (chevron.classList.contains('closed')) {
                chevron.classList.remove('closed');
                treeContainer.style.display = 'block';
            } else {
                chevron.classList.add('closed');
                treeContainer.style.display = 'none';
            }
        });
    }

    // Filter Files Search Box
    const searchInput = document.getElementById('file-search-input');
    const searchClearBtn = document.getElementById('btn-clear-search');
    searchInput.addEventListener('input', (e) => {
        state.searchQuery = e.target.value;
        renderFileTree();
    });
    searchClearBtn.addEventListener('click', () => {
        searchInput.value = '';
        state.searchQuery = '';
        renderFileTree();
    });

    // Working Changes Quickbar Click
    const quickbar = document.getElementById('git-changes-quickbar');
    if (quickbar) {
        quickbar.addEventListener('click', () => {
            // Switch to Changes sidebar pane
            switchSidebarView('changes');
        });
    }

    // Git Status Header Pill Click
    const gitStatusPill = document.getElementById('git-status-pill');
    if (gitStatusPill) {
        gitStatusPill.addEventListener('click', () => {
            switchSidebarView('changes');
        });
    }

    // Activity Bar Switching
    document.getElementById('act-btn-explorer').addEventListener('click', () => switchSidebarView('explorer'));
    document.getElementById('act-btn-changes').addEventListener('click', () => switchSidebarView('changes'));
    document.getElementById('act-btn-tests').addEventListener('click', () => {
        const drawer = document.getElementById('bottom-drawer');
        drawer.classList.remove('collapsed');
        drawer.classList.add('expanded');
        switchDrawerTab('test-results');
    });
    document.getElementById('act-btn-agent').addEventListener('click', () => {
        const promptBox = document.getElementById('task-prompt');
        promptBox.focus();
    });

    function switchSidebarView(view) {
        state.activeSidebarView = view;
        const actExp = document.getElementById('act-btn-explorer');
        const actChg = document.getElementById('act-btn-changes');
        const paneExp = document.getElementById('pane-explorer');
        const paneChg = document.getElementById('pane-changes');

        if (view === 'explorer') {
            actExp.classList.add('active');
            actChg.classList.remove('active');
            paneExp.style.display = 'flex';
            paneChg.style.display = 'none';
        } else {
            actExp.classList.remove('active');
            actChg.classList.add('active');
            paneExp.style.display = 'none';
            paneChg.style.display = 'flex';
            loadGitChanges();
        }
    }

    // On-Demand Pytest Buttons
    const btnHeaderRunTests = document.getElementById('btn-header-run-tests');
    if (btnHeaderRunTests) btnHeaderRunTests.addEventListener('click', runOnDemandTests);
    const btnDrawerRunTests = document.getElementById('btn-drawer-run-tests');
    if (btnDrawerRunTests) btnDrawerRunTests.addEventListener('click', runOnDemandTests);

    // Editor View Mode Switchers
    document.getElementById('btn-view-code').addEventListener('click', () => switchEditorMode('code'));
    document.getElementById('btn-view-diff').addEventListener('click', () => switchEditorMode('diff'));

    // Diff Split / Inline Toggle
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

    // Antigravity Review Bar Controls
    const btnToggleReview = document.getElementById('btn-toggle-review-expand');
    const reviewFilesList = document.getElementById('review-files-list');
    const reviewExpandIcon = document.getElementById('review-expand-icon');
    if (btnToggleReview && reviewFilesList) {
        btnToggleReview.addEventListener('click', () => {
            if (reviewFilesList.style.display === 'none') {
                reviewFilesList.style.display = 'flex';
                reviewExpandIcon.textContent = '▾';
            } else {
                reviewFilesList.style.display = 'none';
                reviewExpandIcon.textContent = '›';
            }
        });
    }

    const btnCloseReview = document.getElementById('btn-close-review-bar');
    if (btnCloseReview) {
        btnCloseReview.addEventListener('click', () => {
            document.getElementById('antigravity-review-bar').style.display = 'none';
        });
    }

    // Drawer Tabs
    document.querySelectorAll('.drawer-tab').forEach(tab => {
        tab.addEventListener('click', () => {
            switchDrawerTab(tab.dataset.tab);
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

    // Global Keyboard Shortcuts
    document.addEventListener('keydown', (e) => {
        // Cmd/Ctrl + B to toggle sidebar
        if ((e.metaKey || e.ctrlKey) && e.key === 'b') {
            e.preventDefault();
            const sidebar = document.getElementById('sidebar-explorer');
            sidebar.style.display = sidebar.style.display === 'none' ? 'flex' : 'none';
        }
        // Cmd/Ctrl + J to toggle drawer
        if ((e.metaKey || e.ctrlKey) && e.key === 'j') {
            e.preventDefault();
            document.getElementById('btn-toggle-drawer').click();
        }
        // Cmd/Ctrl + F to focus search
        if ((e.metaKey || e.ctrlKey) && e.key === 'f' && !e.shiftKey) {
            if (document.activeElement.tagName !== 'INPUT' && document.activeElement.tagName !== 'TEXTAREA') {
                e.preventDefault();
                searchInput.focus();
            }
        }
    });
});
