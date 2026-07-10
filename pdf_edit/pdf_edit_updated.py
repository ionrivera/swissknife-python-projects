import tkinter as tk
from tkinter import filedialog, messagebox
from PIL import Image, ImageTk
import fitz  # PyMuPDF
import copy

class GeneralPDFEditor:
    def __init__(self, root):
        self.root = root
        self.root.title("Python PDF General Editor")
        self.root.geometry("1200x900")
        
        # --- State Variables ---
        self.doc = None
        self.current_page_idx = 0
        self.active_image_path = ""
        self.img_preview = None
        self.zoom = 1.5 
        
        # Core Data Model: { page_idx: [ list of items ] }
        self.pages_data = {} 
        
        # Undo/Redo Stacks
        self.undo_stack = []
        self.redo_stack = []
        
        # UI & Hover Tracking
        self.canvas_references = {} 
        self.selected_item_data = None
        self.hovered_item = None

        # --- UI: Toolbar ---
        self.toolbar = tk.Frame(root, bd=1, relief=tk.RAISED, bg="#f8f9fa")
        self.toolbar.pack(side=tk.TOP, fill=tk.X)

        tk.Button(self.toolbar, text="📂 Open PDF", command=self.open_pdf).pack(side=tk.LEFT, padx=5, pady=5)
        
        # Image Placement Tools
        tk.Button(self.toolbar, text="🖼️ Load Image", command=self.load_image_file).pack(side=tk.LEFT, padx=5, pady=5)
        self.img_all_pages_var = tk.BooleanVar()
        tk.Checkbutton(self.toolbar, text="Apply to all pages", variable=self.img_all_pages_var, bg="#f8f9fa").pack(side=tk.LEFT, padx=2)
        
        tk.Label(self.toolbar, text=" | Text:", bg="#f8f9fa").pack(side=tk.LEFT)
        self.text_entry = tk.Entry(self.toolbar, width=20)
        self.text_entry.insert(0, "Type Here...")
        self.text_entry.pack(side=tk.LEFT, padx=5)
        tk.Button(self.toolbar, text="➕ Add Text", command=self.add_text_to_canvas).pack(side=tk.LEFT, padx=5)
        self.text_all_pages_var = tk.BooleanVar()
        tk.Checkbutton(self.toolbar, text="Apply to all pages", variable=self.text_all_pages_var, bg="#f8f9fa").pack(side=tk.LEFT, padx=2)

        # Navigation
        tk.Label(self.toolbar, text=" | Page:", bg="#f8f9fa").pack(side=tk.LEFT)
        tk.Button(self.toolbar, text="◀", command=lambda: self.change_page(-1)).pack(side=tk.LEFT)
        self.lbl_page = tk.Label(self.toolbar, text="0 / 0", bg="#f8f9fa", width=5)
        self.lbl_page.pack(side=tk.LEFT)
        tk.Button(self.toolbar, text="▶", command=lambda: self.change_page(1)).pack(side=tk.LEFT)

        # Undo/Redo Buttons
        tk.Button(self.toolbar, text="⤺ Undo", command=self.undo).pack(side=tk.LEFT, padx=5)
        tk.Button(self.toolbar, text="⤻ Redo", command=self.redo).pack(side=tk.LEFT, padx=5)

        tk.Button(self.toolbar, text="💾 Export Final PDF", bg="#c8e6c9", command=self.burn_to_pdf).pack(side=tk.RIGHT, padx=10)

        # --- UI: Scrollable Canvas ---
        self.container = tk.Frame(root)
        self.container.pack(fill="both", expand=True)

        self.v_scroll = tk.Scrollbar(self.container, orient=tk.VERTICAL)
        self.v_scroll.pack(side=tk.RIGHT, fill=tk.Y)
        self.h_scroll = tk.Scrollbar(self.container, orient=tk.HORIZONTAL)
        self.h_scroll.pack(side=tk.BOTTOM, fill=tk.X)

        self.canvas = tk.Canvas(self.container, bg="gray", xscrollcommand=self.h_scroll.set, yscrollcommand=self.v_scroll.set)
        self.canvas.pack(side=tk.LEFT, fill="both", expand=True)

        self.v_scroll.config(command=self.canvas.yview)
        self.h_scroll.config(command=self.canvas.xview)
        
        # Background bindings
        self.canvas.bind("<Button-1>", self.place_image_on_click)
        
        # Global Canvas MouseWheel bind (Fixes the TclError exception)
        self.canvas.bind("<MouseWheel>", self.handle_global_mousewheel)
        
        # Keyboard Shortcuts for Undo/Redo
        self.root.bind("<Control-z>", lambda e: self.undo())
        self.root.bind("<Control-y>", lambda e: self.redo())

    def save_snapshot(self):
        """Saves current annotations layout to history stack for Undo."""
        self.undo_stack.append(copy.deepcopy(self.pages_data))
        self.redo_stack.clear()

    def undo(self):
        if self.undo_stack:
            self.redo_stack.append(copy.deepcopy(self.pages_data))
            self.pages_data = self.undo_stack.pop()
            self.render_page()

    def redo(self):
        if self.redo_stack:
            self.undo_stack.append(copy.deepcopy(self.pages_data))
            self.pages_data = self.redo_stack.pop()
            self.render_page()

    def open_pdf(self):
        path = filedialog.askopenfilename(filetypes=[("PDF Files", "*.pdf")])
        if path:
            self.doc = fitz.open(path)
            self.current_page_idx = 0
            self.pages_data = {i: [] for i in range(len(self.doc))}
            self.undo_stack.clear()
            self.redo_stack.clear()
            self.render_page()

    def render_page(self):
        if not self.doc: return
        page = self.doc[self.current_page_idx]
        mat = fitz.Matrix(self.zoom, self.zoom)
        pix = page.get_pixmap(matrix=mat)
        img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
        self.img_preview = ImageTk.PhotoImage(img)
        
        self.canvas.delete("all")
        self.canvas_references.clear()
        
        # Draw background page
        self.canvas.create_image(0, 0, anchor="nw", image=self.img_preview, tags="bg")
        self.canvas.config(scrollregion=(0, 0, pix.width, pix.height))
        self.lbl_page.config(text=f"{self.current_page_idx + 1} / {len(self.doc)}")
        
        # Render page modifications saved in state
        for item_data in self.pages_data.get(self.current_page_idx, []):
            self.draw_item_to_canvas(item_data)

    def draw_item_to_canvas(self, item_data):
        """Draws structured item dictionary data onto the live Tkinter canvas."""
        cx = item_data['x'] * self.zoom
        cy = item_data['y'] * self.zoom
        
        if item_data['type'] == 'text':
            display_size = int(item_data['size'] * self.zoom)
            c_item = self.canvas.create_text(cx, cy, text=item_data['content'], fill="black", font=("Arial", display_size))
        
        elif item_data['type'] == 'img':
            try:
                img = Image.open(item_data['path'])
                base_w, base_h = img.size
                target_w = int(base_w * item_data['scale'] * self.zoom)
                target_h = int(base_h * item_data['scale'] * self.zoom)
                
                target_w, target_h = max(5, target_w), max(5, target_h)
                img = img.resize((target_w, target_h), Image.Resampling.LANCZOS)
                tk_img = ImageTk.PhotoImage(img)
                
                if not hasattr(self, '_live_imgs'): self._live_imgs = []
                self._live_imgs.append(tk_img)
                
                c_item = self.canvas.create_image(cx, cy, image=tk_img)
            except Exception as e:
                print(f"Error drawing image: {e}")
                return

        # Bind events strictly to this added item
        self.canvas_references[c_item] = item_data
        self.canvas.tag_bind(c_item, "<Button-1>", lambda e, item=c_item: self.select_item(item))
        self.canvas.tag_bind(c_item, "<B1-Motion>", lambda e, item=c_item: self.drag_item(e, item))
        self.canvas.tag_bind(c_item, "<ButtonRelease-1>", lambda e: self.save_snapshot_after_move())
        
        # Safe tracking states for resizing instead of direct MouseWheel tag binding
        self.canvas.tag_bind(c_item, "<Enter>", lambda e, item=c_item: self.set_hovered_item(item))
        self.canvas.tag_bind(c_item, "<Leave>", lambda e: self.clear_hovered_item())

    def set_hovered_item(self, item):
        self.hovered_item = item

    def clear_hovered_item(self):
        self.hovered_item = None

    def handle_global_mousewheel(self, event):
        """Directs global wheel actions to the hovered element."""
        if self.hovered_item is not None:
            self.resize_item(event, self.hovered_item)

    def load_image_file(self):
        if not self.doc: return
        path = filedialog.askopenfilename(filetypes=[("Images", "*.png *.jpg *.jpeg")])
        if path:
            self.active_image_path = path
            messagebox.showinfo("Ready", "Image loaded. Click on the canvas to place it.")

    def place_image_on_click(self, event):
        if not self.active_image_path: return
        
        cx, cy = self.canvas.canvasx(event.x), self.canvas.canvasy(event.y)
        if len(self.canvas.find_overlapping(cx, cy, cx, cy)) > 1: return 

        self.save_snapshot()
        
        pdf_x = cx / self.zoom
        pdf_y = cy / self.zoom
        
        try:
            with Image.open(self.active_image_path) as img:
                w, h = img.size
                base_scale = min(150 / w, 150 / h)
        except:
            base_scale = 1.0

        new_img_item = {
            'type': 'img',
            'x': pdf_x,
            'y': pdf_y,
            'scale': base_scale,
            'path': self.active_image_path
        }

        if self.img_all_pages_var.get():
            for p in range(len(self.doc)):
                self.pages_data[p].append(copy.deepcopy(new_img_item))
        else:
            self.pages_data[self.current_page_idx].append(new_img_item)
            
        self.active_image_path = "" 
        self.render_page()

    def add_text_to_canvas(self):
        if not self.doc: return
        self.save_snapshot()
        
        vx = self.canvas.canvasx(self.canvas.winfo_width()/2) / self.zoom
        vy = self.canvas.canvasy(self.canvas.winfo_height()/2) / self.zoom
        content = self.text_entry.get()
        
        new_text_item = {
            'type': 'text',
            'x': vx,
            'y': vy,
            'size': 14,
            'content': content
        }

        if self.text_all_pages_var.get():
            for p in range(len(self.doc)):
                self.pages_data[p].append(copy.deepcopy(new_text_item))
        else:
            self.pages_data[self.current_page_idx].append(new_text_item)
            
        self.render_page()

    def select_item(self, item):
        self._pre_move_state = copy.deepcopy(self.pages_data)
        self.selected_item_data = self.canvas_references.get(item)

    def drag_item(self, event, item):
        item_data = self.canvas_references.get(item)
        if not item_data: return
        
        cx = self.canvas.canvasx(event.x)
        cy = self.canvas.canvasy(event.y)
        
        item_data['x'] = cx / self.zoom
        item_data['y'] = cy / self.zoom
        self.canvas.coords(item, cx, cy)

    def save_snapshot_after_move(self):
        if hasattr(self, '_pre_move_state'):
            self.undo_stack.append(self._pre_move_state)
            self.redo_stack.clear()
            del self._pre_move_state

    def resize_item(self, event, item):
        item_data = self.canvas_references.get(item)
        if not item_data: return
        
        self.save_snapshot()
        factor = 1.1 if (event.delta > 0) else 0.9
        
        if item_data['type'] == 'text':
            item_data['size'] = max(6, int(item_data['size'] * factor))
        elif item_data['type'] == 'img':
            item_data['scale'] = max(0.05, item_data['scale'] * factor)
            
        self.render_page()

    def change_page(self, delta):
        if not self.doc: return
        self.current_page_idx = max(0, min(len(self.doc)-1, self.current_page_idx + delta))
        self.render_page()

    def burn_to_pdf(self):
        if not self.doc: return
        
        for page_idx in range(len(self.doc)):
            page = self.doc[page_idx]
            items = self.pages_data.get(page_idx, [])
            
            for item in items:
                pdf_x, pdf_y = item['x'], item['y']
                
                if item['type'] == 'text':
                    page.insert_text((pdf_x, pdf_y), item['content'], color=(0,0,0), fontsize=item['size'])
                
                elif item['type'] == 'img':
                    try:
                        with Image.open(item['path']) as img:
                            base_w, base_h = img.size
                        w = base_w * item['scale']
                        h = base_h * item['scale']
                        
                        rect = fitz.Rect(pdf_x - w/2, pdf_y - h/2, pdf_x + w/2, pdf_y + h/2)
                        page.insert_image(rect, filename=item['path'])
                    except Exception as e:
                        print(f"Skipped stamping item: {e}")

        save_path = filedialog.asksaveasfilename(defaultextension=".pdf")
        if save_path:
            self.doc.save(save_path)
            messagebox.showinfo("Saved", "Exported successfully!")

if __name__ == "__main__":
    root = tk.Tk()
    app = GeneralPDFEditor(root)
    root.mainloop()