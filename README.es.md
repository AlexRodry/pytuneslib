# pytuneslib

[English](README.md) · **Español**

Genera a partir de una carpeta de música dos archivos de biblioteca de iTunes:

- `iTunes Library.itl` — base de datos binaria (cifrada y comprimida) que iTunes 12.13 abre.
- `iTunes Music Library.xml` — plist con los mismos datos.

Lee las etiquetas con [mutagen](https://mutagen.readthedocs.io/) y escribe ambos archivos con la misma biblioteca en memoria.

## Estado

- Lectura y escritura de `.itl` y `.xml` implementadas. Pruebas: `python -m pytest`.
- Round-trip verificado: biblioteca sintética y biblioteca de referencia completa → `.itl` → lectura, sin diferencias.
- iTunes 12.13.11.1 (Windows) aceptó un `.itl` generado a partir de una biblioteca sintética, y su XML re-exportado tenía las rutas correctas.
- Antes de usar un `.itl` generado con una biblioteca real, compruébalo siguiendo [`docs/VALIDATION.md`](docs/VALIDATION.md), sobre una copia.

## Instalación

Requiere Python 3.10 o superior.

```powershell
pip install -e ".[dev]"
```

Para el modo editable hace falta pip >= 21.3 (`python -m pip install -U pip`). La configuración está en `pyproject.toml`.

## Uso desde la línea de comandos

```powershell
python -m pytuneslib build <music_dir> <out_dir> [--no-itl] [--include-unsupported] [--kind-locale en|es] [--music-folder RUTA]
```

| Opción | Efecto |
|---|---|
| `--no-itl` | Escribe solo `iTunes Music Library.xml`. |
| `--include-unsupported` | Incluye también FLAC, OGG, Opus y WMA. iTunes no los reproduce, así que por defecto se omiten. |
| `--kind-locale en\|es` | Idioma de la columna "Tipo" (p. ej. "MPEG audio file" / "Archivo de audio MPEG"). Por defecto `en`. |
| `--music-folder RUTA` | Carpeta de medios de iTunes. Por defecto `<out_dir>\iTunes Media`. |

La herramienta se niega a escribir en la carpeta real de iTunes (`~\Music\iTunes`). Usa siempre una carpeta de salida distinta, por ejemplo `D:\salida\mi-prueba`.

## API de Python

```python
from pytuneslib.builder import build_library, write_library
from pytuneslib.scanner import scan
from pytuneslib.xml_writer import write_xml
from pytuneslib.xml_reader import read_xml
from pytuneslib.itl.reader import read_itl
from pytuneslib.itl.writer import write_itl, itl_bytes

# Carpeta de música -> archivos de biblioteca
lib, written = build_library("D:/Music", "D:/salida/mi-prueba", itl=False)

# Solo escaneo, sin escribir
lib = scan("D:/Music", include_unsupported=False, kind_locale="en")

# Escribir o leer el XML
write_xml(lib, "D:/salida/mi-prueba/iTunes Music Library.xml")
lib2 = read_xml("D:/salida/mi-prueba/iTunes Music Library.xml")

# write_library(lib, out_dir, itl=True) escribe XML y, si itl=True, el .itl
```

`build_library` devuelve `(Library, dict)`, donde el diccionario asocia `"xml"` y, si aplica, `"itl"` con las rutas escritas.

## Pruebas

```powershell
python -m pytest
```

Las pruebas de fixtures generan una biblioteca sintética con [ffmpeg](https://ffmpeg.org/). El fixture busca `ffmpeg` primero en el `PATH` y después en `C:\Apps\Tools\ffmpeg\bin\`. Si no está en ninguno, esas pruebas se omiten.

## Documentación

- [`README.md`](README.md) — guía de usuario en inglés.
- [`docs/FORMAT.md`](docs/FORMAT.md) — descripción pública del formato `.itl`.
- [`docs/VALIDATION.md`](docs/VALIDATION.md) — cómo validar una biblioteca generada en iTunes 12.13 sin tocar la real.
- [`CHANGELOG.md`](CHANGELOG.md) — historial de versiones.

## Resumen del formato `.itl`

Ver [`docs/FORMAT.md`](docs/FORMAT.md). En resumen: cabecera `hdfm` big-endian de 0x90 bytes; payload comprimido con zlib (nivel 1) y cifrado con AES-128-ECB sobre los primeros 100 KB; contenido en bloques little-endian (`msdh`, `mith`, `mhoh`…).

## Limitaciones

- **FLAC, OGG, Opus y WMA** no son reproducibles en iTunes; se omiten salvo `--include-unsupported`.
- **No se modelan** (todavía): carátulas, historial de reproducción, listas inteligentes ni otros campos de iTunes no presentes en las etiquetas.
- El formato `.itl` no está documentado oficialmente. Las pruebas de compatibilidad con iTunes 12.13 deben hacerse manualmente siguiendo `docs/VALIDATION.md`.
- Solo se ha probado con iTunes 12.13.11.1 en Windows (versión de Microsoft Store).

## Licencia

MIT. Ver [`LICENSE`](LICENSE).
