import ctypes
import os
import tkinter as tk

ICONE_APP = "icons8-coordenada-z-48.ico"


def configurar_dpi():
    if os.name == "nt":
        try:
            myappid = "jadlog.automacao.total.app.1.3"
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(myappid)
            ctypes.windll.shcore.SetProcessDpiAwareness(2)
        except Exception:
            pass


def definir_icone(janela):
    if os.path.exists(ICONE_APP):
        try:
            janela.iconbitmap(ICONE_APP)
        except Exception:
            pass


class BotaoArredondado3D(tk.Canvas):
    def __init__(
        self,
        master,
        text,
        command=None,
        width=190,
        height=36,
        depth=6,
        cor_base="#D31145",
        cor_hover="#E61A54",
        cor_sombra="#8E0B2E",
        cor_texto="white",
        font=("Segoe UI", 9, "bold"),
        bg_app="#FFFFFF",
        **kwargs,
    ):
        super().__init__(
            master,
            width=width,
            height=height + depth,
            bg=bg_app,
            highlightthickness=0,
            **kwargs,
        )
        self.command = command
        self.pressed = False
        self.enabled = True
        self.depth = depth
        self.cor_base = cor_base
        self.cor_hover = cor_hover
        self.cor_sombra = cor_sombra

        self.sombra_ids = self._draw_capsule(0, depth, width, height, self.cor_sombra)
        self.topo_ids = self._draw_capsule(0, 0, width, height, self.cor_base)
        self.texto_id = self.create_text(
            width // 2, height // 2, text=text, fill=cor_texto, font=font
        )

        self.bind("<ButtonPress-1>", self.on_press)
        self.bind("<ButtonRelease-1>", self.on_release)
        self.bind("<Enter>", self.on_enter)
        self.bind("<Leave>", self.on_leave)

    def _draw_capsule(self, x, y, w, h, color):
        r = h / 2
        o1 = self.create_oval(x, y, x + 2 * r, y + h, fill=color, outline=color, width=1)
        o2 = self.create_oval(x + w - 2 * r, y, x + w, y + h, fill=color, outline=color, width=1)
        rct = self.create_rectangle(
            x + r - 1, y, x + w - r + 1, y + h, fill=color, outline=color, width=1
        )
        return [o1, o2, rct]

    def config_state(self, state, text=None):
        if state == tk.DISABLED:
            self.enabled = False
            for item in self.topo_ids:
                self.itemconfig(item, fill="#A0AEC0", outline="#A0AEC0")
            for item in self.sombra_ids:
                self.itemconfig(item, fill="#718096", outline="#718096")
        else:
            self.enabled = True
            for item in self.topo_ids:
                self.itemconfig(item, fill=self.cor_base, outline=self.cor_base)
            for item in self.sombra_ids:
                self.itemconfig(item, fill=self.cor_sombra, outline=self.cor_sombra)
        if text:
            self.itemconfig(self.texto_id, text=text)

    def on_enter(self, event):
        if self.enabled:
            self.config(cursor="hand2")
            for item in self.topo_ids:
                self.itemconfig(item, fill=self.cor_hover, outline=self.cor_hover)

    def on_leave(self, event):
        self.config(cursor="")
        if self.enabled:
            for item in self.topo_ids:
                self.itemconfig(item, fill=self.cor_base, outline=self.cor_base)
        if self.pressed and self.enabled:
            for item in self.topo_ids:
                self.move(item, 0, -self.depth)
            self.move(self.texto_id, 0, -self.depth)
            self.pressed = False

    def on_press(self, event):
        if self.enabled:
            for item in self.topo_ids:
                self.move(item, 0, self.depth)
            self.move(self.texto_id, 0, self.depth)
            self.pressed = True

    def on_release(self, event):
        if self.pressed and self.enabled:
            for item in self.topo_ids:
                self.move(item, 0, -self.depth)
            self.move(self.texto_id, 0, -self.depth)
            self.pressed = False
            if self.command:
                self.after(50, self.command)
