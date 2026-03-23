"""Build the vendored libvterm cffi module."""

from __future__ import annotations

from pathlib import Path

from cffi import FFI


def binding_dir() -> Path:
    return Path(__file__).resolve().parent


def vendor_root() -> Path:
    return Path(__file__).resolve().parents[4] / "third_party" / "libvterm"


def create_builder() -> FFI:
    root = vendor_root()
    include_dir = root / "include"
    source_dir = root / "src"
    if not include_dir.exists() or not source_dir.exists():
        raise FileNotFoundError(
            "Vendored libvterm sources are missing. Expected third_party/libvterm."
        )
    ffi = FFI()
    ffi.cdef(
        """
        typedef struct VTerm VTerm;
        typedef struct VTermState VTermState;
        typedef struct VTermScreen VTermScreen;
        typedef struct { int row; int col; } VTermPos;
        typedef struct { int start_row; int end_row; int start_col; int end_col; } VTermRect;
        typedef enum { VTERM_DAMAGE_CELL, VTERM_DAMAGE_ROW, VTERM_DAMAGE_SCREEN, VTERM_DAMAGE_SCROLL } VTermDamageSize;
        VTerm *vterm_new(int rows, int cols);
        void vterm_free(VTerm *vt);
        void vterm_get_size(const VTerm *vt, int *rowsp, int *colsp);
        void vterm_set_size(VTerm *vt, int rows, int cols);
        void vterm_set_utf8(VTerm *vt, int is_utf8);
        size_t vterm_input_write(VTerm *vt, const char *bytes, size_t len);
        VTermState *vterm_obtain_state(VTerm *vt);
        void vterm_state_get_cursorpos(const VTermState *state, VTermPos *cursorpos);
        VTermScreen *vterm_obtain_screen(VTerm *vt);
        void vterm_screen_enable_altscreen(VTermScreen *screen, int altscreen);
        void vterm_screen_set_damage_merge(VTermScreen *screen, VTermDamageSize size);
        void vterm_screen_flush_damage(VTermScreen *screen);
        void vterm_screen_reset(VTermScreen *screen, int hard);
        size_t vterm_screen_get_text(const VTermScreen *screen, char *str, size_t len, const VTermRect rect);
        """
    )
    ffi.set_source(
        "cockpit.terminal.bindings._libvterm",
        '#include "vterm.h"',
        include_dirs=[str(include_dir)],
        sources=sorted(str(path) for path in source_dir.glob("*.c")),
    )
    return ffi


if __name__ == "__main__":
    target_name = binding_dir() / "_libvterm.*"
    create_builder().compile(
        tmpdir=str(binding_dir()),
        target=str(target_name),
        verbose=True,
    )
