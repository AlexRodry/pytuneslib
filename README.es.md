# pytuneslib

[![PyPI version](https://img.shields.io/pypi/v/pytuneslib.svg)](https://pypi.org/project/pytuneslib/)
[![CI](https://github.com/AlexRodry/pytuneslib/actions/workflows/ci.yml/badge.svg)](https://github.com/AlexRodry/pytuneslib/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

[English](README.md) · **[Español](README.es.md)**

Genera los archivos de biblioteca de iTunes a partir de una carpeta de música: `iTunes Library.itl` (la base de datos binaria que abre iTunes 12.13) y `iTunes Music Library.xml` (la exportación en plist), construidos a partir de la misma biblioteca en memoria.

## Características

- Escanea archivos MP3, M4A (AAC y ALAC), WAV, AIFF y M4B, y lee sus etiquetas con [mutagen](https://mutagen.readthedocs.io/).
- Escribe `iTunes Library.itl` y `iTunes Music Library.xml` con contenido coherente: pistas, álbumes, artistas, listas de reproducción y la lista maestra "Library".
- Lee bibliotecas `.itl` y XML existentes en un modelo de Python, de modo que puedes editar una biblioteca y volver a escribirla.
- Interfaz de línea de comandos y una pequeña API de Python.
- Se niega a escribir en la carpeta de biblioteca de iTunes por defecto.

## Instalación

Requiere Python 3.10 o superior.

```bash
pip install pytuneslib
```

Desde un clon del repositorio, para desarrollo:

```bash
pip install -e ".[dev]"
```

## Inicio rápido: línea de comandos

Crea una biblioteca a partir de una carpeta de música en una carpeta de salida:

```bash
python -m pytuneslib build D:/Music D:/pytuneslib-out/first-try
```

Esto escribe:

```
D:/pytuneslib-out/first-try/
├── iTunes Library.itl
├── iTunes Music Library.xml
└── iTunes Media/          <- carpeta de medios por defecto (la que usará iTunes)
```

Opciones:

| Opción | Efecto |
|---|---|
| `--no-itl` | Escribe solo `iTunes Music Library.xml`. |
| `--include-unsupported` | Escanea también FLAC, OGG, Opus y WMA. iTunes no puede reproducirlos, así que por defecto se omiten. |
| `--kind-locale en\|es` | Idioma del campo "Tipo", por ejemplo `MPEG audio file` (`en`) o `Archivo de audio MPEG` (`es`). Por defecto `en`. |
| `--music-folder RUTA` | Carpeta de medios que se guarda en la biblioteca. Por defecto: `<out_dir>/iTunes Media`. |
| `--path-map ORIGEN=DESTINO` | Reescribe el prefijo de ruta `ORIGEN` de las pistas (como lo ve esta máquina) a `DESTINO` (como lo ve iTunes). Se puede repetir. Ejemplo de Linux a iTunes en Windows: `--path-map "/mnt/nas/music=\\NAS\music"`. |

## Inicio rápido: Python

### Crear una biblioteca

```python
from pytuneslib.builder import build_library

lib, written = build_library("D:/Music", "D:/pytuneslib-out/first-try")
print(len(lib.tracks), "tracks")
print(written["itl"], written["xml"])
```

`build_library` devuelve la `Library` en memoria y un diccionario con las rutas escritas (`"xml"`, y `"itl"` salvo que uses `itl=False`).

### Leer una biblioteca existente

```python
from pytuneslib.itl.reader import read_itl
from pytuneslib.xml_reader import read_xml

lib = read_itl("D:/pytuneslib-out/first-try/iTunes Library.itl")
for track in lib.tracks[:3]:
    print(track.name, "-", track.artist)

lib_xml = read_xml("D:/pytuneslib-out/first-try/iTunes Music Library.xml")
```

### Modificar una biblioteca y escribirla

Este ejemplo añade una lista de reproducción con todas las pistas cuyo género es "Electronic" y escribe el resultado en una carpeta nueva:

```python
from pytuneslib.builder import write_library
from pytuneslib.itl.reader import read_itl
from pytuneslib.model import Playlist

lib = read_itl("D:/pytuneslib-out/first-try/iTunes Library.itl")

next_id = max(p.playlist_id for p in lib.playlists) + 1
electronic = [t.track_id for t in lib.tracks if t.genre == "Electronic"]
lib.playlists.append(Playlist(playlist_id=next_id, name="Electronic", track_ids=electronic))

write_library(lib, "D:/pytuneslib-out/with-playlist", music_folder=lib.music_folder)
```

Pasa `music_folder=lib.music_folder` al reescribir una biblioteca que has leído, para que la carpeta de medios siga siendo la que era. Si no, `write_library` usa `<out_dir>/iTunes Media`.

### Editar un .itl existente en su lugar

`ItlDocument` solo cambia las listas de reproducción que tocas; todos los demás bytes de la biblioteca (pistas, recuentos de reproducción, carpetas, reglas de listas inteligentes, ajustes de vista) se escriben de vuelta tal cual los dejó iTunes. Guardar sin cambios produce un archivo idéntico.

```python
from pytuneslib import ItlDocument

doc = ItlDocument.open("D:/MyLib/iTunes Library.itl")
lib = doc.library  # vista de solo lectura de la Library en su estado actual

folder = doc.add_playlist("Sets", folder=True)
techno = [t.track_id for t in lib.tracks if t.genre == "Techno"]
mix = doc.add_playlist("Friday", techno, parent=folder.persistent_id)

doc.update_playlist(mix.persistent_id, name="Friday mix", track_ids=techno[:30])
doc.update_playlist(mix.persistent_id, parent=None)        # mover al nivel superior
doc.remove_playlist(folder.persistent_id)                   # recursive=True para carpetas no vacías

doc.save("D:/MyLib-edited/iTunes Library.itl")
```

Las listas inteligentes se pueden añadir con sus blobs de reglas en bruto (`smart_info=`, `smart_criteria=`, los mismos bytes que los valores `<data>` del XML); sus reglas nunca se vuelven a codificar.

### Escanear sin escribir

```python
from pytuneslib.scanner import scan

lib = scan("D:/Music", include_unsupported=False, kind_locale="en")
```

### Modelo de datos

Los tres tipos son dataclasses simples en `pytuneslib.model`.

**`Track`**

| Campo | Tipo | Notas |
|---|---|---|
| `track_id` | `int` | Único dentro de la biblioteca. |
| `location` | `str` | Ruta absoluta del archivo. |
| `persistent_id` | `str` | 16 caracteres hexadecimales; aleatorio por defecto. |
| `name`, `artist`, `album_artist`, `album`, `composer`, `genre`, `kind`, `comments` | `str \| None` | Etiquetas. `kind` es la cadena que se muestra, como `MPEG audio file`. |
| `size` | `int` | Bytes. |
| `total_time` | `int` | Milisegundos. |
| `track_number`, `track_count`, `disc_number`, `disc_count`, `year`, `bpm` | `int \| None` | Etiquetas. |
| `bit_rate` (kbps), `sample_rate` (Hz) | `int \| None` | Propiedades de audio. |
| `date_modified`, `date_added` | `datetime` | UTC. |
| `play_count` | `int` | Por defecto `0`. |
| `rating` | `int \| None` | 0–100. |
| `compilation` | `bool` | Por defecto `False`. |
| `grouping`, `work` | `str \| None` | Etiquetas. |
| `loved`, `disliked` | `bool` | Por defecto `False`. |
| `play_date`, `skip_date`, `release_date` | `datetime \| None` | UTC. |
| `skip_count` | `int` | Por defecto `0`. |
| `album_rating` | `int \| None` | 0–100. |
| `sort_name`, `sort_artist`, `sort_album`, `sort_album_artist`, `sort_composer` | `str \| None` | Claves de ordenación. |

**`Playlist`**

| Campo | Tipo | Notas |
|---|---|---|
| `playlist_id` | `int` | Único dentro de la biblioteca. |
| `name` | `str` | |
| `track_ids` | `list[int]` | IDs de las pistas de la lista, en orden. |
| `persistent_id` | `str` | Aleatorio por defecto. |
| `master` | `bool` | `True` para la lista "Library". |
| `distinguished_kind` | `int \| None` | Por ejemplo `4` para la lista Music. |
| `visible` | `bool` | `False` para listas integradas ocultas. Por defecto `True`. |
| `folder` | `bool` | `True` para una carpeta de listas. Sus `track_ids` son la unión de sus hijos. |
| `parent_persistent_id` | `str \| None` | ID persistente de la carpeta que la contiene, si la hay. |
| `smart_info`, `smart_criteria` | `bytes \| None` | Blobs en bruto de la lista inteligente de iTunes, guardados byte a byte. |

**`Library`**

| Campo | Tipo | Notas |
|---|---|---|
| `tracks` | `list[Track]` | |
| `playlists` | `list[Playlist]` | |
| `persistent_id` | `str` | ID persistente de la biblioteca. |
| `application_version` | `str` | Por defecto `"12.13.11.1"`. |
| `music_folder` | `str \| None` | Ruta absoluta de la carpeta de medios de iTunes. |
| `date` | `datetime` | UTC. |

## Abrir la biblioteca en iTunes

1. Cierra iTunes por completo. Comprueba en el Administrador de tareas que `iTunes.exe` ya no se está ejecutando.
2. Mantén pulsada **Mayús (Shift)** mientras inicias iTunes (probado en Windows). Mantenla hasta que aparezca el diálogo.
3. Haz clic en **Choose Library** (Elegir biblioteca) y selecciona el `iTunes Library.itl` generado.
4. iTunes abre la biblioteca generada. Su carpeta de medios es la que elegiste al crearla.

Para volver a tu biblioteca, cierra iTunes y repite los pasos, eligiendo tu `iTunes Library.itl` original.

### Seguridad

- **No apuntes nunca la salida a tu biblioteca real.** La herramienta se niega a usar la carpeta por defecto (`~/Music/iTunes`), pero otras carpetas también pueden contener tu biblioteca real. Usa una carpeta de salida separada.
- **Prueba primero con una copia.** [`docs/VALIDATION.md`](docs/VALIDATION.md) tiene una lista de comprobación paso a paso, que empieza por copiar tu carpeta de biblioteca como respaldo.
- **Desactiva iCloud Music Library y no inicies sesión** en Apple Music mientras pruebas una biblioteca generada.
- **No ejecutes "Organizar biblioteca" ni "Consolidar"** sobre una biblioteca generada, porque mueven archivos.
- **Usa `--music-folder`** si tus medios están en un lugar distinto a la carpeta de salida. Indica dónde busca iTunes los medios.

## Formatos compatibles

| Formato | Lo lee pytuneslib | Se escribe en la biblioteca | Notas |
|---|---|---|---|
| MP3 | Sí | Sí | |
| AAC (M4A, M4B) | Sí | Sí | |
| ALAC (M4A) | Sí | Sí | |
| WAV | Sí | Sí | |
| AIFF | Sí | Sí | |
| FLAC, OGG, Opus, WMA | Solo con `--include-unsupported` | Solo con `--include-unsupported` | iTunes no puede reproducir estos formatos. |

## Limitaciones

- **No modelado:** carátulas. El comando de creación no genera listas inteligentes ni carpetas a partir de una carpeta de música; estas vienen de una biblioteca que lees y reescribes (ver [Editar un .itl existente en su lugar](#editar-un-itl-existente-en-su-lugar)).
- **Listas integradas:** los escritores conservan las listas integradas (Películas, Programas de TV, Podcasts, etc.) que ya tiene la biblioteca.
- **Cola "Up Next":** no se escribe. iTunes 12.13 rechaza una biblioteca que incluya esta sección.
- **Cadenas de tipo:** `Track.kind` usa la cadena en inglés o en español (`--kind-locale`). Otros idiomas no están soportados.
- **Probado solo** con iTunes 12.13.11.1 en Windows (versión de Microsoft Store). Otras versiones y plataformas no están probadas.
- **El formato `.itl` no lo documenta Apple.** Se ha reconstruido por ingeniería inversa; ver [`docs/FORMAT.md`](docs/FORMAT.md).

## Cómo funciona

El archivo `.itl` tiene una cabecera plana de 0x90 bytes con el tamaño del archivo, el ID persistente y los recuentos de pistas de la biblioteca. El resto es un flujo comprimido con zlib, del que los primeros 100 KB van cifrados con AES-128-ECB. Dentro, la biblioteca se guarda en fragmentos little-endian (secciones `msdh` que contienen pistas `mith`, listas `miph` y registros de cadenas y datos `mhoh`). Los registros de cadenas tienen un ID de pool por tipo, y los registros de pista se refieren a álbumes y artistas por ID. La sección de carpeta de medios se reescribe al guardar: iTunes mueve las pistas que estén dentro de otra carpeta de medios a la suya propia al abrir una biblioteca, así que el escritor debe indicar la carpeta que contiene realmente los medios. La descripción completa está en [`docs/FORMAT.md`](docs/FORMAT.md).

## Desarrollo

### Pruebas

```bash
python -m pytest
```

Algunas pruebas generan una biblioteca musical sintética con [ffmpeg](https://ffmpeg.org/). El fixture busca `ffmpeg` primero en el `PATH` y después en `C:\Apps\Tools\ffmpeg\bin\`. Si no está en ninguno, esas pruebas se omiten.

### Estructura del proyecto

```
src/pytuneslib/
  builder.py       # build_library, write_library
  scanner.py       # carpeta de música -> Library (mutagen)
  xml_writer.py    # Library -> XML
  xml_reader.py    # XML -> Library
  itl/             # formato .itl: cifrado, fragmentos, lector, escritor
  model.py         # Track, Playlist, Library
  cli.py           # línea de comandos
tests/             # suite de pytest
docs/              # FORMAT.md (referencia del formato), VALIDATION.md (comprobación manual en iTunes)
```

## Contribuir

Las incidencias y los pull requests son bienvenidos. Antes de abrir un pull request, ejecuta `python -m pytest` y mantén los cambios centrados en una sola cosa. Para cambios de formato, incluye una prueba que lea y escriba los registros afectados, y describe en el pull request cómo lo comprobaste con iTunes.

## Aviso legal

pytuneslib es un proyecto independiente. **No está afiliado, respaldado ni patrocinado por Apple Inc.** iTunes y Apple son marcas registradas de Apple Inc. El formato `.itl` no está documentado; la biblioteca se ofrece tal cual y puede dejar de funcionar con futuras versiones de iTunes. Úsala con copias de tus datos y guarda copias de seguridad de tu biblioteca de iTunes.

## Licencia

MIT. Ver [`LICENSE`](LICENSE).
