(() => {
  "use strict";

  const $ = (id) => document.getElementById(id);

  const state = {
    watchId: null,
    refreshTimer: null,
    lastSentAt: 0,
    latest: null,
    active: false,
    starting: false,
    generation: 0,
    map: null,
    currentMarker: null,
    accuracyCircle: null,
    eventLayer: null,
  };

  // =====================================================
  // TRẠNG THÁI GPS
  // =====================================================

  function setStatus(message, type = "") {
    const el = $("gpsState");
    if (!el) return;

    el.textContent = message;
    el.classList.toggle("is-on", type === "on");
    el.classList.toggle("is-error", type === "error");
  }

  function setGpsButtons() {
    if ($("gpsStartBtn")) {
      $("gpsStartBtn").disabled = state.active || state.starting;
    }

    if ($("gpsStopBtn")) {
      $("gpsStopBtn").disabled = !state.active && !state.starting;
    }
  }

  function formatTime(value) {
    if (!value) return "--";

    const d = new Date(value);
    return Number.isNaN(d.getTime()) ? value : d.toLocaleString("vi-VN");
  }

  function escapeHtml(value) {
    return String(value ?? "").replace(
      /[&<>"']/g,
      (char) =>
        ({
          "&": "&amp;",
          "<": "&lt;",
          ">": "&gt;",
          '"': "&quot;",
          "'": "&#39;",
        }[char])
    );
  }

  // =====================================================
  // BẢN ĐỒ
  // =====================================================

  function initMap() {
    const mapElement = $("gpsMap");
    if (!mapElement) return;

    if (!window.L) {
      mapElement.textContent =
        "Không tải được thư viện bản đồ. Kiểm tra kết nối Internet hoặc CDN Leaflet.";

      setStatus("Không tải được bản đồ", "error");
      return;
    }

    state.map = L.map(mapElement, {
      scrollWheelZoom: true,
    }).setView([16, 106], 5);

    L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
      maxZoom: 19,
      attribution:
        '&copy; <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noopener">OpenStreetMap</a> contributors',
    }).addTo(state.map);

    state.eventLayer = L.layerGroup().addTo(state.map);

    window.setTimeout(() => {
      if (state.map) state.map.invalidateSize();
    }, 250);
  }

  function updateCurrentMarker(position) {
    if (!state.map || !window.L) return;

    const latlng = [position.latitude, position.longitude];

    const popup =
      `<strong>Vị trí hiện tại</strong><br>` +
      `${position.latitude.toFixed(6)}, ${position.longitude.toFixed(6)}<br>` +
      `Độ chính xác: ${
        position.accuracy == null
          ? "Không rõ"
          : `±${Math.round(position.accuracy)} m`
      }`;

    if (!state.currentMarker) {
      state.currentMarker = L.circleMarker(latlng, {
        radius: 9,
        color: "#ffffff",
        weight: 2,
        fillColor: "#16a34a",
        fillOpacity: 1,
      }).addTo(state.map);
    } else {
      state.currentMarker.setLatLng(latlng);
    }

    state.currentMarker.bindPopup(popup);

    if (state.accuracyCircle) {
      state.map.removeLayer(state.accuracyCircle);
    }

    if (Number.isFinite(position.accuracy) && position.accuracy > 0) {
      state.accuracyCircle = L.circle(latlng, {
        radius: position.accuracy,
        color: "#16a34a",
        weight: 1,
        fillColor: "#16a34a",
        fillOpacity: 0.1,
      }).addTo(state.map);
    }

    state.map.setView(latlng, Math.max(state.map.getZoom(), 16));

    if ($("gpsZoomCurrentBtn")) {
      $("gpsZoomCurrentBtn").disabled = false;
    }
  }

  // =====================================================
  // LẤY VÀ GỬI VỊ TRÍ
  // =====================================================

  function showPosition(position, options = {}) {
    const c = position.coords;

    state.latest = {
      latitude: c.latitude,
      longitude: c.longitude,
      accuracy: Number.isFinite(c.accuracy) ? c.accuracy : null,
    };

    if ($("gpsLat")) {
      $("gpsLat").textContent = c.latitude.toFixed(6);
    }

    if ($("gpsLon")) {
      $("gpsLon").textContent = c.longitude.toFixed(6);
    }

    if ($("gpsAccuracy")) {
      $("gpsAccuracy").textContent = Number.isFinite(c.accuracy)
        ? `± ${Math.round(c.accuracy)} m`
        : "Không rõ";
    }

    if ($("gpsUpdated")) {
      $("gpsUpdated").textContent = new Date().toLocaleTimeString("vi-VN");
    }

    const link = $("gpsMapLink");

    if (link) {
      link.href =
        `https://www.openstreetmap.org/?mlat=${encodeURIComponent(
          c.latitude
        )}` +
        `&mlon=${encodeURIComponent(c.longitude)}` +
        `#map=17/${encodeURIComponent(c.latitude)}/${encodeURIComponent(
          c.longitude
        )}`;

      link.hidden = false;
    }

    updateCurrentMarker(state.latest);

    // Chỉ gửi vị trí tối đa một lần mỗi 10 giây.
    // Có thể tắt đồng bộ tự động khi cần gửi lần đầu.
    if (options.send !== false) {
      const now = Date.now();

      if (now - state.lastSentAt >= 10000) {
        state.lastSentAt = now;

        sendLatestPosition(state.latest).catch((error) => {
          console.warn("GPS sync:", error);
        });
      }
    }
  }

  async function sendLatestPosition(position) {
    const response = await fetch("/api/features/gps/location", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify(position),
      cache: "no-store",
    });

    const data = await response.json().catch(() => ({}));

    if (!response.ok || !data.success) {
      throw new Error(data.message || `HTTP ${response.status}`);
    }

    return data;
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
        enableHighAccuracy: true,
        maximumAge: 10000,
        timeout: 25000,
      });
    });
  }

  // =====================================================
  // BẬT GPS
  // =====================================================

  async function startGps() {
    if (state.active || state.starting) return;

    if (!navigator.geolocation) {
      setStatus("Trình duyệt không hỗ trợ GPS", "error");
      return;
    }

    const generation = ++state.generation;

    state.starting = true;
    setGpsButtons();

    setStatus("Camera đã bật · Đang lấy vị trí GPS...");

    try {
      // Bước 1: Lấy vị trí đầu tiên.
      const position = await requestOnePosition();

      // Nếu camera đã tắt trong lúc chờ GPS thì dừng.
      if (generation !== state.generation) return;

      // Bước 2: Hiển thị vị trí lên bản đồ.
      showPosition(position, { send: false });

      // Bước 3: Gửi vị trí đầu tiên lên Flask.
      await sendLatestPosition(state.latest);

      if (generation !== state.generation) return;

      state.starting = false;
      state.active = true;

      setStatus("GPS đang hoạt động", "on");
      setGpsButtons();

      // Bước 4: Theo dõi vị trí liên tục.
      state.watchId = navigator.geolocation.watchPosition(
        (p) => {
          if (!state.active) return;

          showPosition(p);
          setStatus("GPS đang hoạt động", "on");
        },
        handlePositionError,
        {
          enableHighAccuracy: true,
          maximumAge: 10000,
          timeout: 25000,
        }
      );

      // Bước 5: Làm mới vị trí mỗi 30 giây.
      state.refreshTimer = window.setInterval(() => {
        if (!state.active) return;

        navigator.geolocation.getCurrentPosition(
          (p) => {
            if (!state.active) return;
            showPosition(p);
          },
          handlePositionError,
          {
            enableHighAccuracy: true,
            maximumAge: 15000,
            timeout: 20000,
          }
        );
      }, 30000);

      await loadGpsEvents();

      console.log("DRIVEGUARD: GPS đã tự động bật theo camera.");
    } catch (error) {
      if (generation !== state.generation) return;

      if (typeof error.code === "number") {
        handlePositionError(error);
      } else {
        setStatus(error.message || "Không lấy được vị trí GPS.", "error");
      }

      state.starting = false;
      state.active = false;
      setGpsButtons();

      console.warn("DRIVEGUARD GPS:", error);
    }
  }

  // =====================================================
  // TẮT GPS
  // =====================================================

  async function stopGps() {
    // Hủy mọi thao tác GPS đang chờ.
    state.generation++;

    state.starting = false;
    state.active = false;

    if (state.watchId !== null) {
      navigator.geolocation.clearWatch(state.watchId);
      state.watchId = null;
    }

    if (state.refreshTimer !== null) {
      window.clearInterval(state.refreshTimer);
      state.refreshTimer = null;
    }

    // Xóa vị trí hiện tại trên server.
    try {
      await fetch("/api/features/gps/location", {
        method: "DELETE",
        cache: "no-store",
      });
    } catch (error) {
      console.warn("Không xóa được vị trí hiện tại:", error);
    }

    state.latest = null;
    state.lastSentAt = 0;

    if ($("gpsLat")) $("gpsLat").textContent = "--";
    if ($("gpsLon")) $("gpsLon").textContent = "--";
    if ($("gpsAccuracy")) $("gpsAccuracy").textContent = "--";
    if ($("gpsUpdated")) $("gpsUpdated").textContent = "--";

    if ($("gpsMapLink")) {
      $("gpsMapLink").hidden = true;
    }

    if ($("gpsZoomCurrentBtn")) {
      $("gpsZoomCurrentBtn").disabled = true;
    }

    if (state.currentMarker && state.map) {
      state.map.removeLayer(state.currentMarker);
    }

    if (state.accuracyCircle && state.map) {
      state.map.removeLayer(state.accuracyCircle);
    }

    state.currentMarker = null;
    state.accuracyCircle = null;

    setStatus("GPS đang tắt");
    setGpsButtons();

    console.log("DRIVEGUARD: GPS đã được tắt.");
  }

  // =====================================================
  // LỊCH SỬ VỊ TRÍ CẢNH BÁO
  // =====================================================

  function zoomToPoint(latitude, longitude, marker) {
    if (!state.map) return;

    state.map.setView([latitude, longitude], 17);

    if (marker) marker.openPopup();
  }

  async function loadGpsEvents() {
    const container = $("gpsEventsList");
    if (!container) return;

    try {
      const response = await fetch("/api/features/gps/events?limit=50", {
        cache: "no-store",
      });

      const data = await response.json();

      if (!response.ok || !data.success) {
        throw new Error(data.message || "Không tải được GPS events");
      }

      container.replaceChildren();

      if (state.eventLayer) {
        state.eventLayer.clearLayers();
      }

      if (!data.events || !data.events.length) {
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

        if (!Number.isFinite(lat) || !Number.isFinite(lon)) {
          return;
        }

        let marker = null;

        if (state.map && state.eventLayer) {
          marker = L.circleMarker([lat, lon], {
            radius: 7,
            color: "#ffffff",
            weight: 2,
            fillColor: "#ef4444",
            fillOpacity: 0.95,
          });

          marker.bindPopup(
            `<strong>${escapeHtml(event.event_type || "ALERT")} · #${escapeHtml(
              event.alert_rowid
            )}</strong>` +
              `<br>${escapeHtml(formatTime(event.created_at))}` +
              `<br>${lat.toFixed(6)}, ${lon.toFixed(6)}` +
              `<br>Độ chính xác: ±${Math.round(
                Number(event.accuracy_m) || 0
              )} m`
          );

          marker.addTo(state.eventLayer);
          validPoints.push([lat, lon]);
        }

        const row = document.createElement("div");
        row.className = "gps-event-row";

        const info = document.createElement("div");

        const title = document.createElement("strong");
        title.textContent = `${event.event_type || "ALERT"} · #${
          event.alert_rowid
        }`;

        const meta = document.createElement("span");
        meta.textContent =
          `${formatTime(event.created_at)} · ` +
          `${lat.toFixed(6)}, ${lon.toFixed(6)} · ` +
          `±${Math.round(Number(event.accuracy_m) || 0)} m`;

        info.append(title, meta);

        const button = document.createElement("button");
        button.type = "button";
        button.className = "gps-text-btn gps-show-event-btn";
        button.textContent = "Xem trên bản đồ";

        button.addEventListener("click", () => {
          zoomToPoint(lat, lon, marker);
        });

        row.append(info, button);
        container.appendChild(row);
      });

      if (validPoints.length && !state.currentMarker && state.map) {
        if (validPoints.length === 1) {
          state.map.setView(validPoints[0], 16);
        } else {
          state.map.fitBounds(L.latLngBounds(validPoints).pad(0.15), {
            maxZoom: 16,
          });
        }
      }
    } catch (error) {
      container.textContent =
        "Không tải được danh sách vị trí cảnh báo: " + error.message;
    }
  }

  // =====================================================
  // ĐỒNG BỘ CAMERA VỚI GPS
  // =====================================================

  function bindCameraEvents() {
    const cameraFeed = $("cameraFeed");
    const stopCameraBtn = $("stopBtn");

    if (cameraFeed) {
      // Chỉ tự bật GPS khi camera đã tải được hình ảnh.
      cameraFeed.addEventListener("load", () => {
        if (!cameraFeed.getAttribute("src")) return;

        console.log("DRIVEGUARD: Camera đã có hình ảnh. Tự động bật GPS.");

        startGps();
      });

      // Nếu không tải được camera thì không giữ GPS hoạt động.
      cameraFeed.addEventListener("error", () => {
        if (!state.active && !state.starting) return;

        console.warn("DRIVEGUARD: Camera bị lỗi. Tự động tắt GPS.");

        stopGps();
      });
    }

    if (stopCameraBtn) {
      // Khi người dùng nhấn Tắt camera, dừng GPS ngay.
      stopCameraBtn.addEventListener("click", () => {
        console.log("DRIVEGUARD: Người dùng tắt camera. Tự động tắt GPS.");

        stopGps();
      });
    }
  }

  // =====================================================
  // KHỞI TẠO
  // =====================================================

  document.addEventListener("DOMContentLoaded", () => {
    if (!$("gpsPanel")) return;

    initMap();
    bindCameraEvents();

    if ($("gpsStartBtn")) {
      $("gpsStartBtn").addEventListener("click", startGps);
    }

    if ($("gpsStopBtn")) {
      $("gpsStopBtn").addEventListener("click", stopGps);
    }

    if ($("gpsRefreshBtn")) {
      $("gpsRefreshBtn").addEventListener("click", async () => {
        try {
          const position = await requestOnePosition();

          showPosition(position, { send: false });
          await sendLatestPosition(state.latest);

          state.lastSentAt = Date.now();

          setStatus("Đã cập nhật vị trí", "on");
        } catch (error) {
          if (error && typeof error.code === "number") {
            handlePositionError(error);
          } else {
            setStatus(error.message, "error");
          }
        }
      });
    }

    if ($("gpsEventsRefreshBtn")) {
      $("gpsEventsRefreshBtn").addEventListener("click", loadGpsEvents);
    }

    if ($("gpsZoomCurrentBtn")) {
      $("gpsZoomCurrentBtn").addEventListener("click", () => {
        if (state.latest) {
          zoomToPoint(
            state.latest.latitude,
            state.latest.longitude,
            state.currentMarker
          );
        }
      });
    }

    loadGpsEvents();
    setGpsButtons();

    window.setTimeout(() => {
      if (state.map) state.map.invalidateSize();
    }, 400);
  });

  // Dọn tài nguyên theo dõi khi rời trang.
  window.addEventListener("beforeunload", () => {
    state.generation++;

    if (state.watchId !== null) {
      navigator.geolocation.clearWatch(state.watchId);
    }

    if (state.refreshTimer !== null) {
      window.clearInterval(state.refreshTimer);
    }
  });
})();
