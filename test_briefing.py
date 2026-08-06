"""Check de la puerta del briefing matinal: apagado por default, respeta
días/hora y no dispara uno viejo si la PC arrancó tarde."""
import datetime
import importlib.util
import os

_ruta = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                     "skills", "briefing_matinal.py")
_spec = importlib.util.spec_from_file_location("briefing_matinal", _ruta)
bm = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(bm)


def _lunes(hh, mm):
    return datetime.datetime(2026, 8, 3, hh, mm)   # 2026-08-03 = lunes


def test_toca():
    on = {"activo": True, "hora": "09:00", "dias": [0, 1, 2, 3, 4]}
    casos = [
        ({}, _lunes(9, 0), None, False),                      # default: OFF
        ({**on, "activo": False}, _lunes(9, 0), None, False),
        (on, _lunes(9, 0), None, True),
        (on, _lunes(9, 30), None, True),                      # dentro de hora
        (on, _lunes(8, 59), None, False),                     # todavía no
        (on, _lunes(14, 0), None, False),                     # arrancó tarde
        (on, _lunes(9, 5), _lunes(9, 0).date(), False),       # ya lo dio hoy
        ({**on, "dias": [5, 6]}, _lunes(9, 0), None, False),  # lunes no toca
        ({**on, "dias": []}, _lunes(9, 0), None, False),      # sin días = nunca
        ({"activo": True}, _lunes(9, 0), None, True),         # hora/días default
    ]
    for b, ahora, ultimo, want in casos:
        got = bm._toca(b, ahora, ultimo)
        assert got is want, f"_toca({b}, {ahora}, {ultimo}) = {got}"
    assert bm._hora({"hora": "7:5"}) == (7, 5)
    assert bm._hora({"hora": "banana"}) == (9, 0)   # basura → default
    assert bm._hora({"hora": "99:00"}) == (9, 0)
    print("briefing: puerta OK")


if __name__ == "__main__":
    test_toca()
    print("TODO OK")
