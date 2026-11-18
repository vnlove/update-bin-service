# UPDATE BIN SERVICE — Ghi chú dự án

## Mục đích
Công cụ GUI (Tkinter) cập nhật hàng loạt thư mục `bin` của các service iPOS
(VD: `C:\iPOS.vn\DB10012\ACCService*\bin`) từ một thư mục `bin_goc` chuẩn.

## Cấu trúc
- `Main.py` — toàn bộ logic + giao diện.
- `.github/workflows/build-win2008.yml` — build EXE (chạy tay `workflow_dispatch`),
  Python 3.8.10 + PyInstaller 4.10 → tương thích Windows 7 / Server 2008.
  Artifact: `UPDATE_BIN_SERVICE_WIN2008` / `dist/UPDATE_BIN_SERVICE.exe`.

## Luồng xử lý
```
Chọn bin_goc + Thư mục gốc + Tên bắt đầu
  → [Tìm kiếm] os.walk: thư mục tên bắt đầu = prefix VÀ có con 'bin'
  → Hiển thị danh sách
  → [Thực hiện ghi đè] → hỏi xác nhận
      → mỗi thư mục: backup bin → bin_backup_<YYYYmmdd_HHMMSS>
                     → xóa nội dung bin → copy từ bin_goc
                     → lỗi thì ghi nhận, chạy tiếp thư mục khác
  → Báo cáo thành công / lỗi
```

## Quy ước
- Ngôn ngữ code/comment: tiếng Việt không dấu cho tên hàm, có dấu cho docstring/UI.
- Giữ tương thích Python 3.8 (Win7/2008) — không dùng cú pháp 3.9+ (`list[str]`, `match`, `|` type...).
- Branch phát triển: `claude/gracious-turing-450ds4`. **Không push khi chưa được Anh xác nhận.**

## Lịch sử
- PR #1: thêm backup, xác nhận, xử lý lỗi khi ghi đè; thêm `.gitignore`.
