# FreEvnia

**Control no oficial y de código abierto para monitores Philips Evnia en Linux**: cambia de entrada y
activa o desactiva **PBP / PIP** desde tu PC, sin el Evnia Precision Center (que solo existe para Windows).

> Sin relación con Philips ni TPV, ni respaldado por ellos. "Philips" y "Evnia" son marcas de sus
> propietarios y se usan solo para decir con qué monitores funciona.

![Ventana de FreEvnia](docs/gui.png)

## Por qué existe

El Philips Evnia 49M2C8900L solo acepta los cambios de entrada, PBP y PIP **por USB**, no por el canal DDC
de siempre: con `ddcutil` las lecturas funcionan, pero las escrituras a la fuente de entrada se aceptan sin
error y se ignoran. FreEvnia habla directamente con el hub USB del monitor.

Cómo funciona y cómo se descubrió: [PROTOCOL.md](PROTOCOL.md) (en inglés).

## Estado

Probado en un solo monitor: **Philips Evnia 49M2C8900L, firmware 1.08**.

| Funciona (verificado en el panel) | Sin verificar / sin hacer |
|---|---|
| Leer modelo, firmware y valores VCP | PBP 2, PBP 3 |
| Pantalla completa / **PBP** / **PIP** | Intercambiar las dos imágenes |
| PIP en las 4 esquinas y 3 tamaños | HDMI como fuente *principal* |
| Segundo cuadro: USB-C, HDMI 1, HDMI 2 (PBP y PIP) | Otros modelos Evnia |

## Instalación

```bash
sudo apt install libusb-1.0-0
python3 -m venv .venv && . .venv/bin/activate
pip install -e ".[gui]"
sudo cp udev/99-freevnia.rules /etc/udev/rules.d/ && sudo udevadm control --reload
sudo udevadm trigger --subsystem-match=usb --attr-match=idVendor=2109   # tu usuario en el grupo plugdev
```

El **cable USB de subida del monitor debe estar conectado a este equipo**.

## Uso

```bash
freevnia info
freevnia mode pbp1                       # PBP: este PC a la izquierda, USB-C a la derecha
freevnia mode pip --position lower-left --size large
freevnia mode off                        # pantalla completa
freevnia-gui                             # la ventana
```

## Aviso importante

* **El monitor manda su USB (KVM) a la imagen principal, la de la izquierda.** Si pones *otro* aparato como
  fuente principal, este equipo pierde el hub y **no puede volver**: hará falta el mando.
* Siempre se sabe si hay PBP/PIP activo (`0xE6`). El modo, la esquina y el tamaño solo se leen si los pusiste
  desde FreEvnia; lo que eliges con el **mando no se puede leer** (el monitor no lo informa).
* Escribe en la configuración del monitor. Usa los mismos comandos que el programa oficial, pero es software
  alfa: **úsalo bajo tu responsabilidad**, sin garantía (ver [LICENSE](LICENSE)).

## Próximos pasos

Control del **Ambiglow** (la luz trasera, otro dispositivo USB), PBP 2 y 3, intercambio de imágenes,
otros modelos, y empaquetado (PyPI, AUR, Flatpak) y widget de Plasma.

## Licencia

MIT. [English README](README.md).

## Ambiglow

`freevnia ambiglow color red|#ff8800 [--zone all|sides|top|center] [--brightness 50]`, `off`, `release`, `rainbow`, `breathe <color>`, `status`; la ventana tiene un panel de color. Los presets del OSD no se pueden leer ni elegir por USB: tras `release` los LEDs quedan apagados hasta que elijas un preset en el OSD. Ver PROTOCOL.md.
