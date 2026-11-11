"""Licencia de las skills pagas de HARVIS (tienda en PayPal).

Un solo módulo parametrizado por skill: la lógica estaba TRIPLICADA (idiomas,
notas_vault, reuniones) sin un test, y cada copia arrastraba sus propios bugs.
Las skills nuevas usan esto; las tres viejas migran cuando se las toque.

Uso:

    LIC = licencia.Licencia("macros", "la skill de scripts")

    def setup(cfg):
        LIC.cargar(cfg)

    async def alguna_tool(args):
        ok, motivo = await LIC.ok()
        if not ok:
            return motivo
        ...

Qué protege y qué no: el endpoint de validación es PÚBLICO (no lleva API key),
así que puede viajar en el archivo que recibe el comprador. Nada de esto es un
candado — el check es Python borrable. Hace que el camino perezoso sea pagar.
"""
import asyncio
import json
import logging
import os
import time
import urllib.error
import urllib.parse
import urllib.request

log = logging.getLogger("kloom.licencia")

_VALIDATE = "https://harvis-store.kloomstudio.com.ar/v1/licenses/validate"
_ACTIVATE = "https://harvis-store.kloomstudio.com.ar/v1/licenses/activate"
_CADA = 12 * 3600            # revalidar dos veces por día, no en cada uso
_TOPE_OFFLINE = 30 * 86400   # techo sin ver a la tienda ni una vez (licencia sin fin)
_MARGEN_RELOJ = 6 * 3600     # husos y NTP mueven el reloj unas horas
_DIR = os.path.dirname(os.path.abspath(__file__))


def _post(url: str, campos: dict) -> dict:
    datos = urllib.parse.urlencode(campos).encode()
    req = urllib.request.Request(url, data=datos,
                                 headers={"Accept": "application/json",
                                          "User-Agent": "HARVIS/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        # la tienda responde los rechazos (key mala, límite de activaciones) como
        # 4xx CON JSON: eso es una respuesta, no un problema de conexión.
        try:
            return json.load(e)
        except Exception:
            raise


class Licencia:
    def __init__(self, skill: str, descripcion: str = ""):
        self.skill = skill
        self.desc = descripcion or f"la skill {skill}"
        self.estado_file = os.path.join(_DIR, "skills",
                                        f"_{skill}_licencia.json")
        self._lic = {"key": "", "ok": False, "check": 0.0}

    # ---------------------------------------------------------------- disco
    def _leer(self) -> dict:
        try:
            with open(self.estado_file, encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}

    def _escribir(self, d: dict) -> None:
        try:
            os.makedirs(os.path.dirname(self.estado_file), exist_ok=True)
            with open(self.estado_file, "w", encoding="utf-8") as f:
                json.dump(d, f)
        except OSError:
            log.debug("no pude guardar el estado de licencia", exc_info=True)

    # --------------------------------------------------------------- config
    def cargar(self, cfg: dict) -> bool:
        """La key se pega una vez en config.yaml, bajo skills.<skill>.key."""
        scfg = (cfg.get("skills") or {}).get(self.skill) or {}
        self._lic["key"] = str(scfg.get("key", "")).strip()
        if not self._lic["key"]:
            log.info("%s: sin key en config, la skill queda inactiva",
                     self.skill)
            return False
        # El último resultado sobrevive al reinicio: sin esto, arrancar sin
        # internet dejaba afuera a alguien que pagó.
        est = self._leer()
        if est.get("key") == self._lic["key"]:
            self._lic.update({"ok": bool(est.get("ok")),
                              "check": float(est.get("check", 0))})
        return True

    @property
    def hay_key(self) -> bool:
        return bool(self._lic["key"])

    # ---------------------------------------------------------------- tienda
    def _activar(self, key: str) -> tuple[str, str]:
        """Registra ESTA máquina como instancia → (instance_id, motivo). El
        límite (3 máquinas) lo pone la tienda: una key compartida con diez
        amigos muere en la cuarta."""
        import platform
        d = _post(_ACTIVATE, {"license_key": key, "skill": self.skill,
                              "instance_name": platform.node() or "harvis"})
        if d.get("activated"):
            return str((d.get("instance") or {}).get("id") or ""), ""
        err = str(d.get("error") or "no se pudo activar")
        if "limit" in err.lower():
            return "", ("esta clave ya está activada en el máximo de "
                        "máquinas permitido. Escribinos a "
                        "kloomstudio@zohomail.com y liberamos una")
        return "", err

    def _validar(self, key: str, inst: str) -> tuple[bool, str, str]:
        """(vale, motivo, vence_iso). vence_iso vacío = sin vencimiento."""
        campos = {"license_key": key, "skill": self.skill}
        if inst:
            campos["instance_id"] = inst
        d = _post(_VALIDATE, campos)
        lk = d.get("license_key") or {}
        vence = str(lk.get("expires_at") or "")
        if not d.get("valid"):
            motivo = str(d.get("error") or "la licencia no está activa")
            # instancia borrada del panel → reactivar en el próximo intento
            if "instance" in motivo.lower():
                return False, "_reactivar", vence
            return False, "la licencia no está activa", vence
        estado = str(lk.get("status") or "").lower()
        # SOLO "active": notas_vault aceptaba "inactive" y regalaba la skill.
        if estado == "active":
            return True, "", vence
        return False, f"la licencia figura como {estado or 'inactiva'}", vence

    @staticmethod
    def _epoch(iso: str) -> float:
        if not iso:
            return 0.0
        try:
            import datetime
            return datetime.datetime.fromisoformat(
                iso.replace("Z", "+00:00")).timestamp()
        except Exception:
            return 0.0

    # -------------------------------------------------------------- offline
    def _offline(self, ahora: float) -> tuple[bool, str]:
        """Sin internet se decide con el vencimiento que dejó la tienda la última
        vez. El reloj de la PC se puede tocar: se guarda la fecha más alta
        vista y un reloj anterior a eso obliga a revalidar."""
        est = self._leer()
        if not est.get("ok") or est.get("key") != self._lic["key"]:
            return False, ("No puedo verificar la licencia y todavía no la "
                           "validé ni una vez. Fijate la conexión.")
        if ahora < float(est.get("visto", 0)) - _MARGEN_RELOJ:
            return False, ("Necesito chequear la licencia y no me puedo "
                           "conectar. Conectate un momento; ojo que la fecha "
                           "de la computadora está atrasada.")
        vence = float(est.get("vence", 0))
        if vence:
            if ahora > vence:
                return False, ("Se venció el período que tenías pago. "
                               "Conectate para que chequee la licencia.")
            return True, ""
        # compra única (sin vencimiento): tolera un mes sin conexión
        if ahora - float(est.get("check", 0)) < _TOPE_OFFLINE:
            return True, ""
        return False, ("Hace más de un mes que no puedo verificar la "
                       "licencia. Conectate una vez y sigue todo igual.")

    # ----------------------------------------------------------------- API
    def cache_ok(self) -> tuple[bool, str]:
        """Versión SIN red, para lugares que no pueden esperar 10 s ni son
        async: el panel del HUD y las hotkeys globales. Usa lo último que
        dijo la tienda; el watcher de la skill lo refresca al arrancar."""
        if not self._lic["key"]:
            return False, (f"Falta la clave de {self.desc}: se compra en la "
                           "tienda del panel.")
        ahora = time.time()
        if self._lic["ok"] and 0 <= ahora - self._lic["check"] < _CADA:
            return True, ""
        return self._offline(ahora)

    async def ok(self) -> tuple[bool, str]:
        if not self._lic["key"]:
            return False, (f"Falta la clave de {self.desc}. Se compra en la "
                           "tienda del panel y se pega en config.yaml, en "
                           f"skills, {self.skill}, key.")
        ahora = time.time()
        # `0 <=` es la cota que faltaba: con el reloj de Windows para atrás,
        # ahora-check daba negativo y NUNCA revalidaba (bypass gratis).
        if self._lic["ok"] and 0 <= ahora - self._lic["check"] < _CADA:
            return True, ""
        try:
            est = self._leer()
            inst = str(est.get("inst") or "") \
                if est.get("key") == self._lic["key"] else ""
            if not inst:
                inst, err = await asyncio.to_thread(self._activar,
                                                    self._lic["key"])
                if not inst:
                    self._lic.update({"ok": False, "check": ahora})
                    return False, f"No pude usar la licencia: {err}."
            ok, motivo, vence_iso = await asyncio.to_thread(
                self._validar, self._lic["key"], inst)
            if motivo == "_reactivar":
                inst, err = await asyncio.to_thread(self._activar,
                                                    self._lic["key"])
                if inst:
                    ok, motivo, vence_iso = await asyncio.to_thread(
                        self._validar, self._lic["key"], inst)
                else:
                    ok, motivo = False, err
            self._lic.update({"ok": ok, "check": ahora})
            self._escribir({"key": self._lic["key"], "ok": ok, "check": ahora,
                            "inst": inst, "vence": self._epoch(vence_iso),
                            # nunca retrocede: ancla contra el reloj
                            "visto": max(ahora, float(est.get("visto", 0)))})
            return (True, "") if ok else (False, f"No puedo usar {self.desc}: "
                                                 f"{motivo}.")
        except Exception as e:
            log.info("licencia %s sin conexión (%s): decido offline",
                     self.skill, str(e)[:80])
            return self._offline(ahora)
