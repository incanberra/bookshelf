const initialStateElement = document.getElementById("initial-books-data");

const initialState = initialStateElement
    ? JSON.parse(initialStateElement.textContent)
    : { database_ready: false, books: [] };

const state = {
    books: Array.isArray(initialState.books) ? initialState.books : [],
    databaseReady: Boolean(initialState.database_ready),
};

const elements = {
    bookCount: document.getElementById("book-count"),
    listSummary: document.getElementById("list-summary"),
    booksGrid: document.getElementById("books-grid"),
    emptyState: document.getElementById("empty-state"),
    statusBanner: document.getElementById("status-banner"),
    scannerPill: document.getElementById("scanner-pill"),
    databaseNote: document.getElementById("database-note"),
    manualForm: document.getElementById("manual-isbn-form"),
    manualInput: document.getElementById("manual-isbn-input"),
    manualSubmit: document.getElementById("manual-isbn-submit"),
};

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

function setStatus(message, tone = "idle") {
    elements.statusBanner.textContent = message;
    elements.statusBanner.className = `mt-4 rounded-2xl border px-4 py-3 text-sm ${statusClasses[tone] || statusClasses.idle}`;
}

function setScannerPill(label, tone = "idle") {
    elements.scannerPill.textContent = label;
    elements.scannerPill.className = `inline-flex shrink-0 rounded-full px-3 py-1 text-xs font-semibold ${pillClasses[tone] || pillClasses.idle}`;
}

function syncState(payload) {
    state.books = Array.isArray(payload.books) ? payload.books : [];
    state.databaseReady = Boolean(payload.database_ready);
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

    return `
        <article class="overflow-hidden rounded-3xl bg-white shadow-sm ring-1 ring-stone-200">
            <div class="flex gap-4 p-4 sm:p-5">
                <div class="h-32 w-24 shrink-0 overflow-hidden rounded-2xl bg-stone-200">
                    ${coverMarkup}
                </div>

                <div class="min-w-0 flex-1">
                    <div class="flex items-start justify-between gap-3">
                        <div>
                            <h3 class="text-lg font-semibold leading-6 text-stone-900">${escapeHtml(book.title)}</h3>
                            <p class="mt-1 text-sm text-stone-600">${escapeHtml(book.author)}</p>
                        </div>
                        <span class="shrink-0 rounded-full px-3 py-1 text-xs font-semibold ${badgeClasses}">
                            ${book.stamped ? "Stamped" : "Not stamped"}
                        </span>
                    </div>

                    <dl class="mt-4 space-y-2 text-sm text-stone-600">
                        <div>
                            <dt class="font-medium text-stone-800">ISBN</dt>
                            <dd class="break-all">${escapeHtml(book.isbn)}</dd>
                        </div>
                    </dl>
                </div>
            </div>
        </article>
    `;
}

function renderBooks() {
    const bookCount = state.books.length;
    elements.bookCount.textContent = String(bookCount);
    elements.listSummary.textContent = bookCount
        ? `${bookCount} ${bookCount === 1 ? "book" : "books"} in your local catalogue.`
        : "Scan a barcode or enter an ISBN to build your catalogue.";

    elements.databaseNote.hidden = state.databaseReady;

    if (bookCount === 0) {
        elements.booksGrid.innerHTML = "";
        elements.booksGrid.hidden = true;
        elements.emptyState.hidden = false;
        return;
    }

    elements.booksGrid.hidden = false;
    elements.emptyState.hidden = true;
    elements.booksGrid.innerHTML = state.books.map(renderBookCard).join("");
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
        const response = await fetch("/api/books/scan", {
            method: "POST",
            headers: {
                "Content-Type": "application/json",
            },
            body: JSON.stringify({ isbn }),
        });

        if (response.status === 401) {
            window.location.href = `/login?next=${encodeURIComponent(window.location.pathname)}`;
            return;
        }

        const payload = await response.json();

        if (!response.ok) {
            throw new Error(payload.error || "The ISBN could not be saved.");
        }

        syncState(payload);
        renderBooks();
        elements.manualInput.value = "";
        setStatus(payload.message, "success");
        setScannerPill("Saved", "success");
    } catch (error) {
        setStatus(error.message || "The ISBN could not be saved.", "error");
        setScannerPill("Retry", "error");
    } finally {
        isSaving = false;
        elements.manualInput.disabled = false;
        elements.manualSubmit.disabled = false;
        resumeScannerSoon();
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

elements.manualForm.addEventListener("submit", (event) => {
    event.preventDefault();
    void saveIsbn(elements.manualInput.value, "manual entry");
});

window.addEventListener("beforeunload", () => {
    if (scanner) {
        scanner.clear().catch(() => {});
    }
});

renderBooks();
initialiseScanner();
