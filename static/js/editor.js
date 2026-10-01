(() => {
    const body = document.body;
    if (body.dataset.editor !== "1") return;

    const csrf = document.querySelector('meta[name="csrf-token"]')?.content || "";
    const toast = document.querySelector("[data-toast]");

    const targets = Array.from(document.querySelectorAll("[data-edit-key]"));
    if (!targets.length) return;

    const STORAGE_KEY = "cofee-editor-mode";
    let editing = false;
    try {
        editing = localStorage.getItem(STORAGE_KEY) === "on";
    } catch (err) {
        editing = false;
    }

    const showToast = (message) => {
        if (!toast) return;
        window.clearTimeout(toast._editorTimer);
        toast.textContent = message;
        toast.classList.add("show");
        toast._editorTimer = window.setTimeout(() => toast.classList.remove("show"), 2200);
    };

    const save = async (el) => {
        const value = el.textContent.trim();
        const original = (el.dataset.original || "").trim();
        if (value === original) return;

        if (!value) {
            el.textContent = original;
            showToast("內容不可空白");
            return;
        }

        try {
            const res = await fetch("/api/admin/content", {
                method: "POST",
                headers: { "Content-Type": "application/json", "X-CSRFToken": csrf },
                body: JSON.stringify({ key: el.dataset.editKey, value }),
            });
            const data = await res.json().catch(() => ({}));
            if (!res.ok) throw new Error(data.error || "儲存失敗");
            el.dataset.original = value;
            showToast("已儲存，前台內容已更新");
        } catch (err) {
            showToast(err.message || "儲存失敗");
            el.textContent = original;
        }
    };

    const badge = document.createElement("div");
    badge.className = "edit-badge";
    const dot = document.createElement("span");
    dot.className = "edit-dot";
    const label = document.createElement("span");
    label.className = "edit-badge-label";
    const toggle = document.createElement("button");
    toggle.type = "button";
    toggle.className = "edit-toggle";
    badge.append(dot, label, toggle);
    body.appendChild(badge);

    // Listeners are attached once; each one no-ops unless we are in edit mode.
    targets.forEach((el) => {
        el.dataset.original = el.textContent.trim();

        el.addEventListener("click", (event) => {
            if (editing && el.tagName === "A") event.preventDefault();
        });

        el.addEventListener("keydown", (event) => {
            if (editing && event.key === "Enter") {
                event.preventDefault();
                el.blur();
            }
        });

        el.addEventListener("blur", () => {
            if (editing) save(el);
        });
    });

    const applyState = () => {
        badge.classList.toggle("is-editing", editing);
        targets.forEach((el) => {
            if (editing) {
                el.setAttribute("contenteditable", "true");
                el.setAttribute("spellcheck", "false");
                el.classList.add("is-editable");
                el.dataset.original = el.textContent.trim();
            } else {
                el.removeAttribute("contenteditable");
                el.classList.remove("is-editable");
            }
        });
        label.textContent = editing
            ? "編輯模式：點選文字即可修改，離開欄位後自動儲存"
            : "瀏覽模式";
        toggle.textContent = editing ? "切回正常模式" : "進入編輯模式";
    };

    toggle.addEventListener("click", () => {
        editing = !editing;
        try {
            localStorage.setItem(STORAGE_KEY, editing ? "on" : "off");
        } catch (err) {
            /* localStorage 不可用時仍可於本頁切換 */
        }
        applyState();
        showToast(editing ? "已進入編輯模式" : "已切回正常模式");
    });

    applyState();
})();
