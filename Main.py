import os
import shutil
import tkinter as tk
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


def ghi_de_thu_muc(bin_goc, danh_sach_thu_muc):
    """
    Ghi đè nội dung từ bin_goc vào các thư mục bin trong danh sách thư mục đã tìm được.
    """
    ket_qua = []
    for thu_muc in danh_sach_thu_muc:
        bin_thu_muc = os.path.join(thu_muc, "bin")

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

        ket_qua.append(bin_thu_muc)

    return ket_qua


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

    ket_qua = ghi_de_thu_muc(bin_goc, danh_sach_thu_muc)
    messagebox.showinfo("Hoàn tất", f"Đã ghi đè vào {len(ket_qua)} thư mục.\n\n{chr(10).join(ket_qua)}")


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
