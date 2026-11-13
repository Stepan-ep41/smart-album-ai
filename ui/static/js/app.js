let currentPath = "";

// --- Полноразмерный просмотр ---
// 100% = один пиксель фото равен одному пикселю экрана.
const MAX_ZOOM = 5;
const ZOOM_STEP = 1.25;

const lightbox = document.getElementById("lightbox");
const lightboxViewport = document.getElementById("lightbox-viewport");
const lightboxImage = document.getElementById("lightbox-image");
const lightboxStatus = document.getElementById("lightbox-status");
const lightboxTitle = document.getElementById("lightbox-title");
const zoomLevel = document.getElementById("zoom-level");
const manualCaptionInput = document.getElementById("manual-caption");
const autoCaptionEl = document.getElementById("auto-caption");
const captionStatusEl = document.getElementById("caption-status");
const saveCaptionBtn = document.getElementById("save-caption");
const photoPrevBtn = document.getElementById("photo-prev");
const photoNextBtn = document.getElementById("photo-next");
const photoFullscreenBtn = document.getElementById("photo-fullscreen");

let currentPhoto = null;
let currentPhotoList = [];
let currentPhotoIndex = -1;
let lightboxLoadToken = 0;
let captionDirty = false;
let captionTouched = false;
let captionStatusTimer = null;
let edgeNavTimer = null;

let zoomScale = 1;
let panX = 0;
let panY = 0;
let isPanning = false;
let panStartX = 0;
let panStartY = 0;
let panStartPanX = 0;
let panStartPanY = 0;

// Размеры оригинала: пока их нет, процент зума не показываем,
// потому что сначала загружается уменьшенное превью.
let originalNatural = null;
let currentIsOriginal = false;

// Кодируем каждый сегмент пути отдельно: файлы с #, ? или пробелами
// в имени иначе ломали бы URL.
function encodePath(path) {
    return path.split("/").map(encodeURIComponent).join("/");
}

function fileName(path) {
    return path.split("/").pop();
}

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
    currentPhotoList = Array.isArray(photos) ? photos : [];

    photos.forEach((photo, index) => {
        const card = document.createElement("div");
        card.className = "photo-card";
        card.tabIndex = 0;
        card.setAttribute("role", "button");

        const name = fileName(photo.relative_path);
        card.setAttribute("aria-label", `Открыть фото ${name}`);

        // В сетке показываем маленькое готовое превью (WebP), а не оригинал
        // на 4–20 МБ: именно это и было причиной медленной загрузки.
        const img = document.createElement("img");
        img.className = "photo-img";
        img.src = `/thumb/480/${encodePath(photo.relative_path)}`;
        img.width = 480;
        img.height = 270;
        img.decoding = "async";
        img.alt = name;
        img.loading = index < 4 ? "eager" : "lazy";
        if (index < 4) {
            img.fetchPriority = "high";
        }

        // Под миниатюрой показываем имя файла, а не описание.
        const info = document.createElement("div");
        info.className = "photo-info";
        info.textContent = name;
        info.title = photo.relative_path;

        card.append(img, info);

        const open = () => openPhoto(photo, index);
        card.onclick = open;
        card.onkeydown = (event) => {
            if (event.key === "Enter" || event.key === " ") {
                event.preventDefault();
                open();
            }
        };

        container.appendChild(card);
    });
}

// --- Просмотр фотографии в полном размере ---

function formatZoom() {
    if (!originalNatural) {
        // Пока показывается быстрое превью, честный процент неизвестен.
        zoomLevel.textContent = "…";
        zoomLevel.title = "Загрузка оригинала…";
        return;
    }
    zoomLevel.textContent = `${Math.round(zoomScale * 100)}%`;
    zoomLevel.title = "";
}

function zoomViewportSize() {
    // В полноэкранном режиме фото занимает весь экран, а не только
    // область вьюпорта внутри страницы.
    if (isPhotoFullscreen()) {
        return { width: window.innerWidth, height: window.innerHeight };
    }
    return { width: lightboxViewport.clientWidth, height: lightboxViewport.clientHeight };
}

// Масштаб, при котором фото целиком помещается в контейнер.
// 100% (масштаб 1) — это 1:1 с пикселями оригинала.
function fitScaleFor(naturalWidth, naturalHeight) {
    if (!naturalWidth || !naturalHeight) return 1;

    const viewport = zoomViewportSize();
    if (!viewport.width || !viewport.height) return 1;

    const fit = Math.min(viewport.width / naturalWidth, viewport.height / naturalHeight);
    // Маленькие фото не растягиваем больше 100%.
    return Math.min(fit, 1);
}

function minZoomScale() {
    return fitScaleFor(lightboxImage.naturalWidth, lightboxImage.naturalHeight);
}

function displaySize() {
    return {
        width: lightboxImage.naturalWidth * zoomScale,
        height: lightboxImage.naturalHeight * zoomScale,
    };
}

function canPanNow() {
    const viewport = zoomViewportSize();
    const size = displaySize();
    return size.width > viewport.width + 0.5 || size.height > viewport.height + 0.5;
}

function clampPan() {
    const viewport = zoomViewportSize();
    const size = displaySize();
    const maxX = Math.max(0, (size.width - viewport.width) / 2);
    const maxY = Math.max(0, (size.height - viewport.height) / 2);

    panX = Math.min(maxX, Math.max(-maxX, panX));
    panY = Math.min(maxY, Math.max(-maxY, panY));
}

function applyTransform() {
    lightboxImage.style.transform = `translate(${panX}px, ${panY}px) scale(${zoomScale})`;
    const canPan = canPanNow();
    lightboxViewport.classList.toggle("can-pan", canPan);
    lightboxImage.classList.toggle("can-pan", canPan);
    formatZoom();
}

function setZoom(nextScale, originX = 0, originY = 0) {
    const clamped = Math.min(MAX_ZOOM, Math.max(minZoomScale(), nextScale));
    if (Math.abs(clamped - zoomScale) < 0.0001) return;

    // Держим точку под курсором (или центр) на месте при масштабировании.
    const ratio = clamped / zoomScale;
    panX = originX - (originX - panX) * ratio;
    panY = originY - (originY - panY) * ratio;
    zoomScale = clamped;

    clampPan();
    applyTransform();
}

function resetZoom() {
    zoomScale = minZoomScale();
    panX = 0;
    panY = 0;
    applyTransform();
}

function setCaptionStatus(text, isError = false) {
    captionStatusEl.textContent = text;
    captionStatusEl.classList.toggle("is-error", isError);
}

function clearCaptionStatus() {
    clearTimeout(captionStatusTimer);
    setCaptionStatus("");
}

function confirmDiscardCaption() {
    if (!captionDirty) return true;
    return window.confirm(
        "Есть несохранённые изменения описания. Продолжить без сохранения?"
    );
}

function updatePhotoNavigation() {
    const total = currentPhotoList.length;
    const hasNeighbours = total > 1;

    photoPrevBtn.hidden = !hasNeighbours;
    photoNextBtn.hidden = !hasNeighbours;
    photoPrevBtn.disabled = !hasNeighbours || currentPhotoIndex <= 0;
    photoNextBtn.disabled = !hasNeighbours || currentPhotoIndex >= total - 1;
}

async function navigatePhoto(delta) {
    if (!lightbox.hidden) {
        const nextIndex = currentPhotoIndex + delta;
        if (nextIndex < 0 || nextIndex >= currentPhotoList.length) return;
        if (!confirmDiscardCaption()) return;
        await openPhoto(currentPhotoList[nextIndex], nextIndex);
    }
}

// --- Полноэкранный режим ---

function isPhotoFullscreen() {
    // Разворачиваем на весь экран контейнер, а не сам <img>: трансформация
    // на полноэкранном элементе в некоторых браузерах игнорируется, из-за
    // чего зум менял состояние, но картинка визуально не увеличивалась.
    const fsEl = document.fullscreenElement || document.webkitFullscreenElement;
    return fsEl === lightboxViewport
        || lightboxViewport.classList.contains("is-photo-fullscreen");
}

function updateFullscreenButton() {
    const active = isPhotoFullscreen();
    photoFullscreenBtn.title = active
        ? "Выйти из полноэкранного режима (Esc)"
        : "Открыть фото на весь экран";
    photoFullscreenBtn.setAttribute(
        "aria-label",
        active ? "Выйти из полноэкранного режима" : "Открыть фото на весь экран"
    );
}

async function enterPhotoFullscreen() {
    if (lightbox.hidden || isPhotoFullscreen()) return;

    // Сбрасываем панорамирование, если оно было активно при зуме в ПОФ
    isPanning = false;
    lightboxViewport.classList.remove("is-panning");

    const applyFallback = () => {
        const fsEl = document.fullscreenElement || document.webkitFullscreenElement;
        if (fsEl === lightboxViewport) return;
        lightboxViewport.classList.add("is-photo-fullscreen");
        document.body.classList.add("photo-fullscreen-open");
        updateFullscreenButton();
        resetZoom();
    };

    // Если браузер не может включить настоящий fullscreen (или запрос
    // зависает), через мгновение включаем запасной режим на весь экран.
    const fallbackTimer = setTimeout(applyFallback, 350);

    const reqFullscreen = lightboxViewport.requestFullscreen || lightboxViewport.webkitRequestFullscreen;
    if (reqFullscreen) {
        try {
            await reqFullscreen.call(lightboxViewport);
            clearTimeout(fallbackTimer);
            lightboxViewport.classList.remove("is-photo-fullscreen");
            document.body.classList.remove("photo-fullscreen-open");
            updateFullscreenButton();
            resetZoom();
            return;
        } catch (err) {
            clearTimeout(fallbackTimer);
            console.warn("Fullscreen API недоступен, использую запасной режим:", err);
        }
    }

    applyFallback();
}

function exitPhotoFullscreen() {
    const fsEl = document.fullscreenElement || document.webkitFullscreenElement;
    const exitFs = document.exitFullscreen || document.webkitExitFullscreen;

    if (fsEl === lightboxViewport && exitFs) {
        try {
            exitFs.call(document).catch((err) => {
                console.warn("Не удалось выйти из полноэкранного режима:", err);
            });
        } catch (err) {
            console.warn("Не удалось выйти из полноэкранного режима:", err);
        }
    }

    if (lightboxViewport.classList.contains("is-photo-fullscreen")) {
        lightboxViewport.classList.remove("is-photo-fullscreen");
        document.body.classList.remove("photo-fullscreen-open");
    }

    // После выхода из полноэкранного режима возвращаем обычный масштаб.
    resetZoom();
    updateFullscreenButton();
}

async function openPhoto(photo, index = -1) {
    const token = ++lightboxLoadToken;
    currentPhoto = photo;
    currentPhotoIndex = index >= 0
        ? index
        : currentPhotoList.findIndex((item) => item.id === photo.id);
    updatePhotoNavigation();
    captionDirty = false;
    captionTouched = false;
    clearCaptionStatus();

    lightbox.hidden = false;
    document.body.classList.add("lightbox-open");
    lightboxTitle.textContent = fileName(photo.relative_path);
    lightboxTitle.title = photo.relative_path;
    document.getElementById("lightbox-close").focus();

    manualCaptionInput.value = photo.manual_caption || "";
    autoCaptionEl.textContent = photo.auto_caption || "—";

    // Сбрасываем зум: честный процент станет известен после загрузки.
    originalNatural = null;
    currentIsOriginal = false;
    zoomScale = 1;
    panX = 0;
    panY = 0;
    lightboxImage.style.transform = "";
    formatZoom();

    lightboxImage.classList.remove("is-loaded");
    lightboxImage.alt = fileName(photo.relative_path);
    lightboxStatus.hidden = false;
    lightboxStatus.textContent = "Загрузка…";

    // Сначала показываем быстрое превью 960 px, затем подменяем оригиналом.
    lightboxImage.src = `/thumb/960/${encodePath(photo.relative_path)}`;
    lightboxImage.onload = () => {
        if (token !== lightboxLoadToken) return;

        // Это ещё превью — вписываем его в контейнер. Процент не
        // показываем, он будет пересчитан от размера оригинала.
        if (!currentIsOriginal && !originalNatural) {
            zoomScale = fitScaleFor(lightboxImage.naturalWidth, lightboxImage.naturalHeight);
            panX = 0;
            panY = 0;
        }

        clampPan();
        applyTransform();
        lightboxImage.classList.add("is-loaded");
    };

    const fullUrl = `/media/${encodePath(photo.relative_path)}`;
    const preloader = new Image();
    preloader.onload = () => {
        if (token !== lightboxLoadToken) return;

        const width = preloader.naturalWidth;
        const height = preloader.naturalHeight;
        const shownWidth = lightboxImage.naturalWidth;
        const shownHeight = lightboxImage.naturalHeight;

        originalNatural = { width, height };

        // Подменяем превью оригиналом без визуального скачка: сохраняем
        // текущий видимый размер и пересчитываем масштаб уже от оригинала.
        if (shownWidth > 0 && shownHeight > 0) {
            zoomScale = (shownWidth * zoomScale) / width;
        } else {
            zoomScale = fitScaleFor(width, height);
            panX = 0;
            panY = 0;
        }

        currentIsOriginal = true;
        lightboxImage.src = fullUrl;

        clampPan();
        applyTransform();
        lightboxImage.classList.add("is-loaded");
        lightboxStatus.hidden = true;
    };
    preloader.onerror = () => {
        if (token !== lightboxLoadToken) return;

        // Оригинал не загрузился — считаем превью опорным размером,
        // чтобы проценты всё равно оставались корректными.
        if (!originalNatural && lightboxImage.naturalWidth) {
            originalNatural = {
                width: lightboxImage.naturalWidth,
                height: lightboxImage.naturalHeight,
            };
            applyTransform();
        }

        lightboxStatus.hidden = false;
        lightboxStatus.textContent = "Не удалось загрузить оригинал";
    };
    preloader.src = fullUrl;

    // На случай, если данные в сетке устарели, перечитываем фото из БД.
    try {
        const res = await fetch(`/api/photos/${photo.id}`);
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const fresh = await res.json();
        if (token !== lightboxLoadToken) return;

        // Не перетираем текст, если пользователь уже начал редактировать
        // или сохранил описание, пока запрос был в пути.
        if (!captionTouched) {
            currentPhoto = fresh;
            manualCaptionInput.value = fresh.manual_caption || "";
            autoCaptionEl.textContent = fresh.auto_caption || "—";
        }
    } catch (err) {
        console.error("Не удалось получить данные фото:", err);
    }
}

function closeLightbox(force = false) {
    if (lightbox.hidden) return;

    if (!force && captionDirty) {
        if (!confirmDiscardCaption()) return;
    }

    if (isPhotoFullscreen()) {
        exitPhotoFullscreen();
    }

    clearTimeout(edgeNavTimer);
    lightboxLoadToken += 1;
    lightbox.hidden = true;
    document.body.classList.remove("lightbox-open");
    lightboxImage.removeAttribute("src");
    lightboxImage.onload = null;
    currentPhoto = null;
    currentPhotoIndex = -1;
    captionDirty = false;
    captionTouched = false;
    clearCaptionStatus();
    resetZoom();
}

async function saveCaption() {
    if (!currentPhoto) return;

    saveCaptionBtn.disabled = true;
    clearTimeout(captionStatusTimer);
    setCaptionStatus("Сохранение…");

    try {
        const res = await fetch(`/api/photos/${currentPhoto.id}`, {
            method: "PATCH",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ manual_caption: manualCaptionInput.value }),
        });
        if (!res.ok) throw new Error(`HTTP ${res.status}`);

        const updated = await res.json();
        currentPhoto = updated;
        manualCaptionInput.value = updated.manual_caption || "";
        captionDirty = false;
        setCaptionStatus("Сохранено");
        captionStatusTimer = setTimeout(clearCaptionStatus, 2500);
    } catch (err) {
        console.error("Не удалось сохранить описание:", err);
        setCaptionStatus("Не удалось сохранить", true);
    } finally {
        saveCaptionBtn.disabled = false;
    }
}

// --- События интерфейса ---

manualCaptionInput.addEventListener("input", () => {
    captionTouched = true;
    captionDirty = manualCaptionInput.value !== ((currentPhoto && currentPhoto.manual_caption) || "");
    clearCaptionStatus();
});

saveCaptionBtn.onclick = saveCaption;
document.getElementById("lightbox-close").onclick = () => closeLightbox();
document.querySelector("[data-lightbox-close]").onclick = () => closeLightbox();

document.getElementById("zoom-in").onclick = () => setZoom(zoomScale * ZOOM_STEP);
document.getElementById("zoom-out").onclick = () => setZoom(zoomScale / ZOOM_STEP);
document.getElementById("zoom-reset").onclick = resetZoom;

photoPrevBtn.onclick = () => navigatePhoto(-1);
photoNextBtn.onclick = () => navigatePhoto(1);

photoPrevBtn.addEventListener("pointerdown", (event) => event.stopPropagation());
photoNextBtn.addEventListener("pointerdown", (event) => event.stopPropagation());
photoFullscreenBtn.addEventListener("pointerdown", (event) => event.stopPropagation());

photoFullscreenBtn.onclick = () => {
    if (isPhotoFullscreen()) {
        exitPhotoFullscreen();
    } else {
        enterPhotoFullscreen();
    }
};

function handleFullscreenChange() {
    const fsEl = document.fullscreenElement || document.webkitFullscreenElement;
    const nativeFullscreen = fsEl === lightboxViewport;

    if (nativeFullscreen) {
        // Настоящий fullscreen включился — запасной режим больше не нужен.
        lightboxViewport.classList.remove("is-photo-fullscreen");
        document.body.classList.remove("photo-fullscreen-open");
    }

    updateFullscreenButton();

    if (lightbox.hidden) return;

    // И при входе в полноэкранный режим, и при выходе из него (в том числе по Esc)
    // сбрасываем зумирование и адаптируем масштаб под текущий размер области просмотра.
    resetZoom();
}

document.addEventListener("fullscreenchange", handleFullscreenChange);
document.addEventListener("webkitfullscreenchange", handleFullscreenChange);

function handleWheelZoom(event) {
    if (lightbox.hidden) return;
    // Не перехватываем прокрутку панели описаний.
    if (event.target instanceof Element && event.target.closest(".lightbox-captions")) {
        return;
    }
    event.preventDefault();

    let centerX;
    let centerY;
    if (isPhotoFullscreen()) {
        centerX = window.innerWidth / 2;
        centerY = window.innerHeight / 2;
    } else {
        const rect = lightboxViewport.getBoundingClientRect();
        centerX = rect.left + rect.width / 2;
        centerY = rect.top + rect.height / 2;
    }

    const originX = event.clientX - centerX;
    const originY = event.clientY - centerY;
    const factor = event.deltaY < 0 ? 1.15 : 1 / 1.15;
    setZoom(zoomScale * factor, originX, originY);
}

// Слушаем на document: в полноэкранном режиме события колеса приходят
// от самого фото в top layer, а не от области просмотра.
document.addEventListener("wheel", handleWheelZoom, { passive: false });

lightboxViewport.addEventListener("pointerdown", (event) => {
    // Не перехватываем нажатия на кнопки внутри вьюпорта (полный экран, навигация)
    if (event.target.closest("button")) return;
    if (!canPanNow() || event.button !== 0) return;

    isPanning = true;
    panStartX = event.clientX;
    panStartY = event.clientY;
    panStartPanX = panX;
    panStartPanY = panY;
    lightboxViewport.classList.add("is-panning");
    try {
        lightboxViewport.setPointerCapture(event.pointerId);
    } catch (err) {
        // В полноэкранном режиме захват указателя может быть недоступен.
    }
});

lightboxViewport.addEventListener("pointermove", (event) => {
    if (!isPanning) return;

    panX = panStartPanX + (event.clientX - panStartX);
    panY = panStartPanY + (event.clientY - panStartY);
    clampPan();
    applyTransform();
});

function endPan(event) {
    if (!isPanning) return;

    isPanning = false;
    lightboxViewport.classList.remove("is-panning");
    try {
        if (lightboxViewport.hasPointerCapture(event.pointerId)) {
            lightboxViewport.releasePointerCapture(event.pointerId);
        }
    } catch (err) {
        // Игнорируем: захват мог не состояться.
    }
}

lightboxViewport.addEventListener("pointerup", endPan);
lightboxViewport.addEventListener("pointercancel", endPan);

lightboxImage.addEventListener("dragstart", (event) => event.preventDefault());

// Клик по левому/правому краю фотографии переключает на соседнюю.
// Небольшая задержка позволяет отличить одиночный клик от двойного (зум).
lightboxImage.addEventListener("click", (event) => {
    if (lightbox.hidden || isPhotoFullscreen() || canPanNow()) return;

    const rect = lightboxImage.getBoundingClientRect();
    if (!rect.width) return;

    const relativeX = (event.clientX - rect.left) / rect.width;
    let delta = 0;
    if (relativeX < 0.25) {
        delta = -1;
    } else if (relativeX > 0.75) {
        delta = 1;
    }
    if (!delta) return;

    clearTimeout(edgeNavTimer);
    edgeNavTimer = setTimeout(() => navigatePhoto(delta), 240);
});

lightboxImage.addEventListener("dblclick", () => {
    clearTimeout(edgeNavTimer);

    // Двойной клик в полноэкранном режиме выходит из него.
    if (isPhotoFullscreen()) {
        exitPhotoFullscreen();
        return;
    }

    if (canPanNow()) {
        resetZoom();
    } else {
        // Двойной клик показывает фото в натуральном масштабе (100% = 1:1).
        setZoom(1);
    }
});

document.addEventListener("keydown", (event) => {
    if (lightbox.hidden) return;

    if (event.key === "Escape") {
        // Сначала выходим из полноэкранного фото, вторым Esc закрываем просмотр.
        if (isPhotoFullscreen()) {
            exitPhotoFullscreen();
            return;
        }
        closeLightbox();
        return;
    }

    const isFormField = event.target instanceof HTMLElement
        && (event.target.tagName === "TEXTAREA" || event.target.tagName === "INPUT");

    if (event.key === "Enter" && (event.ctrlKey || event.metaKey)) {
        event.preventDefault();
        saveCaption();
        return;
    }

    if (isFormField) return;

    if (event.key === "f" || event.key === "F" || event.key === "а" || event.key === "А") {
        event.preventDefault();
        if (isPhotoFullscreen()) {
            exitPhotoFullscreen();
        } else {
            enterPhotoFullscreen();
        }
        return;
    }

    if (event.key === "ArrowLeft") {
        if (!isPhotoFullscreen() && !canPanNow()) {
            event.preventDefault();
            navigatePhoto(-1);
        }
        return;
    }

    if (event.key === "ArrowRight") {
        if (!isPhotoFullscreen() && !canPanNow()) {
            event.preventDefault();
            navigatePhoto(1);
        }
        return;
    }

    if (event.key === "+" || event.key === "=") {
        event.preventDefault();
        setZoom(zoomScale * ZOOM_STEP);
    } else if (event.key === "-" || event.key === "_") {
        event.preventDefault();
        setZoom(zoomScale / ZOOM_STEP);
    } else if (event.key === "0") {
        resetZoom();
    }
});

window.addEventListener("resize", () => {
    if (!lightbox.hidden) {
        if (!canPanNow()) {
            resetZoom();
        } else {
            clampPan();
            applyTransform();
        }
    }
});

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
