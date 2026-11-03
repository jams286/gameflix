// Reproductor: arma EmulatorJS para un juego y mantiene la partida del perfil en el servidor.
//
// Save del cartucho: EmulatorJS lo deja en su sistema de archivos (guardado en IndexedDB) con el
// nombre de la ROM. La ROM se pide como "p<perfil>-j<juego>.<ext>", así cada perfil tiene su
// propio archivo aunque compartan dispositivo. Al arrancar se trae el del servidor; mientras se
// juega se revisa cada pocos segundos y se sube cuando cambia (y al salir o cambiar de app).
//
// Estados: los botones de guardar/cargar estado del menú de EmulatorJS abren nuestras ranuras.
//
// Tiempo jugado: mientras el juego corre a la vista (sin pausa) se cuentan los segundos y se
// avisan al servidor cada minuto; solo sirve para sugerir juegos, no se muestra en ningún lado.
(() => {
  const API = "api/";
  const DATOS_EMULADOR = "emulatorjs/";
  const CADA_CUANTO_MS = 10000;     // revisión del save mientras se juega
  const MAX_KEEPALIVE = 60000;      // los navegadores no dejan más en un fetch "keepalive"
  const TICK_TIEMPO_MS = 5000;      // cada cuánto se revisa si el juego está corriendo
  const AVISO_TIEMPO_S = 60;        // cada cuántos segundos jugados se avisan al servidor

  const $ = (id) => document.getElementById(id);
  const params = new URLSearchParams(location.search);
  const juegoId = Number(params.get("j"));
  const ranuraInicial = Number(params.get("estado")) || 0;

  let perfil = null;
  let juego = null;
  let ultimoSha = null;      // sha1 del último save que tiene el servidor
  let cola = Promise.resolve();   // las subidas van de una en una
  let saliendo = false;      // la página se está ocultando: la subida va con keepalive
  let eligioRanura = false;
  let temporizadorAviso = 0;
  let pausadoPorMi = false;
  let segundosSinAvisar = 0;

  // ---------- Utilidades ----------

  async function pedir(ruta, opciones = {}) {
    const respuesta = await fetch(API + ruta, { cache: "no-store", ...opciones });
    if (respuesta.status === 401) {
      location.href = "./#perfiles";
      throw new Error("Elige tu perfil otra vez");
    }
    return respuesta;
  }

  async function pedirJson(ruta, opciones) {
    const respuesta = await pedir(ruta, opciones);
    const datos = await respuesta.json().catch(() => ({}));
    if (!respuesta.ok) throw new Error(datos.error || `Error ${respuesta.status}`);
    return datos;
  }

  function crear(etiqueta, clase, texto) {
    const el = document.createElement(etiqueta);
    if (clase) el.className = clase;
    if (texto !== undefined) el.textContent = texto;
    return el;
  }

  async function sha1(bytes) {
    const hash = await crypto.subtle.digest("SHA-1", bytes);
    return [...new Uint8Array(hash)].map((b) => b.toString(16).padStart(2, "0")).join("");
  }

  // Un save "en blanco" (todo 0x00 o todo 0xFF): la memoria del cartucho antes de que el juego guarde
  function enBlanco(bytes) {
    const primero = bytes[0];
    return (primero === 0 || primero === 0xff) && bytes.every((b) => b === primero);
  }

  function avisar(texto) {
    const aviso = $("aviso");
    aviso.textContent = texto;
    aviso.hidden = false;
    clearTimeout(temporizadorAviso);
    temporizadorAviso = setTimeout(() => { aviso.hidden = true; }, 2500);
  }

  function marcarSync(estado, texto) {
    $("sync").dataset.estado = estado;
    $("sync").textContent = texto;
  }

  function mostrarError(texto) {
    $("error").textContent = texto;
    $("error").hidden = false;
  }

  const hora = new Intl.DateTimeFormat("es", { hour: "numeric", minute: "2-digit" });

  // Lo que el servidor ya tiene, por perfil y juego: sirve para saber si el save local es más nuevo
  const claveSync = () => `gameflix.sync.${perfil.id}.${juegoId}`;
  function leerSync() {
    try { return localStorage.getItem(claveSync()); } catch { return null; }
  }
  function guardarSync(sha) {
    try { localStorage.setItem(claveSync(), sha); } catch { /* sin almacenamiento */ }
  }

  // ---------- Save del cartucho ----------

  function emulador() {
    return window.EJS_emulator && window.EJS_emulator.gameManager;
  }

  function escribirSaveLocal(bytes) {
    const gm = emulador();
    const ruta = gm.getSaveFilePath();
    let carpeta = "";
    for (const parte of ruta.split("/").slice(1, -1)) {
      carpeta += "/" + parte;
      if (!gm.FS.analyzePath(carpeta).exists) gm.FS.mkdir(carpeta);
    }
    if (gm.FS.analyzePath(ruta).exists) gm.FS.unlink(ruta);
    gm.FS.writeFile(ruta, bytes);
    gm.loadSaveFiles();
  }

  function subirSave(bytes) {
    if (!bytes || !bytes.length) return cola;
    const keepalive = saliendo && bytes.length < MAX_KEEPALIVE;
    cola = cola.then(() => subirSaveAhora(bytes, keepalive));
    return cola;
  }

  async function subirSaveAhora(bytes, keepalive) {
    const sha = await sha1(bytes);
    if (sha === ultimoSha) return;
    if (ultimoSha === null && enBlanco(bytes)) return;   // nada que guardar todavía
    const anterior = ultimoSha;
    ultimoSha = sha;
    marcarSync("subiendo", "Guardando…");
    try {
      const respuesta = await pedir(`juegos/${juegoId}/save`, { method: "PUT", body: bytes, keepalive });
      if (!respuesta.ok) throw new Error((await respuesta.json().catch(() => ({}))).error || respuesta.status);
      guardarSync(sha);
      marcarSync("ok", `☁ Guardado ${hora.format(new Date())}`);
    } catch (e) {
      ultimoSha = anterior;   // la próxima revisión lo vuelve a intentar
      marcarSync("error", "⚠ Sin guardar");
      console.warn("No se pudo subir el save", e);
    }
  }

  // Pide a EmulatorJS que escriba el save del cartucho; llega por el evento "saveSaveFiles"
  function revisarSave() {
    const gm = emulador();
    if (gm && window.EJS_emulator.started) gm.saveSaveFiles();
  }

  async function traerSave() {
    const gm = emulador();
    const ruta = gm.getSaveFilePath();
    const local = gm.FS.analyzePath(ruta).exists ? gm.FS.readFile(ruta) : null;
    const shaLocal = local ? await sha1(local) : null;
    const respuesta = await pedir(`juegos/${juegoId}/save`);
    if (respuesta.status === 204) {
      // El servidor no tiene nada: si en este dispositivo quedó algo de este perfil, se sube
      if (local) await subirSave(local);
      if (ultimoSha) marcarSync("ok", "☁ Partida al día");
      return;
    }
    if (!respuesta.ok) throw new Error(`No se pudo traer la partida (${respuesta.status})`);
    const remoto = new Uint8Array(await respuesta.arrayBuffer());
    const shaRemoto = respuesta.headers.get("X-Sha1") || (await sha1(remoto));
    const sincronizado = leerSync();
    if (local && shaLocal !== shaRemoto && shaRemoto === sincronizado && shaLocal !== sincronizado) {
      // Lo local es más nuevo (la última subida no llegó): gana lo local
      ultimoSha = shaRemoto;
      await subirSave(local);
      return;
    }
    ultimoSha = shaRemoto;
    guardarSync(shaRemoto);
    if (shaLocal !== shaRemoto) {
      escribirSaveLocal(remoto);
      gm.restart();   // que el juego arranque leyendo la partida del servidor
    }
    marcarSync("ok", "☁ Partida al día");
  }

  // ---------- Estados (ranuras) ----------

  function pausar() {
    if (!window.EJS_emulator.paused) {
      window.EJS_emulator.pause();
      pausadoPorMi = true;
    }
  }

  function reanudar() {
    if (pausadoPorMi) window.EJS_emulator.play();
    pausadoPorMi = false;
  }

  async function abrirRanuras(modo, estado, captura) {
    pausar();
    eligioRanura = false;
    let datos;
    try {
      datos = await pedirJson(`juegos/${juegoId}`);
    } catch (e) {
      avisar(e.message);
      reanudar();
      return;
    }
    const dialogo = $("dialogo-ranuras");
    $("ranuras-titulo").textContent = modo === "guardar" ? "¿En qué ranura lo guardo?" : "¿Qué estado cargo?";
    const cont = $("ranuras");
    cont.replaceChildren();
    for (let n = 1; n <= datos.ranuras; n++) {
      const guardado = datos.estados.find((e) => e.ranura === n);
      const boton = crear("button", "ranura" + (guardado ? " ranura-llena" : ""));
      boton.type = "button";
      boton.disabled = modo === "cargar" && !guardado;
      const imagen = crear("span", "ranura-imagen");
      if (guardado) {
        const img = crear("img");
        img.src = `${API}juegos/${juegoId}/estados/${n}/captura?t=${encodeURIComponent(guardado.creado)}`;
        img.alt = "";
        img.onerror = () => img.remove();
        imagen.append(img);
      } else {
        imagen.textContent = "Vacía";
      }
      const pie = crear("span", "ranura-pie");
      pie.append(crear("span", "", guardado ? `${n} · ${hora.format(new Date(guardado.creado))}` : `Ranura ${n}`));
      boton.append(imagen, pie);
      boton.addEventListener("click", async () => {
        if (modo === "guardar" && guardado && !confirm(`¿Reemplazar el estado de la ranura ${n}?`)) return;
        eligioRanura = true;   // la acción reanuda el juego al terminar
        dialogo.close();
        if (modo === "guardar") await guardarEstado(n, estado, captura);
        else await cargarEstado(n);
      });
      cont.append(boton);
    }
    dialogo.showModal();
  }

  async function guardarEstado(n, estado, captura) {
    const largo = new Uint8Array(4);
    new DataView(largo.buffer).setUint32(0, captura ? captura.length : 0);
    const cuerpo = new Blob([largo, captura || new Uint8Array(0), estado]);
    try {
      const respuesta = await pedir(`juegos/${juegoId}/estados/${n}`, { method: "PUT", body: cuerpo });
      if (!respuesta.ok) throw new Error((await respuesta.json().catch(() => ({}))).error || respuesta.status);
      avisar(`Estado guardado en la ranura ${n}`);
    } catch (e) {
      avisar(`No se pudo guardar el estado: ${e.message}`);
    }
    reanudar();
  }

  async function cargarEstado(n) {
    try {
      const respuesta = await pedir(`juegos/${juegoId}/estados/${n}`);
      if (!respuesta.ok) throw new Error(respuesta.status === 404 ? "esa ranura está vacía" : respuesta.status);
      emulador().loadState(new Uint8Array(await respuesta.arrayBuffer()));
      avisar(`Estado ${n} cargado`);
    } catch (e) {
      avisar(`No se pudo cargar el estado: ${e.message}`);
    }
    reanudar();
  }

  $("ranuras-cancelar").addEventListener("click", () => $("dialogo-ranuras").close());
  $("dialogo-ranuras").addEventListener("close", () => { if (!eligioRanura) reanudar(); });

  // ---------- Tiempo jugado ----------

  function contarTiempo() {
    const ejs = window.EJS_emulator;
    if (document.visibilityState === "visible" && ejs && ejs.started && !ejs.paused) {
      segundosSinAvisar += TICK_TIEMPO_MS / 1000;
    }
    if (segundosSinAvisar >= AVISO_TIEMPO_S) avisarTiempo(false);
  }

  function avisarTiempo(keepalive) {
    const segundos = Math.round(segundosSinAvisar);
    if (segundos < 5) return Promise.resolve();
    segundosSinAvisar = 0;
    return pedir(`juegos/${juegoId}/tiempo`, {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ segundos }), keepalive,
    }).catch(() => { /* no es grave: solo se pierde ese minuto para las sugerencias */ });
  }

  // ---------- EmulatorJS ----------

  async function alArrancar() {
    const ejs = window.EJS_emulator;
    try {
      await traerSave();
    } catch (e) {
      marcarSync("error", "⚠ Sin conexión");
      console.warn(e);
    }
    if (ranuraInicial) await cargarEstado(ranuraInicial);
    ejs.on("saveSaveFiles", (bytes) => { if (bytes) subirSave(bytes); });
    setInterval(revisarSave, CADA_CUANTO_MS);
    setInterval(contarTiempo, TICK_TIEMPO_MS);
  }

  function arrancarEmulador() {
    Object.assign(window, {
      EJS_player: "#juego",
      EJS_core: juego.core,
      EJS_gameUrl: `${API}juegos/${juegoId}/rom/p${perfil.id}-j${juegoId}${juego.ext}`,
      EJS_gameName: `${juego.titulo} (${perfil.nombre})`,
      EJS_pathtodata: DATOS_EMULADOR,
      EJS_language: "es-ES",
      EJS_startButtonName: "▶ Jugar",
      EJS_color: "#e50914",
      EJS_backgroundColor: "#000",
      EJS_disableDatabases: true,     // la ROM y el núcleo no se guardan aparte en el navegador
      EJS_defaultOptions: { "save-save-interval": "0" },   // de eso se encarga revisarSave()
      EJS_Buttons: {
        netplay: false, cacheManager: false, saveSavFiles: false, loadSavFiles: false,
        quickSave: false, quickLoad: false, screenRecord: false, exitEmulation: false,
      },
      EJS_onGameStart: alArrancar,
      EJS_onSaveState: async ({ state }) => {
        let captura = null;
        try { captura = await emulador().screenshot(); } catch { /* sin captura */ }
        abrirRanuras("guardar", state, captura);
      },
      EJS_onLoadState: () => abrirRanuras("cargar"),
    });
    if (juego.caratula) {
      // Absoluta: EmulatorJS le antepone su carpeta (emulatorjs/) a las rutas relativas
      window.EJS_backgroundImage = new URL(`${API}juegos/${juegoId}/caratula?v=${juego.caratula}`, location.href).href;
      window.EJS_backgroundBlur = true;
    }
    const script = document.createElement("script");
    script.src = DATOS_EMULADOR + "loader.js";
    document.body.append(script);
  }

  // ---------- Audio en iPhone ----------
  // iOS calla el audio web (el que usa el emulador) cuando el iPhone está en silencio, como si
  // fuera un sonido de notificación. Pidiendo audio de "reproducción" suena igual que un video.

  // iOS 17 o más nuevo
  if (navigator.audioSession) {
    try { navigator.audioSession.type = "playback"; } catch { /* no se pudo: queda el truco de abajo */ }
  }

  // iOS más viejos: un audio silencioso en bucle, iniciado con un toque, cambia la sesión a reproducción
  function wavSilencioso() {
    const muestras = 800;   // 0.1 s a 8 kHz, 8 bits, mono
    const datos = new DataView(new ArrayBuffer(44 + muestras));
    const texto = (pos, s) => [...s].forEach((c, i) => datos.setUint8(pos + i, c.charCodeAt(0)));
    texto(0, "RIFF"); datos.setUint32(4, 36 + muestras, true); texto(8, "WAVE");
    texto(12, "fmt "); datos.setUint32(16, 16, true); datos.setUint16(20, 1, true); datos.setUint16(22, 1, true);
    datos.setUint32(24, 8000, true); datos.setUint32(28, 8000, true); datos.setUint16(32, 1, true);
    datos.setUint16(34, 8, true); texto(36, "data"); datos.setUint32(40, muestras, true);
    for (let i = 0; i < muestras; i++) datos.setUint8(44 + i, 128);   // 128 = silencio en 8 bits
    return URL.createObjectURL(new Blob([datos.buffer], { type: "audio/wav" }));
  }

  let silencio = null;
  function alTocar() {
    const esIos = /iP(hone|ad|od)/.test(navigator.userAgent) ||
      (navigator.platform === "MacIntel" && navigator.maxTouchPoints > 1);   // iPad se presenta como Mac
    if (esIos && !navigator.audioSession && !silencio) {
      silencio = new Audio(wavSilencioso());
      silencio.loop = true;
      silencio.setAttribute("playsinline", "");
      silencio.play().catch(() => { silencio = null; });   // se reintenta en el próximo toque
    }
    // Si iOS dejó el audio en pausa (p. ej. al volver de otra app), se reanuda con el toque
    const ctx = window.EJS_emulator?.Module?.AL?.currentCtx?.audioCtx;
    if (ctx && ctx.state !== "running") ctx.resume().catch(() => {});
  }
  document.addEventListener("touchend", alTocar, true);
  document.addEventListener("click", alTocar, true);

  // ---------- Salir ----------

  async function salir() {
    $("salir").disabled = true;
    marcarSync("subiendo", "Guardando…");
    revisarSave();   // el evento llega al tiro y deja la subida en la cola
    await Promise.all([cola, avisarTiempo(false)]);
    location.href = juego ? `./#mundo/${juego.consola}` : "./#catalogo";
  }

  $("salir").addEventListener("click", salir);

  // Al cambiar de app o apagar la pantalla en el celular puede que no se vuelva: se guarda ya
  document.addEventListener("visibilitychange", () => {
    saliendo = document.visibilityState === "hidden";
    if (saliendo) {
      revisarSave();
      avisarTiempo(true);
    }
  });

  // ---------- Arranque ----------

  (async () => {
    if (!juegoId) {
      location.href = "./";
      return;
    }
    try {
      const sesion = await pedirJson("perfiles");
      if (!sesion.actual) {
        location.href = "./#perfiles";
        return;
      }
      perfil = sesion.actual;
      juego = (await pedirJson(`juegos/${juegoId}`)).juego;
    } catch (e) {
      mostrarError(`No se pudo abrir el juego: ${e.message}`);
      return;
    }
    document.title = `${juego.titulo} · Gameflix`;
    $("titulo").textContent = juego.titulo;
    arrancarEmulador();
  })();
})();
