# main.py
import os
import sqlite3
import random
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
try:
    from PIL import Image, ImageTk
except Exception as e:
    Image = None
    ImageTk = None

DB_FILE = "palace.db"
ASSETS_DIR = "assets"

# ---------------------------
# Data layer: SQLite + OOP
# ---------------------------
class DB:
    def __init__(self, db_path=DB_FILE):
        self.conn = sqlite3.connect(db_path)
        self._ensure_schema()

    def _ensure_schema(self):
        cur = self.conn.cursor()
        cur.execute("""
        CREATE TABLE IF NOT EXISTS rooms (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE,
            description TEXT
        )
        """)
        cur.execute("""
        CREATE TABLE IF NOT EXISTS items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            room_id INTEGER,
            name TEXT,
            hint TEXT,
            image_path TEXT,
            FOREIGN KEY(room_id) REFERENCES rooms(id) ON DELETE CASCADE
        )
        """)
        cur.execute("""
        CREATE TABLE IF NOT EXISTS progress (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            item_id INTEGER,
            seen_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            note TEXT
        )
        """)
        self.conn.commit()

    # Room CRUD
    def add_room(self, name, description=""):
        cur = self.conn.cursor()
        cur.execute("INSERT INTO rooms (name, description) VALUES (?, ?)", (name, description))
        self.conn.commit()
        return cur.lastrowid

    def list_rooms(self):
        cur = self.conn.cursor()
        cur.execute("SELECT id, name, description FROM rooms ORDER BY id")
        return cur.fetchall()

    def delete_room(self, room_id):
        cur = self.conn.cursor()
        cur.execute("DELETE FROM rooms WHERE id = ?", (room_id,))
        self.conn.commit()

    # Items CRUD
    def add_item(self, room_id, name, hint, image_path):
        cur = self.conn.cursor()
        cur.execute("INSERT INTO items (room_id, name, hint, image_path) VALUES (?, ?, ?, ?)",
                    (room_id, name, hint, image_path))
        self.conn.commit()
        return cur.lastrowid

    def list_items(self, room_id):
        cur = self.conn.cursor()
        cur.execute("SELECT id, name, hint, image_path FROM items WHERE room_id = ? ORDER BY id", (room_id,))
        return cur.fetchall()

    def delete_item(self, item_id):
        cur = self.conn.cursor()
        cur.execute("DELETE FROM items WHERE id = ?", (item_id,))
        self.conn.commit()

    # Progress
    def log_seen(self, item_id, note=""):
        cur = self.conn.cursor()
        cur.execute("INSERT INTO progress (item_id, note) VALUES (?, ?)", (item_id, note))
        self.conn.commit()

    def close(self):
        self.conn.close()


# ---------------------------
# Generator for daily practice
# ---------------------------
def practice_generator(db: DB, rooms=None, shuffle=True, repeat=False):
    """
    Generator that yields (room_id, item_row) in a practice sequence.
    - rooms: list of room ids to include (None => all)
    - shuffle: shuffle items order
    - repeat: if True, loops forever (careful!)
    """
    # fetch all items
    cur = db.conn.cursor()
    if rooms:
        placeholder = ",".join("?" for _ in rooms)
        cur.execute(f"SELECT items.id, items.room_id, items.name, items.hint, items.image_path FROM items WHERE room_id IN ({placeholder})", tuple(rooms))
    else:
        cur.execute("SELECT items.id, items.room_id, items.name, items.hint, items.image_path FROM items")
    items = cur.fetchall()  # list of tuples
    if not items:
        return  # generator will stop immediately

    while True:
        sequence = list(items)
        if shuffle:
            random.shuffle(sequence)
        for it in sequence:
            yield it  # (id, room_id, name, hint, image_path)
        if not repeat:
            break


# ---------------------------
# UI layer - Tkinter
# ---------------------------
class MemoryPalaceApp(tk.Tk):
    def __init__(self, db: DB):
        super().__init__()
        self.title("Memory Palace")
        self.geometry("900x600")
        self.db = db
        self.current_room_id = None
        self.current_image_ref = None  # keep reference to PhotoImage
        self.practice_gen = None
        self._build_ui()
        self.refresh_rooms()

    def _build_ui(self):
        # left: rooms list + controls
        left = ttk.Frame(self)
        left.pack(side="left", fill="y", padx=8, pady=8)

        ttk.Label(left, text="اتاق‌ها").pack()
        self.rooms_listbox = tk.Listbox(left, width=25)
        self.rooms_listbox.pack(fill="y", expand=False)
        self.rooms_listbox.bind("<<ListboxSelect>>", lambda e: self.on_room_select())

        btn_frame = ttk.Frame(left)
        btn_frame.pack(pady=6)
        ttk.Button(btn_frame, text="افزودن اتاق", command=self.add_room_dialog).grid(row=0, column=0, padx=2)
        ttk.Button(btn_frame, text="حذف اتاق", command=self.delete_selected_room).grid(row=0, column=1, padx=2)

        ttk.Separator(left, orient="horizontal").pack(fill="x", pady=8)
        ttk.Label(left, text="آیتم‌های اتاق").pack()
        self.items_tree = ttk.Treeview(left, columns=("hint","img"), show="headings", height=10)
        self.items_tree.heading("hint", text="سرنخ")
        self.items_tree.heading("img", text="عکس")
        self.items_tree.pack()

        item_btns = ttk.Frame(left)
        item_btns.pack(pady=6)
        ttk.Button(item_btns, text="افزودن آیتم", command=self.add_item_dialog).grid(row=0, column=0, padx=2)
        ttk.Button(item_btns, text="حذف آیتم", command=self.delete_selected_item).grid(row=0, column=1, padx=2)

        ttk.Separator(left, orient="horizontal").pack(fill="x", pady=8)
        # practice controls
        ttk.Label(left, text="تمرین روزانه").pack(pady=(4,0))
        practice_frame = ttk.Frame(left)
        practice_frame.pack()
        ttk.Button(practice_frame, text="شروع تمرین", command=self.start_practice).grid(row=0, column=0, padx=2)
        ttk.Button(practice_frame, text="توقف", command=self.stop_practice).grid(row=0, column=1, padx=2)
        ttk.Button(practice_frame, text="بعدی", command=self.next_practice).grid(row=0, column=2, padx=2)
        self.practice_status = ttk.Label(left, text="حالت: آماده")
        self.practice_status.pack(pady=6)

        # right: big canvas to show room / item image and details
        right = ttk.Frame(self)
        right.pack(side="right", fill="both", expand=True, padx=8, pady=8)

        self.canvas = tk.Canvas(right, bg="#eee")
        self.canvas.pack(fill="both", expand=True)

        # bottom info
        bottom = ttk.Frame(right)
        bottom.pack(fill="x")
        self.info_lbl = ttk.Label(bottom, text="انتخاب یک اتاق برای مشاهده آیتم‌ها")
        self.info_lbl.pack(side="left", padx=6)

    # ---------- Room / Item operations ----------
    def refresh_rooms(self):
        self.rooms_listbox.delete(0, "end")
        self.rooms = self.db.list_rooms()
        for r in self.rooms:
            self.rooms_listbox.insert("end", f"{r[1]} (#{r[0]})")

    def on_room_select(self):
        sel = self.rooms_listbox.curselection()
        if not sel:
            return
        idx = sel[0]
        room_id = self.rooms[idx][0]
        self.current_room_id = room_id
        self.refresh_items(room_id)
        self.draw_room(room_id)

    def draw_room(self, room_id):
        # simple drawing: room title + thumbnail of first item if exists
        self.canvas.delete("all")
        room = next((r for r in self.rooms if r[0] == room_id), None)
        if not room:
            return
        self.canvas.create_text(10, 10, anchor="nw", text=f"اتاق: {room[1]}", font=("TkDefaultFont", 16, "bold"))
        items = self.db.list_items(room_id)
        if items:
            # show first item image as preview
            img_path = items[0][3]  # image_path
            if img_path and os.path.exists(img_path):
                self._draw_image_on_canvas(img_path)
            else:
                self.canvas.create_text(20, 50, anchor="nw", text="تصویر پیدا نشد.", fill="red")
        else:
            self.canvas.create_text(20, 50, anchor="nw", text="اتاق خالی است. آیتم اضافه کنید.")

    def refresh_items(self, room_id):
        for i in self.items_tree.get_children():
            self.items_tree.delete(i)
        rows = self.db.list_items(room_id)
        for row in rows:
            iid = f"item-{row[0]}"
            imgname = os.path.basename(row[3]) if row[3] else ""
            self.items_tree.insert("", "end", iid=iid, values=(row[2], imgname))

    def add_room_dialog(self):
        dlg = tk.Toplevel(self)
        dlg.title("افزودن اتاق")
        ttk.Label(dlg, text="نام اتاق:").pack(padx=8, pady=4)
        name_e = ttk.Entry(dlg)
        name_e.pack(padx=8, pady=4)
        ttk.Label(dlg, text="توضیح اختیاری:").pack(padx=8, pady=4)
        desc_e = ttk.Entry(dlg)
        desc_e.pack(padx=8, pady=4)
        def ok():
            name = name_e.get().strip()
            if not name:
                messagebox.showwarning("خطا", "نام اتاق نمی‌تواند خالی باشد.")
                return
            try:
                self.db.add_room(name, desc_e.get())
            except sqlite3.IntegrityError:
                messagebox.showerror("خطا", "اتاق با این نام قبلاً وجود دارد.")
            self.refresh_rooms()
            dlg.destroy()
        ttk.Button(dlg, text="افزودن", command=ok).pack(pady=8)

    def delete_selected_room(self):
        sel = self.rooms_listbox.curselection()
        if not sel:
            return
        idx = sel[0]
        room_id = self.rooms[idx][0]
        if messagebox.askyesno("تأیید", "آیا از حذف این اتاق مطمئن هستید؟"):
            self.db.delete_room(room_id)
            self.current_room_id = None
            self.refresh_rooms()
            self.items_tree.delete(*self.items_tree.get_children())
            self.canvas.delete("all")

    def add_item_dialog(self):
        if not self.current_room_id:
            messagebox.showinfo("اطلاع", "ابتدا یک اتاق انتخاب کنید.")
            return
        dlg = tk.Toplevel(self)
        dlg.title("افزودن آیتم")
        ttk.Label(dlg, text="نام آیتم:").pack(padx=8, pady=4)
        name_e = ttk.Entry(dlg); name_e.pack(padx=8, pady=4)
        ttk.Label(dlg, text="سرنخ/توضیح:").pack(padx=8, pady=4)
        hint_e = ttk.Entry(dlg); hint_e.pack(padx=8, pady=4)
        ttk.Label(dlg, text="عکس (PNG):").pack(padx=8, pady=4)
        img_frame = ttk.Frame(dlg); img_frame.pack(padx=8, pady=4)
        img_path_var = tk.StringVar()
        img_entry = ttk.Entry(img_frame, textvariable=img_path_var, width=40)
        img_entry.pack(side="left")
        def browse():
            p = filedialog.askopenfilename(title="انتخاب تصویر", filetypes=[("PNG","*.png"),("All","*.*")], initialdir=os.getcwd())
            if p:
                img_path_var.set(p)
        ttk.Button(img_frame, text="مرور...", command=browse).pack(side="left", padx=4)

        def ok():
            name = name_e.get().strip()
            hint = hint_e.get().strip()
            imgpath = img_path_var.get().strip()
            if not name:
                messagebox.showwarning("خطا", "نام آیتم لازم است.")
                return
            # optionally copy image to assets
            final_path = imgpath
            if imgpath and os.path.exists(imgpath):
                # copy into assets directory
                if not os.path.isdir(ASSETS_DIR):
                    os.makedirs(ASSETS_DIR, exist_ok=True)
                dest = os.path.join(ASSETS_DIR, os.path.basename(imgpath))
                # if source != dest then copy
                if os.path.abspath(imgpath) != os.path.abspath(dest):
                    try:
                        with open(imgpath, "rb") as rf, open(dest, "wb") as wf:
                            wf.write(rf.read())
                    except Exception as e:
                        messagebox.showwarning("هشدار", f"کپی تصویر به پوشه assets ناموفق بود: {e}")
                final_path = dest
            self.db.add_item(self.current_room_id, name, hint, final_path)
            self.refresh_items(self.current_room_id)
            dlg.destroy()

        ttk.Button(dlg, text="افزودن", command=ok).pack(pady=8)

    def delete_selected_item(self):
        sel = self.items_tree.selection()
        if not sel:
            return
        iid = sel[0]
        item_id = int(iid.split("-")[1])
        if messagebox.askyesno("تأیید", "آیا این آیتم حذف شود؟"):
            self.db.delete_item(item_id)
            self.refresh_items(self.current_room_id)

    # ---------- Image helper ----------
    def _draw_image_on_canvas(self, path):
        self.canvas.delete("img")
        if Image is None:
            self.canvas.create_text(20, 50, anchor="nw", text="PIL نصب نشده، نمایش تصویر ممکن نیست.", fill="red")
            return
        try:
            img = Image.open(path)
            # scale to fit canvas
            c_w = self.canvas.winfo_width() or 400
            c_h = self.canvas.winfo_height() or 300
            max_w = int(c_w * 0.8)
            max_h = int(c_h * 0.6)
            try:
                resample = Image.Resampling.LANCZOS
            except AttributeError:
                resample = Image.LANCZOS

            img.thumbnail((max_w, max_h), resample)

            photo = ImageTk.PhotoImage(img)
            self.current_image_ref = photo  # keep ref
            x = c_w // 2
            y = c_h // 2 + 20
            self.canvas.create_image(x, y, image=photo, anchor="center", tags="img")
        except Exception as e:
            self.canvas.create_text(20, 50, anchor="nw", text=f"خطا در بارگذاری تصویر: {e}", fill="red")

    # ---------- Practice controls ----------
    def start_practice(self):
        # create generator for selected rooms (or all)
        rooms_sel = self.rooms_listbox.curselection()
        rooms = None
        if rooms_sel:
            # only selected room
            idx = rooms_sel[0]
            rooms = [self.rooms[idx][0]]
        self.practice_gen = practice_generator(self.db, rooms=rooms, shuffle=True, repeat=False)
        self.practice_status.config(text="حالت: در حال تمرین")
        self.next_practice()

    def stop_practice(self):
        self.practice_gen = None
        self.practice_status.config(text="حالت: متوقف")

    def next_practice(self):
        if not self.practice_gen:
            messagebox.showinfo("اطلاع", "ابتدا 'شروع تمرین' را بزنید.")
            return
        try:
            it = next(self.practice_gen)
        except StopIteration:
            messagebox.showinfo("پایان", "سلسله تمرین به پایان رسید.")
            self.stop_practice()
            return
        # it = (id, room_id, name, hint, image_path)
        item_id, room_id, name, hint, image_path = it
        # show on canvas
        self.canvas.delete("all")
        self.canvas.create_text(10, 10, anchor="nw", text=f"تمرین: {name}", font=("TkDefaultFont", 18, "bold"))
        self.canvas.create_text(10, 40, anchor="nw", text=f"سرنخ: {hint}")
        if image_path and os.path.exists(image_path):
            self._draw_image_on_canvas(image_path)
        else:
            self.canvas.create_text(20, 70, anchor="nw", text="بدون تصویر برای این آیتم.", fill="gray")
        # log progress
        self.db.log_seen(item_id)
        self.practice_status.config(text=f"آخرین آیتم: {name}")

    def on_closing(self):
        if messagebox.askokcancel("خروج", "آیا مایل به خروج هستید؟"):
            self.db.close()
            self.destroy()


# ---------------------------
# Bootstrap
# ---------------------------
def ensure_assets_example():
    # This function only helps if user has the generated file path known.
    # If you already placed images into assets, it's fine.
    example_src = "/mnt/data/A_2D_digital_illustration_depicts_a_room_within_a_.png"
    if os.path.exists(example_src):
        if not os.path.isdir(ASSETS_DIR):
            os.makedirs(ASSETS_DIR, exist_ok=True)
        dest = os.path.join(ASSETS_DIR, "winged_cat.png")
        try:
            if not os.path.exists(dest):
                with open(example_src, "rb") as rf, open(dest, "wb") as wf:
                    wf.write(rf.read())
        except Exception:
            pass


if __name__ == "__main__":
    ensure_assets_example()
    db = DB()
    # create sample room & item if empty
    if not db.list_rooms():
        r_id = db.add_room("اتاق اول", "اتاق نمونه برای شروع")
        # attempt to add the example image if exists
        example_img = os.path.join(ASSETS_DIR, "winged_cat.png")
        if os.path.exists(example_img):
            db.add_item(r_id, "گربه بالدار", "تصویر گربه با بال طلایی", example_img)
        else:
            db.add_item(r_id, "گربه خیالی", "گربه‌ای با بال طلایی (بدون تصویر)", "")
    app = MemoryPalaceApp(db)
    app.protocol("WM_DELETE_WINDOW", app.on_closing)
    app.mainloop()
