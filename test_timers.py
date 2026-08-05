"""Unit de timers/alarmas: vencimiento con aviso, listado, cancelación."""
import asyncio
import datetime
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from tools import timers

AVISOS = []


async def recorder(text):
    AVISOS.append(text)


async def main():
    timers.ANNOUNCE = recorder

    # timer que vence: avisa y desaparece de pendientes
    r = await timers.set_timer.handler({"minutos": 0.01, "etiqueta": "mate"})
    assert "Timer puesto" in r, r
    assert len(timers.PENDIENTES) == 1
    await asyncio.sleep(1.2)
    assert AVISOS == ["Señor, terminó el timer de mate."], AVISOS
    assert not timers.PENDIENTES

    # alarma con hora ya pasada hoy → queda para mañana
    hace_una_hora = datetime.datetime.now() - datetime.timedelta(hours=1)
    r = await timers.set_alarm.handler(
        {"hora": hace_una_hora.hour, "minuto": hace_una_hora.minute})
    assert "mañana" in r, r

    # listar y cancelar todo
    r = await timers.list_timers.handler({})
    assert "alarma" in r, r
    r = await timers.cancel_timers.handler({})
    assert "Cancelados: 1" in r, r
    assert not timers.PENDIENTES
    r = await timers.list_timers.handler({})
    assert "No hay" in r, r

    # validaciones
    assert "mayores a cero" in await timers.set_timer.handler({"minutos": 0})
    assert "inválida" in await timers.set_alarm.handler({"hora": 25, "minuto": 0})

    print("test_timers OK ✓")


asyncio.run(main())
