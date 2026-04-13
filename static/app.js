const initialStateElement = document.getElementById("initial-books-data");

const initialState = initialStateElement
    ? JSON.parse(initialStateElement.textContent)
    : { database_ready: false, books: [], author_progress: [], current_user: null, users: [] };

const state = {
    books: Array.isArray(initialState.books) ? initialState.books : [],
    authorProgress: Array.isArray(initialState.author_progress) ? initialState.author_progress : [],
    currentUser: initialState.current_user || null,
    users: Array.isArray(initialState.users) ? initialState.users : [],
    databaseReady: Boolean(initialState.database_ready),
    filters: {
        query: "",
        author: "all",
        stamped: "all",
        sort: "title-asc",
    },
    editingBookId: null,
};

const elements = {
    bookCount: document.getElementById("book-count"),
    stampedCount: document.getElementById("stamped-count"),
    visibleCount: document.getElementById("visible-count"),
    listSummary: document.getElementById("list-summary"),
    currentUserName: document.getElementById("current-user-name"),
    currentUserMeta: document.getElementById("current-user-meta"),
    authorProgressGrid: document.getElementById("author-progress-grid"),
    booksGrid: document.getElementById("books-grid"),
    emptyState: document.getElementById("empty-state"),
    emptyStateTitle: document.getElementById("empty-state-title"),
    emptyStateCopy: document.getElementById("empty-state-copy"),
    statusBanner: document.getElementById("status-banner"),
    scannerPill: document.getElementById("scanner-pill"),
    databaseNote: document.getElementById("database-note"),
    manualForm: document.getElementById("manual-isbn-form"),
    manualInput: document.getElementById("manual-isbn-input"),
    manualSubmit: document.getElementById("manual-isbn-submit"),
    importForm: document.getElementById("import-form"),
    importFile: document.getElementById("import-file"),
    importMode: document.getElementById("import-mode"),
    importSubmit: document.getElementById("import-submit"),
    searchInput: document.getElementById("search-input"),
    authorFilter: document.getElementById("author-filter"),
    stampedFilter: document.getElementById("stamped-filter"),
    sortSelect: document.getElementById("sort-select"),
    accountManagement: document.getElementById("account-management"),
    userList: document.getElementById("user-list"),
    accountForm: document.getElementById("account-form"),
    accountDisplayName: document.getElementById("account-display-name"),
    accountUsername: document.getElementById("account-username"),
    accountPassword: document.getElementById("account-password"),
    accountIsAdmin: document.getElementById("account-is-admin"),
    accountSubmit: document.getElementById("account-submit"),
    editModal: document.getElementById("edit-modal"),
    editModalClose: document.getElementById("edit-modal-close"),
    editCancel: document.getElementById("edit-cancel"),
    editForm: document.getElementById("edit-book-form"),
    editBookId: document.getElementById("edit-book-id"),
    editTitle: document.getElementById("edit-title"),
    editAuthor: document.getElementById("edit-author"),
    editIsbn: document.getElementById("edit-isbn"),
    editCoverImageUrl: document.getElementById("edit-cover-image-url"),
    editCopyCount: document.getElementById("edit-copy-count"),
    editStamped: document.getElementById("edit-stamped"),
};

if (elements.editModalClose) {
    elements.editModalClose.innerHTML = "&times;";
}

const statusClasses = {
    idle: "border-stone-200 bg-stone-100 text-stone-700",
    loading: "border-amber-200 bg-amber-50 text-amber-900",
    success: "border-emerald-200 bg-emerald-50 text-emerald-800",
    error: "border-rose-200 bg-rose-50 text-rose-800",
};

const pillClasses = {
    idle: "bg-stone-100 text-stone-700",
    loading: "bg-amber-100 text-amber-800",
    success: "bg-emerald-100 text-emerald-800",
    error: "bg-rose-100 text-rose-800",
};

let scanner = null;
let isSaving = false;
let resumeTimerId = null;
let lastScanValue = "";
let lastScanTimestamp = 0;

function escapeHtml(value) {
    return String(value ?? "").replace(/[&<>"']/g, (character) => {
        const entities = {
            "&": "&amp;",
            "<": "&lt;",
            ">": "&gt;",
            '"': "&quot;",
            "'": "&#39;",
        };
        return entities[character];
    });
}

function normalizeIsbn(value) {
    const normalized = String(value ?? "")
        .toUpperCase()
        .replace(/[^0-9X]/g, "");

    return normalized.length === 10 || normalized.length === 13 ? normalized : null;
}

function getCopyCount(book) {
    const rawCount = Number(book?.copy_count);
    return Number.isFinite(rawCount) && rawCount >= 1 ? rawCount : 1;
}

function formatCopyLabel(copyCount) {
    return `${copyCount} ${copyCount === 1 ? "copy" : "copies"}`;
}

function setStatus(message, tone = "idle") {
    elements.statusBanner.textContent = message;
    elements.statusBanner.className = `mt-4 rounded-2xl border px-4 py-3 text-sm ${statusClasses[tone] || statusClasses.idle}`;
}

function setScannerPill(label, tone = "idle") {
    elements.scannerPill.textContent = label;
    elements.scannerPill.className = `inline-flex shrink-0 rounded-full px-3 py-1 text-xs font-semibold ${pillClasses[tone] || pillClasses.idle}`;
}

function syncState(payload) {
    if (Array.isArray(payload.books)) {
        state.books = payload.books;
    }
    if (Array.isArray(payload.author_progress)) {
        state.authorProgress = payload.author_progress;
    }
    if (payload.current_user) {
        state.currentUser = payload.current_user;
    }
    if (Array.isArray(payload.users)) {
        state.users = payload.users;
    }
    if (typeof payload.database_ready === "boolean") {
        state.databaseReady = payload.database_ready;
    }
}

function isAdminUser() {
    return Boolean(state.currentUser && state.currentUser.is_admin);
}

function getUniqueAuthors() {
    return [...new Set(state.books.map((book) => book.author).filter(Boolean))].sort((left, right) =>
        left.localeCompare(right),
    );
}

function updateAuthorFilterOptions() {
    const currentValue = state.filters.author;
    const authors = getUniqueAuthors();
    elements.authorFilter.innerHTML = [
        '<option value="all">All authors</option>',
        ...authors.map((author) => `<option value="${escapeHtml(author)}">${escapeHtml(author)}</option>`),
    ].join("");

    if (!authors.includes(currentValue)) {
        state.filters.author = "all";
    }

    elements.authorFilter.value = state.filters.author;
}

function renderCurrentUser() {
    if (!state.currentUser || !elements.currentUserName || !elements.currentUserMeta) {
        return;
    }

    elements.currentUserName.textContent = state.currentUser.display_name || state.currentUser.username;
    if (state.currentUser.is_admin) {
        elements.currentUserMeta.textContent = `@${state.currentUser.username} - admin`;
        return;
    }
    elements.currentUserMeta.textContent = state.currentUser.is_admin
        ? `@${state.currentUser.username} • admin`
        : `@${state.currentUser.username}`;
}

function renderUserAccounts() {
    if (!elements.accountManagement || !elements.userList) {
        return;
    }

    if (!isAdminUser()) {
        elements.accountManagement.hidden = true;
        return;
    }

    elements.accountManagement.hidden = false;

    if (!state.users.length) {
        elements.userList.innerHTML = `
            <div class="rounded-2xl border border-dashed border-stone-300 bg-stone-50 px-4 py-4 text-sm text-stone-600">
                No user accounts exist yet.
            </div>
        `;
        return;
    }

    elements.userList.innerHTML = state.users
        .map(
            (user) => `
                <article class="rounded-2xl border border-stone-200 bg-stone-50 px-4 py-4">
                    <div class="flex items-start justify-between gap-3">
                        <div>
                            <h3 class="text-sm font-semibold text-stone-900">${escapeHtml(user.display_name || user.username)}</h3>
                            <p class="mt-1 text-xs text-stone-600">@${escapeHtml(user.username)}</p>
                        </div>
                        <div class="flex flex-wrap items-center justify-end gap-2">
                            <span class="rounded-full bg-white px-3 py-1 text-xs font-semibold text-stone-700 ring-1 ring-stone-200">
                                ${Number(user.book_count || 0)} books
                            </span>
                            ${
                                user.is_admin
                                    ? '<span class="rounded-full bg-amber-100 px-3 py-1 text-xs font-semibold text-amber-900">Admin</span>'
                                    : ""
                            }
                        </div>
                    </div>
                </article>
            `,
        )
        .join("");
}

function renderAuthorProgress() {
    if (!state.authorProgress.length) {
        elements.authorProgressGrid.innerHTML = `
            <div class="rounded-3xl border border-dashed border-stone-300 bg-stone-50 p-6 text-sm text-stone-600">
                Author progress targets have not been configured yet.
            </div>
        `;
        return;
    }

    elements.authorProgressGrid.innerHTML = state.authorProgress
        .map((entry) => {
            const progressWidth = Math.min(entry.completion_percentage || 0, 100);
            return `
                <article class="rounded-3xl border border-stone-200 bg-stone-50 p-5 shadow-sm">
                    <div class="flex items-start justify-between gap-4">
                        <div>
                            <h3 class="text-lg font-semibold text-stone-900">${escapeHtml(entry.author_name)}</h3>
                            <p class="mt-1 text-sm text-stone-600">${entry.owned_books} owned of ${entry.total_books} tracked works</p>
                        </div>
                        <span class="rounded-full bg-stone-900 px-3 py-1 text-xs font-semibold text-white">
                            ${Number(entry.completion_percentage || 0).toFixed(1)}%
                        </span>
                    </div>
                    <div class="mt-4 h-3 overflow-hidden rounded-full bg-stone-200">
                        <div
                            class="h-full rounded-full bg-gradient-to-r from-amber-400 via-orange-500 to-stone-900 transition-all"
                            style="width: ${progressWidth}%"
                        ></div>
                    </div>
                    <div class="mt-4 flex items-center justify-between text-xs text-stone-500">
                        <span>${entry.remaining_books} remaining</span>
                        ${entry.source_url ? `<a class="font-medium text-stone-700 underline-offset-4 hover:underline" href="${escapeHtml(entry.source_url)}" target="_blank" rel="noreferrer">Source</a>` : ""}
                    </div>
                </article>
            `;
        })
        .join("");
}

function compareBooks(left, right, mode) {
    if (mode === "author-asc") {
        const authorCompare = left.author.localeCompare(right.author);
        return authorCompare || left.title.localeCompare(right.title);
    }

    if (mode === "newest") {
        return right.id - left.id;
    }

    if (mode === "oldest") {
        return left.id - right.id;
    }

    if (mode === "stamped-first") {
        return Number(right.stamped) - Number(left.stamped) || left.title.localeCompare(right.title);
    }

    return left.title.localeCompare(right.title);
}

function getFilteredBooks() {
    const query = elements.searchInput.value.trim().toLowerCase();
    const selectedAuthor = state.filters.author;
    const stampedFilter = state.filters.stamped;
    const sortMode = state.filters.sort;

    return [...state.books]
        .filter((book) => {
            if (selectedAuthor !== "all" && book.author !== selectedAuthor) {
                return false;
            }

            if (stampedFilter === "stamped" && !book.stamped) {
                return false;
            }

            if (stampedFilter === "unstamped" && book.stamped) {
                return false;
            }

            if (!query) {
                return true;
            }

            const haystack = `${book.title} ${book.author} ${book.isbn}`.toLowerCase();
            return haystack.includes(query);
        })
        .sort((left, right) => compareBooks(left, right, sortMode));
}

function renderSummary(visibleBooks) {
    const totalCopies = state.books.reduce((sum, book) => sum + getCopyCount(book), 0);
    const stampedCopies = state.books.reduce(
        (sum, book) => sum + (book.stamped ? getCopyCount(book) : 0),
        0,
    );
    const visibleCopies = visibleBooks.reduce((sum, book) => sum + getCopyCount(book), 0);

    elements.bookCount.textContent = String(totalCopies);
    elements.stampedCount.textContent = String(stampedCopies);
    elements.visibleCount.textContent = String(visibleCopies);

    if (!totalCopies) {
        elements.listSummary.textContent = "This library is empty. Scan a book or restore a backup to get started.";
        return;
    }

    elements.listSummary.textContent =
        `Showing ${visibleBooks.length} ${visibleBooks.length === 1 ? "title" : "titles"} ` +
        `across ${visibleCopies} ${visibleCopies === 1 ? "copy" : "copies"}. ` +
        `${stampedCopies} stamped ${stampedCopies === 1 ? "copy" : "copies"} in the library.`;
}

function renderBookCard(book) {
    const badgeClasses = book.stamped
        ? "bg-emerald-100 text-emerald-700"
        : "bg-stone-100 text-stone-600";

    const coverMarkup = book.cover_image_url
        ? `
            <img
                src="${escapeHtml(book.cover_image_url)}"
                alt="Cover for ${escapeHtml(book.title)}"
                class="h-full w-full object-cover"
                loading="lazy"
                referrerpolicy="no-referrer"
            >
        `
        : `
            <div class="flex h-full items-center justify-center bg-stone-300 px-3 text-center text-xs font-semibold uppercase tracking-[0.2em] text-stone-600">
                No cover
            </div>
        `;

    const copyCount = getCopyCount(book);

    return `
        <article class="overflow-hidden rounded-3xl bg-white shadow-sm ring-1 ring-stone-200">
            <div class="flex gap-4 p-4 sm:p-5">
                <div class="h-36 w-24 shrink-0 overflow-hidden rounded-2xl bg-stone-200">
                    ${coverMarkup}
                </div>

                <div class="min-w-0 flex-1">
                    <div class="flex items-start justify-between gap-3">
                        <div>
                            <h3 class="text-lg font-semibold leading-6 text-stone-900">${escapeHtml(book.title)}</h3>
                            <p class="mt-1 text-sm text-stone-600">${escapeHtml(book.author)}</p>
                        </div>
                        <div class="flex flex-col items-end gap-2">
                            <span class="shrink-0 rounded-full px-3 py-1 text-xs font-semibold ${badgeClasses}">
                                ${book.stamped ? "Stamped" : "Not stamped"}
                            </span>
                            <span class="shrink-0 rounded-full bg-amber-100 px-3 py-1 text-xs font-semibold text-amber-900">
                                ${formatCopyLabel(copyCount)}
                            </span>
                        </div>
                    </div>

                    <dl class="mt-4 space-y-2 text-sm text-stone-600">
                        <div>
                            <dt class="font-medium text-stone-800">ISBN</dt>
                            <dd class="break-all">${escapeHtml(book.isbn)}</dd>
                        </div>
                        <div>
                            <dt class="font-medium text-stone-800">Copies owned</dt>
                            <dd>${formatCopyLabel(copyCount)}</dd>
                        </div>
                    </dl>

                    <div class="mt-5 flex flex-wrap gap-2">
                        <button
                            type="button"
                            data-action="toggle-stamped"
                            data-id="${book.id}"
                            class="inline-flex items-center justify-center rounded-2xl border border-stone-300 bg-stone-50 px-4 py-2 text-sm font-semibold text-stone-700 transition hover:border-stone-400 hover:bg-white"
                        >
                            ${book.stamped ? "Remove stamp" : "Mark stamped"}
                        </button>
                        <button
                            type="button"
                            data-action="edit"
                            data-id="${book.id}"
                            class="inline-flex items-center justify-center rounded-2xl border border-stone-300 bg-stone-50 px-4 py-2 text-sm font-semibold text-stone-700 transition hover:border-stone-400 hover:bg-white"
                        >
                            Edit
                        </button>
                        <button
                            type="button"
                            data-action="delete"
                            data-id="${book.id}"
                            class="inline-flex items-center justify-center rounded-2xl border border-rose-200 bg-rose-50 px-4 py-2 text-sm font-semibold text-rose-700 transition hover:border-rose-300 hover:bg-rose-100"
                        >
                            Delete
                        </button>
                    </div>
                </div>
            </div>
        </article>
    `;
}

function renderBooks() {
    const visibleBooks = getFilteredBooks();
    renderSummary(visibleBooks);
    elements.databaseNote.hidden = state.databaseReady;

    if (!state.books.length) {
        elements.booksGrid.innerHTML = "";
        elements.booksGrid.hidden = true;
        elements.emptyState.hidden = false;
        elements.emptyStateTitle.textContent = "No books in this catalogue yet";
        elements.emptyStateCopy.textContent = "Scan a barcode, enter an ISBN, or restore a backup to add your first book.";
        return;
    }

    if (!visibleBooks.length) {
        elements.booksGrid.innerHTML = "";
        elements.booksGrid.hidden = true;
        elements.emptyState.hidden = false;
        elements.emptyStateTitle.textContent = "No books match your current filters";
        elements.emptyStateCopy.textContent = "Try a broader search or reset one of the filters above.";
        return;
    }

    elements.booksGrid.hidden = false;
    elements.emptyState.hidden = true;
    elements.booksGrid.innerHTML = visibleBooks.map(renderBookCard).join("");
}

function renderAll() {
    renderCurrentUser();
    renderUserAccounts();
    updateAuthorFilterOptions();
    renderAuthorProgress();
    renderBooks();
}

function findBook(bookId) {
    return state.books.find((book) => book.id === bookId) || null;
}

function openEditModal(book) {
    if (!book) {
        return;
    }

    state.editingBookId = book.id;
    elements.editBookId.value = String(book.id);
    elements.editTitle.value = book.title;
    elements.editAuthor.value = book.author;
    elements.editIsbn.value = book.isbn;
    elements.editCoverImageUrl.value = book.cover_image_url || "";
    elements.editCopyCount.value = String(getCopyCount(book));
    elements.editStamped.checked = Boolean(book.stamped);
    elements.editModal.classList.remove("hidden");
    elements.editModal.classList.add("flex");
    elements.editTitle.focus();
}

function closeEditModal() {
    state.editingBookId = null;
    elements.editForm.reset();
    elements.editModal.classList.add("hidden");
    elements.editModal.classList.remove("flex");
}

function pauseScanner() {
    if (!scanner) {
        return;
    }

    try {
        scanner.pause(true);
        setScannerPill("Paused", "loading");
    } catch (_error) {
        // Ignore pause failures when the camera is not actively scanning.
    }
}

function resumeScannerSoon(delay = 2500) {
    window.clearTimeout(resumeTimerId);
    resumeTimerId = window.setTimeout(() => {
        if (!scanner) {
            return;
        }

        try {
            scanner.resume();
            setScannerPill("Scanning", "success");
            setStatus("Scanner is ready for the next book.", "idle");
        } catch (_error) {
            // Ignore resume failures when the scanner is not paused.
        }
    }, delay);
}

async function readJsonResponse(response) {
    if (response.status === 401) {
        window.location.href = `/login?next=${encodeURIComponent(window.location.pathname)}`;
        throw new Error("Redirecting to login.");
    }

    let payload = {};
    try {
        payload = await response.json();
    } catch (_error) {
        payload = {};
    }

    if (!response.ok) {
        throw new Error(payload.error || "The request could not be completed.");
    }

    return payload;
}

async function postScanRequest(isbn, extraPayload = {}) {
    const response = await fetch("/api/books/scan", {
        method: "POST",
        headers: {
            "Content-Type": "application/json",
        },
        body: JSON.stringify({ isbn, ...extraPayload }),
    });
    return readJsonResponse(response);
}

async function saveIsbn(rawIsbn, sourceLabel) {
    const isbn = normalizeIsbn(rawIsbn);
    if (!isbn) {
        setStatus("Use a 10 or 13 character ISBN.", "error");
        setScannerPill("Invalid ISBN", "error");
        return;
    }

    if (isSaving) {
        return;
    }

    isSaving = true;
    elements.manualInput.disabled = true;
    elements.manualSubmit.disabled = true;
    setStatus(`Looking up ISBN ${isbn} from ${sourceLabel}...`, "loading");
    setScannerPill("Saving", "loading");

    try {
        let payload = await postScanRequest(isbn);

        if (payload.requires_confirmation && payload.book) {
            const duplicateBook = payload.book;
            const confirmed = window.confirm(
                payload.message ||
                    `${duplicateBook.title} is already in your catalogue with ${formatCopyLabel(getCopyCount(duplicateBook))}. Is this an additional copy?`,
            );

            if (!confirmed) {
                elements.manualInput.value = "";
                setStatus(`Left ${duplicateBook.title} unchanged.`, "idle");
                setScannerPill("Duplicate skipped", "idle");
                return;
            }

            setStatus(`Adding another copy of ${duplicateBook.title}...`, "loading");
            payload = await postScanRequest(isbn, { duplicate_decision: "additional_copy" });
        }

        syncState(payload);
        renderAll();
        elements.manualInput.value = "";
        setStatus(payload.message || "Book saved.", "success");
        setScannerPill("Saved", "success");
    } catch (error) {
        if (error.message !== "Redirecting to login.") {
            setStatus(error.message || "The ISBN could not be saved.", "error");
            setScannerPill("Retry", "error");
        }
    } finally {
        isSaving = false;
        elements.manualInput.disabled = false;
        elements.manualSubmit.disabled = false;
        resumeScannerSoon();
    }
}

async function patchBook(bookId, updates, successMessage) {
    try {
        const response = await fetch(`/api/books/${bookId}`, {
            method: "PATCH",
            headers: {
                "Content-Type": "application/json",
            },
            body: JSON.stringify(updates),
        });
        const payload = await readJsonResponse(response);
        syncState(payload);
        renderAll();
        setStatus(payload.message || successMessage, "success");
        setScannerPill("Updated", "success");
        return true;
    } catch (error) {
        if (error.message !== "Redirecting to login.") {
            setStatus(error.message || "The book could not be updated.", "error");
            setScannerPill("Retry", "error");
        }
        return false;
    }
}

async function deleteBook(bookId) {
    const book = findBook(bookId);
    if (!book) {
        return;
    }

    const confirmed = window.confirm(`Delete "${book.title}" from your catalogue?`);
    if (!confirmed) {
        return;
    }

    try {
        const response = await fetch(`/api/books/${bookId}`, {
            method: "DELETE",
        });
        const payload = await readJsonResponse(response);
        syncState(payload);
        renderAll();
        setStatus(payload.message || "Book deleted.", "success");
        setScannerPill("Updated", "success");
        if (state.editingBookId === bookId) {
            closeEditModal();
        }
    } catch (error) {
        if (error.message !== "Redirecting to login.") {
            setStatus(error.message || "The book could not be deleted.", "error");
            setScannerPill("Retry", "error");
        }
    }
}

function handleScanSuccess(decodedText) {
    const isbn = normalizeIsbn(decodedText);
    if (!isbn) {
        setStatus(`Scanned "${decodedText}", but it does not look like an ISBN.`, "error");
        return;
    }

    const now = Date.now();
    if (isbn === lastScanValue && now - lastScanTimestamp < 3000) {
        return;
    }

    lastScanValue = isbn;
    lastScanTimestamp = now;
    pauseScanner();
    void saveIsbn(isbn, "the camera");
}

function initialiseScanner() {
    if (!window.Html5QrcodeScanner) {
        setStatus(
            "The barcode scanner library failed to load. You can still add books with manual ISBN entry.",
            "error",
        );
        setScannerPill("Unavailable", "error");
        return;
    }

    scanner = new Html5QrcodeScanner(
        "reader",
        {
            fps: 10,
            qrbox: { width: 280, height: 140 },
        },
        false,
    );
    scanner.render(handleScanSuccess, () => {});
    setStatus("Start the scanner below, allow camera access, and aim at a book barcode.", "idle");
    setScannerPill("Ready", "idle");
}

elements.searchInput.addEventListener("input", (event) => {
    state.filters.query = event.target.value;
    renderBooks();
});

elements.authorFilter.addEventListener("change", (event) => {
    state.filters.author = event.target.value;
    renderBooks();
});

elements.stampedFilter.addEventListener("change", (event) => {
    state.filters.stamped = event.target.value;
    renderBooks();
});

elements.sortSelect.addEventListener("change", (event) => {
    state.filters.sort = event.target.value;
    renderBooks();
});

elements.manualForm.addEventListener("submit", (event) => {
    event.preventDefault();
    void saveIsbn(elements.manualInput.value, "manual entry");
});

elements.importForm.addEventListener("submit", async (event) => {
    event.preventDefault();

    const file = elements.importFile.files?.[0];
    if (!file) {
        setStatus("Choose a JSON backup file before restoring.", "error");
        return;
    }

    const mode = elements.importMode.value;
    if (mode === "replace") {
        const confirmed = window.confirm(
            "Replace mode will remove the current account's books before restoring the backup. Continue?",
        );
        if (!confirmed) {
            return;
        }
    }

    const formData = new FormData();
    formData.append("file", file);
    formData.append("mode", mode);

    elements.importSubmit.disabled = true;
    setStatus("Restoring your backup file...", "loading");

    try {
        const response = await fetch("/api/library/import", {
            method: "POST",
            body: formData,
        });
        const payload = await readJsonResponse(response);
        syncState(payload);
        renderAll();
        elements.importForm.reset();
        setStatus(payload.message || "Backup restored.", "success");
    } catch (error) {
        if (error.message !== "Redirecting to login.") {
            setStatus(error.message || "The backup could not be restored.", "error");
        }
    } finally {
        elements.importSubmit.disabled = false;
    }
});

if (elements.accountForm) {
    elements.accountForm.addEventListener("submit", async (event) => {
        event.preventDefault();

        const username = elements.accountUsername.value.trim().toLowerCase();
        const password = elements.accountPassword.value;
        const displayName = elements.accountDisplayName.value.trim();

        if (!username || !password) {
            setStatus("Enter a username and password for the new account.", "error");
            return;
        }

        elements.accountSubmit.disabled = true;
        setStatus(`Creating a separate library account for @${username}...`, "loading");

        try {
            const response = await fetch("/api/users", {
                method: "POST",
                headers: {
                    "Content-Type": "application/json",
                },
                body: JSON.stringify({
                    username,
                    password,
                    display_name: displayName,
                    is_admin: elements.accountIsAdmin.checked,
                }),
            });
            const payload = await readJsonResponse(response);
            syncState(payload);
            renderAll();
            elements.accountForm.reset();
            setStatus(payload.message || "User account created.", "success");
        } catch (error) {
            if (error.message !== "Redirecting to login.") {
                setStatus(error.message || "The user account could not be created.", "error");
            }
        } finally {
            elements.accountSubmit.disabled = false;
        }
    });
}

elements.booksGrid.addEventListener("click", (event) => {
    const actionButton = event.target.closest("[data-action]");
    if (!actionButton) {
        return;
    }

    const bookId = Number(actionButton.dataset.id);
    const book = findBook(bookId);
    if (!book) {
        return;
    }

    if (actionButton.dataset.action === "toggle-stamped") {
        void patchBook(
            bookId,
            { stamped: !book.stamped },
            book.stamped ? "Removed library stamp." : "Marked book as stamped.",
        );
        return;
    }

    if (actionButton.dataset.action === "edit") {
        openEditModal(book);
        return;
    }

    if (actionButton.dataset.action === "delete") {
        void deleteBook(bookId);
    }
});

elements.editForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    const bookId = Number(elements.editBookId.value);

    const saved = await patchBook(
        bookId,
        {
            title: elements.editTitle.value,
            author: elements.editAuthor.value,
            isbn: elements.editIsbn.value,
            cover_image_url: elements.editCoverImageUrl.value,
            copy_count: elements.editCopyCount.value,
            stamped: elements.editStamped.checked,
        },
        "Saved book changes.",
    );

    if (saved) {
        closeEditModal();
    }
});

elements.editCancel.addEventListener("click", closeEditModal);
elements.editModalClose.addEventListener("click", closeEditModal);
elements.editModal.addEventListener("click", (event) => {
    if (event.target === elements.editModal) {
        closeEditModal();
    }
});

window.addEventListener("beforeunload", () => {
    if (scanner) {
        scanner.clear().catch(() => {});
    }
});

renderAll();
initialiseScanner();
