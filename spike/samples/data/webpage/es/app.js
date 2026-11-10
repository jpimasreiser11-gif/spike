// Cuaderno de riego: guarda las plantas en el navegador (localStorage), sin red ni librerías.
const KEY = "cuaderno-de-riego";
const DAY = 24 * 60 * 60 * 1000;
const THIRSTY_AFTER = 3; // días sin agua a partir de los cuales se avisa

const form = document.getElementById("form");
const nameInput = document.getElementById("name");
const list = document.getElementById("plants");
const empty = document.getElementById("empty");

function load() {
  try {
    return JSON.parse(localStorage.getItem(KEY)) || [];
  } catch {
    return [];
  }
}

function save(plants) {
  try {
    localStorage.setItem(KEY, JSON.stringify(plants));
  } catch {
    /* sin almacenamiento: la página sigue funcionando hasta que se recargue */
  }
}

let plants = load();

function daysSince(time) {
  return Math.floor((Date.now() - time) / DAY);
}

function label(days) {
  if (days <= 0) return "regada hoy";
  return days === 1 ? "regada ayer" : `regada hace ${days} días`;
}

function render() {
  list.replaceChildren();
  for (const plant of plants) {
    const days = daysSince(plant.watered);
    const item = document.createElement("li");
    if (days >= THIRSTY_AFTER) item.className = "thirsty";
    const text = document.createElement("div");
    const title = document.createElement("strong");
    title.textContent = plant.name;
    const info = document.createElement("div");
    info.className = "days";
    info.textContent = label(days);
    text.append(title, info);
    const button = document.createElement("button");
    button.type = "button";
    button.textContent = "Regar";
    button.addEventListener("click", () => {
      plant.watered = Date.now();
      save(plants);
      render();
    });
    item.append(text, button);
    list.append(item);
  }
  empty.hidden = plants.length > 0;
}

form.addEventListener("submit", (event) => {
  event.preventDefault();
  const name = nameInput.value.trim();
  if (!name) return;
  plants.push({ name, watered: Date.now() });
  save(plants);
  nameInput.value = "";
  render();
});

render();
