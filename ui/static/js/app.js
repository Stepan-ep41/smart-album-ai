let currentPath = "";

async function fetchStats() {
    try {
        const res = await fetch("/api/stats");
        const data = await res.json();
        document.getElementById("stats-text").innerText = 
            `Всего: ${data.total} | Обработано: ${data.processed} | Ожидают: ${data.unprocessed}`;
    } catch (err) {
        console.error("Ошибка получения статистики:", err);
    }
}

async function loadFolder(path = "") {
    currentPath = path;
    renderBreadcrumbs(path);

    try {
        const res = await fetch(`/api/browse?path=${encodeURIComponent(path)}`);
        const data = await res.json();

        renderFolders(data.subfolders, path);
        renderPhotos(data.photos);

        const isEmpty = data.subfolders.length === 0 && data.photos.length === 0;
        document.getElementById("empty-state").style.display = isEmpty ? "block" : "none";
    } catch (err) {
        console.error("Ошибка загрузки папки:", err);
    }
}

function renderBreadcrumbs(path) {
    const container = document.getElementById("breadcrumbs");
    container.innerHTML = "";

    const rootLink = document.createElement("a");
    rootLink.innerText = "Корень альбома";
    rootLink.onclick = () => loadFolder("");
    container.appendChild(rootLink);

    if (!path) return;

    const parts = path.split("/");
    let accum = "";

    parts.forEach((part) => {
        container.appendChild(document.createTextNode(" / "));
        accum = accum ? `${accum}/${part}` : part;
        const linkPath = accum;

        const link = document.createElement("a");
        link.innerText = part;
        link.onclick = () => loadFolder(linkPath);
        container.appendChild(link);
    });
}

function renderFolders(subfolders, parentPath) {
    const container = document.getElementById("folders-container");
    container.innerHTML = "";

    subfolders.forEach((name) => {
        const card = document.createElement("div");
        card.className = "folder-card";
        card.innerHTML = `
            <div class="folder-icon">📁</div>
            <div class="folder-name">${name}</div>
        `;
        const nextPath = parentPath ? `${parentPath}/${name}` : name;
        card.onclick = () => loadFolder(nextPath);
        container.appendChild(card);
    });
}

function renderPhotos(photos) {
    const container = document.getElementById("photos-container");
    container.innerHTML = "";

    photos.forEach((photo) => {
        const card = document.createElement("div");
        card.className = "photo-card";
        
        // Фотографии запрашиваются через роут /media/
        const imgSrc = `/media/${encodeURI(photo.relative_path)}`;
        const caption = photo.manual_caption || photo.auto_caption || "Без описания";

        card.innerHTML = `
            <img class="photo-img" src="${imgSrc}" loading="lazy" alt="${photo.relative_path}">
            <div class="photo-info">${caption}</div>
        `;
        container.appendChild(card);
    });
}

// Кнопка пересканирования
document.getElementById("btn-scan").onclick = async () => {
    const btn = document.getElementById("btn-scan");
    btn.disabled = true;
    btn.innerText = "Сканирование...";
    try {
        await fetch("/api/scan", { method: "POST" });
        await fetchStats();
        await loadFolder(currentPath);
    } finally {
        btn.disabled = false;
        btn.innerText = "Пересканировать папку";
    }
};

// Первый запуск
fetchStats();
loadFolder("");