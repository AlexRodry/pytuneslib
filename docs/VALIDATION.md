# Validar una biblioteca generada en iTunes 12.13 (sin tocar la real)

Objetivo: abrir `out\<lib>\iTunes Library.itl` en iTunes 12.13 (versión de Microsoft Store) como si fuera una biblioteca distinta, comprobar que carga y que los datos son correctos, y volver a tu biblioteca real. **Nunca** elijas ni guardes en `%USERPROFILE%\Music\iTunes\`.

## 0. Antes de empezar

1. Cierra iTunes por completo (menú de iTunes > Salir, o clic derecho en el icono de la bandeja > Salir). Comprueba en el Administrador de tareas que no queda `iTunes.exe`.
2. Haz una copia de seguridad de tu biblioteca real (solo lectura, no la modifica):
   - Copia `%USERPROFILE%\Music\iTunes\` completa a otra carpeta fuera de iTunes, por ejemplo `%USERPROFILE%\Desktop\backup_itunes_YYYYMMDD\`.
   - Opcional pero recomendado: copia también `iTunes Library.itl` y `iTunes Music Library.xml` por separado.
3. Desactiva la sincronización en la nube antes de abrir la biblioteca de prueba: iTunes > Editar > Preferencias > General, y no inicies sesión en Apple Music/iCloud Music Library desde esa biblioteca.
4. Anota la ruta de la biblioteca generada, por ejemplo `...\iTunes Fork\out\<lib>\`. Debe contener `iTunes Library.itl` y `iTunes Music Library.xml`.

## 1. Abrir la biblioteca generada (Shift + inicio)

1. Con iTunes cerrado, mantén pulsada **Mayús (Shift)** y abre iTunes desde el menú Inicio (no desde un acceso fijado en la barra de tareas; si no funciona, usa la lista de programas).
2. Mantén Shift hasta que aparezca el diálogo de elección de biblioteca ("Create Library" / "Choose Library"). Si no aparece, ver sección 5.
3. Pulsa **Choose Library** y navega a `out\<lib>\`. Selecciona `iTunes Library.itl` (o la carpeta, según permita el diálogo).
4. iTunes abre esa biblioteca. Verifica en la barra de título o en Preferencias > Avanzado la ruta de la biblioteca; debe apuntar a `out\<lib>\`.

Fuentes: Apple, guía de iTunes 12 para Windows (ayuda "Crear o elegir biblioteca", Shift al abrir) y iMore, "How to create a new iTunes Library on Windows" (https://imore.com/how-create-new-itunes-library-windows). Ambas describen la versión de escritorio; la versión de Store puede comportarse distinto, por eso el paso 5.

## 2. Qué comprobar

Haz estas comprobaciones en orden. Anota lo que falle.

| # | Comprobación | Cómo | Resultado esperado |
|---|---|---|---|
| 1 | Carga | iTunes abre sin error "The file iTunes Library.itl cannot be read" ni "newer version" | Abre la biblioteca vacía o con pistas |
| 2 | Número de pistas | Canciones > contar, o Archivo > Biblioteca > Mostrar info | Coincide con el número de `<dict>` de pistas en `iTunes Music Library.xml` |
| 3 | Listas | Barra lateral: Listas de reproducción | Aparecen las listas generadas con el número de pistas correcto |
| 4 | Metadatos | Clic derecho en una pista > Información | Título, artista, artista de álbum, álbum, género, año, pista n/N, disco n/N, BPM, comentario coinciden con la fuente |
| 5 | Compilación | Columna "Compilación" o Información > Opciones | Solo la pista marcada como compilación aparece como tal |
| 6 | Pistas sin etiquetas | Busca la pista "08 No Tags" (o similar) | El título es el nombre de archivo; no hay artista ni álbum |
| 7 | Archivos encontrados | Columna "Ubicación" o selección > "Mostrar en el Explorador" | Ninguna pista marcada con el signo de exclamación de "archivo no encontrado" |
| 8 | Rutas no ASCII | Pista en `Beyoncé\Lemonade\` (o la que corresponda) | Se reproduce; el nombre no aparece como `?` o rombos |
| 9 | Rutas con espacios/&/# | Pista en `Rock & Roll #2\Live Set\` | Se reproduce |
| 10 | Formatos | Reproduce una pista de cada: MP3 192k/320k, AAC, ALAC, WAV, AIFF | Suenan; ALAC/AAC/WAV/AIFF y MP3 se importan |
| 11 | FLAC | Pista `.flac` | **Esperado: no soportada por iTunes.** No aparece o aparece con error; no es un fallo del generador. Anota el comportamiento |
| 12 | Reinicio | Cierra iTunes y vuelve a abrirlo con Shift > Choose Library > la misma biblioteca | Los datos persisten |

Si algo falla, copia el texto exacto del error y el nombre de la pista. No intentes arreglarlo editando el `.itl` a mano.

## 3. Volver a tu biblioteca real

1. Cierra iTunes (Salir), comprobando en el Administrador de tareas que `iTunes.exe` ya no está.
2. Abre iTunes con Shift y elige **Choose Library**.
3. Navega a `%USERPROFILE%\Music\iTunes\` y selecciona `iTunes Library.itl` (la original).
4. Comprueba que tu biblioteca real tiene el número de pistas habitual antes de usarla normalmente.

Si iTunes no vuelve a la biblioteca real: no borres nada. Cierra iTunes y restaura desde la copia del paso 0 solo si tienes certeza de qué archivo falta.

## 4. Fallback: `.itl` eliminado + importar XML (no confirmado para este caso)

Lo que documentan los foros para reconstruir una biblioteca es:
- Cierra iTunes, mueve el `iTunes Library.itl` (y el XML) fuera de la carpeta, abre iTunes, y usa **Archivo > Biblioteca > Importar lista de reproducción** para elegir el XML.
- Fuente: Kirkville, "How to rebuild your iTunes library" (https://kirkville.com/how-to-rebuild-your-itunes-library/). Advierte que puede tardar mucho con bibliotecas grandes.

**No confirmado:** que un `.itl` de 0 bytes provoque una reconstrucción automática desde el XML al abrir. No encontré fuente que lo afirme. Otro hilo de Apple Community dice lo contrario: si no hay un `.itl` válido, iTunes crea una biblioteca vacía e ignora el XML. Por tanto, el paso de importación debe hacerse **manualmente**. Prueba siempre en `out\<lib>\`, nunca en la real.

## 5. Si Shift no muestra el diálogo (versión de Store)

- Cierra iTunes del todo y vuelve a intentarlo manteniendo Shift desde el primer clic hasta que aparezca el diálogo.
- Si no aparece: no hay un método documentado para la versión de Store en las fuentes consultadas. Anota el comportamiento y avísame; no pruebes a renombrar o mover la biblioteca real para forzarlo.

## 6. Qué no hace esta prueba

- No valida que iTunes sincronice con un iPhone/iPad.
- No valida Apple Music/iCloud.
- No garantiza que las carpetas de medios se organicen o copien: no uses "Organizar biblioteca" ni "Consolidar" durante la prueba.
