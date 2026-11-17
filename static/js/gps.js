(() => {
  "use strict";

  const $ = (id) => document.getElementById(id);
  const state = {
    watchId: null,
    refreshTimer: null,
    lastSentAt: 0,
    latest: null,
    active: false,
    map: null,
    currentMarker: null,
    accuracyCircle: null,
    eventLayer: null,
  };

  function setStatus(message, type = "") {
    const el = $("gpsState");
    if (!el) return;
    el.textContent = message;
    el.classList.toggle("is-on", type === "on");
    el.classList.toggle("is-error", type === "error");
  }

  function formatTime(value) {
    if (!value) return "--";
    const d = new Date(value);
    return Number.isNaN(d.getTime()) ? value : d.toLocaleString("vi-VN");
  }

  function escapeHtml(value) {
    return String(value ?? "").replace(/[&<>"']/g, (char) => ({
      "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"
    }[char]));
  }

  function initMap() {
    const mapElement = $("gpsMap");
    if (!mapElement) return;

    if (!window.L) {
      mapElement.textContent = "Không tải được thư viện bản đồ. Kiểm tra kết nối Internet hoặc CDN Leaflet.";
      setStatus("Không tải được bản đồ", "error");
      return;
    }

    // Chỉ là góc nhìn tổng quan ban đầu, không phải vị trí thực của thiết bị.
    state.map = L.map(mapElement, { scrollWheelZoom: true }).setView([16, 106], 5);
    L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
      maxZoom: 19,
      attribution: '&copy; <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noopener">OpenStreetMap</a> contributors'
    }).addTo(state.map);
    state.eventLayer = L.layerGroup().addTo(state.map);

    window.setTimeout(() => state.map && state.map.invalidateSize(), 250);
  }

  function updateCurrentMarker(position) {
    if (!state.map || !window.L) return;
    const latlng = [position.latitude, position.longitude];
    const popup = `<strong>Vị trí hiện tại</strong><br>${position.latitude.toFixed(6)}, ${position.longitude.toFixed(6)}<br>Độ chính xác: ${position.accuracy == null ? "Không rõ" : `±${Math.round(position.accuracy)} m`}`;

    if (!state.currentMarker) {
      state.currentMarker = L.circleMarker(latlng, {
        radius: 9, color: "#ffffff", weight: 2,
        fillColor: "#16a34a", fillOpacity: 1
      }).addTo(state.map);
    } else {
      state.currentMarker.setLatLng(latlng);
    }
    state.currentMarker.bindPopup(popup);

    if (state.accuracyCircle) state.map.removeLayer(state.accuracyCircle);
    if (Number.isFinite(position.accuracy) && position.accuracy > 0) {
      state.accuracyCircle = L.circle(latlng, {
        radius: position.accuracy,
        color: "#16a34a", weight: 1, fillColor: "#16a34a", fillOpacity: 0.10
      }).addTo(state.map);
    }

    state.map.setView(latlng, Math.max(state.map.getZoom(), 16));
    $("gpsZoomCurrentBtn").disabled = false;
  }

  function showPosition(position) {
    const c = position.coords;
    state.latest = {
      latitude: c.latitude,
      longitude: c.longitude,
      accuracy: Number.isFinite(c.accuracy) ? c.accuracy : null,
    };
    $("gpsLat").textContent = c.latitude.toFixed(6);
    $("gpsLon").textContent = c.longitude.toFixed(6);
    $("gpsAccuracy").textContent = Number.isFinite(c.accuracy) ? `± ${Math.round(c.accuracy)} m` : "Không rõ";
    $("gpsUpdated").textContent = new Date().toLocaleTimeString("vi-VN");

    const link = $("gpsMapLink");
    link.href = `https://www.openstreetmap.org/?mlat=${encodeURIComponent(c.latitude)}&mlon=${encodeURIComponent(c.longitude)}#map=17/${encodeURIComponent(c.latitude)}/${encodeURIComponent(c.longitude)}`;
    link.hidden = false;
    updateCurrentMarker(state.latest);

    // Server chỉ giữ một vị trí hiện tại; lịch sử lâu dài chỉ được tạo khi có cảnh báo.
    const now = Date.now();
    if (now - state.lastSentAt >= 10000) {
      state.lastSentAt = now;
      sendLatestPosition(state.latest).catch((err) => console.warn("GPS sync:", err));
    }
  }

  async function sendLatestPosition(position) {
    const response = await fetch("/api/features/gps/location", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(position),
      cache: "no-store",
    });
    const data = await response.json().catch(() => ({}));
    if (!response.ok || !data.success) throw new Error(data.message || `HTTP ${response.status}`);
  }

  function handlePositionError(error) {
    const messages = {
      1: "Bạn chưa cấp quyền vị trí cho trình duyệt.",
      2: "Thiết bị không xác định được vị trí.",
      3: "Lấy vị trí quá thời gian chờ. Hãy thử lại.",
    };
    setStatus(messages[error.code] || "Không lấy được vị trí GPS.", "error");
  }

  function requestOnePosition() {
    return new Promise((resolve, reject) => {
      if (!navigator.geolocation) {
        reject(new Error("Trình duyệt không hỗ trợ Geolocation."));
        return;
      }
      navigator.geolocation.getCurrentPosition(resolve, reject, {
        enableHighAccuracy: true, maximumAge: 10000, timeout: 25000,
      });
    });
  }

  async function startGps() {
    if (!navigator.geolocation) {
      setStatus("Trình duyệt không hỗ trợ GPS", "error");
      return;
    }
    $("gpsStartBtn").disabled = true;
    setStatus("Đang xin quyền và lấy vị trí…");
    try {
      const position = await requestOnePosition();
      showPosition(position);
      await sendLatestPosition(state.latest);
      state.active = true;
      setStatus("GPS đang hoạt động", "on");
      $("gpsStopBtn").disabled = false;
      $("gpsStartBtn").disabled = true;

      state.watchId = navigator.geolocation.watchPosition(
        (p) => { showPosition(p); setStatus("GPS đang hoạt động", "on"); },
        handlePositionError,
        { enableHighAccuracy: true, maximumAge: 10000, timeout: 25000 }
      );

      state.refreshTimer = window.setInterval(() => {
        if (!state.active) return;
        navigator.geolocation.getCurrentPosition(
          showPosition, handlePositionError,
          { enableHighAccuracy: true, maximumAge: 15000, timeout: 20000 }
        );
      }, 30000);
      await loadGpsEvents();
    } catch (error) {
      if (typeof error.code === "number") handlePositionError(error);
      else setStatus(error.message || "Không lấy được vị trí GPS.", "error");
      $("gpsStartBtn").disabled = false;
      $("gpsStopBtn").disabled = true;
    }
  }

  async function stopGps() {
    state.active = false;
    if (state.watchId !== null) {
      navigator.geolocation.clearWatch(state.watchId);
      state.watchId = null;
    }
    if (state.refreshTimer !== null) {
      window.clearInterval(state.refreshTimer);
      state.refreshTimer = null;
    }
    try {
      await fetch("/api/features/gps/location", { method: "DELETE", cache: "no-store" });
    } catch (error) {
      console.warn("Không xóa được vị trí hiện tại:", error);
    }
    state.latest = null;
    state.lastSentAt = 0;
    $("gpsLat").textContent = "--";
    $("gpsLon").textContent = "--";
    $("gpsAccuracy").textContent = "--";
    $("gpsUpdated").textContent = "--";
    $("gpsMapLink").hidden = true;
    $("gpsStopBtn").disabled = true;
    $("gpsStartBtn").disabled = false;
    $("gpsZoomCurrentBtn").disabled = true;
    if (state.currentMarker && state.map) state.map.removeLayer(state.currentMarker);
    if (state.accuracyCircle && state.map) state.map.removeLayer(state.accuracyCircle);
    state.currentMarker = null;
    state.accuracyCircle = null;
    setStatus("GPS đang tắt");
  }

  function zoomToPoint(latitude, longitude, marker) {
    if (!state.map) return;
    state.map.setView([latitude, longitude], 17);
    if (marker) marker.openPopup();
  }

  async function loadGpsEvents() {
    const container = $("gpsEventsList");
    try {
      const response = await fetch("/api/features/gps/events?limit=50", { cache: "no-store" });
      const data = await response.json();
      if (!response.ok || !data.success) throw new Error(data.message || "Không tải được GPS events");
      container.replaceChildren();
      if (state.eventLayer) state.eventLayer.clearLayers();

      if (!data.events.length) {
        const p = document.createElement("p");
        p.className = "gps-empty";
        p.textContent = "Chưa có cảnh báo nào được lưu kèm tọa độ GPS.";
        container.appendChild(p);
        return;
      }

      const validPoints = [];
      data.events.forEach((event) => {
        const lat = Number(event.latitude);
        const lon = Number(event.longitude);
        if (!Number.isFinite(lat) || !Number.isFinite(lon)) return;

        let marker = null;
        if (state.map && state.eventLayer) {
          marker = L.circleMarker([lat, lon], {
            radius: 7, color: "#ffffff", weight: 2,
            fillColor: "#ef4444", fillOpacity: 0.95
          });
          marker.bindPopup(
            `<strong>${escapeHtml(event.event_type || "ALERT")} · #${escapeHtml(event.alert_rowid)}</strong>` +
            `<br>${escapeHtml(formatTime(event.created_at))}` +
            `<br>${lat.toFixed(6)}, ${lon.toFixed(6)}` +
            `<br>Độ chính xác: ±${Math.round(Number(event.accuracy_m) || 0)} m`
          );
          marker.addTo(state.eventLayer);
          validPoints.push([lat, lon]);
        }

        const row = document.createElement("div");
        row.className = "gps-event-row";
        const info = document.createElement("div");
        const title = document.createElement("strong");
        title.textContent = `${event.event_type || "ALERT"} · #${event.alert_rowid}`;
        const meta = document.createElement("span");
        meta.textContent = `${formatTime(event.created_at)} · ${lat.toFixed(6)}, ${lon.toFixed(6)} · ±${Math.round(Number(event.accuracy_m) || 0)} m`;
        info.append(title, meta);
        const button = document.createElement("button");
        button.type = "button";
        button.className = "gps-text-btn gps-show-event-btn";
        button.textContent = "Xem trên bản đồ";
        button.addEventListener("click", () => zoomToPoint(lat, lon, marker));
        row.append(info, button);
        container.appendChild(row);
      });

      if (validPoints.length && !state.currentMarker && state.map) {
        if (validPoints.length === 1) state.map.setView(validPoints[0], 16);
        else state.map.fitBounds(L.latLngBounds(validPoints).pad(0.15), { maxZoom: 16 });
      }
    } catch (error) {
      container.textContent = "Không tải được danh sách vị trí cảnh báo: " + error.message;
    }
  }

  document.addEventListener("DOMContentLoaded", () => {
    if (!$("gpsPanel")) return;
    initMap();
    $("gpsStartBtn").addEventListener("click", startGps);
    $("gpsStopBtn").addEventListener("click", stopGps);
    $("gpsRefreshBtn").addEventListener("click", async () => {
      try {
        const position = await requestOnePosition();
        showPosition(position);
        await sendLatestPosition(state.latest);
        setStatus("Đã cập nhật vị trí", "on");
      } catch (error) {
        if (error && typeof error.code === "number") handlePositionError(error);
        else setStatus(error.message, "error");
      }
    });
    $("gpsEventsRefreshBtn").addEventListener("click", loadGpsEvents);
    $("gpsZoomCurrentBtn").addEventListener("click", () => {
      if (state.latest) zoomToPoint(state.latest.latitude, state.latest.longitude, state.currentMarker);
    });
    loadGpsEvents();
    window.setTimeout(() => state.map && state.map.invalidateSize(), 400);
  });

  window.addEventListener("beforeunload", () => {
    if (state.watchId !== null) navigator.geolocation.clearWatch(state.watchId);
    if (state.refreshTimer !== null) window.clearInterval(state.refreshTimer);
  });
})();
