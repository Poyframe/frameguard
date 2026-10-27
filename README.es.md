# Frameguard

**Una cola de render nocturna para Blender que no se detiene cuando algo falla.**

*[Read in English](README.md)*

Renderizar varios `.blend` de noche suele significar un `.bat` con una línea `blender -b archivo.blend -a` por
shot, una hoja de cálculo para saber qué está listo y cruzar los dedos. Si Blender se cae a las 3 de la mañana
(un reinicio del driver de la GPU, falta de memoria, un frame congelado), el resto de la noche se pierde y te
enteras por la mañana.

Frameguard lo cambia por una cola visual que vigila mientras duermes:

- **Una cola en lugar de un .bat.** Arrastra archivos `.blend` o carpetas enteras; de cada archivo toma la versión
  más alta (`_V03` antes que `_V02`). Reordena shots, ajusta rangos y guarda la cola (`.fgq`) para reabrirla
  cuando necesites volver a renderizar.
- **Progreso real, contado en disco.** Un shot termina cuando todos sus frames están en disco, recién escritos y
  no vacíos. Se cuentan los archivos que escriben tus nodos **File Output**, así que funciona también con
  *Save Output* apagado, incluidos los montajes de varias escenas en el compositor (capas de render de varias
  escenas, Cycles o EEVEE, en un único EXR multicapa).
- **Recuperación automática.** Si Blender se cae o se congela, Frameguard lo vuelve a lanzar y renderiza **solo los
  frames que faltan**, y luego sigue con el siguiente shot. Blender corre desde un motor aparte, en segundo plano:
  cerrar la ventana no detiene nada, y tras un reinicio la cola continúa desde el último frame verificado.
- **Antes de irte a dormir:** chequeo previo (texturas o archivos enlazados que faltan, sin cámara, sin salidas),
  informe al terminar la cola, avisos con sonido y apagar / suspender / reiniciar al terminar (con cuenta atrás
  para cancelarlo).
- **Seguir trabajando mientras renderiza:** límite opcional de cuánto procesador usa Blender, con prioridad baja.

La interfaz está en **español e inglés** (sigue el idioma de Windows; se puede cambiar en Ajustes).

## Descarga

Descarga el instalador desde [Releases](../../releases) y ejecútalo. Se instala por usuario, sin permisos de
administrador. Al actualizar se conservan la cola, los ajustes y los logs. Desde la 0.2.0, Frameguard avisa
cuando sale una versión nueva y la instala con un clic (se puede desactivar en Ajustes → Actualizaciones).

- Solo **Windows 10/11**.
- **Blender:** desarrollado y probado con Blender 5.2 (usa la API del compositor de la serie 5). Encuentra solo
  las instalaciones de `Program Files\Blender Foundation`, o puedes elegir `blender.exe` en Ajustes.
- El instalador **todavía no está firmado digitalmente**: Windows SmartScreen puede avisar la primera vez.
  Pulsa *Más información → Ejecutar de todas formas*.

## Cómo se hizo

Frameguard lo creó **Claude** (la IA de [Anthropic](https://www.anthropic.com)) en **Claude Code**, bajo la
dirección de [@Poyframe](https://github.com/Poyframe), artista de iluminación y render.

- **Dirección (@Poyframe):** los problemas reales de producción, las decisiones de diseño y la prueba de cada
  versión con shots reales.
- **Desarrollo (Claude):** el código, el instalador y las pruebas automáticas.

## Cómo funciona

- **Dos procesos:** la ventana (`Frameguard.exe`) y el motor (`Frameguard.exe --engine`). La cola vive en el
  motor. Si la ventana se cierra o se cuelga, el render sigue, y al reabrirla se ve el progreso. Si el motor
  muere, al volver retoma desde el último frame verificado.
- **Un shot termina** cuando todos sus frames están **verificados en disco**. Si Blender termina pero no se
  cierra, se cierra a la fuerza tras `exit_grace_seconds` y la cola sigue.
- **Fallos:** si Blender se cae o se congela (`stall_minutes` sin señales de vida), se reintenta **solo desde los
  frames que faltan**. Tras `max_attempts` intentos el shot queda como "Falló" y la cola continúa.
- **Seguridad:** el script de arranque (`blender_scripts/fg_render_bootstrap.py`) corre dentro de Blender antes de
  renderizar. Blender se lanza con `--python-exit-code 87`: si el script falla, Blender se cierra **sin
  renderizar**; si empieza a renderizar sin haberlo cargado, el motor lo mata. El `.blend` nunca se guarda.
- El render se lanza por tramos `-s/-e/-a`, así que respeta *Persistent Data* de Cycles.
- El límite de CPU usa la afinidad y la prioridad del proceso. **No** limita la GPU ni la RAM.

### Datos (no se borran al actualizar ni al desinstalar)

`%APPDATA%\Frameguard\`: `queue.json` (la cola y los ajustes), `logs\` (un log por intento), `informes\`,
`engine.log`, `ui.log` y `*_crash.log`. Las preferencias de la ventana (tema, idioma, últimas carpetas) van al
registro, en `HKCU\Software\Frameguard`.

## Desarrollo

```bash
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
.venv\Scripts\python.exe -m frameguard            # ventana (arranca el motor si no está)
.venv\Scripts\python.exe -m frameguard --engine   # solo el motor
```

Variables útiles:
- `FRAMEGUARD_HOME`: otra carpeta de datos (y las preferencias de la ventana en un `.ini` dentro), para pruebas.
- `FRAMEGUARD_LANG=es|en`: fuerza el idioma.
- `FRAMEGUARD_DRY_POWER=1`: no apaga ni suspende de verdad.

### Idiomas

Los textos se escriben en español en el código, envueltos en `tr("...")`, y su traducción está en
`frameguard/i18n_en.py`. `tools/check_i18n.py` comprueba que no falte ninguna y que las variables `{x}`
coincidan. Las notas de versión (`frameguard/changelog.py`) llevan cada punto en los dos idiomas.

### Pruebas

- `tools/smoke_test.ps1 -Blend <.blend>`: la ventana real contra un motor aislado (normal, menú y panel).
- `tools/pruebas/capturas.py [--exe ...] [--lang en|es]`: render real, límite de CPU y una captura de cada pantalla.
- `tools/pruebas/arrastre.py`: arrastre real desde otro programa (mueve el ratón unos segundos).
- `tools/pruebas/avisos.py`: los avisos se van solos solo con el usuario presente.
- `tools/pruebas/cpu.py --exe ...`: consumo de la ventana en reposo, renderizando y minimizada.
- `tools/pruebas/actualizaciones.py [--exe ...]`: avisos de GitHub y de la carpeta contra un servidor local que
  imita a GitHub (descarga, errores, prioridad de la carpeta y nunca durante un render).

El `.blend` de prueba lo genera `tools/make_fixture.py` (las pruebas lo crean solas si falta). Todas usan su
propia carpeta de datos y nunca tocan la cola, los ajustes ni el registro del usuario.

## Compilar el instalador

```bash
powershell -ExecutionPolicy Bypass -File build.ps1
```

Genera `dist\installer\Frameguard-Setup-<versión>.exe`. Requiere Inno Setup 6. No compila si
`tools\check_names.py` encuentra nombres sin definir o `tools\check_i18n.py` encuentra textos sin traducir.

## Publicar una actualización

1. Subir `__version__` en `frameguard/__init__.py` y añadir la entrada en `frameguard/changelog.py`.
2. Ejecutar `build.ps1`.
3. **GitHub** (llega a todos): crear la release `vX.Y.Z` con `Frameguard-Setup-X.Y.Z.exe` adjunto. Las notas
   van en inglés, una línea `---` y luego en español, con los puntos como `- **Título:** texto`: de ahí sale el
   resumen del aviso en cada idioma.
4. **Red local** (opcional): copiar `Frameguard-Setup-X.Y.Z.exe` a la carpeta de actualizaciones configurada en
   **Ajustes** (opcionalmente con un `Frameguard-X.Y.Z-novedades.txt`).
5. Frameguard (desde la 0.2.0) lo comprueba al abrir y cada 6 horas y muestra un aviso: **Actualizar ahora**,
   **Más tarde** u **Omitir esta versión**. Si la carpeta tiene la misma versión que GitHub o una más nueva, manda
   la carpeta; si no, el instalador se descarga de GitHub a `%TEMP%` (con progreso y comprobando tamaño y
   SHA-256). Sin internet no avisa de nada. GitHub se puede desactivar en **Ajustes → Actualizaciones**.
   La instalación va encima de la anterior (AppId fijo) y nunca durante un render. Para volver atrás:
   **Ajustes → Versiones…** (con la carpeta).

### Edición interna (sin GitHub)

Para los PC de un estudio que no deben conectarse a internet para actualizarse:

```bash
powershell -ExecutionPolicy Bypass -File build.ps1 -SinGitHub
```

Genera `dist\installer-interna\Frameguard-Setup-X.Y.Z.exe`. Ese `.exe` se compila **sin** el módulo
`frameguard/github_updates.py`, así que no tiene ningún código que se conecte a GitHub: solo se actualiza desde la
carpeta de la red. `build.ps1` comprueba el contenido del `.exe` y no termina si el módulo se cuela. En Ajustes no
aparece la casilla de GitHub, y las Novedades muestran los puntos de esa edición (ver `frameguard/changelog.py`).
`tools/pruebas/interna.py` lo verifica con un «GitHub» falso que cuenta las peticiones.

## Licencia

Ver [LICENSE](LICENSE). El instalador incluye [Qt for Python (PySide6)](https://doc.qt.io/qtforpython/), usado
bajo la LGPL-3.0.

Blender es una marca registrada de la Blender Foundation. Frameguard es un proyecto independiente, sin relación
ni respaldo de la Blender Foundation.
