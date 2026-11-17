# DRIVEGUARD AI - DRIVER DROWSINESS DETECTION

1. GIOI THIEU

---

DriveGuard AI la he thong nguyen mau phat hien dau hieu ngu gat va ngay cua tai xe o to bang webcam, xu ly anh va Deep Learning. He thong duoc xay dung bang Python, Flask va SQLite, phuc vu muc dich hoc tap, nghien cuu va demo do an.

2. CONG NGHE SU DUNG

---

- Python
- TensorFlow / Keras
- CNN V3
- MediaPipe FaceMesh
- OpenCV
- Flask
- SQLite
- HTML, CSS, JavaScript
- Chart.js (neu duoc su dung trong giao dien dashboard)

3. CHUC NANG CHINH

---

- Doc hinh anh tu webcam va phat hien khuon mat bang MediaPipe FaceMesh.
- Trich xuat vung mat (ROI), chuan hoa anh va phan loai trang thai mat bang CNN V3.
- Ket hop xac suat CNN voi chi so Eye Aspect Ratio (EAR) de ho tro phat hien mat nham keo dai.
- Su dung EAR lam nhanh ho tro/du phong theo logic duoc cau hinh trong camera_stream.py.
- Tinh Mouth Aspect Ratio (MAR) de ho tro phat hien hanh vi ngay.
- Phat am thanh canh bao khi dieu kien su kien duoc duy tri du thoi gian.
- Luu lich su su kien DROWSY/YAWNING vao SQLite.
- Hien thi camera, chi so, thong ke va lich su tren Dashboard Flask.
- Ho tro loc lich su, phan trang va xuat du lieu CSV.
- Trang giam sat nang cao co ho so tai xe, hieu chinh nguong EAR va hien thi mot so chi so hieu suat AI nhu FPS/thoi gian xu ly (neu cac module nang cao duoc kem trong ban ma nguon ban giao).

4. CAU TRUC THU MUC QUAN TRONG

---

- app.py: ung dung Flask va cac route/API.
- camera_stream.py: doc webcam, FaceMesh, CNN V3, EAR/MAR va logic canh bao.
- database.py: khoi tao va thao tac voi SQLite.
- models/eye_cnn_v3.keras: mo hinh CNN V3 duoc su dung khi chay camera.
- templates/: cac trang HTML.
- static/: CSS, JavaScript va tai nguyen giao dien.
- requirements.txt: danh sach thu vien Python.
- start.bat: tep ho tro khoi dong tren Windows.
- drowsiness.db: database chinh (neu duoc cung cap cung bo ma nguon).

5. YEU CAU MOI TRUONG

---

- Windows 10/11.
- Webcam hoat dong va duoc Windows cho phep truy cap.
- Python phu hop voi cac phien ban thu vien trong requirements.txt.
- Cac phien ban da duoc su dung/kiem tra trong moi truong phat trien cua nhom: OpenCV 4.11.0, MediaPipe 0.10.21, TensorFlow 2.18.1. Can uu tien requirements.txt cua ban ban giao va khong nang cap dong loat neu chua kiem tra tuong thich.
- Phai co tep models/eye_cnn_v3.keras. Neu thieu tep mo hinh, chuc nang CNN se khong the khoi tao.

6. CAI DAT TREN MAY TINH MOI

---

Mo PowerShell tai thu muc giai nen du an, sau do chay:

    python --version
    python -m venv .venv
    .\.venv\Scripts\Activate.ps1
    python -m pip install --upgrade pip
    pip install -r requirements.txt

Neu PowerShell chan kich hoat virtual environment, chay lenh sau trong cua so PowerShell hien tai roi kich hoat lai:

    Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
    .\.venv\Scripts\Activate.ps1

Kiem tra cu phap cac tep chinh:

    python -m py_compile .\app.py .\camera_stream.py .\database.py

Luu y: phien ban Python can phu hop voi cac goi da khai bao trong requirements.txt. Neu cai dat tren may moi gap loi TensorFlow/MediaPipe, kiem tra lai phien ban Python va cac phien ban thu vien thay vi tu y nang cap.

7. KHOI CHAY UNG DUNG TREN WINDOWS

---

Cach 1 - Khoi dong nhanh:

- Nhap dup tep start.bat.
- Cho den khi Flask khoi dong thanh cong trong cua so CMD/PowerShell.
- Mo trinh duyet tai dia chi:
  http://127.0.0.1:5000

Cach 2 - Chay bang Terminal:

    .\.venv\Scripts\Activate.ps1
    python app.py

Sau do mo:

    http://127.0.0.1:5000

Trang giam sat nang cao (neu co trong ban ban giao):

    http://127.0.0.1:5000/advanced

Khong dong cua so CMD/PowerShell dang chay Flask trong khi dang su dung ung dung. De dung he thong, tat camera tren giao dien va nhan Ctrl+C trong cua so chay Flask.

8. THONG SO PHAT HIEN THAM KHAO

---

- CNN_THRESHOLD: 0.052847 (nguong P(open_eyes) dang duoc cau hinh trong camera_stream.py).
- EAR_THRESHOLD co so: 0.21 (nguong mac dinh; neu bat tinh nang hieu chinh tai xe, nguong ap dung co the thay doi theo ho so).
- DROWSY_SECONDS: 2.0 giay.
- EAR_FALLBACK_SECONDS: 3.0 giay.
- MAR_THRESHOLD: 0.50.
- YAWN_SECONDS: 1.5 giay.

Giai thich nguong CNN:

- He thong so sanh P(open_eyes) voi CNN_THRESHOLD.
- Neu P(open_eyes) nho hon nguong, nhanh CNN xem trang thai mat la closed_eyes; nguoc lai la open_eyes.
- Nguong 0.500 chi la nguong doi chieu trong mot so lan danh gia, KHONG phai nguong dang cau hinh cho luong camera hien tai.
- Cac nguong tren la tham so thuc nghiem cua du an, khong phai gia tri phu hop cho moi nguoi, webcam hay dieu kien anh sang.

9. DATABASE VA KHOI PHUC DU LIEU

---

- Du an su dung SQLite. Tep database chinh thuong co ten drowsiness.db.
- Ban sao luu database duoc nop rieng trong thu muc 03_Database, vi du drowsiness_backup.db.
- De khoi phuc ban sao luu: dung ung dung Flask; sao luu tep drowsiness.db hien tai neu co; copy drowsiness_backup.db vao thu muc goc du an va doi ten thanh drowsiness.db.
- Khong ghi de database dang co neu chua can khoi phuc, vi thao tac nay co the thay the lich su canh bao hien tai.

10. LUU Y KHI SU DUNG

---

- Dat webcam ngang tam mat, bao dam khuon mat nam trong khung hinh va du anh sang.
- Dong cac ung dung khac dang su dung webcam neu camera khong mo duoc.
- Khi demo tinh huong nham mat/ngap, thuc hien khi dang ngoi thu nghiem an toan; khong thu nghiem trong khi dang lai xe.
- Day la nguyen mau hoc tap/nghien cuu, chua duoc chung nhan de thay the thiet bi an toan tren oto hoac su chu y cua nguoi lai xe.
- Neu luu anh minh chung, can thong bao va co su dong y cua nguoi duoc ghi hinh; khong chia se anh khuon mat cong khai neu khong co muc dich va su cho phep phu hop.

Neu gap loi khi cai dat/chay, kiem tra terminal Flask, duong dan tep mo hinh, webcam, requirements.txt va quyen truy cap camera cua Windows.
