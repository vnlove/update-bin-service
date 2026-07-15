import os
import shutil
import tkinter as tk
from datetime import datetime
from tkinter import filedialog, messagebox


def tim_tat_ca_thu_muc_theo_ten(thu_muc_goc, ten_bat_dau):
    """
    Tìm tất cả thư mục bắt đầu bằng một tên cụ thể trong thư mục gốc
    và chỉ chọn những thư mục cha có chứa thư mục con tên là 'bin'.
    """
    ket_qua = []
    for root, dirs, _ in os.walk(thu_muc_goc):
        for dir_name in dirs:
            if dir_name.startswith(ten_bat_dau):
                thu_muc_cha = os.path.join(root, dir_name)
                if "bin" in os.listdir(thu_muc_cha):  # Kiểm tra nếu có thư mục 'bin'
                    ket_qua.append(thu_muc_cha)
    return ket_qua


def sao_luu_thu_muc_bin(bin_thu_muc, moc_thoi_gian):
    """
    Sao lưu thư mục bin hiện tại sang thư mục bin_backup_<thời gian>
    nằm cạnh nó, trả về đường dẫn bản sao lưu.
    """
    thu_muc_cha = os.path.dirname(bin_thu_muc)
    backup_path = os.path.join(thu_muc_cha, f"bin_backup_{moc_thoi_gian}")
    shutil.copytree(bin_thu_muc, backup_path)
    return backup_path


def ghi_de_thu_muc(bin_goc, danh_sach_thu_muc):
    """
    Ghi đè nội dung từ bin_goc vào các thư mục bin trong danh sách thư mục đã tìm được.

    Trước khi ghi đè, mỗi thư mục bin cũ được sao lưu lại. Nếu một thư mục gặp lỗi,
    hàm ghi nhận lỗi và tiếp tục với các thư mục còn lại thay vì dừng giữa chừng.

    Trả về (danh_sach_thanh_cong, danh_sach_loi) trong đó mỗi phần tử lỗi là
    một tuple (đường_dẫn_bin, thông_báo_lỗi).
    """
    moc_thoi_gian = datetime.now().strftime("%Y%m%d_%H%M%S")
    thanh_cong = []
    loi = []

    for thu_muc in danh_sach_thu_muc:
        bin_thu_muc = os.path.join(thu_muc, "bin")

        try:
            # Sao lưu thư mục bin cũ trước khi thay đổi
            sao_luu_thu_muc_bin(bin_thu_muc, moc_thoi_gian)

            # Xóa nội dung cũ trong thư mục bin
            for item in os.listdir(bin_thu_muc):
                item_path = os.path.join(bin_thu_muc, item)
                if os.path.isfile(item_path) or os.path.islink(item_path):
                    os.unlink(item_path)
                elif os.path.isdir(item_path):
                    shutil.rmtree(item_path)

            # Sao chép nội dung từ bin_goc vào bin
            for item in os.listdir(bin_goc):
                src_path = os.path.join(bin_goc, item)
                dst_path = os.path.join(bin_thu_muc, item)
                if os.path.isdir(src_path):
                    shutil.copytree(src_path, dst_path)
                else:
                    shutil.copy2(src_path, dst_path)

            thanh_cong.append(bin_thu_muc)
        except Exception as e:
            loi.append((bin_thu_muc, str(e)))

    return thanh_cong, loi


def chon_thu_muc(entry_field):
    """Mở hộp thoại để chọn thư mục."""
    thu_muc = filedialog.askdirectory()
    if thu_muc:
        entry_field.delete(0, tk.END)
        entry_field.insert(0, thu_muc)


def hien_thi_danh_sach(danh_sach):
    """Hiển thị danh sách thư mục trong giao diện."""
    text_danh_sach.delete("1.0", tk.END)  # Xóa nội dung cũ
    for thu_muc in danh_sach:
        text_danh_sach.insert(tk.END, f"{thu_muc}\n")


def tim_kiem_thu_muc():
    """Tìm kiếm và hiển thị danh sách thư mục cha trong giao diện."""
    thu_muc_goc = entry_thu_muc_goc.get().strip()
    ten_bat_dau = entry_ten_bat_dau.get().strip()

    if not os.path.exists(thu_muc_goc):
        messagebox.showerror("Lỗi", "Thư mục gốc không tồn tại.")
        return
    if not ten_bat_dau:
        messagebox.showerror("Lỗi", "Tên bắt đầu không được để trống.")
        return

    danh_sach_thu_muc = tim_tat_ca_thu_muc_theo_ten(thu_muc_goc, ten_bat_dau)
    if not danh_sach_thu_muc:
        messagebox.showinfo("Kết quả", "Không tìm thấy thư mục nào phù hợp.")
        return

    hien_thi_danh_sach(danh_sach_thu_muc)
    messagebox.showinfo("Kết quả", f"Tìm thấy {len(danh_sach_thu_muc)} thư mục cha có chứa thư mục 'bin'.")


def thuc_hien_ghi_de():
    """Thực hiện ghi đè sau khi đã hiển thị danh sách."""
    bin_goc = entry_bin_goc.get().strip()
    thu_muc_goc = entry_thu_muc_goc.get().strip()
    ten_bat_dau = entry_ten_bat_dau.get().strip()

    if not os.path.exists(bin_goc):
        messagebox.showerror("Lỗi", "Thư mục bin_goc không tồn tại.")
        return

    danh_sach_thu_muc = tim_tat_ca_thu_muc_theo_ten(thu_muc_goc, ten_bat_dau)
    if not danh_sach_thu_muc:
        messagebox.showinfo("Kết quả", "Không tìm thấy thư mục nào phù hợp.")
        return

    # Xác nhận trước khi ghi đè (thao tác xóa nội dung bin cũ)
    xac_nhan = messagebox.askyesno(
        "Xác nhận ghi đè",
        f"Sẽ ghi đè thư mục 'bin' của {len(danh_sach_thu_muc)} thư mục.\n"
        f"Nội dung bin cũ được sao lưu vào 'bin_backup_<thời gian>' cạnh mỗi thư mục.\n\n"
        f"Bạn có chắc chắn muốn tiếp tục?",
    )
    if not xac_nhan:
        return

    thanh_cong, loi = ghi_de_thu_muc(bin_goc, danh_sach_thu_muc)

    thong_bao = f"Đã ghi đè thành công {len(thanh_cong)} thư mục."
    if thanh_cong:
        thong_bao += "\n\n" + "\n".join(thanh_cong)

    if loi:
        chi_tiet_loi = "\n".join(f"- {bin_path}: {msg}" for bin_path, msg in loi)
        thong_bao += f"\n\n{len(loi)} thư mục gặp lỗi:\n{chi_tiet_loi}"
        messagebox.showwarning("Hoàn tất (có lỗi)", thong_bao)
    else:
        messagebox.showinfo("Hoàn tất", thong_bao)


# Tạo giao diện Tkinter
root = tk.Tk()
root.title("UPDATE BIN SERVICE")

# Các nhãn và ô nhập liệu
tk.Label(root, text="Thư mục bin_goc:").grid(row=0, column=0, padx=5, pady=5, sticky="e")
entry_bin_goc = tk.Entry(root, width=50)
entry_bin_goc.grid(row=0, column=1, padx=5, pady=5)
btn_chon_bin_goc = tk.Button(root, text="Chọn", command=lambda: chon_thu_muc(entry_bin_goc))
btn_chon_bin_goc.grid(row=0, column=2, padx=5, pady=5)

tk.Label(root, text="Thư mục cần tìm đè(VD: C:\iPOS.vn\DB10012):").grid(row=1, column=0, padx=5, pady=5, sticky="e")
entry_thu_muc_goc = tk.Entry(root, width=50)
entry_thu_muc_goc.grid(row=1, column=1, padx=5, pady=5)
btn_chon_thu_muc_goc = tk.Button(root, text="Chọn", command=lambda: chon_thu_muc(entry_thu_muc_goc))
btn_chon_thu_muc_goc.grid(row=1, column=2, padx=5, pady=5)

tk.Label(root, text="Tên bắt đầu của thư mục cha(VD: ACCService):").grid(row=2, column=0, padx=5, pady=5, sticky="e")
entry_ten_bat_dau = tk.Entry(root, width=50)
entry_ten_bat_dau.grid(row=2, column=1, padx=5, pady=5)

# Nút tìm kiếm và hiển thị kết quả
btn_tim_kiem = tk.Button(root, text="Tìm kiếm", command=tim_kiem_thu_muc)
btn_tim_kiem.grid(row=3, column=0, columnspan=3, pady=10)

# Vùng hiển thị danh sách kết quả
text_danh_sach = tk.Text(root, height=10, width=70)
text_danh_sach.grid(row=4, column=0, columnspan=3, padx=5, pady=5)

# Nút thực hiện ghi đè
btn_thuc_hien = tk.Button(root, text="Thực hiện ghi đè", command=thuc_hien_ghi_de)
btn_thuc_hien.grid(row=5, column=0, columnspan=3, pady=10)

# Chạy ứng dụng
root.mainloop()
