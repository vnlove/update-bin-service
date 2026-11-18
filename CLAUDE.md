# UPDATE BIN SERVICE — Ghi chú dự án

## Mục đích
Công cụ GUI (Tkinter) cập nhật hàng loạt thư mục `bin` của các service iPOS
(VD: `C:\iPOS.vn\DB10012\ACCService*\bin`) từ một thư mục `bin_goc` chuẩn.

## Cấu trúc
- `Main.py` — toàn bộ logic + giao diện (class `UngDung`).
  - Phần lõi (không phụ thuộc GUI, test được): `quet_nhieu_thu_muc`, `ghi_de_mot_thu_muc`,
    `chay_ghi_de`, `khoi_phuc_tu_backup`.
  - Luồng nền gửi tiến độ qua `queue.Queue`; GUI đọc mỗi 100 ms (`_xu_ly_hang_doi`).
    **Không bao giờ đụng widget Tk từ luồng nền.**
- `.github/workflows/build-win2008.yml` — build EXE (chạy tay `workflow_dispatch`).
- File sinh ra khi chạy (đã gitignore): `logs/update_bin_<thời gian>.log`, `update_bin_config.json`
  (nhớ bin_goc, danh sách thư mục gốc, tên bắt đầu) — nằm cạnh EXE; không ghi được thì log vào %TEMP%.

## Nghiệp vụ
- ACCService và WarehouseService dùng CHUNG một bộ bin → chạy chung 1 lần với cùng bin_goc (VD: `ACCService;WarehouseService`).
- So khớp tên không phân biệt hoa thường → không cần nhập cả `WarehouseService` lẫn `Warehouseservice`.

## Luồng xử lý
```
Chọn bin_goc + NHIỀU thư mục gốc + tên bắt đầu (nhiều tên, cách nhau ';')
  → [1. Tìm kiếm] (luồng nền)
      bỏ thư mục gốc trùng/lồng nhau → ThreadPoolExecutor (≤8 luồng, mỗi gốc 1 luồng)
      os.walk: tên khớp prefix (không phân biệt hoa thường) VÀ có con 'bin'
      không đi vào bin/ và bin_backup_*  → hiện kết quả trực tiếp vào bảng
  → Bảng kết quả (bỏ bớt dòng được)
  → [2. Thực hiện ghi đè] → xác nhận → (luồng nền, tuần tự từng thư mục)
      Sao lưu bin → bin_backup_<YYYYmmdd_HHMMSS>   (lỗi: bin chưa bị đụng)
      Xóa bin cũ → Copy bin_goc                    (lỗi: tự khôi phục từ backup)
      Bảng: trạng thái từng dòng | Progress Tổng + Hiện tại | Nhật ký + file log
  → [Dừng]: quét dừng ngay; ghi đè dừng sau thư mục đang chạy (không để bin dở dang)
```

## Tương thích nền tảng (BẮT BUỘC)
- Đích: **Windows Server 2008 R2 SP1 → 2012/2012 R2 → 2016 → 2019 → 2022** (+ Win7 SP1 → Win11), x64.
- Build bằng **Python 3.8.10** (dòng cuối hỗ trợ Win7/2008 R2) + PyInstaller 4.10.
  → Code chỉ dùng cú pháp/thư viện có ở 3.8: không `list[str]`, `match`, `X | Y`, `str.removeprefix`...
  Kiểm tra: `vermin --no-tips -t=3.8- --violations Main.py`.
- UCRT được đóng gói vào EXE khi build → 2008 R2 không cần KB2999226.
- 2008 R2 vẫn cần **SP1 + KB2533623 (hoặc KB3063858)** — Python 3.8 yêu cầu, không đóng gói được.
- Server 2008 **không R2** (nhân Vista) và **Server Core** (không có GUI): KHÔNG hỗ trợ.
- EXE build với `--uac-admin` (luôn chạy quyền admin để ghi được vào thư mục service).
- DPI awareness (`bat_dpi_awareness`) để không mờ khi RDP/màn hình scale > 100%.
- Sửa lỗi màu tag Treeview của Tk 8.6.9 (`_sua_mau_treeview`).
- Chỉ dùng ký tự Unicode cơ bản trong UI (tránh ký hiệu như ⚠ không có font trên 2008 R2).

## Quy ước
- Tên hàm/biến tiếng Việt không dấu; docstring/UI tiếng Việt có dấu.
- Branch phát triển: `claude/gracious-turing-450ds4`. **Không push khi chưa được Anh xác nhận.**

## Lịch sử
- PR #1: thêm backup, xác nhận, xử lý lỗi khi ghi đè; thêm `.gitignore`.
- Nhiều thư mục gốc quét song song; ghi đè chạy nền có tiến trình/nhật ký/log file;
  tự khôi phục khi lỗi; nút Dừng; nhớ cấu hình; build tương thích 2008 R2 → 2022.
