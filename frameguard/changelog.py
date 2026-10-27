"""Notas de cada versión (las muestra la ventana de Novedades al abrir tras actualizar).

Al publicar una versión, añadir su entrada ARRIBA. Tipos: "nuevo", "mejora", "correccion".
Cada punto va en los dos idiomas: (tipo, (título, texto) en español, (título, texto) en inglés)."""
from .i18n import lang

CHANGELOG = [
    {"version": "0.1.9", "date": "2026-10-27", "items": [
        ("nuevo",
         ("En inglés y en español", "Frameguard usa el idioma de Windows del equipo: español si Windows está en "
                                    "español, inglés en cualquier otro idioma. Se puede cambiar en Ajustes → "
                                    "Apariencia → Idioma. El instalador también elige el idioma solo."),
         ("English and Spanish", "Frameguard follows the Windows language of the computer: Spanish if Windows is "
                                 "in Spanish, English for any other language. You can change it in Settings → "
                                 "Appearance → Language. The installer picks its language automatically too.")),
        ("correccion",
         ("Los avisos se van solos", "Ya no hay que cerrarlos a mano: desaparecen tras unos segundos. Su tiempo "
                                     "solo corre mientras usas el PC, así que los avisos de la noche los ves al "
                                     "volver y luego se van."),
         ("Notifications close by themselves", "No need to close them by hand: they disappear after a few seconds. "
                                               "Their timer only runs while you are using the PC, so you still see "
                                               "the overnight ones when you come back.")),
    ]},
    {"version": "0.1.8", "date": "2026-10-14", "items": [
        ("nuevo",
         ("Varias carpetas a la vez", "En Agregar → Carpetas… marca varias con Ctrl o Shift. Frameguard busca dentro "
                                      "de todas y te muestra la lista agrupada por carpeta para elegir qué va a la "
                                      "cola; lo que ya está en la cola se avisa."),
         ("Several folders at once", "In Add → Folders… select several with Ctrl or Shift. Frameguard searches all of "
                                     "them and shows the list grouped by folder so you can choose what goes into the "
                                     "queue; files already queued are flagged.")),
        ("nuevo",
         ("Arrastrar y soltar", "Suelta archivos o carpetas en cualquier parte de la ventana: los .blend entran "
                                "directo a la cola y las carpetas abren la lista para elegir."),
         ("Drag and drop", "Drop files or folders anywhere on the window: .blend files go straight into the queue "
                           "and folders open the list to choose from.")),
        ("nuevo",
         ("Limitar los recursos del PC", "En Ajustes → Rendimiento del PC: el render usa solo el 25, 50 o 75 % del "
                                         "procesador y con prioridad baja, para poder seguir trabajando. Se aplica "
                                         "al momento, también al shot en marcha."),
         ("Limit PC resources", "In Settings → PC performance: rendering uses only 25, 50 or 75 % of the CPU at low "
                                "priority, so you can keep working. It applies immediately, even to the shot being "
                                "rendered.")),
        ("mejora",
         ("Al terminar la cola, con iconos", "Suspender, apagar y reiniciar llevan los iconos de Windows, y por "
                                             "defecto esperan 10 minutos con una cuenta atrás que puedes cancelar o "
                                             "adelantar."),
         ("When the queue finishes, with icons", "Sleep, shut down and restart use the Windows icons and, by "
                                                 "default, wait 10 minutes with a countdown you can cancel or skip.")),
        ("mejora",
         ("Ajustes ordenados por secciones", "Blender, render, rendimiento, al terminar, notificaciones, apariencia y "
                                             "actualizaciones, cada uno en su recuadro."),
         ("Settings in sections", "Blender, render, performance, queue end, notifications, appearance and updates, "
                                  "each in its own box.")),
        ("mejora",
         ("Barra de progreso de líquido", "Más gruesa y como un depósito que se llena: el líquido ondula mientras "
                                          "renderiza y chapotea con cada frame."),
         ("Liquid progress bar", "Thicker and like a tank filling up: the liquid ripples while rendering and "
                                 "splashes with every frame.")),
        ("correccion",
         ("Adiós al botón «Más»", "No abría su menú. Sus opciones (quitar terminados, volver a leer todo, carpeta de "
                                  "logs) están ahora en el menú lateral."),
         ("Goodbye «More» button", "It did not open its menu. Its options (remove finished, re-read everything, logs "
                                   "folder) are now in the side menu.")),
    ]},
    {"version": "0.1.7", "date": "2026-10-09", "items": [
        ("mejora",
         ("Logo nuevo", "Frameguard estrena icono: el fotograma ahora va dentro de un escudo, con relieve. Se ve en "
                        "la ventana, la barra de tareas, la bandeja, el instalador y los archivos .fgq."),
         ("New logo", "Frameguard has a new icon: the film frame now sits inside a shield, with relief. It shows in "
                      "the window, the taskbar, the tray, the installer and .fgq files.")),
    ]},
    {"version": "0.1.6", "date": "2026-10-08", "items": [
        ("mejora",
         ("Botones con onda", "Al pulsar cualquier botón, una onda se expande desde donde hiciste clic."),
         ("Ripple buttons", "Pressing any button sends a ripple out from where you clicked.")),
        ("mejora",
         ("Menús y diálogos animados", "Los menús desplegables, Ajustes, el panel de detalles y las confirmaciones "
                                       "aparecen con un fundido y un pequeño deslizamiento."),
         ("Animated menus and dialogs", "Drop-down menus, Settings, the details panel and confirmations appear with "
                                        "a fade and a small slide.")),
        ("mejora",
         ("La cola cobra vida", "Los shots nuevos entran expandiéndose, al quitarlos se pliegan, y al terminar "
                                "destellan en verde (en rojo si fallan)."),
         ("A livelier queue", "New shots expand into the list, removed ones fold away, and finished shots flash "
                              "green (red if they fail).")),
        ("mejora",
         ("Progreso más vivo", "Las barras avanzan suave y brillan mientras renderizan; los números de arriba "
                               "cuentan; el punto del motor late durante el render."),
         ("Livelier progress", "Bars move smoothly and shine while rendering; the numbers at the top count up; the "
                               "engine dot pulses during the render.")),
        ("mejora",
         ("Detalles suaves", "Interruptores que se deslizan, estados que cambian de color con un pulso y fundido al "
                             "cambiar entre tema claro y oscuro."),
         ("Smooth details", "Sliding switches, status labels that change colour with a pulse, and a fade when "
                            "switching between light and dark themes.")),
        ("nuevo",
         ("Ajuste «Animaciones»", "En Ajustes puedes apagarlas (útil por escritorio remoto). Ninguna afecta al "
                                  "render: con la cola quieta la ventana no consume nada."),
         ("«Animations» setting", "You can turn them off in Settings (handy over remote desktop). None of them "
                                  "affects rendering: with the queue idle the window uses nothing.")),
    ]},
    {"version": "0.1.5", "date": "2026-10-08", "items": [
        ("nuevo",
         ("Vaciar la cola", "Botón «Vaciar cola» sobre la lista. Si la cola está renderizando, quita todos los shots "
                            "menos el que se está renderizando. Quitar de uno en uno sigue igual."),
         ("Clear the queue", "«Clear queue» button above the list. While rendering, it removes every shot except "
                             "the one being rendered. Removing one by one still works.")),
        ("nuevo",
         ("Novedades al actualizar", "Después de cada actualización verás esta ventana con lo nuevo. En Ajustes → "
                                     "«Notas de la versión» tienes el historial completo."),
         ("What's new after updating", "After each update you will see this window with what's new. Settings → "
                                       "«Release notes» has the full history.")),
        ("mejora",
         ("Casillas con ✓", "Las casillas activadas muestran un chulito, no solo el color."),
         ("Checkboxes with ✓", "Checked boxes show a tick, not just a colour.")),
        ("mejora",
         ("Flechas en los campos numéricos", "Intentos, minutos y segundos en Ajustes tienen flechas ▲▼ para subir o "
                                             "bajar el valor; los desplegables, su flecha."),
         ("Arrows on number fields", "Attempts, minutes and seconds in Settings have ▲▼ arrows to raise or lower the "
                                     "value; drop-downs have their arrow.")),
    ]},
    {"version": "0.1.4", "date": "2026-10-08", "items": [
        ("nuevo",
         ("Avisos con sonido", "Tarjeta en la esquina y sonido propio al terminar cada shot, al terminar la cola y "
                               "cuando un shot falla. Se configuran en Ajustes → Notificaciones."),
         ("Notifications with sound", "A card in the corner and its own sound when each shot finishes, when the "
                                      "queue finishes and when a shot fails. Set them up in Settings → "
                                      "Notifications.")),
    ]},
    {"version": "0.1.3", "date": "2026-10-08", "items": [
        ("correccion",
         ("La ventana se cerraba sola", "En la 0.1.2 la ventana se cerraba al cambiar de tamaño. Corregido, y ahora "
                                        "un error puntual ya no cierra la ventana."),
         ("The window closed by itself", "In 0.1.2 the window closed when resized. Fixed, and a one-off error no "
                                         "longer closes the window.")),
    ]},
    {"version": "0.1.2", "date": "2026-10-08", "items": [
        ("nuevo",
         ("Guardar y abrir colas", "Archivos .fgq con rango, modo y escena de cada shot. Colas recientes y doble clic "
                                   "en un .fgq para abrirlo."),
         ("Save and open queues", ".fgq files with each shot's range, mode and scene. Recent queues, and double-click "
                                  "a .fgq to open it.")),
        ("nuevo",
         ("Menú hamburguesa", "Panel lateral animado con cola, agregar y herramientas."),
         ("Hamburger menu", "Animated side panel with queue, add and tools.")),
        ("mejora",
         ("Última carpeta usada", "Agregar archivos o carpetas abre donde lo dejaste la última vez."),
         ("Last folder used", "Adding files or folders opens where you left off last time.")),
    ]},
    {"version": "0.1.1", "date": "2026-10-08", "items": [
        ("mejora",
         ("Icono nuevo", "Inspirado en Blender, con un fotograma en el centro."),
         ("New icon", "Inspired by Blender, with a film frame in the middle.")),
        ("nuevo",
         ("Quitar desde la fila", "Papelera al final de cada shot (además del clic derecho)."),
         ("Remove from the row", "A bin at the end of each shot (as well as the right-click menu).")),
        ("mejora",
         ("Panel de detalles por secciones", "Escena, progreso, salidas, avisos y render."),
         ("Details panel in sections", "Scene, progress, outputs, warnings and render.")),
    ]},
    {"version": "0.1.0", "date": "2026-10-08", "items": [
        ("nuevo",
         ("Primera versión", "Motor independiente de la ventana, frames verificados en disco, reintentos solo de lo "
                             "que falta, chequeo previo, informe y apagado al terminar."),
         ("First version", "Engine independent from the window, frames verified on disk, retries of only what is "
                           "missing, pre-flight check, report and shutdown when done.")),
    ]},
]

_MONTHS_EN = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")


def items(entry: dict, language: str | None = None) -> list[tuple[str, str, str]]:
    """Puntos de una versión en el idioma actual: [(tipo, título, texto)]."""
    i = 2 if (language or lang()) == "en" else 1
    return [(it[0], *it[i]) for it in entry["items"]]


def date(entry: dict, language: str | None = None) -> str:
    """14/10/2026 en español, Oct 14, 2026 en inglés."""
    y, m, d = (int(x) for x in entry["date"].split("-"))
    return f"{_MONTHS_EN[m - 1]} {d}, {y}" if (language or lang()) == "en" else f"{d:02d}/{m:02d}/{y}"


def _key(v: str) -> tuple:
    return tuple(int(x) for x in v.split("."))


def versions_after(last_seen: str | None, current: str) -> list[dict]:
    """Entradas nuevas desde la última versión vista (incluida la actual)."""
    out = [e for e in CHANGELOG if _key(e["version"]) <= _key(current)]
    if last_seen:
        try:
            out = [e for e in out if _key(e["version"]) > _key(last_seen)]
        except ValueError:
            out = out[:1]
    else:
        out = out[:1]
    return out
