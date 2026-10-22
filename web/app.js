(() => {
  const API = "api/";   // relativo: /gameflix/api/ (nginx -> servicio en 8777)
  const CLAVE_DENTRO = "gameflix.dentro";   // sessionStorage: ya eligió perfil en esta visita
  const CONSOLAS = {
    nes: "NES", snes: "Super Nintendo", gb: "Game Boy", gbc: "Game Boy Color", gba: "Game Boy Advance",
  };
  const AVATARES = ["🎮", "🦖", "🐱", "🐶", "🦊", "🐼", "🐸", "🦄", "🐙", "🐲", "👾", "🤖",
                    "👻", "🚀", "⚽", "🍄", "⭐", "🔥", "🌈", "🍕", "🎸", "🏎️", "🧙", "🥷"];
  const COLORES = ["#e50914", "#2e86ab", "#7fb069", "#a15dd1", "#f2a541", "#d6457b", "#17a398", "#6c757d"];
  const MAX_LADO_CARATULA = 1000;   // px; las más grandes se achican antes de subir

  const $ = (id) => document.getElementById(id);
  const vistas = { perfiles: $("vista-perfiles"), catalogo: $("vista-catalogo"), admin: $("vista-admin") };

  let perfiles = [];
  let actual = null;      // perfil con sesión en este dispositivo
  let catalogo = null;    // { perfil, consolas: [...], seguir: [ids] }
  let juegos = new Map(); // id -> juego (de todas las consolas)
  let editandoJuego = null;
  let editandoPerfil = null;   // null = perfil nuevo
  let elegido = { avatar: AVATARES[0], color: COLORES[0] };
  let temporizadorAviso = 0;

  // ---------- Utilidades ----------

  async function pedir(ruta, opciones = {}) {
    const esJson = opciones.body && !(opciones.body instanceof Blob);
    const respuesta = await fetch(API + ruta, {
      cache: "no-store",
      ...opciones,
      headers: esJson ? { "Content-Type": "application/json" } : {},
      body: esJson ? JSON.stringify(opciones.body) : opciones.body,
    });
    const datos = await respuesta.json().catch(() => ({}));
    if (respuesta.status === 401) {
      // La sesión ya no vale (le pusieron PIN al perfil, o se cerró): de vuelta a elegir perfil
      actual = null;
      salirDeVisita();
      location.hash = "#perfiles";
    }
    if (!respuesta.ok) throw new Error(datos.error || `Error ${respuesta.status}`);
    return datos;
  }

  function crear(etiqueta, clase, texto) {
    const el = document.createElement(etiqueta);
    if (clase) el.className = clase;
    if (texto !== undefined) el.textContent = texto;
    return el;
  }

  function avatar(perfil, clase = "") {
    const el = crear("span", `avatar ${clase}`, perfil.avatar);
    el.style.setProperty("--color", perfil.color);
    el.setAttribute("aria-hidden", "true");
    return el;
  }

  function urlCaratula(juego) {
    return `${API}juegos/${juego.id}/caratula?v=${juego.caratula}`;
  }

  // Cartucho con la carátula como etiqueta (o una etiqueta armada con el título)
  function cartucho(juego) {
    const caja = crear("span", "cartucho-caja");
    const plastico = crear("span", `cartucho cartucho-${juego.consola}`);
    const etiqueta = crear("span", "etiqueta");
    if (juego.caratula) {
      const img = crear("img");
      img.src = urlCaratula(juego);
      img.alt = "";
      img.loading = "lazy";
      img.decoding = "async";
      etiqueta.append(img);
    } else {
      const vacia = crear("span", "etiqueta-vacia");
      vacia.append(crear("b", "", juego.titulo), crear("small", "", CONSOLAS[juego.consola]));
      etiqueta.append(vacia);
    }
    plastico.append(etiqueta);
    caja.append(plastico);
    return caja;
  }

  function fondoDe(juego) {
    const fondo = crear("div", "destacado-fondo");
    if (juego.caratula) fondo.style.setProperty("--fondo-destacado", `url("${urlCaratula(juego)}")`);
    else fondo.style.setProperty("--fondo-destacado", `var(--${juego.consola}-etiqueta)`);
    return fondo;
  }

  const formatoFecha = new Intl.DateTimeFormat("es", { day: "numeric", month: "short", hour: "numeric", minute: "2-digit" });

  function cuando(iso) {
    const fecha = new Date(iso);
    const minutos = Math.round((Date.now() - fecha) / 60000);
    if (minutos < 1) return "hace un momento";
    if (minutos < 60) return `hace ${minutos} min`;
    if (minutos < 24 * 60) return `hace ${Math.round(minutos / 60)} h`;
    return formatoFecha.format(fecha);
  }

  function tamano(bytes) {
    if (bytes >= 1024 * 1024) return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
    return `${Math.max(1, Math.round(bytes / 1024))} KB`;
  }

  function avisar(texto) {
    const aviso = $("aviso");
    // Un diálogo abierto queda encima de todo (incluido su oscurecido): el aviso va dentro de él
    // para que no salga tapado. Sin diálogo, vuelve a la página.
    const dialogo = document.querySelector("dialog[open]");
    const destino = dialogo || document.body;
    if (aviso.parentElement !== destino) destino.append(aviso);
    aviso.textContent = texto;
    aviso.hidden = false;
    clearTimeout(temporizadorAviso);
    temporizadorAviso = setTimeout(() => { aviso.hidden = true; }, 3000);
  }

  function mostrarError(texto) {
    $("error").textContent = texto || "";
    $("error").hidden = !texto;
  }

  function errorEn(id, texto) {
    $(id).textContent = texto || "";
    $(id).hidden = !texto;
  }

  function enVisita() {
    try { return sessionStorage.getItem(CLAVE_DENTRO) === "1"; } catch { return false; }
  }
  function entrarAVisita() {
    try { sessionStorage.setItem(CLAVE_DENTRO, "1"); } catch { /* sin almacenamiento */ }
  }
  function salirDeVisita() {
    try { sessionStorage.removeItem(CLAVE_DENTRO); } catch { /* sin almacenamiento */ }
  }

  function jugar(juego, ranura) {
    location.href = `jugar.html?j=${juego.id}` + (ranura ? `&estado=${ranura}` : "");
  }

  // ---------- Navegación ----------

  function mostrarVista(nombre) {
    for (const [clave, el] of Object.entries(vistas)) el.hidden = clave !== nombre;
    $("barra").hidden = nombre === "perfiles";
    cerrarMenu();
    window.scrollTo(0, 0);
  }

  async function navegar() {
    mostrarError("");
    const destino = location.hash.slice(1) || "catalogo";
    if (destino === "perfiles" || !actual || !enVisita()) {
      if (destino !== "perfiles") history.replaceState(null, "", "#perfiles");
      dibujarPerfiles();
      mostrarVista("perfiles");
      return;
    }
    dibujarBarra();
    if (destino === "admin" && actual.admin) {
      mostrarVista("admin");
      await cargarCatalogo();
      dibujarAdmin();
      return;
    }
    if (location.hash !== "#catalogo") history.replaceState(null, "", "#catalogo");
    mostrarVista("catalogo");
    await cargarCatalogo();
  }

  // ---------- Perfiles ----------

  async function cargarPerfiles() {
    const datos = await pedir("perfiles");
    perfiles = datos.perfiles;
    actual = datos.actual;
  }

  function dibujarPerfiles() {
    const lista = $("lista-perfiles");
    lista.replaceChildren();
    for (const p of perfiles) {
      const boton = crear("button", "perfil");
      boton.type = "button";
      boton.append(avatar(p), crear("span", "perfil-nombre", p.nombre));
      if (p.tiene_pin) boton.append(crear("span", "perfil-candado", "🔒 PIN"));
      boton.addEventListener("click", () => elegirPerfil(p));
      lista.append(boton);
    }
  }

  async function elegirPerfil(p) {
    // Si este dispositivo ya tiene sesión con ese perfil, no hace falta pedir el PIN otra vez
    if (actual && actual.id === p.id) return entrar(actual);
    if (p.tiene_pin) {
      pedirPin(p);
      return;
    }
    try {
      const datos = await pedir("entrar", { method: "POST", body: { perfil_id: p.id } });
      entrar(datos.perfil);
    } catch (e) {
      mostrarError(e.message);
    }
  }

  function pedirPin(p) {
    const dialogo = $("dialogo-pin");
    $("pin-avatar").replaceWith(Object.assign(avatar(p, "avatar-mediano"), { id: "pin-avatar" }));
    $("pin-titulo").textContent = `PIN de ${p.nombre}`;
    $("pin").value = "";
    errorEn("pin-error", "");
    dialogo.dataset.perfil = p.id;
    dialogo.showModal();
    $("pin").focus();
  }

  $("form-pin").addEventListener("submit", async (e) => {
    e.preventDefault();
    const dialogo = $("dialogo-pin");
    try {
      const datos = await pedir("entrar", {
        method: "POST", body: { perfil_id: Number(dialogo.dataset.perfil), pin: $("pin").value },
      });
      dialogo.close();
      entrar(datos.perfil);
    } catch (err) {
      errorEn("pin-error", err.message);
      $("pin").select();
    }
  });

  function entrar(perfil) {
    actual = perfil;
    catalogo = null;
    entrarAVisita();
    if (location.hash === "#catalogo") navegar();
    else location.hash = "#catalogo";
  }

  function dibujarBarra() {
    $("avatar-actual").replaceWith(Object.assign(avatar(actual, "avatar-chico"), { id: "avatar-actual" }));
    $("menu-nombre").textContent = actual.nombre;
    $("menu-admin").hidden = !actual.admin;
    $("enlace-admin").hidden = !actual.admin;
  }

  function cerrarMenu() {
    $("menu-perfil").hidden = true;
    $("boton-perfil").setAttribute("aria-expanded", "false");
  }

  $("boton-perfil").addEventListener("click", (e) => {
    e.stopPropagation();
    const abrir = $("menu-perfil").hidden;
    $("menu-perfil").hidden = !abrir;
    $("boton-perfil").setAttribute("aria-expanded", String(abrir));
  });
  document.addEventListener("click", (e) => {
    if (!$("menu-perfil").contains(e.target)) cerrarMenu();
  });
  $("cambiar-perfil").addEventListener("click", async () => {
    salirDeVisita();
    await cargarPerfiles().catch(() => {});
    location.hash = "#perfiles";
  });

  // ---------- Catálogo ----------

  async function cargarCatalogo() {
    try {
      catalogo = await pedir("catalogo");
    } catch (e) {
      mostrarError(e.message);
      return;
    }
    juegos = new Map();
    for (const c of catalogo.consolas) for (const j of c.juegos) juegos.set(j.id, j);
    actual = catalogo.perfil;
    dibujarBarra();
    dibujarCatalogo();
  }

  function tarjeta(juego) {
    const boton = crear("button", "juego");
    boton.type = "button";
    const titulo = crear("span", "juego-titulo");
    if (juego.con_save) {
      const marca = crear("span", "juego-save", "●");
      marca.title = "Tiene partida guardada";
      titulo.append(marca);
    }
    titulo.append(juego.titulo);
    boton.append(cartucho(juego), titulo);
    boton.setAttribute("aria-label", `${juego.titulo} (${CONSOLAS[juego.consola]})`);
    boton.addEventListener("click", () => abrirJuego(juego.id));
    return boton;
  }

  function fila(titulo, lista) {
    const seccion = crear("section", "fila");
    seccion.append(crear("h2", "", titulo));
    const carril = crear("div", "fila-juegos");
    for (const j of lista) carril.append(tarjeta(j));
    seccion.append(carril);
    return seccion;
  }

  function dibujarCatalogo() {
    const filas = $("filas");
    filas.replaceChildren();
    const seguir = catalogo.seguir.map((id) => juegos.get(id)).filter(Boolean);
    if (seguir.length) filas.append(fila(`Seguir jugando, ${actual.nombre}`, seguir));
    for (const c of catalogo.consolas) if (c.juegos.length) filas.append(fila(c.nombre, c.juegos));

    const hay = juegos.size > 0;
    $("catalogo-vacio").hidden = hay;
    $("catalogo-vacio-admin").hidden = !actual.admin;
    $("catalogo-vacio-texto").textContent = actual.admin
      ? "Sube las primeras ROMs desde Administrar." : "Pídele al admin que suba los primeros.";
    dibujarDestacado(seguir[0] || null);
  }

  function dibujarDestacado(ultimo) {
    const destacado = $("destacado");
    destacado.replaceChildren();
    const todos = [...juegos.values()];
    if (!todos.length) {
      destacado.hidden = true;
      return;
    }
    destacado.hidden = false;
    // Lo último que jugó este perfil; si no ha jugado nada, uno al azar para animarlo
    const juego = ultimo || todos[Math.floor(Math.random() * todos.length)];
    const texto = crear("div", "destacado-texto");
    texto.append(
      crear("span", "destacado-etiqueta", ultimo ? "Seguir jugando" : "Prueba este"),
      crear("h2", "", juego.titulo),
      crear("p", "destacado-meta", CONSOLAS[juego.consola] + (juego.con_save ? " · tienes partida guardada" : "")),
    );
    const botones = crear("div", "destacado-botones");
    const jugarBoton = crear("button", "boton boton-claro", ultimo ? "▶ Continuar" : "▶ Jugar");
    jugarBoton.type = "button";
    jugarBoton.addEventListener("click", () => jugar(juego));
    const info = crear("button", "boton", "ⓘ Más info");
    info.type = "button";
    info.addEventListener("click", () => abrirJuego(juego.id));
    botones.append(jugarBoton, info);
    texto.append(botones);
    destacado.append(fondoDe(juego), texto, cartucho(juego));
  }

  // ---------- Detalle del juego ----------

  async function abrirJuego(id) {
    const dialogo = $("dialogo-juego");
    let datos;
    try {
      datos = await pedir(`juegos/${id}`);
    } catch (e) {
      avisar(e.message);
      return;
    }
    const juego = { ...juegos.get(id), ...datos.juego };
    const detalle = $("detalle");
    detalle.replaceChildren();

    const cabeza = crear("div", "detalle-cabeza");
    cabeza.append(fondoDe(juego), cartucho(juego));

    const cuerpo = crear("div", "detalle-cuerpo");
    const titulo = crear("div");
    titulo.append(crear("h2", "", juego.titulo),
                  crear("p", "detalle-meta", `${datos.juego.consola_nombre} · ${tamano(juego.tamano)}`));

    const botones = crear("div", "detalle-botones");
    const jugarBoton = crear("button", "boton boton-principal", datos.save ? "▶ Continuar" : "▶ Jugar");
    jugarBoton.type = "button";
    jugarBoton.addEventListener("click", () => jugar(juego));
    botones.append(jugarBoton);
    if (actual.admin) {
      const editar = crear("button", "boton", "✎ Editar");
      editar.type = "button";
      editar.addEventListener("click", () => { dialogo.close(); abrirEditarJuego(juego); });
      botones.append(editar);
    }

    // Partida (save del cartucho)
    const partida = crear("section", "detalle-seccion");
    partida.append(crear("h3", "", "Tu partida"));
    partida.append(crear("p", "", datos.save
      ? `Guardada ${cuando(datos.save.creado)}. Se guarda sola mientras juegas, cuando el juego guarda.`
      : "Todavía no hay partida. Cuando el juego guarde, se sube sola y la puedes seguir en cualquier dispositivo."));
    if (datos.save) {
      const ver = crear("button", "boton boton-texto", "Ver versiones anteriores");
      ver.type = "button";
      ver.addEventListener("click", () => mostrarHistorial(juego, partida, ver));
      partida.append(ver);
    }

    // Estados guardados (ranuras)
    const estados = crear("section", "detalle-seccion");
    estados.append(crear("h3", "", "Estados guardados"));
    const ranuras = crear("div", "ranuras");
    for (let n = 1; n <= datos.ranuras; n++) {
      const estado = datos.estados.find((e) => e.ranura === n);
      ranuras.append(ranura(juego, n, estado));
    }
    estados.append(ranuras);
    estados.append(crear("p", "ayuda",
      "Se guardan desde el menú del juego (💾). Tocar uno abre el juego justo en ese momento."));

    cuerpo.append(titulo, botones, partida, estados);
    detalle.append(cabeza, cuerpo);
    if (!dialogo.open) dialogo.showModal();
    dialogo.scrollTop = 0;
  }

  function ranura(juego, n, estado) {
    const caja = crear("div", "ranura" + (estado ? " ranura-llena" : ""));
    const imagen = crear(estado ? "button" : "div", "ranura-imagen");
    if (estado) {
      imagen.type = "button";
      imagen.title = `Cargar el estado ${n}`;
      const img = crear("img");
      img.src = `${API}juegos/${juego.id}/estados/${n}/captura?t=${encodeURIComponent(estado.creado)}`;
      img.alt = `Estado ${n}`;
      img.onerror = () => img.replaceWith(crear("span", "", "▶"));
      imagen.append(img);
      imagen.addEventListener("click", () => jugar(juego, n));
    } else {
      imagen.textContent = "Vacío";
    }
    const pie = crear("div", "ranura-pie");
    pie.append(crear("span", "", estado ? `${n} · ${cuando(estado.creado)}` : `Ranura ${n}`));
    if (estado) {
      const borrar = crear("button", "ranura-borrar", "🗑");
      borrar.type = "button";
      borrar.title = `Borrar el estado ${n}`;
      borrar.addEventListener("click", async () => {
        if (!confirm(`¿Borrar el estado guardado ${n}?`)) return;
        try {
          await pedir(`juegos/${juego.id}/estados/${n}`, { method: "DELETE" });
          abrirJuego(juego.id);
        } catch (e) {
          avisar(e.message);
        }
      });
      pie.append(borrar);
    }
    caja.append(imagen, pie);
    return caja;
  }

  async function mostrarHistorial(juego, seccion, boton) {
    let datos;
    try {
      datos = await pedir(`juegos/${juego.id}/saves`);
    } catch (e) {
      avisar(e.message);
      return;
    }
    boton.remove();
    const lista = crear("ul", "historial");
    datos.saves.forEach((s, i) => {
      const li = crear("li");
      li.append(crear("span", "", `${formatoFecha.format(new Date(s.creado))}${i === 0 ? " (la actual)" : ""}`));
      if (i > 0) {
        const recuperar = crear("button", "boton", "Recuperar");
        recuperar.type = "button";
        recuperar.addEventListener("click", async () => {
          if (!confirm("¿Volver a esta versión de la partida? La actual queda en la lista por si acaso.")) return;
          try {
            await pedir(`juegos/${juego.id}/saves/${s.id}/restaurar`, { method: "POST" });
            avisar("Listo: esa versión es ahora tu partida");
            abrirJuego(juego.id);
          } catch (e) {
            avisar(e.message);
          }
        });
        li.append(recuperar);
      }
      lista.append(li);
    });
    seccion.append(lista);
  }

  // ---------- Administración: juegos ----------

  function dibujarAdmin() {
    const cont = $("admin-juegos");
    cont.replaceChildren();
    for (const c of catalogo.consolas) {
      if (!c.juegos.length) continue;
      cont.append(crear("h3", "", `${c.nombre} (${c.juegos.length})`));
      const grupo = crear("div", "admin-juegos");
      for (const j of c.juegos) {
        const boton = crear("button", "admin-juego");
        boton.type = "button";
        boton.append(cartucho(j), crear("span", "", j.titulo));
        boton.addEventListener("click", () => abrirEditarJuego(j));
        grupo.append(boton);
      }
      cont.append(grupo);
    }
    if (!juegos.size) cont.append(crear("p", "ayuda", "Todavía no hay juegos."));
    dibujarAdminPerfiles();
  }

  $("archivos-roms").addEventListener("change", async (e) => {
    const archivos = [...e.target.files];
    e.target.value = "";
    for (const archivo of archivos) await subirRom(archivo);   // de una en una
    await cargarCatalogo();
    dibujarAdmin();
  });

  function subirRom(archivo) {
    const li = crear("li", "subida");
    const linea = crear("div", "subida-linea");
    const estado = crear("span", "subida-estado", "Subiendo…");
    linea.append(crear("span", "subida-nombre", archivo.name), estado);
    const barra = crear("progress");
    barra.max = 1;
    barra.value = 0;
    li.append(linea, barra);
    $("subidas").prepend(li);

    // XMLHttpRequest y no fetch: así se puede mostrar el avance de la subida
    return new Promise((resolver) => {
      const xhr = new XMLHttpRequest();
      xhr.open("POST", `${API}admin/juegos?nombre=${encodeURIComponent(archivo.name)}`);
      xhr.upload.onprogress = (ev) => { if (ev.lengthComputable) barra.value = ev.loaded / ev.total; };
      xhr.onload = () => {
        let datos = {};
        try { datos = JSON.parse(xhr.responseText); } catch { /* respuesta vacía */ }
        barra.remove();
        if (xhr.status === 200) {
          li.dataset.estado = "listo";
          estado.textContent = `✓ ${datos.titulo} (${CONSOLAS[datos.consola]})`;
        } else {
          li.dataset.estado = "error";
          estado.textContent = datos.error || (xhr.status === 413 ? "Archivo demasiado grande" : `Error ${xhr.status}`);
        }
        resolver();
      };
      xhr.onerror = () => {
        barra.remove();
        li.dataset.estado = "error";
        estado.textContent = "No se pudo subir (¿se cortó la conexión?)";
        resolver();
      };
      xhr.send(archivo);
    });
  }

  function abrirEditarJuego(juego) {
    editandoJuego = juego;
    $("juego-titulo").value = juego.titulo;
    const gameboy = juego.consola === "gb" || juego.consola === "gbc";
    $("campo-consola").hidden = !gameboy;
    if (gameboy) $("juego-consola").value = juego.consola;
    $("quitar-caratula").hidden = !juego.caratula;
    $("juego-vista").replaceChildren(cartucho(juego));
    errorEn("juego-error", "");
    $("dialogo-editar-juego").showModal();
  }

  async function refrescarJuego(juego) {
    editandoJuego = { ...editandoJuego, ...juego };
    juegos.set(juego.id, { ...juegos.get(juego.id), ...juego });
    $("quitar-caratula").hidden = !editandoJuego.caratula;
    $("juego-vista").replaceChildren(cartucho(editandoJuego));
    await cargarCatalogo();
    if (location.hash === "#admin") dibujarAdmin();
  }

  $("form-juego").addEventListener("submit", async (e) => {
    e.preventDefault();
    const cambios = { titulo: $("juego-titulo").value };
    if (!$("campo-consola").hidden) cambios.consola = $("juego-consola").value;
    try {
      await refrescarJuego(await pedir(`admin/juegos/${editandoJuego.id}`, { method: "PATCH", body: cambios }));
      $("dialogo-editar-juego").close();
      avisar("Juego guardado");
    } catch (err) {
      errorEn("juego-error", err.message);
    }
  });

  $("archivo-caratula").addEventListener("change", async (e) => {
    const archivo = e.target.files[0];
    e.target.value = "";
    if (!archivo) return;
    try {
      const imagen = await prepararImagen(archivo);
      await refrescarJuego(await pedir(`admin/juegos/${editandoJuego.id}/caratula`, { method: "PUT", body: imagen }));
      avisar("Carátula lista");
    } catch (err) {
      errorEn("juego-error", err.message);
    }
  });

  $("quitar-caratula").addEventListener("click", async () => {
    try {
      await refrescarJuego(await pedir(`admin/juegos/${editandoJuego.id}/caratula`, { method: "DELETE" }));
    } catch (err) {
      errorEn("juego-error", err.message);
    }
  });

  $("borrar-juego").addEventListener("click", async () => {
    if (!confirm(`¿Borrar "${editandoJuego.titulo}"? Se borran también las partidas de todos los perfiles en este juego.`)) return;
    try {
      await pedir(`admin/juegos/${editandoJuego.id}`, { method: "DELETE" });
      $("dialogo-editar-juego").close();
      avisar("Juego borrado");
      await cargarCatalogo();
      if (location.hash === "#admin") dibujarAdmin();
    } catch (err) {
      errorEn("juego-error", err.message);
    }
  });

  // Achica las imágenes grandes (fotos de celular) antes de subirlas; las chicas van tal cual
  async function prepararImagen(archivo) {
    if (!/^image\/(jpeg|png|webp)$/.test(archivo.type)) throw new Error("La carátula debe ser JPEG, PNG o WebP");
    const bitmap = await createImageBitmap(archivo).catch(() => null);
    if (!bitmap) throw new Error("No se pudo leer la imagen");
    const escala = Math.min(1, MAX_LADO_CARATULA / Math.max(bitmap.width, bitmap.height));
    if (escala === 1 && archivo.size <= 1.5 * 1024 * 1024) return archivo;
    const lienzo = document.createElement("canvas");
    lienzo.width = Math.round(bitmap.width * escala);
    lienzo.height = Math.round(bitmap.height * escala);
    lienzo.getContext("2d").drawImage(bitmap, 0, 0, lienzo.width, lienzo.height);
    return new Promise((resolver) => lienzo.toBlob(resolver, "image/jpeg", 0.88));
  }

  // ---------- Administración: perfiles ----------

  function dibujarAdminPerfiles() {
    const lista = $("admin-perfiles");
    lista.replaceChildren();
    for (const p of perfiles) {
      const li = crear("li");
      const nombre = crear("span", "lista-admin-nombre", p.nombre);
      if (p.admin) nombre.append(crear("span", "insignia", "Admin"));
      if (p.tiene_pin) nombre.append(crear("span", "insignia", "🔒 PIN"));
      if (p.id === actual.id) nombre.append(crear("span", "insignia", "Tú"));
      const editar = crear("button", "boton", "Editar");
      editar.type = "button";
      editar.addEventListener("click", () => abrirPerfil(p));
      li.append(avatar(p), nombre, editar);
      lista.append(li);
    }
  }

  function dibujarOpciones() {
    const avatares = $("opciones-avatar");
    avatares.replaceChildren();
    for (const a of AVATARES) {
      const b = crear("button", "", a);
      b.type = "button";
      b.setAttribute("aria-pressed", String(a === elegido.avatar));
      b.addEventListener("click", () => { elegido.avatar = a; dibujarOpciones(); });
      avatares.append(b);
    }
    const colores = $("opciones-color");
    colores.replaceChildren();
    for (const c of COLORES) {
      const b = crear("button");
      b.type = "button";
      b.style.setProperty("--color", c);
      b.setAttribute("aria-label", `Color ${c}`);
      b.setAttribute("aria-pressed", String(c === elegido.color));
      b.addEventListener("click", () => { elegido.color = c; dibujarOpciones(); });
      colores.append(b);
    }
    $("perfil-vista").replaceWith(Object.assign(
      avatar({ avatar: elegido.avatar, color: elegido.color }, "avatar-mediano"), { id: "perfil-vista" }));
  }

  function abrirPerfil(p) {
    editandoPerfil = p;
    $("perfil-titulo").textContent = p ? `Editar a ${p.nombre}` : "Nuevo perfil";
    $("perfil-nombre").value = p ? p.nombre : "";
    $("perfil-pin").value = "";
    $("perfil-pin").placeholder = p && p.tiene_pin ? "Igual que antes" : "Sin PIN";
    $("perfil-pin-ayuda").textContent = p && p.tiene_pin
      ? "(déjalo vacío para no cambiarlo)" : "(opcional, de 4 a 8 números)";
    $("campo-quitar-pin").hidden = !(p && p.tiene_pin);
    $("perfil-quitar-pin").checked = false;
    $("perfil-admin").checked = !!(p && p.admin);
    $("perfil-admin").disabled = !!(p && p.id === actual.id);   // no se puede quitar el admin a sí mismo
    $("borrar-perfil").hidden = !p || p.id === actual.id;
    elegido = {
      avatar: p ? p.avatar : AVATARES[Math.floor(Math.random() * AVATARES.length)],
      color: p ? p.color : COLORES[perfiles.length % COLORES.length],
    };
    dibujarOpciones();
    errorEn("perfil-error", "");
    $("dialogo-perfil").showModal();
  }

  $("nuevo-perfil").addEventListener("click", () => abrirPerfil(null));

  $("form-perfil").addEventListener("submit", async (e) => {
    e.preventDefault();
    const datos = { nombre: $("perfil-nombre").value, avatar: elegido.avatar, color: elegido.color };
    if (!$("perfil-admin").disabled) datos.admin = $("perfil-admin").checked;
    const pin = $("perfil-pin").value.trim();
    if (pin) datos.pin = pin;
    else if ($("perfil-quitar-pin").checked) datos.pin = "";
    try {
      const r = editandoPerfil
        ? await pedir(`admin/perfiles/${editandoPerfil.id}`, { method: "PATCH", body: datos })
        : await pedir("admin/perfiles", { method: "POST", body: datos });
      perfiles = r.perfiles;
      if (editandoPerfil && editandoPerfil.id === actual.id) {
        actual = perfiles.find((p) => p.id === actual.id);
        dibujarBarra();
      }
      $("dialogo-perfil").close();
      dibujarAdminPerfiles();
      avisar(editandoPerfil ? "Perfil guardado" : "Perfil creado");
    } catch (err) {
      errorEn("perfil-error", err.message);
    }
  });

  $("borrar-perfil").addEventListener("click", async () => {
    if (!confirm(`¿Borrar el perfil de ${editandoPerfil.nombre}? Se borran también todas sus partidas.`)) return;
    try {
      perfiles = (await pedir(`admin/perfiles/${editandoPerfil.id}`, { method: "DELETE" })).perfiles;
      $("dialogo-perfil").close();
      dibujarAdminPerfiles();
      avisar("Perfil borrado");
    } catch (err) {
      errorEn("perfil-error", err.message);
    }
  });

  // ---------- Arranque ----------

  for (const boton of document.querySelectorAll("[data-cerrar]")) {
    boton.addEventListener("click", () => boton.closest("dialog").close());
  }
  // Tocar fuera del diálogo lo cierra
  for (const dialogo of document.querySelectorAll("dialog")) {
    dialogo.addEventListener("click", (e) => {
      if (e.target !== dialogo) return;
      const r = dialogo.getBoundingClientRect();
      const fuera = e.clientX < r.left || e.clientX > r.right || e.clientY < r.top || e.clientY > r.bottom;
      if (fuera) dialogo.close();
    });
  }

  window.addEventListener("hashchange", navegar);

  (async () => {
    try {
      await cargarPerfiles();
    } catch (e) {
      mostrarError(`No se pudo conectar con Gameflix: ${e.message}`);
      return;
    }
    navegar();
  })();
})();
