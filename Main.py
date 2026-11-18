# -*- coding: utf-8 -*-
"""
UPDATE BIN SERVICE
Cập nhật hàng loạt thư mục 'bin' của các service iPOS từ một thư mục bin_goc.

- Chọn nhiều thư mục gốc, quét song song (mỗi thư mục gốc 1 luồng).
- Ghi đè chạy nền, hiển thị tiến trình theo từng thư mục + nhật ký (log).
- Mỗi bin được sao lưu trước khi ghi đè; lỗi giữa chừng tự khôi phục từ bản sao lưu.

Giữ tương thích Python 3.8 (build cho Windows 7 / Server 2008).
"""
import json
import os
import queue
import shutil
import stat
import sys
import tempfile
import threading
import time
import traceback
import tkinter as tk
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from tkinter import filedialog, messagebox, ttk

TEN_BIN = "bin"
TIEN_TO_BACKUP = "bin_backup_"
SO_LUONG_QUET_SONG_SONG = 8          # số thư mục gốc quét đồng thời tối đa
CHU_KY_CAP_NHAT_GUI_MS = 100         # chu kỳ giao diện đọc hàng đợi tiến độ
CHU_KY_BAO_TIEN_DO_GIAY = 0.15       # giới hạn tần suất gửi tiến độ từ luồng nền
TEN_FILE_CAU_HINH = "update_bin_config.json"

# Chế độ sao lưu khi ghi đè
BACKUP_XOA_KHI_OK = "xoa_khi_ok"      # sao lưu -> thành công thì xóa, lỗi thì giữ (mặc định)
BACKUP_GIU_TAT_CA = "giu_tat_ca"      # giữ lại mọi bản sao lưu
BACKUP_KHONG = "khong"                # không sao lưu: nhanh, nhưng lỗi giữa chừng KHÔNG khôi phục được
CAC_CHE_DO_BACKUP = [
    (BACKUP_XOA_KHI_OK, "Xóa backup khi OK, lỗi thì giữ (khuyên dùng)"),
    (BACKUP_GIU_TAT_CA, "Giữ tất cả backup"),
    (BACKUP_KHONG, "Không sao lưu (rủi ro)"),
]


class DaHuy(Exception):
    """Người dùng bấm Dừng."""


class LoiGhiDe(Exception):
    """Lỗi khi ghi đè một thư mục bin (thông báo đã mô tả tình trạng khôi phục)."""


# =============================================================================
# Tiện ích chung
# =============================================================================
def thu_muc_ung_dung():
    """Thư mục chứa file EXE (khi đóng gói) hoặc file Main.py."""
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


def chuan_hoa(duong_dan):
    return os.path.normcase(os.path.normpath(os.path.abspath(duong_dan)))


def nam_trong(con, cha):
    """True nếu 'con' trùng hoặc nằm bên trong 'cha'."""
    con, cha = chuan_hoa(con), chuan_hoa(cha)
    return con == cha or con.startswith(cha.rstrip(os.sep) + os.sep)


def loai_bo_thu_muc_long_nhau(ds_thu_muc):
    """Bỏ trùng và bỏ các thư mục nằm trong một thư mục khác của danh sách."""
    ket_qua = []
    for p in sorted(set(ds_thu_muc), key=lambda x: len(chuan_hoa(x))):
        if not any(nam_trong(p, q) for q in ket_qua):
            ket_qua.append(p)
    return ket_qua


def tach_danh_sach(chuoi):
    """Tách chuỗi nhiều giá trị ngăn cách bởi ';' ',' hoặc xuống dòng."""
    for ky_tu in (",", "\n", "\r"):
        chuoi = chuoi.replace(ky_tu, ";")
    return [t.strip().strip('"') for t in chuoi.split(";") if t.strip().strip('"')]


def ten_khop(ten, ds_tien_to):
    ten = ten.lower()
    return any(ten.startswith(t.lower()) for t in ds_tien_to)


def dem_file(thu_muc):
    tong = 0
    for _, _, files in os.walk(thu_muc):
        tong += len(files)
    return tong


def doc_cau_hinh():
    try:
        with open(os.path.join(thu_muc_ung_dung(), TEN_FILE_CAU_HINH), "r", encoding="utf-8") as f:
            du_lieu = json.load(f)
        return du_lieu if isinstance(du_lieu, dict) else {}
    except Exception:
        return {}


def ghi_cau_hinh(du_lieu):
    try:
        with open(os.path.join(thu_muc_ung_dung(), TEN_FILE_CAU_HINH), "w", encoding="utf-8") as f:
            json.dump(du_lieu, f, ensure_ascii=False, indent=2)
    except Exception:
        pass  # thư mục chỉ đọc -> bỏ qua, không ảnh hưởng chức năng chính


class BoDemTienDo:
    """Đếm tiến độ và gọi callback có giới hạn tần suất để không làm nghẽn giao diện."""

    def __init__(self, callback, tong):
        self.callback = callback
        self.tong = tong
        self.da_xong = 0
        self._lan_cuoi = 0.0
        callback(0, tong)

    def tang(self, so=1):
        self.da_xong += so
        bay_gio = time.monotonic()
        if self.da_xong >= self.tong or bay_gio - self._lan_cuoi >= CHU_KY_BAO_TIEN_DO_GIAY:
            self._lan_cuoi = bay_gio
            self.callback(self.da_xong, self.tong)


# =============================================================================
# Quét thư mục (chạy ở luồng nền)
# =============================================================================
def quet_mot_thu_muc_goc(thu_muc_goc, ds_tien_to, su_kien_huy, bao_cao):
    """
    Duyệt thu_muc_goc, tìm các thư mục có tên bắt đầu bằng một trong ds_tien_to
    (không phân biệt hoa thường) và có thư mục con 'bin'.
    bao_cao(loai, *du_lieu) dùng để gửi tiến độ về giao diện.
    """
    ket_qua = []
    so_da_duyet = 0
    lan_cuoi = 0.0

    def kiem_tra(thu_muc):
        if os.path.isdir(os.path.join(thu_muc, TEN_BIN)):
            ket_qua.append(thu_muc)
            bao_cao("tim_thay", thu_muc)

    def khi_loi(err):
        bao_cao("log", "CANH_BAO", "Không đọc được {}: {}".format(err.filename, err.strerror))

    # Bản thân thư mục gốc cũng có thể chính là thư mục service
    if ten_khop(os.path.basename(os.path.normpath(thu_muc_goc)), ds_tien_to):
        kiem_tra(thu_muc_goc)

    for root, dirs, _ in os.walk(thu_muc_goc, onerror=khi_loi):
        if su_kien_huy.is_set():
            raise DaHuy()
        so_da_duyet += 1
        for d in dirs:
            if ten_khop(d, ds_tien_to):
                kiem_tra(os.path.join(root, d))
        # Không đi sâu vào bin / bin_backup_*: không chứa service, lại rất nhiều file
        dirs[:] = [d for d in dirs
                   if d.lower() != TEN_BIN and not d.lower().startswith(TIEN_TO_BACKUP)]
        bay_gio = time.monotonic()
        if bay_gio - lan_cuoi >= CHU_KY_BAO_TIEN_DO_GIAY:
            lan_cuoi = bay_gio
            bao_cao("dang_quet", thu_muc_goc, root, so_da_duyet)

    bao_cao("dang_quet", thu_muc_goc, None, so_da_duyet)
    bao_cao("log", "INFO", "Quét xong {} — duyệt {} thư mục, tìm thấy {}.".format(
        thu_muc_goc, so_da_duyet, len(ket_qua)))
    return ket_qua


def quet_nhieu_thu_muc(ds_thu_muc_goc, ds_tien_to, su_kien_huy, bao_cao):
    """Quét song song nhiều thư mục gốc, trả về danh sách thư mục service (đã bỏ trùng, sắp xếp)."""
    ds_goc = loai_bo_thu_muc_long_nhau(ds_thu_muc_goc)
    if len(ds_goc) < len(set(ds_thu_muc_goc)):
        bao_cao("log", "INFO", "Đã bỏ {} thư mục gốc trùng/nằm trong thư mục gốc khác.".format(
            len(set(ds_thu_muc_goc)) - len(ds_goc)))

    tat_ca = {}
    so_luong = max(1, min(SO_LUONG_QUET_SONG_SONG, len(ds_goc)))
    with ThreadPoolExecutor(max_workers=so_luong) as pool:
        cong_viec = [(g, pool.submit(quet_mot_thu_muc_goc, g, ds_tien_to, su_kien_huy, bao_cao))
                     for g in ds_goc]
        for goc, f in cong_viec:
            try:
                for p in f.result():
                    tat_ca.setdefault(chuan_hoa(p), p)
            except DaHuy:
                pass
            except Exception as e:
                bao_cao("log", "LOI", "Quét {} thất bại: {}".format(goc, e))

    if su_kien_huy.is_set():
        raise DaHuy()
    return sorted(tat_ca.values(), key=lambda p: p.lower())


# =============================================================================
# Sao lưu / ghi đè / khôi phục (chạy ở luồng nền)
# =============================================================================
def _bo_chi_doc(func, path, _exc_info):
    """onerror cho rmtree: bỏ thuộc tính read-only (Windows) rồi thử lại."""
    os.chmod(path, stat.S_IWRITE)
    func(path)


def _xoa_mot_muc(duong_dan):
    if os.path.isdir(duong_dan) and not os.path.islink(duong_dan):
        shutil.rmtree(duong_dan, onerror=_bo_chi_doc)
    else:
        try:
            os.unlink(duong_dan)
        except PermissionError:
            os.chmod(duong_dan, stat.S_IWRITE)
            os.unlink(duong_dan)


def xoa_noi_dung(thu_muc, bo_qua_loi=False):
    """Xóa toàn bộ nội dung bên trong thu_muc (giữ lại chính thu_muc). Trả về số mục lỗi."""
    so_loi = 0
    for item in os.listdir(thu_muc):
        try:
            _xoa_mot_muc(os.path.join(thu_muc, item))
        except Exception:
            if not bo_qua_loi:
                raise
            so_loi += 1
    return so_loi


def _giong_nhau(a, b):
    try:
        sa, sb = os.stat(a), os.stat(b)
        return sa.st_size == sb.st_size and int(sa.st_mtime) == int(sb.st_mtime)
    except OSError:
        return False


def sao_chep_noi_dung(nguon, dich, bo_dem=None, bo_qua_loi=False):
    """Sao chép toàn bộ nội dung nguon vào dich (tạo dich nếu chưa có). Trả về số file lỗi."""
    so_loi = 0
    for root, _, files in os.walk(nguon):
        rel = os.path.relpath(root, nguon)
        dich_root = dich if rel == os.curdir else os.path.join(dich, rel)
        os.makedirs(dich_root, exist_ok=True)
        for f in files:
            src, dst = os.path.join(root, f), os.path.join(dich_root, f)
            try:
                shutil.copy2(src, dst)
            except Exception:
                if not bo_qua_loi:
                    raise
                # File đang bị khóa nhưng vẫn là bản gốc (cùng kích thước + thời gian) -> coi như OK
                if not _giong_nhau(src, dst):
                    so_loi += 1
            if bo_dem:
                bo_dem.tang()
    return so_loi


def tao_duong_dan_backup(thu_muc_cha, moc_thoi_gian):
    duong_dan = os.path.join(thu_muc_cha, TIEN_TO_BACKUP + moc_thoi_gian)
    i = 1
    while os.path.exists(duong_dan):
        duong_dan = os.path.join(thu_muc_cha, "{}{}_{}".format(TIEN_TO_BACKUP, moc_thoi_gian, i))
        i += 1
    return duong_dan


def khoi_phuc_tu_backup(backup, bin_dich):
    """Đưa bin_dich về đúng nội dung bản sao lưu. Trả về số file không khôi phục được."""
    xoa_noi_dung(bin_dich, bo_qua_loi=True)
    return sao_chep_noi_dung(backup, bin_dich, bo_qua_loi=True)


def ghi_de_mot_thu_muc(bin_goc, thu_muc_cha, moc_thoi_gian, tong_file_moi, bao_cao_buoc,
                       che_do_backup=BACKUP_XOA_KHI_OK):
    """
    [Sao lưu] -> xóa bin cũ -> copy từ bin_goc -> [xóa bản sao lưu nếu chế độ xoa_khi_ok].
    Lỗi giữa chừng: có sao lưu thì tự khôi phục và GIỮ bản sao lưu; không sao lưu thì báo lỗi.
    bao_cao_buoc(ten_buoc, da_xong, tong). Trả về chuỗi mô tả kết quả về bản sao lưu.
    """
    bin_dich = os.path.join(thu_muc_cha, TEN_BIN)
    if nam_trong(bin_goc, bin_dich) or nam_trong(bin_dich, bin_goc):
        raise LoiGhiDe("Bỏ qua: trùng/lồng với thư mục bin_goc.")

    # 1. Sao lưu
    backup = None
    if che_do_backup != BACKUP_KHONG:
        backup = tao_duong_dan_backup(thu_muc_cha, moc_thoi_gian)
        try:
            sao_chep_noi_dung(bin_dich, backup,
                              BoDemTienDo(lambda a, b: bao_cao_buoc("Sao lưu", a, b), dem_file(bin_dich)))
        except Exception as e:
            # Dọn bản sao lưu dở dang, bin chưa bị đụng tới
            shutil.rmtree(backup, ignore_errors=True)
            raise LoiGhiDe("Sao lưu thất bại, bin CHƯA bị thay đổi: {}".format(e))

    # 2 + 3. Xóa bin cũ và copy bin mới
    try:
        bao_cao_buoc("Xóa bin cũ", 0, 0)
        xoa_noi_dung(bin_dich)
        sao_chep_noi_dung(bin_goc, bin_dich,
                          BoDemTienDo(lambda a, b: bao_cao_buoc("Copy", a, b), tong_file_moi))
    except Exception as e:
        if backup is None:
            raise LoiGhiDe("{} → KHÔNG có sao lưu, bin có thể đang DỞ DANG, cần kiểm tra tay!".format(e))
        bao_cao_buoc("Khôi phục", 0, 0)
        so_loi = khoi_phuc_tu_backup(backup, bin_dich)
        if so_loi == 0:
            raise LoiGhiDe("{} → ĐÃ KHÔI PHỤC bin cũ, giữ backup: {}".format(
                e, os.path.basename(backup)))
        raise LoiGhiDe("{} → khôi phục KHÔNG trọn vẹn ({} file lỗi), kiểm tra tay: {}".format(
            e, so_loi, backup))

    # 4. Thành công
    if backup is None:
        return "không sao lưu"
    if che_do_backup == BACKUP_XOA_KHI_OK:
        bao_cao_buoc("Xóa backup", 0, 0)
        try:
            shutil.rmtree(backup, onerror=_bo_chi_doc)
            return "đã xóa backup"
        except Exception as e:
            return "KHÔNG xóa được backup {} ({})".format(os.path.basename(backup), e)
    return "Backup: {}".format(os.path.basename(backup))


def chay_ghi_de(bin_goc, ds_thu_muc, che_do_backup, su_kien_huy, bao_cao):
    moc = datetime.now().strftime("%Y%m%d_%H%M%S")
    tong_file_moi = dem_file(bin_goc)
    bao_cao("log", "INFO", "Bắt đầu ghi đè {} thư mục từ {} ({} file). Chế độ sao lưu: {}".format(
        len(ds_thu_muc), bin_goc, tong_file_moi, dict(CAC_CHE_DO_BACKUP)[che_do_backup]))
    thanh_cong = loi = 0
    for i, thu_muc in enumerate(ds_thu_muc):
        if su_kien_huy.is_set():
            break
        bao_cao("bat_dau", i, thu_muc)
        try:
            ket_qua_backup = ghi_de_mot_thu_muc(
                bin_goc, thu_muc, moc, tong_file_moi,
                lambda buoc, a, b, i=i: bao_cao("buoc", i, buoc, a, b),
                che_do_backup)
            thanh_cong += 1
            bao_cao("xong", i, True, ket_qua_backup)
        except Exception as e:
            loi += 1
            bao_cao("xong", i, False, str(e))
    bo_qua = len(ds_thu_muc) - thanh_cong - loi
    bao_cao("ket_thuc_ghi_de", thanh_cong, loi, bo_qua)


# =============================================================================
# Giao diện
# =============================================================================
def _sua_mau_treeview(style):
    """Sửa lỗi Tk 8.6.9 (Python 3.8) không hiển thị màu theo tag trong Treeview."""
    def loc(option):
        return [e for e in style.map("Treeview", query_opt=option)
                if e[:2] != ("!disabled", "!selected")]
    style.map("Treeview", foreground=loc("foreground"), background=loc("background"))


class UngDung:
    def __init__(self, root):
        self.root = root
        root.title("UPDATE BIN SERVICE")
        root.minsize(820, 600)

        self.hang_doi = queue.Queue()
        self.su_kien_huy = threading.Event()
        self.dang_chay = None           # None | "quet" | "ghi_de"
        self.dong_khi_xong = False
        self.ds_ket_qua = []            # danh sách thư mục service
        self.tien_do_quet = {}          # thư mục gốc -> số thư mục đã duyệt
        self.tong_ghi_de = 0
        self.so_goc_quet = 0
        self.thoi_diem_bat_dau = None
        self.duong_dan_log = None
        self.file_log = None

        self._tao_giao_dien()
        self._nap_cau_hinh()
        root.protocol("WM_DELETE_WINDOW", self.khi_dong_cua_so)
        root.after(CHU_KY_CAP_NHAT_GUI_MS, self._xu_ly_hang_doi)

    # ------------------------------------------------------------------ UI
    def _tao_giao_dien(self):
        style = ttk.Style(self.root)
        _sua_mau_treeview(style)

        khung = ttk.Frame(self.root, padding=8)
        khung.pack(fill="both", expand=True)
        khung.columnconfigure(0, weight=1)

        # --- bin_goc
        f_nguon = ttk.LabelFrame(khung, text="Thư mục bin_goc (bản bin mới)", padding=6)
        f_nguon.grid(row=0, column=0, sticky="ew")
        f_nguon.columnconfigure(0, weight=1)
        self.entry_bin_goc = ttk.Entry(f_nguon)
        self.entry_bin_goc.grid(row=0, column=0, sticky="ew", padx=(0, 5))
        ttk.Button(f_nguon, text="Chọn...", command=self.chon_bin_goc).grid(row=0, column=1)

        # --- Nhiều thư mục gốc
        f_goc = ttk.LabelFrame(
            khung, text="Thư mục gốc cần quét — chọn nhiều, quét song song (VD: C:\\iPOS.vn\\DB10012)",
            padding=6)
        f_goc.grid(row=1, column=0, sticky="ew", pady=(6, 0))
        f_goc.columnconfigure(0, weight=1)

        self.entry_them_goc = ttk.Entry(f_goc)
        self.entry_them_goc.grid(row=0, column=0, sticky="ew", padx=(0, 5))
        self.entry_them_goc.bind("<Return>", lambda _e: self.them_tu_o_nhap())
        ttk.Button(f_goc, text="Thêm đường dẫn", command=self.them_tu_o_nhap).grid(
            row=0, column=1, sticky="ew")

        f_lb = ttk.Frame(f_goc)
        f_lb.grid(row=1, column=0, sticky="nsew", pady=(5, 0), padx=(0, 5))
        f_lb.columnconfigure(0, weight=1)
        self.lb_goc = tk.Listbox(f_lb, height=5, selectmode="extended", activestyle="none")
        self.lb_goc.grid(row=0, column=0, sticky="nsew")
        sb = ttk.Scrollbar(f_lb, orient="vertical", command=self.lb_goc.yview)
        sb.grid(row=0, column=1, sticky="ns")
        self.lb_goc.configure(yscrollcommand=sb.set)
        self.lb_goc.bind("<Delete>", lambda _e: self.bo_goc_da_chon())

        f_nut_goc = ttk.Frame(f_goc)
        f_nut_goc.grid(row=1, column=1, sticky="n", pady=(5, 0))
        self.nut_goc = [
            ttk.Button(f_nut_goc, text="Thêm thư mục...", command=self.them_thu_muc_goc),
            ttk.Button(f_nut_goc, text="Thêm các thư mục con...", command=self.them_thu_muc_con),
            ttk.Button(f_nut_goc, text="Bỏ dòng đã chọn", command=self.bo_goc_da_chon),
            ttk.Button(f_nut_goc, text="Xóa hết", command=self.xoa_het_goc),
        ]
        for i, nut in enumerate(self.nut_goc):
            nut.grid(row=i, column=0, sticky="ew", pady=1)

        # --- Tên bắt đầu
        f_ten = ttk.Frame(khung)
        f_ten.grid(row=2, column=0, sticky="ew", pady=(6, 0))
        f_ten.columnconfigure(1, weight=1)
        ttk.Label(f_ten, text="Tên bắt đầu thư mục service (nhiều tên cách nhau bởi ;  VD: ACCService;POSService):"
                  ).grid(row=0, column=0, columnspan=2, sticky="w")
        self.entry_ten_bat_dau = ttk.Entry(f_ten)
        self.entry_ten_bat_dau.grid(row=1, column=0, columnspan=2, sticky="ew")
        self.entry_ten_bat_dau.bind("<Return>", lambda _e: self.tim_kiem())

        # --- Chế độ sao lưu
        f_bk = ttk.Frame(khung)
        f_bk.grid(row=3, column=0, sticky="ew", pady=(6, 0))
        ttk.Label(f_bk, text="Sao lưu bin cũ:").grid(row=0, column=0, sticky="w", padx=(0, 5))
        self.bien_che_do_backup = tk.StringVar(value=BACKUP_XOA_KHI_OK)
        self.nut_backup = []
        for cot, (gia_tri, nhan) in enumerate(CAC_CHE_DO_BACKUP, start=1):
            rb = ttk.Radiobutton(f_bk, text=nhan, value=gia_tri, variable=self.bien_che_do_backup)
            rb.grid(row=0, column=cot, sticky="w", padx=(0, 12))
            self.nut_backup.append(rb)

        # --- Nút chức năng
        f_nut = ttk.Frame(khung)
        f_nut.grid(row=10, column=0, pady=8)
        self.btn_tim = ttk.Button(f_nut, text="1. Tìm kiếm", width=18, command=self.tim_kiem)
        self.btn_ghi_de = ttk.Button(f_nut, text="2. Thực hiện ghi đè", width=20, command=self.ghi_de)
        self.btn_dung = ttk.Button(f_nut, text="Dừng", width=10, command=self.dung, state="disabled")
        self.btn_tim.grid(row=0, column=0, padx=4)
        self.btn_ghi_de.grid(row=0, column=1, padx=4)
        self.btn_dung.grid(row=0, column=2, padx=4)

        # --- Danh sách kết quả
        f_kq = ttk.LabelFrame(khung, text="Danh sách thư mục service", padding=6)
        f_kq.grid(row=11, column=0, sticky="nsew")
        f_kq.columnconfigure(0, weight=1)
        f_kq.rowconfigure(0, weight=1)
        khung.rowconfigure(11, weight=3)

        self.tree = ttk.Treeview(f_kq, columns=("stt", "duong_dan", "trang_thai"),
                                 show="headings", height=7, selectmode="extended")
        self.tree.heading("stt", text="#")
        self.tree.heading("duong_dan", text="Thư mục service")
        self.tree.heading("trang_thai", text="Trạng thái")
        self.tree.column("stt", width=40, stretch=False, anchor="center")
        self.tree.column("duong_dan", width=430)
        self.tree.column("trang_thai", width=300)
        self.tree.tag_configure("dang_chay", background="#dbeafe")
        self.tree.tag_configure("ok", foreground="#15803d")
        self.tree.tag_configure("loi", foreground="#b91c1c")
        self.tree.tag_configure("bo_qua", foreground="#6b7280")
        self.tree.grid(row=0, column=0, sticky="nsew")
        sb_tree = ttk.Scrollbar(f_kq, orient="vertical", command=self.tree.yview)
        sb_tree.grid(row=0, column=1, sticky="ns")
        self.tree.configure(yscrollcommand=sb_tree.set)
        self.tree.bind("<Double-1>", self.mo_thu_muc_dong)
        self.tree.bind("<Delete>", lambda _e: self.bo_dong_ket_qua())

        f_kq_duoi = ttk.Frame(f_kq)
        f_kq_duoi.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(4, 0))
        f_kq_duoi.columnconfigure(0, weight=1)
        self.lbl_so_luong = ttk.Label(f_kq_duoi, text="0 thư mục")
        self.lbl_so_luong.grid(row=0, column=0, sticky="w")
        self.btn_bo_dong = ttk.Button(f_kq_duoi, text="Bỏ dòng đã chọn khỏi danh sách",
                                      command=self.bo_dong_ket_qua)
        self.btn_bo_dong.grid(row=0, column=1)

        # --- Tiến trình
        f_td = ttk.LabelFrame(khung, text="Tiến trình", padding=6)
        f_td.grid(row=12, column=0, sticky="ew", pady=(6, 0))
        f_td.columnconfigure(1, weight=1)
        self.lbl_trang_thai = ttk.Label(f_td, text="Sẵn sàng.")
        self.lbl_trang_thai.grid(row=0, column=0, columnspan=3, sticky="w")
        ttk.Label(f_td, text="Tổng:").grid(row=1, column=0, sticky="w")
        self.pb_tong = ttk.Progressbar(f_td, mode="determinate")
        self.pb_tong.grid(row=1, column=1, sticky="ew", padx=5, pady=2)
        self.lbl_pt_tong = ttk.Label(f_td, text="", width=14)
        self.lbl_pt_tong.grid(row=1, column=2, sticky="w")
        ttk.Label(f_td, text="Hiện tại:").grid(row=2, column=0, sticky="w")
        self.pb_hien_tai = ttk.Progressbar(f_td, mode="determinate")
        self.pb_hien_tai.grid(row=2, column=1, sticky="ew", padx=5, pady=2)
        self.lbl_pt_hien_tai = ttk.Label(f_td, text="", width=14)
        self.lbl_pt_hien_tai.grid(row=2, column=2, sticky="w")
        self.lbl_chi_tiet = ttk.Label(f_td, text="")
        self.lbl_chi_tiet.grid(row=3, column=0, columnspan=3, sticky="w")

        # --- Nhật ký
        f_log = ttk.LabelFrame(khung, text="Nhật ký", padding=6)
        f_log.grid(row=13, column=0, sticky="nsew", pady=(6, 0))
        f_log.columnconfigure(0, weight=1)
        f_log.rowconfigure(0, weight=1)
        khung.rowconfigure(13, weight=2)
        self.txt_log = tk.Text(f_log, height=5, wrap="none", state="disabled")
        self.txt_log.grid(row=0, column=0, sticky="nsew")
        sb_log = ttk.Scrollbar(f_log, orient="vertical", command=self.txt_log.yview)
        sb_log.grid(row=0, column=1, sticky="ns")
        self.txt_log.configure(yscrollcommand=sb_log.set)
        self.txt_log.tag_configure("LOI", foreground="#b91c1c")
        self.txt_log.tag_configure("CANH_BAO", foreground="#b45309")
        self.txt_log.tag_configure("OK", foreground="#15803d")
        ttk.Button(f_log, text="Mở thư mục log", command=self.mo_thu_muc_log).grid(
            row=1, column=0, sticky="e", pady=(4, 0))

    # ------------------------------------------------------- cấu hình lưu
    def _nap_cau_hinh(self):
        ch = doc_cau_hinh()
        self.entry_bin_goc.insert(0, ch.get("bin_goc", ""))
        self.entry_ten_bat_dau.insert(0, ch.get("ten_bat_dau", ""))
        for p in ch.get("thu_muc_goc", []):
            self.lb_goc.insert("end", p)
        if ch.get("che_do_backup") in dict(CAC_CHE_DO_BACKUP):
            self.bien_che_do_backup.set(ch["che_do_backup"])

    def _luu_cau_hinh(self):
        ghi_cau_hinh({
            "bin_goc": self.entry_bin_goc.get().strip(),
            "ten_bat_dau": self.entry_ten_bat_dau.get().strip(),
            "thu_muc_goc": list(self.lb_goc.get(0, "end")),
            "che_do_backup": self.bien_che_do_backup.get(),
        })

    # ------------------------------------------------- thư mục gốc
    def _them_goc(self, duong_dan):
        duong_dan = os.path.normpath(duong_dan)
        da_co = {chuan_hoa(p) for p in self.lb_goc.get(0, "end")}
        if chuan_hoa(duong_dan) not in da_co:
            self.lb_goc.insert("end", duong_dan)
            return True
        return False

    def chon_bin_goc(self):
        p = filedialog.askdirectory(title="Chọn thư mục bin_goc",
                                    initialdir=self.entry_bin_goc.get() or None)
        if p:
            self.entry_bin_goc.delete(0, "end")
            self.entry_bin_goc.insert(0, os.path.normpath(p))

    def them_thu_muc_goc(self):
        p = filedialog.askdirectory(title="Thêm thư mục gốc cần quét")
        if p:
            self._them_goc(p)

    def them_thu_muc_con(self):
        cha = filedialog.askdirectory(title="Chọn thư mục cha — sẽ thêm TẤT CẢ thư mục con trực tiếp")
        if not cha:
            return
        try:
            ds = sorted(d for d in os.listdir(cha) if os.path.isdir(os.path.join(cha, d)))
        except OSError as e:
            messagebox.showerror("Lỗi", "Không đọc được thư mục:\n{}".format(e))
            return
        them = sum(1 for d in ds if self._them_goc(os.path.join(cha, d)))
        self.ghi_log("INFO", "Đã thêm {} thư mục con của {}.".format(them, cha))

    def them_tu_o_nhap(self):
        for p in tach_danh_sach(self.entry_them_goc.get()):
            if os.path.isdir(p):
                self._them_goc(p)
            else:
                self.ghi_log("CANH_BAO", "Bỏ qua, không phải thư mục: {}".format(p))
        self.entry_them_goc.delete(0, "end")

    def bo_goc_da_chon(self):
        for i in reversed(self.lb_goc.curselection()):
            self.lb_goc.delete(i)

    def xoa_het_goc(self):
        self.lb_goc.delete(0, "end")

    # ------------------------------------------------- danh sách kết quả
    def _ve_lai_danh_sach(self):
        self.tree.delete(*self.tree.get_children())
        for i, p in enumerate(self.ds_ket_qua):
            self.tree.insert("", "end", iid=str(i), values=(i + 1, p, "Chờ"))
        self.lbl_so_luong.configure(text="{} thư mục".format(len(self.ds_ket_qua)))

    def _dat_trang_thai_dong(self, i, text, tag=None):
        iid = str(i)
        if self.tree.exists(iid):
            self.tree.set(iid, "trang_thai", text)
            if tag is not None:
                self.tree.item(iid, tags=(tag,) if tag else ())

    def bo_dong_ket_qua(self):
        if self.dang_chay:
            return
        chon = {int(iid) for iid in self.tree.selection()}
        if not chon:
            return
        self.ds_ket_qua = [p for i, p in enumerate(self.ds_ket_qua) if i not in chon]
        self._ve_lai_danh_sach()

    def mo_thu_muc_dong(self, event):
        iid = self.tree.identify_row(event.y)
        if iid and hasattr(os, "startfile"):
            try:
                os.startfile(self.ds_ket_qua[int(iid)])
            except Exception:
                pass

    # ------------------------------------------------------------ log
    def _mo_file_log(self):
        if self.file_log:
            return
        ten = "update_bin_{}.log".format(datetime.now().strftime("%Y%m%d_%H%M%S"))
        for thu_muc in (os.path.join(thu_muc_ung_dung(), "logs"),
                        os.path.join(tempfile.gettempdir(), "UPDATE_BIN_SERVICE_logs")):
            try:
                os.makedirs(thu_muc, exist_ok=True)
                self.file_log = open(os.path.join(thu_muc, ten), "a", encoding="utf-8")
                self.duong_dan_log = os.path.join(thu_muc, ten)
                return
            except OSError:
                continue

    def ghi_log(self, muc, noi_dung):
        dong = "[{}] {:<8} {}".format(datetime.now().strftime("%H:%M:%S"), muc, noi_dung)
        self.txt_log.configure(state="normal")
        self.txt_log.insert("end", dong + "\n", (muc,))
        self.txt_log.see("end")
        self.txt_log.configure(state="disabled")
        self._mo_file_log()
        if self.file_log:
            try:
                self.file_log.write(dong + "\n")
                self.file_log.flush()
            except OSError:
                pass

    def mo_thu_muc_log(self):
        self._mo_file_log()
        if self.duong_dan_log and hasattr(os, "startfile"):
            os.startfile(os.path.dirname(self.duong_dan_log))
        elif self.duong_dan_log:
            messagebox.showinfo("Log", self.duong_dan_log)

    # ------------------------------------------------- trạng thái chạy
    def _bat_dau_chay(self, loai):
        self.dang_chay = loai
        self.su_kien_huy.clear()
        self.thoi_diem_bat_dau = time.monotonic()
        for w in [self.btn_tim, self.btn_ghi_de, self.btn_bo_dong] + self.nut_goc + self.nut_backup:
            w.configure(state="disabled")
        self.btn_dung.configure(state="normal")
        self._luu_cau_hinh()

    def _ket_thuc_chay(self):
        self.dang_chay = None
        for w in [self.btn_tim, self.btn_ghi_de, self.btn_bo_dong] + self.nut_goc + self.nut_backup:
            w.configure(state="normal")
        self.btn_dung.configure(state="disabled")
        if str(self.pb_tong.cget("mode")) == "indeterminate":
            self.pb_tong.stop()
            self.pb_tong.configure(mode="determinate", value=0)
        if self.dong_khi_xong:
            self._dong()

    def _thoi_gian_da_chay(self):
        if not self.thoi_diem_bat_dau:
            return ""
        giay = int(time.monotonic() - self.thoi_diem_bat_dau)
        return "{:02d}:{:02d}".format(giay // 60, giay % 60)

    def dung(self):
        if not self.dang_chay:
            return
        self.su_kien_huy.set()
        self.btn_dung.configure(state="disabled")
        if self.dang_chay == "ghi_de":
            self.ghi_log("CANH_BAO", "Đã yêu cầu dừng — sẽ dừng sau khi xong thư mục đang chạy.")
        else:
            self.ghi_log("CANH_BAO", "Đã yêu cầu dừng quét.")

    def _chay_nen(self, ham, *tham_so):
        def bao_cao(*du_lieu):
            self.hang_doi.put(du_lieu)

        def chay():
            try:
                ham(*(tham_so + (self.su_kien_huy, bao_cao)))
            except Exception:
                bao_cao("log", "LOI", "Lỗi không mong muốn:\n" + traceback.format_exc())
                bao_cao("loi_nghiem_trong",)

        threading.Thread(target=chay, daemon=True).start()

    # ------------------------------------------------------------ Tìm kiếm
    def tim_kiem(self):
        if self.dang_chay:
            return
        ds_goc = list(self.lb_goc.get(0, "end"))
        ds_ten = tach_danh_sach(self.entry_ten_bat_dau.get())
        if not ds_goc:
            messagebox.showerror("Lỗi", "Chưa có thư mục gốc nào. Bấm 'Thêm thư mục...' để thêm.")
            return
        if not ds_ten:
            messagebox.showerror("Lỗi", "Tên bắt đầu không được để trống.")
            return
        ton_tai = [p for p in ds_goc if os.path.isdir(p)]
        for p in ds_goc:
            if p not in ton_tai:
                self.ghi_log("CANH_BAO", "Thư mục gốc không tồn tại, bỏ qua: {}".format(p))
        if not ton_tai:
            messagebox.showerror("Lỗi", "Không thư mục gốc nào tồn tại.")
            return

        self.ds_ket_qua = []
        self._ve_lai_danh_sach()
        self.tien_do_quet = {}
        self.so_goc_quet = len(loai_bo_thu_muc_long_nhau(ton_tai))
        self._bat_dau_chay("quet")
        self.pb_tong.configure(mode="indeterminate")
        self.pb_tong.start(15)
        self.pb_hien_tai.configure(value=0)
        self.lbl_pt_tong.configure(text="")
        self.lbl_pt_hien_tai.configure(text="")
        self.ghi_log("INFO", "Bắt đầu quét {} thư mục gốc, tên bắt đầu: {}".format(
            len(ton_tai), "; ".join(ds_ten)))
        self._chay_nen(self._luong_quet, ton_tai, ds_ten)

    @staticmethod
    def _luong_quet(ds_goc, ds_ten, su_kien_huy, bao_cao):
        try:
            ket_qua = quet_nhieu_thu_muc(ds_goc, ds_ten, su_kien_huy, bao_cao)
            bao_cao("quet_xong", ket_qua, False)
        except DaHuy:
            bao_cao("quet_xong", None, True)

    # ------------------------------------------------------------ Ghi đè
    def ghi_de(self):
        if self.dang_chay:
            return
        bin_goc = self.entry_bin_goc.get().strip()
        if not os.path.isdir(bin_goc):
            messagebox.showerror("Lỗi", "Thư mục bin_goc không tồn tại.")
            return
        if not self.ds_ket_qua:
            messagebox.showinfo("Chưa có danh sách", "Hãy bấm '1. Tìm kiếm' trước khi ghi đè.")
            return
        so_file = dem_file(bin_goc)
        che_do = self.bien_che_do_backup.get()
        canh_bao_rong = "\n\nCẢNH BÁO: bin_goc đang RỖNG (0 file)!" if so_file == 0 else ""
        mo_ta_backup = {
            BACKUP_XOA_KHI_OK: "Bin cũ được sao lưu tạm; thư mục chạy OK sẽ tự xóa bản sao lưu, "
                               "thư mục lỗi được tự khôi phục và GIỮ bản sao lưu.",
            BACKUP_GIU_TAT_CA: "Bin cũ được sao lưu vào 'bin_backup_<thời gian>' cạnh mỗi thư mục "
                               "và giữ lại tất cả; lỗi giữa chừng sẽ tự khôi phục.",
            BACKUP_KHONG: "KHÔNG sao lưu: nếu lỗi giữa chừng (VD: file .dll đang bị service khóa) "
                          "thì bin sẽ DỞ DANG và KHÔNG tự khôi phục được.",
        }[che_do]
        if not messagebox.askyesno(
                "Xác nhận ghi đè",
                "Sẽ ghi đè thư mục 'bin' của {} thư mục bằng {} file từ:\n{}\n\n{}{}\n\nTiếp tục?".format(
                    len(self.ds_ket_qua), so_file, bin_goc, mo_ta_backup, canh_bao_rong),
                icon="warning"):
            return
        if che_do == BACKUP_KHONG and not messagebox.askyesno(
                "Xác nhận lần 2 - KHÔNG sao lưu",
                "Chế độ KHÔNG sao lưu chỉ nên dùng khi đã DỪNG hết service.\n\n"
                "Chắc chắn chạy không sao lưu?", icon="warning", default="no"):
            return

        self._ve_lai_danh_sach()
        self.tong_ghi_de = len(self.ds_ket_qua)
        self._bat_dau_chay("ghi_de")
        self.pb_tong.configure(mode="determinate", maximum=self.tong_ghi_de, value=0)
        self.pb_hien_tai.configure(maximum=1, value=0)
        self.lbl_pt_tong.configure(text="0/{}".format(self.tong_ghi_de))
        self._chay_nen(chay_ghi_de, bin_goc, list(self.ds_ket_qua), che_do)

    # ------------------------------------------------- xử lý hàng đợi
    def _xu_ly_hang_doi(self):
        try:
            for _ in range(500):
                try:
                    tin = self.hang_doi.get_nowait()
                except queue.Empty:
                    break
                self._xu_ly_tin(tin[0], tin[1:])
        finally:
            if self.dang_chay:
                self._cap_nhat_trang_thai_chung()
            self.root.after(CHU_KY_CAP_NHAT_GUI_MS, self._xu_ly_hang_doi)

    def _cap_nhat_trang_thai_chung(self):
        if self.dang_chay == "quet":
            tong_duyet = sum(self.tien_do_quet.values())
            self.lbl_trang_thai.configure(
                text="Đang quét {} thư mục gốc song song... đã duyệt {} thư mục, tìm thấy {}  ({})".format(
                    self.so_goc_quet, tong_duyet, len(self.ds_ket_qua),
                    self._thoi_gian_da_chay()))

    def _xu_ly_tin(self, loai, d):
        if loai == "log":
            self.ghi_log(d[0], d[1])

        elif loai == "dang_quet":
            goc, dang_o, so = d
            self.tien_do_quet[goc] = so
            if dang_o:
                self.lbl_chi_tiet.configure(text="Đang duyệt: {}".format(dang_o))

        elif loai == "tim_thay":
            self.ds_ket_qua.append(d[0])
            i = len(self.ds_ket_qua) - 1
            self.tree.insert("", "end", iid=str(i), values=(i + 1, d[0], "Chờ"))
            self.lbl_so_luong.configure(text="{} thư mục".format(len(self.ds_ket_qua)))

        elif loai == "quet_xong":
            ket_qua, da_huy = d
            if not da_huy:
                self.ds_ket_qua = ket_qua
                self._ve_lai_danh_sach()
            tong_duyet = sum(self.tien_do_quet.values())
            thong_bao = "{} — duyệt {} thư mục, tìm thấy {} thư mục service ({}).".format(
                "ĐÃ DỪNG quét" if da_huy else "Quét xong", tong_duyet,
                len(self.ds_ket_qua), self._thoi_gian_da_chay())
            self.lbl_trang_thai.configure(text=thong_bao)
            self.lbl_chi_tiet.configure(text="")
            self.ghi_log("CANH_BAO" if da_huy else "OK", thong_bao)
            self._ket_thuc_chay()
            if not da_huy and not self.ds_ket_qua:
                messagebox.showinfo("Kết quả", "Không tìm thấy thư mục nào phù hợp.")

        elif loai == "bat_dau":
            i, thu_muc = d
            self._dat_trang_thai_dong(i, "Đang chạy...", "dang_chay")
            self.tree.see(str(i))
            self.lbl_trang_thai.configure(text="Đang ghi đè {}/{}: {}".format(
                i + 1, self.tong_ghi_de, thu_muc))

        elif loai == "buoc":
            i, buoc, da_xong, tong = d
            if tong:
                text = "{} {}/{} file".format(buoc, da_xong, tong)
                ti_le = float(da_xong) / tong
            else:
                text = "{}...".format(buoc)
                ti_le = 0.0
            self._dat_trang_thai_dong(i, text)
            self.lbl_chi_tiet.configure(text="{}  ({})".format(text, self._thoi_gian_da_chay()))
            self.pb_hien_tai.configure(maximum=1, value=ti_le)
            self.lbl_pt_hien_tai.configure(text="{}%".format(int(ti_le * 100)))
            # Tổng: sao lưu ~40%, xóa ~10%, copy ~50% thời gian của một thư mục
            phan = {"Sao lưu": 0.4 * ti_le, "Xóa bin cũ": 0.45,
                    "Copy": 0.5 + 0.5 * ti_le, "Xóa backup": 0.97}.get(buoc, 0.95)
            self.pb_tong.configure(value=i + phan)

        elif loai == "xong":
            i, ok, thong_bao = d
            self._dat_trang_thai_dong(i, ("OK — " if ok else "LỖI — ") + thong_bao,
                                      "ok" if ok else "loi")
            self.pb_tong.configure(value=i + 1)
            self.lbl_pt_tong.configure(text="{}/{}".format(i + 1, self.tong_ghi_de))
            self.pb_hien_tai.configure(value=1 if ok else 0)
            self.lbl_pt_hien_tai.configure(text="100%" if ok else "")
            self.ghi_log("OK" if ok else "LOI", "{} | {}".format(
                os.path.join(self.ds_ket_qua[i], TEN_BIN), thong_bao))

        elif loai == "ket_thuc_ghi_de":
            thanh_cong, loi, bo_qua = d
            for i in range(self.tong_ghi_de - bo_qua, self.tong_ghi_de):
                self._dat_trang_thai_dong(i, "Bỏ qua (đã dừng)", "bo_qua")
            tom_tat = "Hoàn tất ghi đè: {} thành công, {} lỗi, {} bỏ qua ({}).".format(
                thanh_cong, loi, bo_qua, self._thoi_gian_da_chay())
            self.lbl_trang_thai.configure(text=tom_tat)
            self.lbl_chi_tiet.configure(text="")
            self.ghi_log("OK" if not loi and not bo_qua else "CANH_BAO", tom_tat)
            self._ket_thuc_chay()
            if not self.dong_khi_xong:
                chi_tiet = "\n\nXem chi tiết lỗi trong danh sách / nhật ký." if loi else ""
                if loi or bo_qua:
                    messagebox.showwarning("Hoàn tất (có lỗi/bỏ qua)", tom_tat + chi_tiet)
                else:
                    messagebox.showinfo("Hoàn tất", tom_tat)

        elif loai == "loi_nghiem_trong":
            self.lbl_trang_thai.configure(text="Lỗi không mong muốn — xem nhật ký.")
            self._ket_thuc_chay()

    # ------------------------------------------------------------ đóng
    def khi_dong_cua_so(self):
        if self.dang_chay == "ghi_de":
            if messagebox.askyesno(
                    "Đang ghi đè",
                    "Đang ghi đè. Thoát ngay có thể để lại thư mục bin dở dang.\n\n"
                    "Dừng sau thư mục hiện tại rồi tự đóng?"):
                self.dong_khi_xong = True
                self.dung()
            return
        if self.dang_chay == "quet":
            self.su_kien_huy.set()
        self._dong()

    def _dong(self):
        self._luu_cau_hinh()
        if self.file_log:
            try:
                self.file_log.close()
            except OSError:
                pass
        self.root.destroy()


def bat_dpi_awareness():
    """
    Tránh giao diện bị mờ trên màn hình/RDP scale > 100%.
    - Windows 8.1 / Server 2012 R2 trở lên: shcore.SetProcessDpiAwareness
    - Windows 7 / Server 2008 R2: user32.SetProcessDPIAware
    """
    if sys.platform != "win32":
        return
    try:
        import ctypes
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except Exception:
            ctypes.windll.user32.SetProcessDPIAware()
    except Exception:
        pass


def main():
    bat_dpi_awareness()
    root = tk.Tk()
    UngDung(root)
    root.mainloop()


if __name__ == "__main__":
    main()
