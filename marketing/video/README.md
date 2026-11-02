# SPIKE · Proyecto audiovisual editable (LAUNCH1)

Proyecto de producción separado del motor de SPIKE. Contiene **25 composiciones Remotion**: master español de 180 s,
master con textos/subtítulos EN y voz ES, promos de 30/60 s, vertical de 30 s, diez clips de 10 s y diez referencias fijas.
1920×1080 a 30 fps; vertical 1080×1920. La app no importa este proyecto ni instala Remotion al arrancar.

**Estado real:** código compilado, referencias de montaje y guiones preparados. No hay capturas del candidato integrado,
narración grabada, sincronización definitiva ni vídeo final. Todas las escenas llevan «Visión del producto». Las
referencias muestran explícitamente el lugar de la captura; no representan una interfaz de SPIKE ya terminada.

## Abrir y comprobar

```sh
cd marketing/video
npm ci --ignore-scripts --no-audit --no-fund
npm test
npm run check
npm run preflight
npm run studio
```

Instalación autorizada como herramienta de producción en esta tarea; paquetes fijados en `package-lock.json`.
`npm run studio` abre el editor local. No llama a servicios de IA ni compra licencias. Leer los avisos de Remotion y
confirmar las condiciones del operador antes de producir material comercial. No añadir claves en este proyecto.

```sh
npm run bundle
npm run captions
```

El bundle va en `out/bundle`; las 26 pistas SRT (master, promos y diez clips × ES/EN) en `out/subtitles`. Los nombres
`.draft.srt` significan tiempos estimados del texto, **no sincronización con voz real**. La marca solo cambia cuando
se aportan tiempos revisados y la revisión editorial correspondiente. No acelerar la voz larga para encajar un clip.
Los clips tienen su propio texto corto en `clipNarration` y su propia pista `voice.clip`.

Referencias PNG, una detrás de otra, con un Chromium ya instalado:

```sh
SPIKE_VIDEO_BROWSER=/ruta/a/chromium npm run references
```

En PowerShell usar `$env:SPIKE_VIDEO_BROWSER = 'C:\ruta\chrome.exe'` y después `npm run references`.
No descarga navegador automáticamente. La galería abre en `out/references/index.html`. Son fotogramas ligeros de
previsualización, no un render largo del master. El vídeo final espera a que se liberen los recursos del entrenamiento.

## Sustituir los materiales provisionales

1. Claude selecciona el commit integrado y el recorrido probado en `docs/release/catalog.json`. El Mac graba con datos
   de ejemplo propios, sin credenciales, conversaciones privadas ni escritorio personal. Gemini revisa foco, tamaño de
   texto, estados vacíos y errores. Conservar las grabaciones completas para comprobar cualquier aceleración/corte.
2. Añadir medios bajo `public/captures/`, voz bajo `public/voice/`, pruebas bajo `public/evidence/`. Estos directorios
   están ignorados por Git deliberadamente. Compartir un paquete revisado aparte; no subir datos personales.
3. Editar `src/content.json`: `capture` admite `{path, kind: "image" | "video", frames, speed, reviewed, sha256}`;
   los frames describen la duración a 30 fps, con vídeo suficiente para la escena. Solo `speed >= 1`; las aceleraciones
   muestran ×N. Se usa `objectFit: contain` para no recortar controles, también en vertical.
4. `voice.master` y `voice.clip`: `{path, frames, reviewed, sha256}`. Conservar la voz separada de la captura y medir su
   duración real con una herramienta de medios; no inventar `frames`. El preflight comprueba metadatos y hash, **no
   decodifica el vídeo ni mide su duración real**. Probar el medio en Remotion y reproducir el archivo final completo.
5. `captions.es/en` y `clipCaptions.es/en`: lista de `{from, to, text}` relativa al inicio de la escena en frames,
   alineada con voz grabada. Máximo 90 caracteres por bloque, sin superposiciones; ajustar saltos y ritmo en pantalla.
   Revisar traducción y sincronización antes de poner `captionsReviewed: true`.
6. Mantener `status: "vision"` salvo evidencia real de todo lo anunciado en ese plano. `verified` exige
   `releaseRevision` (SHA completo), `evidence: {path, sha256}` y captura revisada; el revisor debe comprobar el contenido.
   El hash no verifica la calidad ni la autenticidad de una demostración. Actualizar también la narración si la
   demostración pasa de visión futura a capacidad efectivamente validada.
7. `licenseReviewed` solo se cambia tras comprobar las condiciones aplicables a quien produce el vídeo y los derechos
   de todos los recursos. No es un permiso para publicar. Claude revisa funciones/mediciones; Joan autoriza publicación.

Exportación final por variante, después de completar los materiales y las revisiones:

```sh
npm run render:master
npm run render:promo30
npm run render:promo60
npm run render:vertical30
```

Estos comandos pasan primero el preflight de su variante y usan un único trabajador de render. No eliminan los límites
físicos de RAM: no ejecutarlos durante otro trabajo pesado. Es posible usar Remotion directamente para borradores,
pero saltarse el preflight no convierte un borrador en material revisado. No hay publicación ni gasto automático.

## Guion, voz y dirección visual

Guiones completos en `src/content.json`; instrucciones por capítulo en `SHOTLIST.md`. Voz: español natural y claro,
misma persona durante todo el vídeo, registro cercano y seguro, sin tono exagerado de anuncio. Leer SPIKE como «spaik»,
Dev como «dev», Forge de forma coherente; pronunciar MCP como «eme ce pe». Grabar cada capítulo por separado con
pequeñas pausas al inicio/final; escucha humana para ajustar términos, respiraciones y énfasis. No clonar la voz de una
persona sin autorización ni activar servicios externos de voz desde estos scripts.

Transiciones y animaciones se calculan a partir del frame: entrada suave, aparición secuencial de pasos, corte con
fundido breve; sin animaciones CSS ni tiempos dependientes del reloj. Texto, títulos y etiquetas son capas editables.
El original `public/spike-logo-original.png` se copia sin modificar de `brand/spike-logo-original.png`. Los colores son
crema #FDFDFA, menta #E3FADA, verde #88D445 y verde oscuro #052E1E. Inter se sirve localmente con su licencia OFL.

Reproducir de principio a fin master, diez clips y cada versión promocional. Revisar especialmente legibilidad del
código/controles, límites de texto, recortes verticales, desajustes de voz, pérdida de permiso en la historia y la
veracidad de «comprobado». Un still correcto no demuestra que todo el vídeo reproduzca bien.

## Licencias y fuentes

[Remotion 4.0.539](https://www.remotion.dev/docs/license/pricing) se usa únicamente para producción separada: particulares
y pequeñas empresas pueden estar cubiertos por su licencia gratuita, sujeta a sus condiciones; comprobar elegibilidad,
especialmente si se produce para terceros. No se redistribuye su código como parte del motor SPIKE ni se ha contratado
servicio. Código de este proyecto original; dependencias con sus licencias propias, no relicenciadas por SPIKE.
[Audio](https://www.remotion.dev/docs/media/audio), [vídeo](https://www.remotion.dev/docs/media/video) y
[render](https://www.remotion.dev/docs/cli/render): documentación oficial consultada. Fuente Inter: copia del paquete ya
usado en la app, texto completo en `public/Inter-LICENSE.txt`. Cactus: identidad propia del fundador, sin redibujarlo.
