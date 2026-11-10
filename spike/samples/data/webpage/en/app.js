// Watering log: keeps the plants in the browser (localStorage), with no network and no libraries.
const KEY = "watering-log";
const DAY = 24 * 60 * 60 * 1000;
const THIRSTY_AFTER = 3; // days without water after which a plant is flagged

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
    /* no storage: the page keeps working until it is reloaded */
  }
}

let plants = load();

function daysSince(time) {
  return Math.floor((Date.now() - time) / DAY);
}

function label(days) {
  if (days <= 0) return "watered today";
  return days === 1 ? "watered yesterday" : `watered ${days} days ago`;
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
    button.textContent = "Water";
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
