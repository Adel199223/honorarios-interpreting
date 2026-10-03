// Read-only phone browsing; the existing upload/review flow owns source recovery.
export function createCameraPicker({ requestJson, fetchFile, onState, onSelectionStart, onChoose, getRevision, isAvailable }) {
  const state = { configured: false, label: "Camera", open: false, busy: false,
    items: [], query: "", offset: 0, nextOffset: null, total: 0, truncated: false, error: "" };
  let nonce = 0;
  const snapshot = () => ({ ...state, items: state.items.map(item => ({ ...item })) });
  const emit = () => onState(snapshot());
  const available = () => isAvailable();
  function close() { nonce += 1; state.open = false; state.busy = false; emit(); }
  async function initialize() {
    const ticket = ++nonce;
    try {
      const result = await requestJson("/api/camera/status");
      if (ticket !== nonce) return;
      state.configured = result.configured === true;
      state.label = result.label || "Camera";
      state.error = "";
      emit();
    } catch {
      if (ticket !== nonce) return;
      state.error = "Camera is unavailable. You can choose another local file.";
      emit();
    }
  }
  async function load(query = "", offset = 0) {
    if (!state.open || !available()) return false;
    const ticket = ++nonce;
    state.busy = true; state.error = ""; state.items = [];
    state.nextOffset = null; state.total = 0; state.truncated = false;
    state.query = String(query).trim(); state.offset = offset; emit();
    try {
      const result = await requestJson(`/api/camera/files?query=${encodeURIComponent(state.query)}&offset=${offset}&limit=50`);
      if (ticket !== nonce || !state.open) return false;
      if (!available()) { close(); return false; }
      state.items = result.items || []; state.nextOffset = result.next_offset ?? null;
      state.total = result.total || 0; state.truncated = result.truncated === true;
      return true;
    } catch (error) {
      if (ticket === nonce && state.open) state.error = error.message || "Camera could not be opened. Check the phone connection.";
      return false;
    } finally {
      if (ticket === nonce) { state.busy = false; emit(); }
    }
  }
  async function open() {
    if (!state.configured || !available()) return false;
    state.open = true;
    return load(state.query, 0);
  }
  async function select(item) {
    if (!state.open || state.busy || !available() || !state.items.some(row => row.name === item.name && row.fingerprint === item.fingerprint)) return false;
    const ticket = ++nonce;
    state.busy = true; state.error = ""; emit();
    let revision;
    try {
      onSelectionStart();
      revision = getRevision();
      const file = await fetchFile({ ...item });
      if (ticket !== nonce || !state.open) return false;
      if (!available() || revision !== getRevision()) {
        state.error = "The request changed. Choose the photo again.";
        return false;
      }
      onChoose(file);
      close();
      return true;
    } catch (error) {
      if (ticket === nonce && state.open) state.error = !available() || (revision !== undefined && revision !== getRevision())
        ? "The request changed. Choose the photo again."
        : error.message || "The photo could not be read. Check the phone connection and try again.";
      return false;
    } finally {
      if (ticket === nonce) { state.busy = false; emit(); }
    }
  }
  return { initialize, open, load, close, invalidate: close, select, snapshot };
}

// One visible listing owns its previews. Thumbnail work never selects or reviews
// an original; callers keep those actions in the existing source workflow.
export function createCameraThumbnailGrid({ document, container, root, onChoose, fetchThumbnail,
  createObjectURL = blob => URL.createObjectURL(blob), revokeObjectURL = url => URL.revokeObjectURL(url),
  observe = typeof globalThis.IntersectionObserver === "function"
    ? (callback, options) => new globalThis.IntersectionObserver(callback, options) : null }) {
  let listingKey = "", opened = false, paused = true, observer = null, inFlight = 0;
  const entries = new Map(), byElement = new Map();
  const current = entry => opened && entries.get(entry.key) === entry;

  function release(entry) {
    entry.controller?.abort();
    entry.controller = null;
    if (entry.url) revokeObjectURL(entry.url);
    entry.url = "";
    entry.image.removeAttribute("src");
  }
  function clear() {
    opened = false; paused = true; listingKey = "";
    observer?.disconnect(); observer = null;
    entries.forEach(release); entries.clear(); byElement.clear();
    container.replaceChildren();
  }
  function failed(entry, error) {
    if (!current(entry)) return;
    if (entry.url) revokeObjectURL(entry.url);
    entry.url = "";
    entry.image.removeAttribute("src");
    entry.status = "error";
    entry.frame.classList.remove("has-preview");
    const message = error?.code === "camera_photo_changed"
      ? "Photo changed. Refresh photos to load its latest version."
      : "Preview unavailable. Refresh photos to try again.";
    entry.placeholder.textContent = message;
    entry.button.title = message;
    entry.button.setAttribute("aria-label", `${entry.label} · ${message}`);
  }
  function pump() {
    if (!opened || paused) return;
    for (const entry of entries.values()) {
      if (inFlight >= 3) break;
      if (!entry.visible || entry.status !== "idle") continue;
      entry.status = "loading";
      entry.placeholder.textContent = "Loading preview…";
      const controller = new AbortController();
      entry.controller = controller;
      inFlight += 1;
      const active = () => current(entry) && entry.controller === controller && !controller.signal.aborted;
      (async () => {
        try {
          const blob = await fetchThumbnail({ ...entry.item }, controller.signal);
          if (!active()) return;
          entry.url = createObjectURL(blob);
          entry.status = "loaded";
          entry.image.src = entry.url;
        } catch (error) {
          if (active()) failed(entry, error);
        } finally {
          if (entry.controller === controller) entry.controller = null;
          inFlight -= 1;
          pump();
        }
      })();
    }
  }
  function pause(value) {
    paused = value;
    if (paused) entries.forEach(entry => {
      if (!entry.controller) return;
      entry.controller.abort(); entry.controller = null;
      entry.status = "idle";
      entry.placeholder.textContent = "Photo preview";
    });
    else pump();
  }
  function update(view, disabled = false) {
    if (!view.open) { clear(); return; }
    const nextKey = JSON.stringify([view.query || "", view.offset || 0,
      view.items.map(item => [item.name, item.fingerprint, item.size])]);
    if (nextKey !== listingKey || !opened) {
      clear(); opened = true; listingKey = nextKey;
      for (const item of view.items) {
        const key = JSON.stringify([item.name, item.fingerprint]);
        const button = document.createElement("button");
        button.type = "button"; button.className = "camera-photo-tile";
        const size = `${(item.size / 1024 / 1024).toFixed(1)} MB`;
        const label = `${item.name} · ${size}`;
        button.setAttribute("aria-label", label);
        const frame = document.createElement("span"); frame.className = "camera-photo-preview";
        frame.setAttribute("aria-hidden", "true");
        const image = document.createElement("img"); image.alt = ""; image.decoding = "async";
        const placeholder = document.createElement("span"); placeholder.className = "camera-photo-placeholder";
        placeholder.textContent = observe ? "Photo preview" : "Preview unavailable";
        frame.append(image, placeholder);
        const caption = document.createElement("span"); caption.className = "camera-photo-caption";
        const filename = document.createElement("strong"); filename.textContent = item.name;
        const detail = document.createElement("small"); detail.textContent = size;
        caption.append(filename, detail); button.append(frame, caption);
        const entry = { key, item: { ...item }, label, button, frame, image, placeholder,
          visible: false, status: "idle", controller: null, url: "" };
        entries.set(key, entry); byElement.set(button, entry);
        button.addEventListener("click", () => {
          if (current(entry) && !button.disabled) return onChoose({ ...entry.item });
        });
        image.addEventListener("load", () => {
          if (current(entry) && entry.url && entry.status === "loaded") frame.classList.add("has-preview");
        });
        image.addEventListener("error", () => { if (entry.url) failed(entry); });
        container.append(button);
      }
      if (observe) {
        observer = observe(changes => {
          for (const change of changes) {
            const entry = byElement.get(change.target);
            if (entry && current(entry)) entry.visible = change.isIntersecting;
          }
          pump();
        }, { root, rootMargin: "0px", threshold: 0.01 });
        entries.forEach(entry => observer.observe(entry.button));
      }
    }
    entries.forEach(entry => { entry.button.disabled = Boolean(view.busy || disabled); });
    pause(Boolean(view.busy || disabled));
  }
  return { update, clear };
}
